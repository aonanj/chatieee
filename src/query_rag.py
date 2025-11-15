# query_rag.py
"""
Simple RAG query pipeline:

1. Embed a user question.
2. Retrieve top-k nodes from Neon/Postgres (pgvector).
3. Build a context prompt.
4. Call OpenAI chat completion to answer using only retrieved context.

Usage:
    DATABASE_URL=... OPENAI_API_KEY=... python query_rag.py "What is the scope of IEEE 802-2024?"

Optional flags:
    --k 8                         # number of chunks to retrieve
    --max-context-chars 8000      # max combined context length
    --document-file-name ...      # optionally restrict to a specific document file_name
"""

import argparse
from typing import Any

from openai import OpenAI
from pgvector.psycopg import Vector, register_vector
import psycopg

from src import config
from src.utils.database import get_connection

logger = config.LOGGER

EMBEDDING_MODEL = config.EMBEDDING_MODEL
ANSWER_MODEL = config.ANSWER_MODEL


def get_openai_client() -> OpenAI:
    api_key = config.OPENAI_API_KEY
    if not api_key:
        api_key_error = "OPENAI_API_KEY is not set"
        logger.error(api_key_error)
        raise RuntimeError(api_key_error)
    return OpenAI(api_key=api_key)


def embed_query(client: OpenAI, query: str) -> list[float]:
    resp = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=query,
    )
    return resp.data[0].embedding

def fetch_chunks(
    conn: psycopg.Connection,
    query_embedding: list[float],
    k: int,
    max_context_chars: int,
    document_external_id: str | None,
) -> list[dict[str, Any]]:
    """
    Fetch top-k chunks from rag_chunk by vector similarity, truncated to
    max_context_chars total content length.

    Returns a list of dicts:
      {
        "chunk_id": int,
        "document_id": int,
        "document_external_id": Optional[str],
        "document_title": Optional[str],
        "content": str,
        "metadata": dict,
        "page_start": Optional[int],
        "page_end": Optional[int],
        "chunk_type": str,
        "distance": float,
      }
    """
    # Ensure pgvector adapter is registered
    register_vector(conn)

    base_sql = """
    SELECT
        rc.id AS chunk_id,
        rc.document_id,
        rd.external_id,
        rd.title,
        rc.content,
        rc.metadata,
        rc.page_start,
        rc.page_end,
        rc.chunk_type,
        (rc.embedding <-> %(query_vec)s) AS distance
    FROM rag_chunk rc
    JOIN rag_document rd
      ON rc.document_id = rd.id
    WHERE rc.embedding IS NOT NULL
    """
    params: dict[str, Any] = {"query_vec": Vector(query_embedding), "limit": k}


    if document_external_id:
        base_sql += " AND rd.external_id = %(external_id)s"
        params["external_id"] = document_external_id

    base_sql += """
    ORDER BY rc.embedding <-> %(query_vec)s
    LIMIT %(limit)s
    """

    results: list[dict[str, Any]] = []

    with conn.cursor() as cur:
        cur.execute(base_sql, params)
        rows = cur.fetchall()

    total_chars = 0
    for row in rows:
        (
            chunk_id,
            document_id,
            external_id,
            title,
            content,
            metadata,
            page_start,
            page_end,
            chunk_type,
            distance,
        ) = row

        content = content or ""
        if total_chars + len(content) > max_context_chars and results:
            break

        results.append(
            {
                "chunk_id": int(chunk_id),
                "document_id": int(document_id),
                "document_external_id": external_id,
                "document_title": title,
                "content": content,
                "metadata": metadata or {},
                "page_start": page_start,
                "page_end": page_end,
                "chunk_type": chunk_type,
                "distance": float(distance),
            }
        )
        total_chars += len(content)

    return results


