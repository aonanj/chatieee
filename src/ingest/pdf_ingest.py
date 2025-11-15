# pdf_ingest.py
"""
Ingest and chunk a PDF using pdfplumber and store chunks in Postgres/Neon.

Usage (example):
    DATABASE_URL=... python pdf_ingest.py example_doc.pdf \
        --external-id example_doc_v1 \
        --title "Example Document" \
        --description "First 40 pages of example"

This script:
  - Computes a checksum for the PDF.
  - Extracts per-page text and tables via pdfplumber.
  - Builds body chunks (~max_chars) and table chunks.
  - Upserts rag_document and replaces its rag_chunk rows.
"""

import argparse
import hashlib
from pathlib import Path
from typing import Any

import pdfplumber
from pdfplumber.page import Page

from utils.database import replace_chunks, upsert_document
from utils.logger import setup_logger

logger = setup_logger(__name__)

MAX_CHARS_PER_BODY_CHUNK = 1800  # adjust as needed


def compute_checksum(path: str) -> str:
    """
    Compute SHA-256 checksum of the file for change detection.
    """
    hasher = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def clean_text(text: str) -> str:
    """
    Normalize whitespace and strip leading/trailing spaces.
    """
    # Replace multiple whitespace with single spaces
    return " ".join(text.split()).strip()


def extract_body_paragraphs(page: Page) -> list[str]:
    """
    Extract body text paragraphs from a pdfplumber page.

    This is intentionally simple: we use page.extract_text() and split
    on double newlines as a first-pass approximation of paragraphs.
    You can refine this with layout-aware logic later.
    """
    raw = page.extract_text(x_tolerance=3, y_tolerance=3)
    if not raw:
        logger.info("No text extracted from page.")
        return []

    # pdfplumber usually uses '\n' between lines. We treat '\n\n' as paragraph
    # breaks where they exist, otherwise we just treat the whole page as one block.
    paras = raw.split("\n\n") if "\n\n" in raw else [raw]

    paragraphs: list[str] = []
    for p in paras:
        cleaned = clean_text(p)
        if cleaned:
            paragraphs.append(cleaned)
    return paragraphs


def extract_table_texts(page: Page) -> list[dict[str, Any]]:
    """
    Extract tables from a page and represent them as text chunks.

    Each returned dict:
      - "text": str (markdown-like representation)
      - "metadata": dict (e.g., table_index_on_page)
    """
    table_chunks: list[dict[str, Any]] = []
    tables = page.extract_tables()
    if not tables:
        return table_chunks

    for idx, table in enumerate(tables):
        if not table:
            continue

        # table is a list of rows, each row is a list of cell strings or None
        header = table[0] if len(table) > 0 else None
        rows = table[1:] if len(table) > 1 else []

        lines: list[str] = []

        # Build a markdown-ish representation
        if header:
            header_line = " | ".join((cell or "").strip() for cell in header)
            lines.append(header_line)
            lines.append("-" * len(header_line))

        for row in rows:
            row_line = " | ".join((cell or "").strip() for cell in row)
            lines.append(row_line)

        table_text = "\n".join(lines).strip()
        if not table_text:
            continue

        table_chunks.append(
            {
                "text": table_text,
                "metadata": {
                    "table_index_on_page": idx + 1,
                },
            }
        )

    return table_chunks


