"""Thin HTTP client for LlamaCloud embeddings."""

from __future__ import annotations

import logging
from typing import Iterable, Sequence
from urllib.parse import urljoin

import requests

from .config import LlamaCloudConfig
from .models import Chunk, DocumentRecord, NodePayload

LOGGER = logging.getLogger(__name__)


class LlamaCloudError(RuntimeError):
    """Raised when LlamaCloud returns an error response."""


class LlamaCloudClient:
    """Client capable of creating embeddings for chunks via LlamaCloud."""

    def __init__(
        self,
        config: LlamaCloudConfig,
        session: requests.Session | None = None,
    ) -> None:
        self._config = config
        self._session = session or requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json",
            },
        )

    def embed_document_chunks(
        self,
        document: DocumentRecord,
        chunks: Sequence[Chunk],
    ) -> list[NodePayload]:
        """Create embeddings for the provided chunks."""

        if not chunks:
            return []

        LOGGER.info(
            "Requesting %s embeddings from LlamaCloud for %s",
            len(chunks),
            document.file_name,
        )
        embeddings = self._request_embeddings(chunk.text for chunk in chunks)

        if len(embeddings) != len(chunks):
            raise LlamaCloudError(
                "Embedding count did not match chunk count.",
            )

        nodes: list[NodePayload] = []
        for chunk, embedding in zip(chunks, embeddings, strict=True):
            metadata = {
                "file_name": document.file_name,
                "file_hash": document.file_hash,
                "chunk_index": chunk.index,
                "section_title": chunk.section_title,
                "page_span": {
                    "start": chunk.page_span[0],
                    "end": chunk.page_span[1],
                },
            }
            nodes.append(
                NodePayload(
                    text_content=chunk.text,
                    metadata=metadata,
                    embedding=embedding,
                ),
            )
        return nodes

    def _request_embeddings(
        self,
        texts: Iterable[str],
    ) -> list[list[float]]:
        """Call the LlamaCloud embedding endpoint."""

        payload = {
            "project_id": self._config.project_id,
            "inputs": list(texts),
        }
        url = urljoin(self._config.base_url, "embeddings")
        response = self._session.post(
            url,
            json=payload,
            timeout=self._config.timeout_seconds,
        )
        if not response.ok:
            LOGGER.error(
                "LlamaCloud responded with %s: %s",
                response.status_code,
                response.text,
            )
            raise LlamaCloudError(
                f"Embedding request failed with HTTP {response.status_code}.",
            )
        data = response.json()
        embeddings = []
        for entry in data.get("data", []):
            embedding = entry.get("embedding")
            if embedding is None:
                raise LlamaCloudError("LlamaCloud response missing embedding key.")
            embeddings.append(embedding)
        return embeddings
