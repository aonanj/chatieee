"""Shared dataclasses and type aliases."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

JsonDict = dict[str, Any]


@dataclass(slots=True)
class DocumentRecord:
    """Metadata about an ingested document."""

    path: Path
    file_name: str
    file_hash: str
    document_id: int | None = None


@dataclass(slots=True)
class PageText:
    """Text extracted from a single PDF page."""

    page_number: int
    text: str


@dataclass(slots=True)
class ParsedDocument:
    """Representation of a parsed PDF document."""

    document: DocumentRecord
    pages: list[PageText]


@dataclass(slots=True)
class Chunk:
    """A textual chunk produced by the splitter."""

    index: int
    text: str
    section_title: str | None
    page_span: tuple[int, int]


@dataclass(slots=True)
class NodePayload:
    """Data ready to be written into the nodes table."""

    text_content: str
    metadata: JsonDict
    embedding: Sequence[float]


__all__ = [
    "Chunk",
    "DocumentRecord",
    "JsonDict",
    "NodePayload",
    "ParsedDocument",
    "PageText",
]
