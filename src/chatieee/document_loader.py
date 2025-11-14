"""Utilities for loading and hashing PDF documents."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from pypdf import PdfReader

from .models import DocumentRecord, PageText, ParsedDocument

LOGGER = logging.getLogger(__name__)


class PDFDocumentLoader:
    """Load PDF files into memory and extract per-page text."""

    def load(self, path: Path) -> ParsedDocument:
        """Read a PDF file and return a structured representation.

        Args:
            path: Path to the PDF file.

        Returns:
            ParsedDocument: Structured document with metadata and pages.

        Raises:
            FileNotFoundError: If the supplied path does not exist.
            ValueError: If no textual content was found in the PDF.
        """

        if not path.exists():
            raise FileNotFoundError(f"Document {path} does not exist.")

        file_hash = _hash_file(path)
        document = DocumentRecord(
            path=path,
            file_name=path.name,
            file_hash=file_hash,
        )

        LOGGER.info("Loading document %s", path)
        reader = PdfReader(path)
        pages = []
        for index, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            text = text.strip()
            if not text:
                LOGGER.debug(
                    "Page %s of %s did not yield text; placeholder added.",
                    index,
                    path,
                )
            pages.append(PageText(page_number=index, text=text))

        if not any(page.text for page in pages):
            raise ValueError(f"Document {path} did not contain extractable text.")

        return ParsedDocument(document=document, pages=pages)


def _hash_file(path: Path) -> str:
    """Compute the SHA-256 hash of a file."""

    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
