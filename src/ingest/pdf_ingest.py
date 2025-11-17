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

from collections.abc import Callable, Sequence
import hashlib
from io import BytesIO
from pathlib import Path
import re
from typing import Any

import pdfplumber
from pdfplumber.page import Page

from src import config
from src.ingest.embed_and_update_chunks import embed_and_update_chunks
from src.utils.database import (
    insert_figures,
    replace_chunks,
    replace_document_pages,
    upsert_document,
)
from src.utils.storage import upload_image_fn

logger = config.LOGGER

MAX_CHARS_PER_BODY_CHUNK = 1800

# Figure captions use an em dash after the label (e.g., "Figure 9-22c—").
FIGURE_LABEL_RE = re.compile(
    r"\b(FIG(?:URE)?\.?\s*(?:[A-Z]+(?:[.\-]\s*)?)?\d+(?:[.\-–]\d+)*(?:[A-Za-z]+)?)\s*(?=[—–])",
    re.IGNORECASE,
)

CAPTION_LINE_GAP = 8.0  # Max vertical gap (points) allowed between caption lines
MIN_FIGURE_HEIGHT = 40.0
MAX_FIGURE_HEIGHT_RATIO = 0.55  # Of total page height
MAX_FIGURE_HEIGHT = 360.0  # Absolute cap on search height
FIGURE_WIDTH_PADDING = 12.0  # Minimum width padding (pts)
FIGURE_WIDTH_PADDING_RATIO = 0.35  # Proportional padding per figure width
FIGURE_HEIGHT_PADDING = 20.0  # Vertical padding (pts) when rendering crops


def _group_words_into_lines(words: list[dict[str, Any]], line_tol: float = 2.5) -> list[dict[str, Any]]:
    """Group pdfplumber words into lines in reading order."""
    if not words:
        return []

    lines: list[dict[str, Any]] = []
    sorted_words = sorted(words, key=lambda w: (round(w["top"], 1), w["x0"]))
    for word in sorted_words:
        text = (word.get("text") or "").strip()
        if not text:
            continue

        if not lines or abs(float(word["top"]) - lines[-1]["top"]) > line_tol:
            lines.append(
                {
                    "words": [word],
                    "top": float(word["top"]),
                    "bottom": float(word["bottom"]),
                    "x0": float(word["x0"]),
                    "x1": float(word["x1"]),
                }
            )
            continue

        line = lines[-1]
        line["words"].append(word)
        line["top"] = min(line["top"], float(word["top"]))
        line["bottom"] = max(line["bottom"], float(word["bottom"]))
        line["x0"] = min(line["x0"], float(word["x0"]))
        line["x1"] = max(line["x1"], float(word["x1"]))

    for line in lines:
        ordered_words = sorted(line["words"], key=lambda w: w["x0"])
        line["text"] = " ".join(w["text"] for w in ordered_words).strip()

    return [line for line in lines if line["text"]]


def _extract_caption_candidates(page: Page) -> list[dict[str, Any]]:
    """Detect figure captions by locating lines that start with 'Figure'."""
    try:
        words = page.extract_words(x_tolerance=2, y_tolerance=2)
    except TypeError:
        words = page.extract_words()

    lines = _group_words_into_lines(words)
    captions: list[dict[str, Any]] = []
    idx = 0

    while idx < len(lines):
        line = lines[idx]
        match = FIGURE_LABEL_RE.match(line["text"])
        if not match:
            idx += 1
            continue

        figure_label = normalise_figure_label(match.group(1))
        caption_lines = [line]
        j = idx + 1
        while (
            j < len(lines)
            and lines[j]["top"] - caption_lines[-1]["bottom"] <= CAPTION_LINE_GAP
            and not FIGURE_LABEL_RE.match(lines[j]["text"])
        ):
            caption_lines.append(lines[j])
            j += 1

        caption_text = " ".join(l["text"] for l in caption_lines).strip()
        caption_bbox = (
            min(l["x0"] for l in caption_lines),
            min(l["top"] for l in caption_lines),
            max(l["x1"] for l in caption_lines),
            max(l["bottom"] for l in caption_lines),
        )

        captions.append(
            {
                "figure_label": figure_label,
                "caption_text": caption_text,
                "caption_bbox": caption_bbox,
            }
        )
        idx = j

    return captions


