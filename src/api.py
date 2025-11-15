from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio
import json
import os
from pathlib import Path
from typing import Annotated, Any

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import psycopg
from pydantic import BaseModel

from src.utils.database import  get_conn, init_pool
from src.ingest.pdf_ingest import ingest_pdf
from .query import answer_query


@asynccontextmanager
async def lifespan(_: FastAPI):
    load_dotenv()
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
    "https://localhost:5174",
    "https://127.0.0.1:5174",
]

_FAVICON_PATH = Path(__file__).resolve().parent.parent / "public" / "favicon.ico"
_DOCUMENTS_DIR = Path(__file__).resolve().parent.parent / "documents"

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
    pdf: UploadFile = File(...),
    external_id: str | None = Form(None),
    title: str | None = Form(None),
    description: str | None = Form(None),
    source_uri: str | None = Form(None),
    conn: Conn = Depends(),
) -> dict[str, str]:
    """Persist an uploaded PDF and ingest it into the system."""
    del conn  # Ensures dependency is evaluated for connection health checks.

    filename = (pdf.filename or "uploaded.pdf").strip()
    if not filename.lower().endswith(".pdf") and pdf.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Uploaded file must be a PDF document.")

    _DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename).name
    destination = _DOCUMENTS_DIR / safe_name

    counter = 1
    while destination.exists():
        destination = _DOCUMENTS_DIR / f"{Path(safe_name).stem}_{counter}{Path(safe_name).suffix or '.pdf'}"
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
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=500, detail="Failed to ingest PDF.") from exc

    relative_path = destination.relative_to(_DOCUMENTS_DIR.parent)
    return {
        "status": "completed",
        "document_path": str(relative_path),
        "message": f"Document '{destination.name}' ingested successfully.",
    }

@app.post("/query", tags=["Query"])
async def query_endpoint(payload: QueryRequest, conn: Conn = Depends()) -> dict[str, Any]:
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
