"""Utilities for deriving section-aware text chunks."""

from __future__ import annotations

import logging
import re
from typing import Iterable, Sequence

from .models import Chunk, PageText

LOGGER = logging.getLogger(__name__)


class SectionAwareTextSplitter:
    """Split page text while respecting headings and overlap constraints."""

    HEADING_PATTERN = re.compile(r"^\s*(\d+(\.\d+)*)?\s*[A-Z][A-Z0-9 ,\-]{3,}$")

    def __init__(self, max_chars: int = 1500, overlap_chars: int = 200) -> None:
        if max_chars <= 0:
            raise ValueError("max_chars must be positive.")
        if overlap_chars < 0:
            raise ValueError("overlap_chars must be >= 0.")
        self.max_chars = max_chars
        self.overlap_chars = overlap_chars

    def split(self, pages: Sequence[PageText]) -> list[Chunk]:
        """Split the given pages into `Chunk` objects."""

        chunks: list[Chunk] = []
        buffer: list[str] = []
        buffer_chars = 0
        buffer_start_page: int | None = None
        current_section: str | None = None
        chunk_index = 0
        last_page_number = 1

        for page in pages:
            last_page_number = page.page_number
            for paragraph in _paragraphs(page.text):
                if not paragraph:
                    continue
                if self._looks_like_heading(paragraph):
                    if buffer:
                        chunks.append(
                            self._emit_chunk(
                                chunk_index,
                                buffer,
                                buffer_start_page or page.page_number,
                                page.page_number,
                                current_section,
                            ),
                        )
                        chunk_index += 1
                        buffer = []
                        buffer_chars = 0
                        buffer_start_page = None
                    current_section = paragraph.strip()
                    buffer_start_page = page.page_number
                    continue

                if buffer_start_page is None:
                    buffer_start_page = page.page_number

                buffer.append(paragraph)
                buffer_chars += len(paragraph)

                if buffer_chars >= self.max_chars:
                    chunks.append(
                        self._emit_chunk(
                            chunk_index,
                            buffer,
                            buffer_start_page,
                            page.page_number,
                            current_section,
                        ),
                    )
                    chunk_index += 1
                    buffer, buffer_chars = self._with_overlap(buffer)
                    buffer_start_page = page.page_number

        if buffer:
            chunks.append(
                self._emit_chunk(
                    chunk_index,
                    buffer,
                    buffer_start_page or last_page_number,
                    last_page_number,
                    current_section,
                ),
            )

        return chunks

    def _with_overlap(self, buffer: list[str]) -> tuple[list[str], int]:
        """Return an overlapped buffer and its size."""

        if not buffer or self.overlap_chars == 0:
            return [], 0

        text = "\n\n".join(buffer)
        overlap_text = text[-self.overlap_chars :]
        return [overlap_text], len(overlap_text)

    def _emit_chunk(
        self,
        index: int,
        paragraphs: list[str],
        start_page: int,
        end_page: int,
        section_title: str | None,
    ) -> Chunk:
        """Create a chunk from the buffered paragraphs."""

        text = "\n\n".join(paragraphs).strip()
        LOGGER.debug(
            "Emitting chunk %s covering pages %s-%s with section %s",
            index,
            start_page,
            end_page,
            section_title,
        )
        return Chunk(
            index=index,
            text=text,
            section_title=section_title,
            page_span=(start_page, end_page),
        )

    def _looks_like_heading(self, value: str) -> bool:
        """Return True if the given paragraph looks like a heading."""

        stripped = value.strip()
        if len(stripped.split()) <= 1 and stripped.isupper():
            return True
        return bool(self.HEADING_PATTERN.match(stripped))


def _paragraphs(text: str) -> Iterable[str]:
    """Split text into normalized paragraphs."""

    for candidate in text.splitlines():
        stripped = candidate.strip()
        if stripped:
            yield stripped