def _gather_vector_boxes(page: Page) -> list[tuple[float, float, float, float]]:
    """Collect bounding boxes for shapes (rects/lines/curves) drawn on a page."""
    boxes: list[tuple[float, float, float, float]] = []

    for rect in getattr(page, "rects", []):
        boxes.append((float(rect["x0"]), float(rect["top"]), float(rect["x1"]), float(rect["bottom"])))

    for line in getattr(page, "lines", []):
        x0 = min(float(line["x0"]), float(line["x1"]))
        x1 = max(float(line["x0"]), float(line["x1"]))
        top = min(float(line["y0"]), float(line["y1"]))
        bottom = max(float(line["y0"]), float(line["y1"]))
        boxes.append((x0, top, x1, bottom))

    for curve in getattr(page, "curves", []):
        pts = curve.get("pts")
        if not pts:
            continue
        xs = [float(pt[0]) for pt in pts]
        ys = [float(pt[1]) for pt in pts]
        boxes.append((min(xs), min(ys), max(xs), max(ys)))

    return boxes


def _collect_image_boxes(page: Page) -> list[tuple[float, float, float, float]]:
    """Collect bounding boxes for raster images embedded in the page."""
    boxes: list[tuple[float, float, float, float]] = []
    for image in getattr(page, "images", []):
        boxes.append(
            (
                float(image["x0"]),
                float(image["top"]),
                float(image["x1"]),
                float(image["bottom"]),
            )
        )
    return boxes


def _build_figure_bbox(
    page: Page,
    caption_bbox: tuple[float, float, float, float],
    graphic_boxes: list[tuple[float, float, float, float]],
    min_top: float,
) -> tuple[float, float, float, float] | None:
    """Estimate the figure bounding box located above a caption."""
    if not graphic_boxes:
        return None

    caption_top = caption_bbox[1]
    search_bottom = max(min(float(page.height) - 1, caption_top - 2), min_top + 1)
    max_height = min(float(page.height) * MAX_FIGURE_HEIGHT_RATIO, MAX_FIGURE_HEIGHT)
    search_top = max(min_top, search_bottom - max_height)

    if search_bottom <= search_top:
        return None

    region_boxes: list[tuple[float, float, float, float]] = []
    for x0, top, x1, bottom in graphic_boxes:
        if bottom <= search_top or top >= search_bottom:
            continue
        region_boxes.append(
            (
                max(0.0, x0),
                max(search_top, top),
                min(float(page.width), x1),
                min(search_bottom, bottom),
            )
        )

    if not region_boxes:
        return None

    bbox = (
        max(0.0, min(b[0] for b in region_boxes) - 6),
        max(search_top, min(b[1] for b in region_boxes) - 6),
        min(float(page.width), max(b[2] for b in region_boxes) + 6),
        min(search_bottom, max(b[3] for b in region_boxes) + 6),
    )

    height = bbox[3] - bbox[1]
    if height < MIN_FIGURE_HEIGHT:
        needed = MIN_FIGURE_HEIGHT - height
        bbox = (
            bbox[0],
            max(search_top, bbox[1] - needed),
            bbox[2],
            bbox[3],
        )
        if bbox[3] - bbox[1] < MIN_FIGURE_HEIGHT:
            return None

    if bbox[2] - bbox[0] < 20:
        return None

    return bbox


def _render_bbox(page: Page, bbox: tuple[float, float, float, float]) -> bytes:
    """Render a cropped region of the page to PNG bytes."""
    width = max(1.0, bbox[2] - bbox[0])
    pad = min(
        max(FIGURE_WIDTH_PADDING, width * FIGURE_WIDTH_PADDING_RATIO),
        float(page.width) * 0.35,
    )
    v_pad = min(FIGURE_HEIGHT_PADDING, float(page.height) * 0.05)
    expanded = (
        max(0.0, bbox[0] - pad),
        max(0.0, bbox[1] - v_pad),
        min(float(page.width), bbox[2] + pad),
        min(float(page.height), bbox[3] + v_pad),
    )
    clipped = (
        max(0.0, expanded[0]),
        max(0.0, expanded[1]),
        min(float(page.width), expanded[2]),
        min(float(page.height), expanded[3]),
    )
    cropped = page.crop(clipped).to_image(resolution=200)
    buffer = BytesIO()
    cropped.save(buffer, format="PNG")
    return buffer.getvalue()


