"""PostgreSQL persistence helpers."""

from __future__ import annotations

from contextlib import contextmanager
import logging
from typing import Iterator, Sequence

import psycopg
from pgvector.psycopg import Vector, register_vector
from psycopg.types.json import Jsonb

from .models import DocumentRecord, NodePayload

LOGGER = logging.getLogger(__name__)


class PostgresDocumentStore:
    """Read and write data from PostgreSQL per the documented schema."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def document_exists(self, file_hash: str) -> bool:
        """Return True if the document hash already exists."""

        result = self.fetch_document_id(file_hash)
        return result is not None

    def fetch_document_id(self, file_hash: str) -> int | None:
        """Fetch a document_id by file hash."""

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT document_id FROM documents WHERE file_hash = %s",
                    (file_hash,),
                )
                row = cur.fetchone()
        return row[0] if row else None

    def upsert_document(self, document: DocumentRecord) -> tuple[int, bool]:
        """Insert the document metadata if absent or refresh if it changed.

        Returns:
            Tuple of (document_id, needs_ingest_flag).
        """

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT document_id FROM documents WHERE file_hash = %s",
                    (document.file_hash,),
                )
                existing_by_hash = cur.fetchone()
                if existing_by_hash:
                    LOGGER.info(
                        "Document %s already ingested with matching hash.",
                        document.file_name,
                    )
                    return existing_by_hash[0], False

                cur.execute(
                    "SELECT document_id FROM documents WHERE file_name = %s",
                    (document.file_name,),
                )
                existing_by_name = cur.fetchone()

                if existing_by_name:
                    document_id = existing_by_name[0]
                    LOGGER.info(
                        "Replacing existing document %s (id %s) with new content.",
                        document.file_name,
                        document_id,
                    )
                    cur.execute(
                        "UPDATE documents SET file_hash = %s WHERE document_id = %s",
                        (document.file_hash, document_id),
                    )
                    cur.execute(
                        "DELETE FROM nodes WHERE document_id = %s",
                        (document_id,),
                    )
                    conn.commit()
                    return document_id, True

                cur.execute(
                    """
                    INSERT INTO documents (file_name, file_hash)
                    VALUES (%s, %s)
                    RETURNING document_id
                    """,
                    (document.file_name, document.file_hash),
                )
                row = cur.fetchone()
                if not row:
                    raise RuntimeError("Failed to insert document metadata.")
                document_id = row[0]
                conn.commit()
                LOGGER.info(
                    "Registered document %s with id %s",
                    document.file_name,
                    document_id,
                )
                return document_id, True

    def insert_nodes(
        self,
        document_id: int,
        nodes: Sequence[NodePayload],
    ) -> None:
        """Insert multiple node rows for a document."""

        if not nodes:
            LOGGER.info("No nodes to insert for document %s.", document_id)
            return

        payload = [
            (
                document_id,
                node.text_content,
                Jsonb(node.metadata),
                Vector(list(node.embedding)),
            )
            for node in nodes
        ]

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO nodes (document_id, text_content, metadata, embedding)
                    VALUES (%s, %s, %s, %s)
                    """,
                    payload,
                )
            conn.commit()
        LOGGER.info("Inserted %s nodes for document %s", len(nodes), document_id)

    @contextmanager
    def _connect(self) -> Iterator[psycopg.Connection]:
        """Yield a psycopg connection with pgvector registered."""

        with psycopg.connect(self._dsn) as conn:
            register_vector(conn)
            yield conn
