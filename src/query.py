from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

import psycopg
from psycopg import sql as _sql
from psycopg.rows import dict_row

from src import config
from src.ingest.embedding import EmbeddingClient, embedding_to_pgvector

logger = config.LOGGER

try:  # pragma: no
    from openai import OpenAI
except Exception:  # pragma: no cover
    logger.info("OpenAI library not found, LLM reranking will be disabled")
    OpenAI = None  # type: ignore

FIGURE_RE = re.compile(r"\b(FIG(?:URE)?\.?\s*\d+[A-Z]?)", re.IGNORECASE)

@dataclass(slots=True)
class ChunkMatch:
    id: int
    document_id: int
    content: str
    metadata: dict[str, Any]
    vector_score: float | None = None
    lexical_score: float | None = None
    rerank_score: float | None = None
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "document_id": self.document_id,
            "content": self.content,
            "metadata": self.metadata,
            "vector_score": self.vector_score,
            "lexical_score": self.lexical_score,
            "rerank_score": self.rerank_score,
        }

# query.py
@dataclass(slots=True)
class FigureMatch:
    id: int
    document_id: int
    figure_label: str
    page_number: int | None
    caption: str | None
    image_uri: str
    metadata: dict[str, Any]

class LLMReranker:
    def __init__(self, model: str | None = None) -> None:
        api_key = os.getenv("OPENAI_API_KEY")
        self._client = OpenAI(api_key=api_key) if (OpenAI and api_key) else None
        self.model = model or os.getenv("RAG_RERANK_MODEL", "gpt-5-mini")
    @property
    def available(self) -> bool:
        return self._client is not None
    def rerank(self, query: str, candidates: list[ChunkMatch]) -> list[ChunkMatch]:
        if not self.available or not candidates:
            return self._fallback(candidates)
        prompt = self._build_prompt(query, candidates)
        try:
            if not self._client:
                raise RuntimeError("OpenAI client is not available")
            response = self._client.responses.create(
                model=self.model,
                input=prompt
            )
            output = getattr(response, "output_text", None)
            if not output:
                output = response.output[0].content[0].text  # type: ignore[attr-defined]
            data = json.loads(output)
            scores = {entry["id"]: float(entry["score"]) for entry in data.get("ranking", [])}
            for candidate in candidates:
                if candidate.id in scores:
                    candidate.rerank_score = scores[candidate.id]
            remaining = [c for c in candidates if c.rerank_score is not None]
            if remaining:
                remaining.sort(key=lambda c: c.rerank_score or 0.0, reverse=True)
                rest = [c for c in candidates if c.rerank_score is None]
                rest.sort(key=lambda c: (c.vector_score or 0.0) + (c.lexical_score or 0.0), reverse=True)
                return remaining + rest
        except Exception as exc:  # pragma: no cover - API failure path
            logger.warning("LLM reranker failed, falling back to heuristic ranking", exc_info=exc)
        return self._fallback(candidates)
    def _fallback(self, candidates: list[ChunkMatch]) -> list[ChunkMatch]:
        if not candidates:
            return []
        max_vector = max((c.vector_score or 0.0) for c in candidates)
        max_lexical = max((c.lexical_score or 0.0) for c in candidates)
        for candidate in candidates:
            vector_component = (candidate.vector_score or 0.0) / max_vector if max_vector else 0.0
            lexical_component = (candidate.lexical_score or 0.0) / max_lexical if max_lexical else 0.0
            candidate.rerank_score = 0.6 * vector_component + 0.4 * lexical_component
        return sorted(candidates, key=lambda c: c.rerank_score or 0.0, reverse=True)

    def _build_prompt(self, query: str, candidates: list[ChunkMatch]) -> str:
        lines = [
            "You are a legal research assistant. Rank the provided passages by their usefulness",
            "for answering the user's question. Return a JSON object with a 'ranking' array",
            "containing {\"id\": chunk_id, \"score\": relevance} objects in descending order.",
            "Query:",
            query.strip(),
            "\nPassages:",
        ]
        for _, candidate in enumerate(candidates, start=1):
            snippet = candidate.content.strip().replace("\n", " ")
            if len(snippet) > 600:
                snippet = snippet[:600] + "…"
            lines.append(f"[{candidate.id}] {snippet}")
        return "\n".join(lines)