def _extract_caption_text_from_bbox(page: Page, bbox: tuple[float, float, float, float]) -> str:
    """Pull text immediately below a bounding box as a fallback caption."""
    caption_box = (
        bbox[0],
        min(float(page.height), bbox[3]),
        bbox[2],
        min(float(page.height), bbox[3] + 60),
    )
    text = page.within_bbox(caption_box).extract_text(x_tolerance=2, y_tolerance=2) or ""
    return clean_text(text)


def _persist_figure(
    document_id: int,
    page_num: int,
    figure_label: str,
    caption_text: str,
    image_bytes: bytes,
    upload_image_fn: Callable[..., str],
) -> None:
    """Upload the rendered figure and insert into rag_figure."""
    safe_label = re.sub(r"[^A-Za-z0-9]+", "_", figure_label).strip("_") or "figure"
    suggested_name = f"doc{document_id}_p{page_num}_{safe_label}.png"
    image_uri = upload_image_fn(image_bytes, suggested_name)

    insert_figures(
        document_id=document_id,
        figures=[
            {
                "figure_label": figure_label,
                "page_number": page_num,
                "caption": caption_text.strip(),
                "image_uri": image_uri,
                "metadata": {},
            }
        ],
    )

def _render_full_page(page: Page, resolution: int = 180) -> bytes:
    """Render a full PDF page to PNG bytes."""
    snapshot = page.to_image(resolution=resolution)
    buffer = BytesIO()
    snapshot.save(buffer, format="PNG")
    return buffer.getvalue()


def persist_document_pages(
    pdf_path: str,
    document_id: int,
    upload_image_fn: Callable[..., str],
    resolution: int = 180,
) -> None:
    """Render and upload each page, then upsert rag_document_page rows."""
    page_payloads: list[dict[str, Any]] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            logger.info("Rendering page image for document_id=%d page=%d", document_id, page_num)
            try:
                image_bytes = _render_full_page(page, resolution=resolution)
            except Exception as exc:
                error = f"Failed to render page {page_num}: {exc}"
                logger.exception(error)
                raise RuntimeError(error) from exc

            suggested_name = f"doc{document_id}_page_{page_num:04d}.png"
            image_uri = upload_image_fn(image_bytes, suggested_name, folder="pages")
            page_payloads.append(
                {
                    "page_number": page_num,
                    "image_uri": image_uri,
                    "metadata": {
                        "width": float(page.width),
                        "height": float(page.height),
                        "rotation": getattr(page, "rotation", 0),
                        "resolution": resolution,
                    },
                }
            )

    replace_document_pages(document_id=document_id, pages=page_payloads)


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


STRIKEOUT_BBOX_PADDING = 1.5


def _normalize_bbox(coords: Sequence[float]) -> tuple[float, float, float, float] | None:
    """Normalize a 4-value coordinate sequence into a bbox tuple."""
    if len(coords) < 4:
        return None
    x0, y0, x1, y1 = (float(coords[0]), float(coords[1]), float(coords[2]), float(coords[3]))
    left = min(x0, x1)
    right = max(x0, x1)
    top = min(y0, y1)
    bottom = max(y0, y1)
    if right - left <= 0 or bottom - top <= 0:
        return None
    return (left, top, right, bottom)


def _expand_bbox(
    bbox: tuple[float, float, float, float],
    page_width: float,
    page_height: float,
    padding: float = STRIKEOUT_BBOX_PADDING,
) -> tuple[float, float, float, float]:
    x0, top, x1, bottom = bbox
    pad = max(0.0, float(padding))
    return (
        max(0.0, x0 - pad),
        max(0.0, top - pad),
        min(page_width, x1 + pad),
        min(page_height, bottom + pad),
    )