def build_context_snippets(chunks: list[dict[str, Any]]) -> str:
    """
    Convert retrieved chunks into a context string for the LLM.
    Includes simple document + page metadata.
    """
    snippets: list[str] = []

    for i, ch in enumerate(chunks, start=1):
        meta = ch.get("metadata") or {}

        # Prefer heading/section information if you're storing it
        heading = ch.get("metadata", {}).get("section") or ch.get("metadata", {}).get("heading") or ch.get("metadata", {}).get("title") or ch.get("metadata", {}).get("heading_override") or ch.get("metadata", {}).get("section_title")
        if not heading:
            heading = ch.get("metadata", {}).get("heading") or ch.get("metadata", {}).get("section")

        page_start = ch.get("page_start") or meta.get("page_start") or meta.get("page")
        page_end = ch.get("page_end") or meta.get("page_end")

        location_parts: list[str] = []

        doc_label = (
            ch.get("document_external_id")
            or ch.get("document_title")
            or f"doc-{ch['document_id']}"
        )
        location_parts.append(f"Document: {doc_label}")

        if heading:
            location_parts.append(f"Section: {heading}")

        if page_start and page_end and page_start != page_end:
            location_parts.append(f"Pages: {page_start}-{page_end}")
        elif page_start:
            location_parts.append(f"Page: {page_start}")

        location_str = " | ".join(location_parts)

        snippet_header = f"[Source {i}] {location_str}"
        snippet_body = ch["content"].strip()

        snippets.append(snippet_header + "\n" + snippet_body)

    return "\n\n---\n\n".join(snippets)


def build_prompt(question: str, context_snippets: str) -> str:
    """
    Instructions for the RAG assistant.
    """
    return (
        "You are a technical assistant that answers questions strictly using the "
        "provided context snippets, which are excerpts from PDF documents such as "
        "technical standards or legal/technical specifications.\n"
        "Rules:\n"
        "1. Use ONLY the given context to answer. If the answer is not supported by the context, say you do not know.\n"
        "2. When you state a fact, reference the relevant source number(s) (e.g., [Source 1], [Source 3]).\n"
        "3. Do not invent section numbers, clause numbers, or page numbers that are not present in the context.\n"
        "4. Be concise and precise; prefer quoting short exact definitions or sentences from the context.\n"
        "5. If the context is contradictory or ambiguous, explain the ambiguity instead of guessing.\n\n"
        "You are given several labeled source snippets from one or more PDF documents.\n\n"
        "Context snippets:\n"
        f"{context_snippets}\n\n"
        "Task:\n"
        f"Answer the following question using ONLY the information in the snippets above.\n\n"
        f"Question: {question}\n"
        "After your answer, list the sources you relied on in a brief 'Sources:' line, "
        "like 'Sources: [Source 1], [Source 3]'."
    )


def answer_question(
    question: str,
    document_external_id: str | None,
    k: int,
    max_context_chars: int,
) -> str:
    client = get_openai_client()

    # 1. Embed query
    query_vec = embed_query(client, question)

    # 2. Retrieve candidate chunks
    with get_connection() as conn:
        chunks = fetch_chunks(
            conn=conn,
            query_embedding=query_vec,
            k=k,
            max_context_chars=max_context_chars,
            document_external_id=document_external_id,
        )

    if not chunks:
        return "No relevant content found in the indexed documents."

    # 3. Build context and prompts
    context_snippets = build_context_snippets(chunks)
    prompt = build_prompt(question, context_snippets)

    # 4. Call the chat completion model
    completion = client.responses.create(
        model=ANSWER_MODEL,
        input=prompt
    )

    if not completion.output_text:
        return "Error: No answer generated by the language model."

    return completion.output_text.strip()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Query the RAG system over rag_chunk/rag_document."
    )
    parser.add_argument("question", type=str, help="The natural-language question to ask.")
    parser.add_argument(
        "--k",
        type=int,
        default=8,
        help="Number of candidate chunks to retrieve (default: 8).",
    )
    parser.add_argument(
        "--max-context-chars",
        type=int,
        default=8000,
        help="Maximum total characters of context to send to the LLM (default: 8000).",
    )
    parser.add_argument(
        "--document-external-id",
        type=str,
        default=None,
        help="Optional: restrict retrieval to a single document by rag_document.external_id.",
    )
    args = parser.parse_args()

    answer = answer_question(
        question=args.question,
        document_external_id=args.document_external_id,
        k=args.k,
        max_context_chars=args.max_context_chars,
    )

    logger.info("ANSWER:\n%s", answer)


if __name__ == "__main__":
    main()
