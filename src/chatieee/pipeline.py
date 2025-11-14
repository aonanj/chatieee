"""High level RAG ingestion pipeline."""

from __future__ import annotations

import logging
from pathlib import Path

from .config import AppConfig
from .document_loader import PDFDocumentLoader
from .llamacloud import LlamaCloudClient
from .storage import PostgresDocumentStore
from .text_splitter import SectionAwareTextSplitter

LOGGER = logging.getLogger(__name__)


class RAGIngestionPipeline:
    """Coordinate document ingestion end-to-end."""

    def __init__(
        self,
        documents_dir: Path,
        loader: PDFDocumentLoader,
        splitter: SectionAwareTextSplitter,
        store: PostgresDocumentStore,
        client: LlamaCloudClient,
    ) -> None:
        self._documents_dir = documents_dir
        self._loader = loader
        self._splitter = splitter
        self._store = store
        self._client = client

    def run(self) -> None:
        """Process every PDF located in the configured directory."""

        if not self._documents_dir.exists():
            raise FileNotFoundError(
                f"Documents directory {self._documents_dir} does not exist.",
            )

        pdf_paths = sorted(self._documents_dir.glob("*.pdf"))
        LOGGER.info("Found %s PDF(s) in %s", len(pdf_paths), self._documents_dir)
        for path in pdf_paths:
            try:
                self._process_document(path)
            except Exception:  # noqa: BLE001
                LOGGER.exception("Failed to process %s", path)
                continue

    def _process_document(self, path: Path) -> None:
        """Parse, embed, and persist a single document."""

        parsed = self._loader.load(path)
        doc_id, created = self._store.upsert_document(parsed.document)
        if not created:
            LOGGER.info("Skipping %s; already present.", path.name)
            return

        chunks = self._splitter.split(parsed.pages)
        LOGGER.info(
            "Split %s into %s chunk(s).",
            path.name,
            len(chunks),
        )
        nodes = self._client.embed_document_chunks(parsed.document, chunks)
        self._store.insert_nodes(doc_id, nodes)


def build_pipeline(config: AppConfig) -> RAGIngestionPipeline:
    """Construct a pipeline using the provided configuration."""

    loader = PDFDocumentLoader()
    splitter = SectionAwareTextSplitter(
        max_chars=config.max_chunk_chars,
        overlap_chars=config.chunk_overlap_chars,
    )
    store = PostgresDocumentStore(dsn=config.database.dsn)
    client = LlamaCloudClient(config.llamacloud)
    return RAGIngestionPipeline(
        documents_dir=config.documents_dir,
        loader=loader,
        splitter=splitter,
        store=store,
        client=client,
    )