def _quadpoints_to_boxes(quadpoints: Sequence[float] | Sequence[Sequence[float]]) -> list[tuple[float, float, float, float]]:
    boxes: list[tuple[float, float, float, float]] = []
    if not isinstance(quadpoints, Sequence):
        return boxes

    if quadpoints and isinstance(quadpoints[0], Sequence):  # type: ignore[index]
        quad_sets = quadpoints  # already grouped
    else:
        flat = [float(value) for value in quadpoints]  # type: ignore[arg-type]
        if len(flat) % 8 != 0:
            return boxes
        quad_sets = [flat[i : i + 8] for i in range(0, len(flat), 8)]

    for quad in quad_sets:
        if len(quad) < 8:
            continue
        xs = [float(quad[idx]) for idx in range(0, len(quad), 2)]
        ys = [float(quad[idx]) for idx in range(1, len(quad), 2)]
        bbox = _normalize_bbox((min(xs), min(ys), max(xs), max(ys)))
        if bbox:
            boxes.append(bbox)
    return boxes


def _annotation_boxes_from_strikeout(annot: dict[str, Any], page: Page) -> list[tuple[float, float, float, float]]:
    boxes: list[tuple[float, float, float, float]] = []
    quadpoints = annot.get("quadpoints") or annot.get("QuadPoints")
    if quadpoints:
        boxes.extend(_quadpoints_to_boxes(quadpoints))

    rect = annot.get("rect") or annot.get("Rect")
    if rect:
        bbox = _normalize_bbox(rect)
        if bbox:
            boxes.append(bbox)
    elif all(key in annot for key in ("x0", "top", "x1", "bottom")):
        bbox = _normalize_bbox((annot["x0"], annot["top"], annot["x1"], annot["bottom"]))  # type: ignore[index]
        if bbox:
            boxes.append(bbox)

    normalized: list[tuple[float, float, float, float]] = []
    width = float(page.width)
    height = float(page.height)
    for raw in boxes:
        x0, top, x1, bottom = raw
        normalized.append(
            (
                max(0.0, min(x0, x1)),
                max(0.0, min(top, bottom)),
                min(width, max(x0, x1)),
                min(height, max(top, bottom)),
            )
        )
    return [_expand_bbox(bbox, width, height) for bbox in normalized if bbox[0] < bbox[2] and bbox[1] < bbox[3]]


def _strikeout_boxes(page: Page) -> list[tuple[float, float, float, float]]:
    annotations = getattr(page, "annots", None) or []
    boxes: list[tuple[float, float, float, float]] = []
    for annot in annotations:
        subtype = (annot.get("subtype") or annot.get("Subtype") or "").lower()
        if subtype != "strikeout":
            continue
        boxes.extend(_annotation_boxes_from_strikeout(annot, page))
    return boxes


