"""Application configuration helpers."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(slots=True)
class DatabaseConfig:
    """PostgreSQL connection settings."""

    dsn: str


@dataclass(slots=True)
class LlamaCloudConfig:
    """Configuration required to talk to the LlamaCloud API."""

    api_key: str
    project_id: str
    base_url: str = "https://api.llamacloud.com/v1/"
    timeout_seconds: float = 30.0


@dataclass(slots=True)
class AppConfig:
    """Container for all runtime configuration."""

    documents_dir: Path
    database: DatabaseConfig
    llamacloud: LlamaCloudConfig
    max_chunk_chars: int = 1500
    chunk_overlap_chars: int = 200


def load_config() -> AppConfig:
    """Load configuration from environment variables.

    Returns:
        AppConfig: Fully populated configuration object.

    Raises:
        RuntimeError: If required environment variables are not set.
    """

    documents_dir = Path(
        os.getenv("CHATI_DOCUMENTS_DIR", Path("documents")),
    ).expanduser().resolve()

    db_dsn = _require_env("PG_DSN")
    api_key = _require_env("LLAMACLOUD_API_KEY")
    project_id = _require_env("LLAMACLOUD_PROJECT_ID")
    base_url = os.getenv("LLAMACLOUD_BASE_URL", "https://api.llamacloud.com/v1/")
    base_url = base_url.rstrip("/") + "/"
    timeout_raw = os.getenv("LLAMACLOUD_TIMEOUT_SECONDS", "30")

    max_chunk_chars = int(os.getenv("CHATI_CHUNK_SIZE", "1500"))
    chunk_overlap = int(os.getenv("CHATI_CHUNK_OVERLAP", "200"))

    try:
        timeout_seconds = float(timeout_raw)
    except ValueError as exc:
        raise RuntimeError(
            "LLAMACLOUD_TIMEOUT_SECONDS must be a float value.",
        ) from exc

    return AppConfig(
        documents_dir=documents_dir,
        database=DatabaseConfig(dsn=db_dsn),
        llamacloud=LlamaCloudConfig(
            api_key=api_key,
            project_id=project_id,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
        ),
        max_chunk_chars=max_chunk_chars,
        chunk_overlap_chars=chunk_overlap,
    )


def _require_env(var_name: str) -> str:
    """Fetch a variable from the environment or raise an error."""

    try:
        value = os.environ[var_name]
    except KeyError as exc:
        raise RuntimeError(f"Environment variable {var_name} is required.") from exc
    if not value.strip():
        raise RuntimeError(f"Environment variable {var_name} must not be empty.")
    return value
