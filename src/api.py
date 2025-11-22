from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import tempfile
from typing import Annotated, Any

from dotenv import load_dotenv
from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import firebase_admin
from firebase_admin import credentials
import psycopg
from pydantic import BaseModel

from src.config import FIREBASE_ADMIN_CREDS, LOGGER
from src.ingest.embed_and_update_chunks import backfill_missing_chunk_embeddings
from src.ingest.pdf_ingest import compute_checksum, ingest_pdf
from src.utils.database import (
    create_ingestion_run,
    get_conn,
    get_ingestion_run,
    init_pool,
    update_ingestion_status,
    upsert_document,
)

from .query import answer_query


@asynccontextmanager
async def lifespan(_: FastAPI):
    load_dotenv()
    LOGGER.info("Starting ChatIEEE API application lifespan.")
    cred = credentials.Certificate(FIREBASE_ADMIN_CREDS)
    app = firebase_admin.initialize_app(cred)
    if app:
        LOGGER.info("Initialized Firebase Admin SDK with app name: %s", app.name)
    pool = init_pool()
    try:
        yield
    finally:
        await pool.close()


app = FastAPI(title="ChatIEEE API", version="0.1.0", lifespan=lifespan)
Conn = Annotated[psycopg.AsyncConnection, Depends(get_conn)]
origins = [o.strip() for o in os.getenv("CORS_ALLOW_ORIGINS", "").split(",") if o.strip()] or [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://localhost:3000",
    "https://127.0.0.1:3000",
    "https://localhost:8000",
    "https://127.0.0.1:8000",
    "https://localhost:5174",
    "https://127.0.0.1:5174",
    "https://chatieee-backend-751780377614.us-west1.run.app",
    "https://us-west1-chat-ieee.cloudfunctions.net/ssrchatieee",
    "https://chat-ieee.firebaseapp.com",
    "https://chat-ieee.web.app",
]

_FAVICON_PATH = Path(__file__).resolve().parent.parent / "public" / "favicon.ico"
_DEFAULT_DOCUMENTS_DIR = Path(__file__).resolve().parent.parent / "documents"
_RESOLVED_DOCUMENTS_DIR: Path | None = None


def _resolve_documents_dir() -> Path:
    """
    Choose a writable directory for uploads.

    Order of preference:
      1) Env override (DOCUMENTS_DIR or UPLOAD_BASE_DIR)
      2) Repo's documents folder (for local dev)
      3) Ephemeral /tmp mount (Cloud Run safe)
    """
    global _RESOLVED_DOCUMENTS_DIR
    if _RESOLVED_DOCUMENTS_DIR is not None:
        LOGGER.info("Using cached upload directory: %s", _RESOLVED_DOCUMENTS_DIR)
        return _RESOLVED_DOCUMENTS_DIR

    env_dir = os.getenv("DOCUMENTS_DIR") or os.getenv("UPLOAD_BASE_DIR")
    LOGGER.info("Attempting to resolve upload directory. Env override: %s", env_dir)
    candidates = [Path(env_dir)] if env_dir else []
    candidates.append(_DEFAULT_DOCUMENTS_DIR)
    tmp_candidate = Path(os.getenv("TMPDIR", tempfile.gettempdir())) / "documents"
    candidates.append(tmp_candidate)

    errors: list[str] = []
    for directory in candidates:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            if not os.access(directory, os.W_OK):
                LOGGER.error("Directory is not writable: %s", directory)
                raise PermissionError(f"Directory is not writable: {directory}")  # noqa
            _RESOLVED_DOCUMENTS_DIR = directory
            LOGGER.info("Upload directory is usable: %s", directory)
            return directory
        except Exception as exc:  # pragma: no cover - defensive logging
            errors.append(f"{directory}: {exc}")
            LOGGER.error("Upload directory unusable (%s): %s", directory, exc)

    LOGGER.error("No writable upload directory selected. Attempts: %s", "; ".join(errors))
    raise HTTPException(status_code=500, detail="Server storage is unavailable for uploads.")

class QueryRequest(BaseModel):
    query: str

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["*"],
)

def process_ingest_background(
    run_id: str,
    pdf_path: str,
    doc_id: int,
    metadata: dict[str, Any],
    check_strikeouts: bool,
):
    """Background task wrapper to handle status updates."""
    try:
        ingest_pdf(
            pdf_path=pdf_path,
            external_id=metadata["external_id"],
            title=metadata["title"],
            description=metadata["description"],
            source_uri=metadata["source_uri"],
            check_strikeouts=check_strikeouts,
        )
        update_ingestion_status(run_id, "completed")
        LOGGER.info("Ingestion run %s completed successfully", run_id)
    except Exception as e:
        LOGGER.error("Ingestion run %s failed: %s", run_id, e, exc_info=True)
        update_ingestion_status(run_id, "failed", str(e))

