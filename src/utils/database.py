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

import asyncio
from collections.abc import AsyncIterator, Iterable
from typing import Any
from uuid import uuid4

import psycopg
from psycopg import OperationalError
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from src import config

logger = config.LOGGER
_pool: AsyncConnectionPool | None = None
_MAX_RETRIES = 5
_BASE_BACKOFF = 0.1
_RECOVERABLE_SUBSTRINGS: tuple[str, ...] = (
    "ssl connection has been closed unexpectedly",
    "server closed the connection unexpectedly",
    "connection already closed",
    "connection not open",
)


def _iter_causes(exc: BaseException) -> Iterable[BaseException]:
    """Yield the exception and its causes."""
    current: BaseException | None = exc
    while current is not None:
        yield current
        current = current.__cause__  # type: ignore[attr-defined]

def _jsonb(value: Any | None) -> Jsonb:
    """Wrap Python values so psycopg knows they target a JSONB column."""
    return Jsonb({} if value is None else value)

async def _reset_pool(bad_pool: AsyncConnectionPool | None) -> None:
    """Close and clear the cached pool so the next call recreates it."""
    global _pool
    if bad_pool is None:
        return
    try:
        await bad_pool.close()
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("Error closing connection pool after failure: %s", exc)
    finally:
        _pool = None

def init_pool() -> AsyncConnectionPool:
    """Initialize a global async connection pool.

    Returns:
        A configured `AsyncConnectionPool`.
    """
    global _pool
    if _pool is None:
        dsn = config.DATABASE_URL or ""
        _pool = AsyncConnectionPool(
            conninfo=dsn,
            min_size=1,
            max_size=10,
            kwargs={"autocommit": False},
        )
    return _pool

async def reset_pool() -> None:
    """Explicitly reset the cached pool."""
    await _reset_pool(_pool)


async def get_conn() -> AsyncIterator[psycopg.AsyncConnection]:
    """Yield an async connection from the pool with a transaction.

    Handles dropped SSL connections by recreating the pool with backoff.
    """
    attempt = 0
    last_error: OperationalError | None = None

    while attempt < _MAX_RETRIES:
        pool = init_pool()
        try:
            async with pool.connection() as conn, conn.transaction():
                yield conn
        except OperationalError as exc:
            attempt += 1
            last_error = exc
            if not is_recoverable_operational_error(exc):
                raise
            logger.error(
                "Recoverable database connection error (attempt %s/%s): %s",
                attempt,
                _MAX_RETRIES,
                exc,
            )
            await _reset_pool(pool)
            await asyncio.sleep(min(_BASE_BACKOFF * attempt, 1.0))
        except Exception:
            # Propagate non-connection errors immediately
            raise
        else:
            return

    # Only reached if all attempts failed with a recoverable OperationalError
    assert last_error is not None
    raise last_error

def get_connection() -> psycopg.Connection:
    """
    Returns a synchronous psycopg connection.

    Expects DATABASE_URL to be set, e.g. the Neon connection string.
    """
    dsn = config.DATABASE_URL
    if not dsn:
        error = "DATABASE_URL environment variable is not set"
        logger.error(error)
        raise RuntimeError(error)
    return psycopg.connect(dsn)

def insert_figures(
    document_id: int,
    figures: list[dict[str, Any]],
) -> None:
    """
    Insert one or more figures for a document.

    Each figure dict:
      - figure_label: str
      - page_number: Optional[int]
      - caption: Optional[str]
      - image_uri: str
      - metadata: Optional[dict]
    """
    if not figures:
        return

    sql = """
    INSERT INTO rag_figure (
        document_id,
        figure_label,
        page_number,
        caption,
        image_uri,
        metadata
    ) VALUES (
        %(document_id)s,
        %(figure_label)s,
        %(page_number)s,
        %(caption)s,
        %(image_uri)s,
        %(metadata)s
    )
    ON CONFLICT (document_id, figure_label)
    DO UPDATE SET
        page_number = EXCLUDED.page_number,
        caption     = EXCLUDED.caption,
        image_uri   = EXCLUDED.image_uri,
        metadata    = EXCLUDED.metadata;
    """
    logger.info("Upserting %d figures for document_id=%d", len(figures), document_id)
    with get_connection() as conn:
        with conn.cursor() as cur:
            for fig in figures:
                params = {
                    "document_id": document_id,
                    "figure_label": fig["figure_label"],
                    "page_number": fig.get("page_number"),
                    "caption": fig.get("caption"),
                    "image_uri": fig["image_uri"],
                    "metadata": _jsonb(fig.get("metadata")),
                }
                cur.execute(sql, params)
        conn.commit()

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
        "metadata": _jsonb(metadata),
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
                    "metadata": _jsonb(chunk.get("metadata")),
                }
                cur.execute(insert_sql, params)

        conn.commit()


def replace_document_pages(
    document_id: int,
    pages: list[dict[str, Any]],
) -> None:
    """
    Replace rag_document_page rows for a document with the provided payload.

    Each page dict should include:
      - page_number: int
      - image_uri: str
      - metadata: dict[str, Any] | None
    """
    delete_sql = "DELETE FROM rag_document_page WHERE document_id = %(document_id)s;"
    insert_sql = """
    INSERT INTO rag_document_page (
        document_id,
        page_number,
        image_uri,
        metadata
    ) VALUES (
        %(document_id)s,
        %(page_number)s,
        %(image_uri)s,
        %(metadata)s
    );
    """

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(delete_sql, {"document_id": document_id})
            for page in pages:
                params = {
                    "document_id": document_id,
                    "page_number": page["page_number"],
                    "image_uri": page["image_uri"],
                    "metadata": _jsonb(page.get("metadata")),
                }
                cur.execute(insert_sql, params)
        conn.commit()


def is_recoverable_operational_error(exc: BaseException) -> bool:
    """Return True when the error represents a dropped database connection."""
    if not isinstance(exc, psycopg.OperationalError):
        return False

    for candidate in _iter_causes(exc):
        message = " ".join(
            part for part in (str(candidate), getattr(candidate, "pgerror", None)) if part
        ).lower()
        if any(token in message for token in _RECOVERABLE_SUBSTRINGS):
            return True
    return False

def create_ingestion_run(document_id: int) -> str:
    """
    Create a new ingestion run record and return its ID (UUID).
    """
    run_id = str(uuid4())
    sql = """
    INSERT INTO rag_ingestion_run (id, document_id, status, started_at)
    VALUES (%(id)s, %(document_id)s, 'processing', now());
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {"id": run_id, "document_id": document_id})
        conn.commit()
    return run_id

def update_ingestion_status(run_id: str, status: str, error_message: str | None = None) -> None:
    """
    Update the status of an ingestion run.
    """
    sql = """
    UPDATE rag_ingestion_run
    SET status = %(status)s,
        error_message = %(error_message)s,
        finished_at = (CASE WHEN %(status)s IN ('completed', 'failed') THEN now() ELSE finished_at END)
    WHERE id = %(id)s;
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {"id": run_id, "status": status, "error_message": error_message})
        conn.commit()

def get_ingestion_run(run_id: str) -> dict[str, Any] | None:
    """
    Fetch the status of an ingestion run.
    """
    sql = """
    SELECT id, document_id, status, error_message
    FROM rag_ingestion_run
    WHERE id = %(id)s;
    """
    with get_connection() as conn, conn.cursor() as cur:
            cur.execute(sql, {"id": run_id})
            row = cur.fetchone()
    if row:
        return {
            "id": row[0],
            "document_id": row[1],
            "status": row[2],
            "error_message": row[3],
        }
    return None