class AnswerGenerator:
    def __init__(self, model: str | None = None, verbosity: str | None = None) -> None:
        if not OpenAI:
            raise RuntimeError("OpenAI SDK is required to generate answers")
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY must be set to generate answers")
        self._client = OpenAI(api_key=api_key)
        self.model = model or config.ANSWER_MODEL
        self.verbosity = verbosity or config.DEFAULT_VERBOSITY

    def generate(self, question: str, chunks: Sequence[ChunkMatch], max_context_chars: int) -> str:
        if not chunks:
            return "No relevant content found in the indexed documents."
        context = self._build_context_snippets(chunks, max_context_chars)
        if not context:
            return "No relevant content found in the indexed documents."
        prompt = self._build_prompt(question, context)
        try:
            response = self._client.responses.create(model=self.model, input=prompt)
        except Exception as exc:  # pragma: no cover - network failure path
            logger.error("Failed to generate answer from OpenAI", exc_info=exc)
            return "Unable to generate an answer at this time."
        answer = getattr(response, "output_text", None)
        if not answer:
            answer = response.output[0].content[0].text  # type: ignore[attr-defined]
        return answer.strip()

    def _build_context_snippets(self, chunks: Sequence[ChunkMatch], max_context_chars: int) -> str:
        snippets: list[str] = []
        total_chars = 0
        for index, chunk in enumerate(chunks, start=1):
            body = (chunk.content or "").strip()
            if not body:
                continue
            snippet = self._format_snippet(index, chunk, body)
            if max_context_chars > 0 and (total_chars + len(body) > max_context_chars and snippets):
                break
            snippets.append(snippet)
            total_chars += len(body)
        return "\n\n---\n\n".join(snippets)

    def _format_snippet(self, index: int, chunk: ChunkMatch, body: str) -> str:
        metadata = chunk.metadata or {}
        heading = (
            metadata.get("section")
            or metadata.get("heading")
            or metadata.get("title")
            or metadata.get("heading_override")
            or metadata.get("section_title")
        )
        page_start = metadata.get("page_start") or metadata.get("page") or metadata.get("page_number")
        page_end = metadata.get("page_end")
        document_label = (
            metadata.get("document_external_id")
            or metadata.get("document_title")
            or metadata.get("file_name")
            or f"doc-{chunk.document_id}"
        )
        location_parts = [f"Document: {document_label}"]
        if heading:
            location_parts.append(f"Section: {heading}")
        if page_start and page_end and page_start != page_end:
            location_parts.append(f"Pages: {page_start}-{page_end}")
        elif page_start:
            location_parts.append(f"Page: {page_start}")
        header = f"[Source {index}] {' | '.join(location_parts)}"
        return f"{header}\n{body}"

    def _build_prompt(self, question: str, context_snippets: str) -> str:
        return (
        "You are a technical assistant that answers questions strictly using the "
        "provided context snippets, which are excerpts from PDF documents such as "
        "technical standards or legal/technical specifications.\n"
        "Rules:\n"
        "1. Use ONLY the given context to answer. If the answer is not supported by the context, say you do not know.\n"
        "2. When you state a fact, reference the relevant source number(s) (e.g., [Source 1], [Source 3]).\n"
        "3. Do not invent section numbers, clause numbers, or page numbers that are not present in the context.\n"
        "4. Be concise and precise; prefer quoting short exact definitions or sentences from the context.\n"
        "5. If the context is contradictory or ambiguous, explain the ambiguity instead of guessing.\n"
        "6. If related figures are provided for a context, mention them explicitly (e.g., \"As shown in FIG. 3 …\"). Do not invent figures that are not listed.\n\n"
        "You are given several labeled source snippets from one or more PDF documents.\n\n"
        "Context snippets:\n"
        f"{context_snippets}\n\n"
        "Task:\n"
        f"Answer the following question using ONLY the information in the snippets above.\n\n"
        f"Question: {question}\n"
        ## "After your answer, list the sources you relied on in a brief 'Sources:' line, "
        ## "like 'Sources: [Source 1], [Source 3]'."
        )