@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> FileResponse:
    if not _FAVICON_PATH.exists():
        raise HTTPException(status_code=404, detail="favicon not found")
    return FileResponse(_FAVICON_PATH, media_type="image/x-icon")

@app.get("/healthz", tags=["Health"])
async def healthz() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}

async def ingest_pdf_endpoint(
    background_tasks: BackgroundTasks,
    pdf: UploadFile | None = None,
    external_id: str | None = Form(None),
    title: str | None = Form(None),
    description: str | None = Form(None),
    source_uri: str | None = Form(None),
    draft_document: bool = Form(False),
) -> dict[str, str]:
    """Persist an uploaded PDF and ingest it into the system."""

    if pdf is None:
        pdf = File(...)
    if pdf:
        filename = (pdf.filename or "uploaded.pdf").strip()
        if not filename.lower().endswith(".pdf") and pdf.content_type != "application/pdf":
            LOGGER.error("Uploaded file is not a PDF: filename=%s, content_type=%s", filename, pdf.content_type)
            raise HTTPException(status_code=400, detail="Uploaded file must be a PDF document.")

        target_dir = _resolve_documents_dir()
        safe_name = Path(filename).name
        destination = target_dir / safe_name

        counter = 1
        while destination.exists():
            destination = target_dir / f"{Path(safe_name).stem}_{counter}{Path(safe_name).suffix or '.pdf'}"
            counter += 1

        try:
            with destination.open("wb") as buffer:
                while True:
                    chunk = await pdf.read(1024 * 1024)
                    if not chunk:
                        break
                    buffer.write(chunk)
        except Exception as exc:
            LOGGER.error("Failed to store uploaded PDF: %s", exc, exc_info=True)
            if destination.exists():
                destination.unlink(missing_ok=True)
            raise HTTPException(status_code=500, detail="Failed to store uploaded PDF.") from exc
        finally:
            LOGGER.info("Closing uploaded PDF file: %s", filename)
            await pdf.close()

        if destination.stat().st_size == 0:
            destination.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail="Uploaded PDF is empty.")

        checksum = await asyncio.to_thread(compute_checksum, str(destination))

        eff_external_id = external_id or destination.name

        doc_id = await asyncio.to_thread(
            upsert_document,
            external_id=eff_external_id,
            title=title or destination.stem,
            description=description,
            source_uri=source_uri,
            checksum=checksum,
            total_pages=0,
            metadata={}
        )

        run_id = await asyncio.to_thread(
            create_ingestion_run,
            doc_id
        )
        check_strikeouts = bool(draft_document)

        background_tasks.add_task(
            process_ingest_background,
            run_id=run_id,
            pdf_path=str(destination),
            doc_id=doc_id,
            metadata={
                    "external_id": eff_external_id,
                    "title": title or destination.stem,
                    "description": description,
                    "source_uri": source_uri,
                    "check_strikeouts": check_strikeouts,
            },
            check_strikeouts=check_strikeouts,
        )

        relative_path = destination.relative_to(_resolve_documents_dir().parent)
        return {
            "status": "processing",
            "run_id": run_id,
            "document_path": str(relative_path),
            "message": f"Document '{destination.name}' is being processed.",
        }
    raise HTTPException(status_code=400, detail="No PDF file uploaded.")

@app.get("/ingest/{run_id}", tags=["Ingestion"])
async def get_ingest_status(run_id: str, conn: Conn) -> dict[str, Any]:
    """Check the status of a background ingestion run."""
    del conn
    run = await asyncio.to_thread(get_ingestion_run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run

@app.post("/chunks/backfill_missing_embeddings", tags=["Maintenance"])
async def backfill_missing_embeddings(conn: Conn, limit: int | None = None) -> dict[str, Any]:
    """Fill in missing embeddings while stripping headers/footers and merging metadata."""
    del conn
    try:
        updated = await asyncio.to_thread(backfill_missing_chunk_embeddings, limit)
    except Exception as exc:  # pragma: no cover - defensive logging
        LOGGER.error("Failed to backfill missing embeddings: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to backfill missing embeddings.") from exc
    return {"status": "ok", "updated_chunks": updated}

@app.post("/query", tags=["Query"])
async def query_endpoint(payload: QueryRequest, conn: Conn) -> dict[str, Any]:
    """Answer a natural language question using ingested documents."""
    del conn  # Ensures dependency runs even though synchronous helpers are used elsewhere.

    query = payload.query.strip()
    if not query:
        LOGGER.error("Empty query received.")
        raise HTTPException(status_code=400, detail="Query text is required.")

    try:
        raw_response = await asyncio.to_thread(answer_query, query)
    except Exception as exc:  # pragma: no cover - defensive logging
        LOGGER.error("Error processing query: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Query processing failed.") from exc

    try:
        return json.loads(raw_response)
    except json.JSONDecodeError as exc:
        LOGGER.error("Received malformed response from answer generator: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Received malformed response from answer generator.") from exc