def _boxes_overlap(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> bool:
    return not (a[2] <= b[0] or a[0] >= b[2] or a[3] <= b[1] or a[1] >= b[3])


def _page_without_strikeouts(page: Page) -> Page:
    boxes = _strikeout_boxes(page)
    if not boxes:
        return page

    def keep_object(obj: dict[str, Any]) -> bool:
        if obj.get("object_type") != "char":
            return True
        bbox = (
            float(obj.get("x0", 0.0)),
            float(obj.get("top", 0.0)),
            float(obj.get("x1", 0.0)),
            float(obj.get("bottom", 0.0)),
        )
        return not any(_boxes_overlap(bbox, strike) for strike in boxes)

    if hasattr(page, "filter"):
        try:
            return page.filter(keep_object, inplace=False)
        except TypeError:
            return page.filter(keep_object)
    return page


def extract_body_paragraphs(page: Page) -> list[str]:
    """
    Extract body text paragraphs from a pdfplumber page.

    This is intentionally simple: we use page.extract_text() and split
    on double newlines as a first-pass approximation of paragraphs.
    You can refine this with layout-aware logic later.
    """
    filtered_page = _page_without_strikeouts(page)
    raw = filtered_page.extract_text(x_tolerance=3, y_tolerance=3)
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

def extract_figures_from_pdf(
    pdf_path: str,
    document_id: int,
    upload_image_fn: Callable[..., str],
) -> None:
    """
    Extract figure images and captions from the PDF and insert into rag_figure.

    upload_image_fn(image_bytes, suggested_name) -> image_uri
    """

    seen_labels: set[str] = set()

    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            logger.info("Extracting figures from document_id=%d, page=%d", document_id, page_num)
            captions = _extract_caption_candidates(page)
            vector_boxes = _gather_vector_boxes(page) if captions else []
            image_boxes = _collect_image_boxes(page) if captions else []
            graphic_boxes = vector_boxes + image_boxes
            min_top = 0.0
            figures_on_page = 0

            for caption in captions:
                figure_label = caption["figure_label"]
                if figure_label in seen_labels:
                    continue

                bbox = _build_figure_bbox(page, caption["caption_bbox"], graphic_boxes, min_top)
                min_top = max(min_top, caption["caption_bbox"][3] + 2)
                if not bbox:
                    logger.info("Unable to determine bounding box for %s on page %d", figure_label, page_num)
                    continue

                try:
                    image_bytes = _render_bbox(page, bbox)
                except Exception as exc:
                    logger.error(
                        "Failed to render figure %s on page %d: %s",
                        figure_label,
                        page_num,
                        exc,
                    )
                    continue

                _persist_figure(
                    document_id=document_id,
                    page_num=page_num,
                    figure_label=figure_label,
                    caption_text=caption["caption_text"],
                    image_bytes=image_bytes,
                    upload_image_fn=upload_image_fn,
                )
                figures_on_page += 1
                seen_labels.add(figure_label)

            if figures_on_page:
                continue

            logger.info(
                "No caption-derived figures found on page %d, falling back to raw image objects.",
                page_num,
            )
            page_text = page.extract_text() or ""
            for idx, img in enumerate(page.images):
                bbox = (
                    float(img["x0"]),
                    float(img["top"]),
                    float(img["x1"]),
                    float(img["bottom"]),
                )
                caption_text = _extract_caption_text_from_bbox(page, bbox)
                match = FIGURE_LABEL_RE.search(caption_text) or FIGURE_LABEL_RE.search(page_text)
                if not match:
                    continue

                figure_label = normalise_figure_label(match.group(1))
                if figure_label in seen_labels:
                    continue

                try:
                    image_bytes = _render_bbox(page, bbox)
                except Exception as exc:
                    logger.error(
                        "Failed to render fallback image index=%d on page %d: %s",
                        idx,
                        page_num,
                        exc,
                    )
                    continue

                _persist_figure(
                    document_id=document_id,
                    page_num=page_num,
                    figure_label=figure_label,
                    caption_text=caption_text or "",
                    image_bytes=image_bytes,
                    upload_image_fn=upload_image_fn,
                )
                seen_labels.add(figure_label)

def normalise_figure_label(raw: str) -> str:
    """Normalise 'Fig 3', 'FIGURE 3A' -> 'FIG. 3', 'FIG. 3A'."""
    cleaned = " ".join(raw.replace("FIGURE", "FIG.").replace("Fig", "FIG.").split())
    if not cleaned.upper().startswith("FIG."):
        cleaned = "FIG. " + cleaned.split()[-1]
    return cleaned.upper()

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

    return chunks

def ingest_pdf(pdf_path: str = "documents/*.pdf",
               external_id: str | None = None,
               title: str | None = None,
               description: str | None = None,
               source_uri: str | None = None) -> None:
    """Ingest a PDF document, chunk it, store in DB, and extract figures."""

    if not Path(pdf_path).is_file():
        error = f"PDF file not found: {pdf_path}"
        logger.error(error)
        raise FileNotFoundError(error)

    external_id = external_id or Path(pdf_path).name
    title = title or Path(pdf_path).stem

    checksum = compute_checksum(pdf_path)

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
        metadata={},  
    )

    chunks = build_chunks_from_pdf(pdf_path)

    # Upsert chunks (replace all existing chunks for this document)
    replace_chunks(document_id=document_id, chunks=chunks)

    log_info = f"chunks_inserted={len(chunks)}"
    logger.info(log_info)

    persist_document_pages(
        pdf_path=pdf_path,
        document_id=document_id,
        upload_image_fn=upload_image_fn,
    )

    log_info = f"Extracting figures for document_id={document_id}"
    logger.info(log_info)

    extract_figures_from_pdf(
        pdf_path=pdf_path,
        document_id=document_id,
        upload_image_fn=upload_image_fn,
    )

    log_info = f"Ingested document_id={document_id}, total_pages={total_pages}"
    logger.info(log_info)
    log_info = f"chunks_inserted={len(chunks)}"
    logger.info(log_info)

    embed_and_update_chunks()