class HybridRetriever:
    VECTOR_QUERY = """
        SELECT id, document_id, content, metadata,
               1 - (embedding <=> %(embedding)s::vector) AS similarity,
               (embedding <=> %(embedding)s::vector) AS distance
          FROM rag_chunk
         WHERE embedding IS NOT NULL
      ORDER BY embedding <=> %(embedding)s::vector
         LIMIT %(limit)s
    """
    LEXICAL_QUERY = """
        SELECT id, document_id, content, metadata,
               ts_rank_cd(content_tsv, plainto_tsquery('english', %(query)s)) AS rank
          FROM rag_chunk
         WHERE content_tsv @@ plainto_tsquery('english', %(query)s)
      ORDER BY rank DESC
         LIMIT %(limit)s
    """
    def __init__(
        self,
        conninfo: str,
        embedder: EmbeddingClient | None = None,
        reranker: LLMReranker | None = None,
    ) -> None:
        self.conninfo = conninfo
        self.embedder = embedder or EmbeddingClient()
        self.reranker = reranker or LLMReranker()
    def search(self, query: str, vector_k: int = 20, lexical_k: int = 20, final_k: int = 10) -> list[ChunkMatch]:
        query_embedding = self.embedder.embed(query)
        vector_param = embedding_to_pgvector(query_embedding.vector)
        with psycopg.connect(self.conninfo) as conn:
            vector_results = self._vector_search(conn, vector_param, limit=vector_k)
            lexical_results = self._lexical_search(conn, query, limit=lexical_k)
        combined = self._combine_results(vector_results, lexical_results)
        reranked = self.reranker.rerank(query, combined)
        return reranked[:final_k]
    def _vector_search(self, conn: psycopg.Connection[Any], vector_param: str, limit: int) -> list[ChunkMatch]:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(self.VECTOR_QUERY, {"embedding": vector_param, "limit": limit})
            rows = cur.fetchall()
        results: list[ChunkMatch] = []
        for row in rows:
            results.append(
                ChunkMatch(
                    id=row["id"],
                    document_id=row["document_id"],
                    content=row["content"],
                    metadata=row.get("metadata") or {},
                    vector_score=row["similarity"],
                )
            )
        return results
    def _lexical_search(self, conn: psycopg.Connection[Any], query: str, limit: int) -> list[ChunkMatch]:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(self.LEXICAL_QUERY, {"query": query, "limit": limit})
            rows = cur.fetchall()
        results: list[ChunkMatch] = []
        for row in rows:
            results.append(
                ChunkMatch(
                    id=row["id"],
                    document_id=row["document_id"],
                    content=row["content"],
                    metadata=row.get("metadata") or {},
                    lexical_score=row["rank"],
                )
            )
        return results
    def _combine_results(
        self,
        vector_results: Iterable[ChunkMatch],
        lexical_results: Iterable[ChunkMatch],
    ) -> list[ChunkMatch]:
        combined: dict[int, ChunkMatch] = {}
        for result in vector_results:
            combined[result.id] = result
        for result in lexical_results:
            existing = combined.get(result.id)
            if existing:
                existing.lexical_score = result.lexical_score
                #if existing.metadata == {} and result.metadata:
                #    existing.metadata = result.metadata
            else:
                combined[result.id] = result
        return list(combined.values())

def extract_figure_labels(text: str) -> list[str]:
    labels: set[str] = set()
    for match in FIGURE_RE.finditer(text or ""):
        labels.add(normalise_figure_label(match.group(1)))
    return sorted(labels)

def normalise_figure_label(raw: str) -> str:
    cleaned = " ".join(raw.replace("FIGURE", "FIG.").replace("Fig", "FIG.").split())
    if not cleaned.upper().startswith("FIG."):
        cleaned = "FIG. " + cleaned.split()[-1]
    return cleaned.upper()

def get_figures_for_chunks(
    conninfo: str,
    chunks: list[ChunkMatch],
) -> list[FigureMatch]:
    if not chunks:
        return []

    pairs: set[tuple[int, str]] = set()
    for ch in chunks:
        for label in extract_figure_labels(ch.content):
            pairs.add((ch.document_id, label))

    if not pairs:
        return []

    values = ",".join(["(%s, %s)"] * len(pairs))
    sql = f"""
        WITH q(document_id, figure_label) AS (
            VALUES {values}
        )
        SELECT f.id, f.document_id, f.figure_label, f.page_number,
               f.caption, f.image_uri, f.metadata
          FROM rag_figure f
          JOIN q
            ON f.document_id = q.document_id
           AND f.figure_label = q.figure_label
    """

    params: list[Any] = []
    for doc_id, label in pairs:
        params.extend([doc_id, label])

    matches: list[FigureMatch] = []
    with psycopg.connect(conninfo) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(_sql.SQL(sql), params) # type: ignore
            for row in cur:
                matches.append(
                    FigureMatch(
                        id=row["id"],
                        document_id=row["document_id"],
                        figure_label=row["figure_label"],
                        page_number=row["page_number"],
                        caption=row["caption"],
                        image_uri=row["image_uri"],
                        metadata=row["metadata"] or {},
                    )
                )
    return matches

def answer_query(query: str):
    database_url = config.DATABASE_URL or ""

    embedder = EmbeddingClient(model=config.EMBEDDING_MODEL)
    reranker = LLMReranker(model=config.RERANK_MODEL)
    retriever = HybridRetriever(conninfo=database_url, embedder=embedder, reranker=reranker)
    results = retriever.search(query, vector_k=config.VECTOR_K, lexical_k=config.LEXICAL_K, final_k=config.TOP_K)
    logger.info("Retrieved %s candidate chunks for query '%s'", len(results), query)
    figures = get_figures_for_chunks(database_url, results)
    answerer = AnswerGenerator(model=config.ANSWER_MODEL, verbosity=config.DEFAULT_VERBOSITY)
    answer = answerer.generate(query, results, max_context_chars=config.MAX_CONTEXT_CHARS)
    payload = {
        "answer": answer,
        "chunks": [r.to_dict() for r in results],
        "figures": [vars(f) for f in figures],
    }

    return json.dumps(payload, indent=2)

