from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

import psycopg
from psycopg import sql as _sql
from psycopg.types.json import Jsonb

from src import config

from .embedding import EmbeddingClient, embedding_to_pgvector

logger = config.LOGGER

@dataclass(slots=True)
class ChunkRow:
    id: int
    document_id: int
    content: str
    metadata: dict[str, Any]
    needs_update: bool = True

@dataclass(slots=True)
class StructureState:
    heading: str | None = None
    section: str | None = None
    subsection: str | None = None
    page_number: int | None = None
    page_span: tuple[int, ...] = ()
    def to_metadata(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        hierarchy: list[str] = []
        if self.heading:
            payload["heading"] = self.heading
            hierarchy.append(self.heading)
        if self.section:
            payload["section"] = self.section
            hierarchy.append(self.section)
        if self.subsection:
            payload["subsection"] = self.subsection
            hierarchy.append(self.subsection)
        if hierarchy:
            payload["section_hierarchy"] = hierarchy
        if self.page_number is not None:
            payload["page_number"] = self.page_number
        if self.page_span:
            payload["page_numbers"] = list(self.page_span)
        return payload

class StructureTracker:
    """Track headings, sections, and page numbers across a document."""
    STRUCTURE_RE = re.compile(
        r"^\s*(?:Section\s+)?(?P<num>\d+(?:\.\d+){0,3})[\.)]?\s+(?P<title>[A-Za-z0-9][^\n]*)$",
        re.IGNORECASE,
    )
    ALT_HEADING_RE = re.compile(r"^[A-Z][A-Z0-9 /&'\-]{3,}$")
    PAGE_PATTERNS = (
        re.compile(r"(?i)\bpage\s+(?P<page>\d{1,4})\b"),
        re.compile(r"(?i)\bpg\.\s*(?P<page>\d{1,4})\b"),
        re.compile(r"(?i)\bp\.\s*(?P<page>\d{1,4})\b"),
        re.compile(r"^\s*-{0,3}\s*(?P<page>\d{1,4})\s*-{0,3}\s*$"),
    )
    def __init__(self) -> None:
        self._state = StructureState()
    def reset(self) -> None:
        self._state = StructureState()
    def consume(self, content: str) -> dict[str, Any]:
        pages = self._extract_page_numbers(content)
        if pages:
            ordered = tuple(sorted(set(pages)))
            self._state.page_span = ordered
            self._state.page_number = ordered[0]
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            matched_page = self._match_page_number(stripped)
            if matched_page is not None:
                self._state.page_number = matched_page
                self._state.page_span = tuple(sorted({matched_page, *self._state.page_span}))
                continue
            match = self.STRUCTURE_RE.match(stripped)
            if match:
                numbering = match.group("num")
                title = match.group("title").strip().rstrip(". ")
                label = f"{numbering} {title}".strip()
                self._update_hierarchy(numbering, label)
                continue
            if self.ALT_HEADING_RE.match(stripped):
                formatted = stripped.title()
                self._state.heading = formatted
                self._state.section = None
                self._state.subsection = None
        return self._state.to_metadata()
    def _match_page_number(self, line: str) -> int | None:
        for pattern in self.PAGE_PATTERNS:
            match = pattern.search(line)
            if match:
                page = match.group("page")
                try:
                    return int(page)
                except ValueError:
                    continue
        return None
    def _extract_page_numbers(self, content: str) -> list[int]:
        pages: list[int] = []
        for pattern in self.PAGE_PATTERNS:
            for match in pattern.finditer(content):
                raw = match.group("page")
                try:
                    pages.append(int(raw))
                except ValueError:
                    continue
        return pages
    def _update_hierarchy(self, numbering: str, label: str) -> None:
        segments = [segment for segment in numbering.split(".") if segment]
        if not segments:
            return
        if len(segments) == 1:
            self._state.heading = label
            self._state.section = None
            self._state.subsection = None
        elif len(segments) == 2:
            if self._state.heading is None:
                self._state.heading = f"{segments[0]}. {label}" if segments[0] not in label else label
            self._state.section = label
            self._state.subsection = None
        else:
            if self._state.heading is None:
                self._state.heading = f"{segments[0]} {label}"
            if self._state.section is None:
                parent = ".".join(segments[:2])
                self._state.section = f"{parent} {label.split(' ', 1)[-1]}" if " " in label else parent
            self._state.subsection = label

class ChunkUpdater:
    START_HEADING_RE = re.compile(r"\b1[\.\)]?\s*overview\b", re.IGNORECASE)

    def __init__(self, conninfo: str, batch_size: int = 64, embedding_model: str | None = None) -> None:
        self.conninfo = conninfo
        self.batch_size = batch_size
        self.embedder = EmbeddingClient(model=embedding_model)
        self._header_patterns = self._build_literal_patterns(config.DOCUMENT_HEADERS)
        self._footer_patterns = self._build_literal_patterns(config.DOCUMENT_FOOTERS)

    def run(self, limit: int | None = None, only_missing_embeddings: bool = False) -> int:
        logger.info(
            "Starting chunk update job",
            extra={"limit": limit, "only_missing_embeddings": only_missing_embeddings},
        )
        with psycopg.connect(self.conninfo) as conn:
            conn.execute("SET statement_timeout TO '10min'")
            tracker = StructureTracker()
            batch: list[tuple[str, str, Jsonb, int]] = []
            processed = 0
            current_document: int | None = None
            document_rows: list[ChunkRow] = []
            query_parts = [
                "SELECT id, document_id, COALESCE(chunk_index, id) AS order_index,",
                "content, COALESCE(metadata, '{}'::jsonb) AS metadata,",
                "embedding IS NULL AS needs_update",
                "FROM rag_chunk",
            ]
            params: tuple[int, ...] | None = None
            if only_missing_embeddings:
                query_parts.append(
                    "WHERE document_id IN (SELECT DISTINCT document_id FROM rag_chunk WHERE embedding IS NULL)"
                )
            query_parts.append("ORDER BY document_id, order_index")
            if limit:
                query_parts.append("LIMIT %s")
                params = (int(limit),)
            query = " ".join(query_parts)
            with conn.cursor() as cur:
                cur.execute(_sql.SQL(query), params)    # type: ignore
                for row in cur:
                    chunk = ChunkRow(
                        id=row[0],
                        document_id=row[1],
                        content=row[3] or "",
                        metadata=row[4] or {},
                        needs_update=bool(row[5]),
                    )
                    if current_document is None:
                        current_document = chunk.document_id
                    if chunk.document_id != current_document:
                        processed += self._process_document(
                            conn,
                            tracker,
                            document_rows,
                            batch,
                            update_missing_only=only_missing_embeddings,
                        )
                        document_rows = [chunk]
                        current_document = chunk.document_id
                    else:
                        document_rows.append(chunk)
                if document_rows:
                    processed += self._process_document(
                        conn,
                        tracker,
                        document_rows,
                        batch,
                        update_missing_only=only_missing_embeddings,
                    )
            if batch:
                self._flush_batch(conn, batch)
            conn.commit()
        logger.info(
            "Completed chunk update job",
            extra={"chunks": processed, "only_missing_embeddings": only_missing_embeddings},
        )
        return processed

    def _process_document(
        self,
        conn: psycopg.Connection[Any],
        tracker: StructureTracker,
        rows: list[ChunkRow],
        batch: list[tuple[str, str, Jsonb, int]],
        update_missing_only: bool,
    ) -> int:
        filtered = self._prepare_rows(rows)
        if not filtered:
            document_id = rows[0].document_id if rows else None
            logger.info(
                "Skipping document_id=%s during chunk update because no eligible content was found after filtering",
                document_id,
            )
            return 0

        tracker.reset()
        updated = 0
        for chunk in filtered:
            updates = tracker.consume(chunk.content)
            merged = self._merge_metadata(chunk.metadata, updates)
            if update_missing_only and not chunk.needs_update:
                continue
            embedding = self.embedder.embed(chunk.content)
            pgvector = embedding_to_pgvector(embedding.vector)
            batch.append((pgvector, chunk.content, Jsonb(merged or {}), chunk.id))
            updated += 1
            if len(batch) >= self.batch_size:
                self._flush_batch(conn, batch)
        return updated

    def _flush_batch(self, conn: psycopg.Connection[Any], batch: list[tuple[str, str, Jsonb, int]]) -> None:
        logger.info("Flushing %s chunk updates", len(batch))
        with conn.cursor() as cur:
            cur.executemany(
                """
                UPDATE rag_chunk
                   SET embedding = %s::vector,
                       content = %s,
                       metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb
                 WHERE id = %s
                """,
                batch,
            )
        conn.commit()
        batch.clear()

    def _merge_metadata(self, existing: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
        merged = dict(existing or {})
        for key, value in updates.items():
            if value is None:
                continue
            if key == "page_numbers":
                merged[key] = value
                if value and "page_number" not in updates:
                    merged.setdefault("page_number", value[0])
            else:
                merged[key] = value
        return merged

    def _prepare_rows(self, rows: list[ChunkRow]) -> list[ChunkRow]:
        filtered: list[ChunkRow] = []
        start_found = False
        for chunk in rows:
            cleaned = self._strip_headers_and_footers(chunk.content)
            if not cleaned:
                continue
            if not start_found:
                match = self.START_HEADING_RE.search(cleaned)
                if not match:
                    continue
                start_found = True
                cleaned = cleaned[match.start():].lstrip()
                if not cleaned:
                    continue
            chunk.content = cleaned
            filtered.append(chunk)
        return filtered

    def _strip_headers_and_footers(self, content: str) -> str:
        if not content:
            return ""
        cleaned = content
        for pattern in self._header_patterns:
            cleaned = pattern.sub(" ", cleaned)
        for pattern in self._footer_patterns:
            cleaned = pattern.sub(" ", cleaned)
        return cleaned.strip()

    @staticmethod
    def _build_literal_patterns(values: list[str]) -> tuple[re.Pattern[str], ...]:
        patterns: list[re.Pattern[str]] = []
        for value in values:
            if not value:
                continue
            trimmed = value.strip()
            if not trimmed:
                continue
            tokens = [token for token in re.split(r"\s+", trimmed) if token]
            if not tokens:
                continue
            token_pattern = r"\s+".join(re.escape(token) for token in tokens)
            patterns.append(re.compile(token_pattern, re.IGNORECASE | re.DOTALL | re.MULTILINE))
        return tuple(patterns)

def embed_and_update_chunks():
    database_url = config.DATABASE_URL
    batch_size = config.CHUNK_UPDATE_BATCH_SIZE
    embedding_model = config.EMBEDDING_MODEL

    if not database_url:
        error = "DATABASE_URL must be provided"
        logger.error(error)
        raise SystemExit(error)

    updater = ChunkUpdater(
        conninfo=database_url,
        batch_size=batch_size,
        embedding_model=embedding_model,
    )
    return updater.run(limit=None)


def backfill_missing_chunk_embeddings(limit: int | None = None) -> int:
    database_url = config.DATABASE_URL
    batch_size = config.CHUNK_UPDATE_BATCH_SIZE
    embedding_model = config.EMBEDDING_MODEL

    if not database_url:
        error = "DATABASE_URL must be provided"
        logger.error(error)
        raise SystemExit(error)

    updater = ChunkUpdater(
        conninfo=database_url,
        batch_size=batch_size,
        embedding_model=embedding_model,
    )
    return updater.run(limit=limit, only_missing_embeddings=True)
