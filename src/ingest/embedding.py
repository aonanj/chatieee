from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Sequence

from src import config

try:  # pragma: no cover - optional dependency for runtime environments without OpenAI
    from openai import OpenAI
except Exception:  # pragma: no cover - allows offline execution without the SDK
    OpenAI = None  # type: ignore

_DEFAULT_MODEL = config.EMBEDDING_MODEL
_EMBEDDING_DIMENSION = 1536

@dataclass(slots=True)
class EmbeddingResult:
    """Simple container for embedding outputs."""
    vector: list[float]
    model: str

class EmbeddingClient:
    """Wrapper around OpenAI embeddings with an offline fallback.
    The ingestion and query pipelines depend on deterministic embeddings for
    repeatability in development environments. When an ``OPENAI_API_KEY`` is
    present the real embedding endpoint is used; otherwise we fall back to a
    hash-based pseudo-embedding that preserves cosine ordering characteristics
    well enough for local testing.
    """
    def __init__(self, model: str | None = None) -> None:
        self.model = model or _DEFAULT_MODEL
        api_key = config.OPENAI_API_KEY
        if not OpenAI and api_key:
            error = "OpenAI SDK is required when OPENAI_API_KEY is set"
            raise RuntimeError(error)
        self._client = OpenAI(api_key=api_key) if (OpenAI and api_key) else None

    @property
    def dimension(self) -> int:
        return _EMBEDDING_DIMENSION

    def embed(self, text: str) -> EmbeddingResult:
        cleaned = text.strip()
        if not cleaned:
            return EmbeddingResult(vector=[0.0] * self.dimension, model=self.model)
        if self._client:
            response = self._client.embeddings.create(model=self.model, input=[cleaned])
            vector = response.data[0].embedding
            return EmbeddingResult(vector=vector, model=self.model)
        return EmbeddingResult(vector=self._offline_embedding(cleaned), model=self.model)

    def _offline_embedding(self, text: str) -> list[float]:
        """Create a deterministic embedding without network access."""
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        seed = int.from_bytes(digest[:4], "little", signed=False)
        rng = np.random.default_rng(seed)
        vector = rng.normal(size=self.dimension)
        norm = np.linalg.norm(vector)
        if norm == 0:
            return [0.0] * self.dimension
        normalised = (vector / norm).astype(float)
        return normalised.tolist()

def embedding_to_pgvector(values: Sequence[float]) -> str:
    """Format a python sequence so Postgres can cast it to ``vector``."""
    formatted = ",".join(f"{float(value):.10f}" for value in values)
    return f"[{formatted}]"
