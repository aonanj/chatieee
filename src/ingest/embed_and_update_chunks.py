# embed_and_update_chunks.py
"""
Batch job to compute embeddings for rag_chunk rows where embedding IS NULL.

Usage examples:

    # Embed up to 500 chunks across all documents
    DATABASE_URL=... OPENAI_API_KEY=... python embed_and_update_chunks.py --max-chunks 500

    # Embed up to 200 chunks for a single document
    DATABASE_URL=... OPENAI_API_KEY=... python embed_and_update_chunks.py --document-id 42 --max-chunks 200

Environment variables:
    DATABASE_URL      - Neon/Postgres connection string
    OPENAI_API_KEY    - OpenAI API key
    EMBEDDING_MODEL   - (optional) defaults to "text-embedding-3-small"
"""

import argparse
import os
from typing import Any

from openai import OpenAI
from pgvector.psycopg import register_vector
import psycopg

from utils.database import get_connection
from utils.logger import setup_logger

logger = setup_logger(__name__)


def get_client() -> OpenAI:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        error = "OPENAI_API_KEY environment variable is not set"
        logger.error(error)
        raise RuntimeError(error)
    return OpenAI(api_key=api_key)


def fetch_chunks_to_embed(
    conn: psycopg.Connection,
    document_id: int | None,
    max_chunks: int,
) -> list[tuple[int, str]]:
    """
    Fetch chunk ids and content for rows where embedding IS NULL.

    Returns list of (chunk_id, content).
    """
    sql = """
    SELECT id, content
    FROM rag_chunk
    WHERE embedding IS NULL
    """
    params: dict[str, Any] = {}
    if document_id is not None:
        sql += " AND document_id = %(document_id)s"
        params["document_id"] = document_id

    sql += " ORDER BY id LIMIT %(limit)s"
    params["limit"] = max_chunks

    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    return [(int(r[0]), r[1]) for r in rows]


def embed_texts(
    client: OpenAI,
    texts: list[str],
    model: str,
) -> list[list[float]]:
    """
    Call OpenAI embedding API for a batch of texts.
    """
    if not texts:
        return []

    resp = client.embeddings.create(
        model=model,
        input=texts,
    )
    # Ensure ordering is preserved
    vectors: list[list[float]] = [d.embedding for d in resp.data]
    return vectors


def update_embeddings(
    conn: psycopg.Connection,
    chunk_ids: list[int],
    vectors: list[list[float]],
) -> None:
    """
    Update rag_chunk.embedding for corresponding chunk_ids.

    Assumes pgvector adapter is registered on this connection.
    """
    if not chunk_ids:
        return
    if len(chunk_ids) != len(vectors):
        error = "chunk_ids and vectors length mismatch"
        logger.error(error)
        raise ValueError(error)

    sql = """
    UPDATE rag_chunk
    SET embedding = %(embedding)s
    WHERE id = %(id)s
    """

    with conn.cursor() as cur:
        for chunk_id, vec in zip(chunk_ids, vectors, strict=True):
            params = {
                "id": chunk_id,
                "embedding": vec,  # pgvector adapter will handle list[float]
            }
            cur.execute(sql, params)

    conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Embed and update rag_chunk rows with NULL embedding.")
    parser.add_argument(
        "--document-id",
        type=int,
        default=None,
        help="Optional document_id to restrict embedding to a single document.",
    )
    parser.add_argument(
        "--max-chunks",
        type=int,
        default=512,
        help="Maximum number of chunks to embed in this run (default: 512).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=64,
        help="Embedding API batch size (default: 64).",
    )
    args = parser.parse_args()

    embedding_model = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")

    client = get_client()

    # Get DB connection and register pgvector adapter
    with get_connection() as conn:
        register_vector(conn)

        # Fetch up to max_chunks to embed
        rows = fetch_chunks_to_embed(
            conn=conn,
            document_id=args.document_id,
            max_chunks=args.max_chunks,
        )

        if not rows:
            logger.info("No chunks with NULL embedding found.")
            return

        log_info = f"Found {len(rows)} chunks to embed."
        logger.info(log_info)

        # Process in batches
        total_processed = 0
        for i in range(0, len(rows), args.batch_size):
            batch = rows[i : i + args.batch_size]
            chunk_ids = [row[0] for row in batch]
            texts = [row[1] for row in batch]

            # Optionally, you could truncate overly long texts here, but
            # if your chunker is sane they should already be within model limits.
            vectors = embed_texts(
                client=client,
                texts=texts,
                model=embedding_model,
            )

            update_embeddings(
                conn=conn,
                chunk_ids=chunk_ids,
                vectors=vectors,
            )

            total_processed += len(chunk_ids)
            log_info = f"Processed batch {i // args.batch_size + 1}, chunks={len(chunk_ids)}, total_processed={total_processed}"
            logger.info(log_info)

        log_info = f"Done. Total chunks embedded this run: {total_processed}"
        logger.info(log_info)


if __name__ == "__main__":
    main()