def build_chunks_from_pdf(path: str) -> list[dict[str, Any]]:
    """
    Parse the PDF and build chunk dicts ready for DB insertion.

    Returns a list of:
      {
        "chunk_index": int,
        "page_start": int,
        "page_end": int,
        "content": str,
        "heading": Optional[str],
        "chunk_type": "body" | "table",
        "metadata": dict,
        "embedding": None,   # placeholder, to be filled later
      }
    """
    chunks: list[dict[str, Any]] = []

    with pdfplumber.open(path) as pdf:

        # --- Body chunks (text) ---
        buffer: list[str] = []
        buffer_page_start: int | None = None
        buffer_page_end: int | None = None

        chunk_index = 0

        for page_num, page in enumerate(pdf.pages, start=1):
            paragraphs = extract_body_paragraphs(page)
            if not paragraphs:
                continue

            for para in paragraphs:
                if buffer_page_start is None:
                    buffer_page_start = page_num
                buffer_page_end = page_num

                prospective_len = sum(len(p) for p in buffer) + len(buffer) + len(para)
                if prospective_len > MAX_CHARS_PER_BODY_CHUNK and buffer:
                    # Flush current buffer as a chunk
                    body_text = " ".join(buffer).strip()
                    if body_text:
                        chunks.append(
                            {
                                "chunk_index": chunk_index,
                                "page_start": buffer_page_start,
                                "page_end": buffer_page_end,
                                "content": body_text,
                                "heading": None,
                                "chunk_type": "body",
                                "metadata": {},
                                "embedding": None,
                            }
                        )
                        chunk_index += 1

                    # Reset buffer for next chunk
                    buffer = [para]
                    buffer_page_start = page_num
                    buffer_page_end = page_num
                else:
                    buffer.append(para)

        # Flush remainder body buffer
        if buffer:
            body_text = " ".join(buffer).strip()
            if body_text:
                chunks.append(
                    {
                        "chunk_index": chunk_index,
                        "page_start": buffer_page_start,
                        "page_end": buffer_page_end,
                        "content": body_text,
                        "heading": None,
                        "chunk_type": "body",
                        "metadata": {},
                        "embedding": None,
                    }
                )
                chunk_index += 1

        # --- Table chunks ---
        # We do a second pass for tables so they get their own chunks.
        for page_num, page in enumerate(pdf.pages, start=1):
            table_infos = extract_table_texts(page)
            for table_info in table_infos:
                table_text = table_info["text"]
                if not table_text:
                    continue

                chunks.append(
                    {
                        "chunk_index": chunk_index,
                        "page_start": page_num,
                        "page_end": page_num,
                        "content": table_text,
                        "heading": None,
                        "chunk_type": "table",
                        "metadata": {
                            "table_index_on_page": table_info["metadata"][
                                "table_index_on_page"
                            ],
                        },
                        "embedding": None,
                    }
                )
                chunk_index += 1

        # You might want to store num_pages somewhere; we return only chunks here.
        # Caller can separately track total_pages via the pdf object.

    return chunks


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest and chunk a PDF into Neon/Postgres.")
    parser.add_argument("pdf_path", type=str, help="Path to the PDF file to ingest.")
    parser.add_argument(
        "--external-id",
        type=str,
        default=None,
        help="Stable external ID for the document (default: basename of PDF).",
    )
    parser.add_argument(
        "--title",
        type=str,
        default=None,
        help="Title for the document (default: basename without extension).",
    )
    parser.add_argument(
        "--description",
        type=str,
        default=None,
        help="Optional description of the document.",
    )
    parser.add_argument(
        "--source-uri",
        type=str,
        default=None,
        help="Optional URI/URL where the source PDF lives (e.g., S3 URL).",
    )

    args = parser.parse_args()

    pdf_path = args.pdf_path
    if not Path(pdf_path).is_file():
        error = f"PDF file not found: {pdf_path}"
        logger.error(error)
        raise FileNotFoundError(error)

    external_id = args.external_id or Path(pdf_path).name
    title = args.title or Path(pdf_path).stem
    description = args.description
    source_uri = args.source_uri

    checksum = compute_checksum(pdf_path)

    # Open once to count pages
    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)

    # Upsert the document row
    document_id = upsert_document(
        external_id=external_id,
        title=title,
        description=description,
        source_uri=source_uri,
        checksum=checksum,
        total_pages=total_pages,
        metadata={},  # you can add domain-specific fields here
    )

    # Build chunks
    chunks = build_chunks_from_pdf(pdf_path)

    # Upsert chunks (replace all existing chunks for this document)
    replace_chunks(document_id=document_id, chunks=chunks)

    log_info = f"Ingested document_id={document_id}, total_pages={total_pages}"
    logger.info(log_info)
    log_info = f"chunks_inserted={len(chunks)}"
    logger.info(log_info)


if __name__ == "__main__":
    main()
