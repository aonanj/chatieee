from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import tempfile
from typing import Annotated, Any

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import firebase_admin
from firebase_admin import credentials
import psycopg
from pydantic import BaseModel

from src.config import FIREBASE_ADMIN_CREDS, LOGGER
from src.ingest.pdf_ingest import ingest_pdf
from src.utils.database import get_conn, init_pool

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
        return _RESOLVED_DOCUMENTS_DIR

    env_dir = os.getenv("DOCUMENTS_DIR") or os.getenv("UPLOAD_BASE_DIR")
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
                raise PermissionError(f"Directory is not writable: {directory}")
            _RESOLVED_DOCUMENTS_DIR = directory
            LOGGER.info("Using upload directory: %s", directory)
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

@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> FileResponse:
    if not _FAVICON_PATH.exists():
        raise HTTPException(status_code=404, detail="favicon not found")
    return FileResponse(_FAVICON_PATH, media_type="image/x-icon")

@app.get("/healthz", tags=["Health"])
async def healthz() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}

@app.post("/ingest_pdf", tags=["Ingestion"])
async def ingest_pdf_endpoint(
    conn: Conn,
    pdf: UploadFile = File(...),
    external_id: str | None = Form(None),
    title: str | None = Form(None),
    description: str | None = Form(None),
    source_uri: str | None = Form(None)
) -> dict[str, str]:
    """Persist an uploaded PDF and ingest it into the system."""
    del conn  # Ensures dependency is evaluated for connection health checks.

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
        if destination.exists():
            destination.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="Failed to store uploaded PDF.") from exc
    finally:
        await pdf.close()

    if destination.stat().st_size == 0:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Uploaded PDF is empty.")

    try:
        await asyncio.to_thread(
            ingest_pdf,
            pdf_path=str(destination),
            external_id=external_id,
            title=title,
            description=description,
            source_uri=source_uri,
        )
    except FileNotFoundError as exc:
        LOGGER.error("PDF file not found during ingestion: %s", exc)
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive
        LOGGER.error("Unexpected error during PDF ingestion: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to ingest PDF.") from exc

    relative_path = destination.relative_to(target_dir.parent)
    return {
        "status": "completed",
        "document_path": str(relative_path),
        "message": f"Document '{destination.name}' ingested successfully.",
    }

@app.post("/query", tags=["Query"])
async def query_endpoint(payload: QueryRequest, conn: Conn) -> dict[str, Any]:
    """Answer a natural language question using ingested documents."""
    del conn  # Ensures dependency runs even though synchronous helpers are used elsewhere.

    query = payload.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query text is required.")

    try:
        raw_response = await asyncio.to_thread(answer_query, query)
    except Exception as exc:  # pragma: no cover - defensive logging
        raise HTTPException(status_code=500, detail="Query processing failed.") from exc

    try:
        return json.loads(raw_response)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="Received malformed response from answer generator.") from exc
