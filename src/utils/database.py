# db.py
"""
Database helpers for RAG PDF ingestion.

Assumes the following tables (names can be adjusted if needed):

CREATE TABLE rag_document (
    id              BIGSERIAL PRIMARY KEY,
    external_id     TEXT UNIQUE,
    title           TEXT,
    description     TEXT,
    source_type     TEXT NOT NULL DEFAULT 'pdf',
    source_uri      TEXT,
    checksum        TEXT,
    total_pages     INTEGER,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE rag_chunk (
    id              BIGSERIAL PRIMARY KEY,
    document_id     BIGINT NOT NULL REFERENCES rag_document(id) ON DELETE CASCADE,
    chunk_index     INTEGER NOT NULL,
    page_start      INTEGER,
    page_end        INTEGER,
    content         TEXT NOT NULL,
    heading         TEXT,
    chunk_type      TEXT NOT NULL DEFAULT 'body',
    embedding       vector(1536),
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX idx_rag_chunk_document_index
    ON rag_chunk (document_id, chunk_index);

CREATE INDEX idx_rag_chunk_document_id
    ON rag_chunk (document_id);
"""

import os
from typing import Any

import psycopg  # psycopg v3

from utils.logger import setup_logger

logger = setup_logger(__name__)


def get_connection() -> psycopg.Connection:
    """
    Returns a synchronous psycopg connection.

    Expects DATABASE_URL to be set, e.g. the Neon connection string.
    """
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        error = "DATABASE_URL environment variable is not set"
        logger.error(error)
        raise RuntimeError(error)
    return psycopg.connect(dsn)


def upsert_document(
    external_id: str,
    title: str | None,
    description: str | None,
    source_uri: str | None,
    checksum: str,
    total_pages: int,
    metadata: dict[str, Any] | None,
) -> int:
    """
    Upsert a row into rag_document and return document_id.

    external_id should be a stable key (e.g., filename, or your own ID).
    """
    if metadata is None:
        metadata = {}

    sql = """
    INSERT INTO rag_document (
        external_id, title, description, source_type,
        source_uri, checksum, total_pages, metadata, updated_at
    )
    VALUES (
        %(external_id)s, %(title)s, %(description)s, 'pdf',
        %(source_uri)s, %(checksum)s, %(total_pages)s, %(metadata)s, now()
    )
    ON CONFLICT (external_id)
    DO UPDATE SET
        title       = EXCLUDED.title,
        description = EXCLUDED.description,
        source_uri  = EXCLUDED.source_uri,
        checksum    = EXCLUDED.checksum,
        total_pages = EXCLUDED.total_pages,
        metadata    = EXCLUDED.metadata,
        updated_at  = now()
    RETURNING id;
    """

    params = {
        "external_id": external_id,
        "title": title,
        "description": description,
        "source_uri": source_uri,
        "checksum": checksum,
        "total_pages": total_pages,
        "metadata": metadata,
    }

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            if row is None:
                error = "Failed to insert or update document"
                logger.error(error)
                raise RuntimeError(error)
            (doc_id,) = row
        conn.commit()
    return int(doc_id)


def replace_chunks(
    document_id: int,
    chunks: list[dict[str, Any]],
) -> None:
    """
    Delete existing chunks for the document and insert the new ones.

    Each chunk dict is expected to contain:
      - chunk_index: int
      - page_start: Optional[int]
      - page_end: Optional[int]
      - content: str
      - heading: Optional[str]
      - chunk_type: str
      - metadata: dict[str, Any]
      - embedding: Optional[list[float]]  (can be None; to be filled later)
    """

    delete_sql = "DELETE FROM rag_chunk WHERE document_id = %(document_id)s;"

    insert_sql = """
    INSERT INTO rag_chunk (
        document_id,
        chunk_index,
        page_start,
        page_end,
        content,
        heading,
        chunk_type,
        embedding,
        metadata
    ) VALUES (
        %(document_id)s,
        %(chunk_index)s,
        %(page_start)s,
        %(page_end)s,
        %(content)s,
        %(heading)s,
        %(chunk_type)s,
        %(embedding)s,
        %(metadata)s
    );
    """

    with get_connection() as conn:
        with conn.cursor() as cur:
            # Remove old chunks
            cur.execute(delete_sql, {"document_id": document_id})

            # Insert new chunks
            for chunk in chunks:
                params = {
                    "document_id": document_id,
                    "chunk_index": chunk["chunk_index"],
                    "page_start": chunk.get("page_start"),
                    "page_end": chunk.get("page_end"),
                    "content": chunk["content"],
                    "heading": chunk.get("heading"),
                    "chunk_type": chunk.get("chunk_type", "body"),
                    # embedding can be None for now; you can backfill later
                    "embedding": chunk.get("embedding"),
                    "metadata": chunk.get("metadata", {}),
                }
                cur.execute(insert_sql, params)

        conn.commit()
