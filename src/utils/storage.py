from __future__ import annotations

import re
import uuid

from google.cloud import storage

from src import config

DEFAULT_BUCKET_NAME = config.DEFAULT_BUCKET_NAME

_storage_client: storage.Client | None = None
logger = config.LOGGER

def _get_storage_client() -> storage.Client:
    global _storage_client
    if _storage_client is None:
        # Relies on GOOGLE_APPLICATION_CREDENTIALS or ADC
        _storage_client = storage.Client()
    return _storage_client


def _sanitize_name(name: str) -> str:
    """
    Make a reasonably safe object name fragment:
    - lowercased
    - spaces and invalid chars -> dash
    - strip leading/trailing dashes
    """
    base = name.strip().lower()
    # Replace path separators just in case
    base = base.replace("\\", "/").split("/")[-1]
    base = re.sub(r"[^a-z0-9._-]+", "-", base)
    base = base.strip("-")
    return base or "asset"


def _sanitize_folder(folder: str | None) -> str:
    """Restrict folder names to safe characters and fall back to 'figures'."""
    if not folder:
        return "figures"
    cleaned = re.sub(r"[^a-z0-9/_-]+", "-", folder.strip().lower())
    cleaned = cleaned.strip("/-")
    if not cleaned:
        return "figures"
    return cleaned


def upload_image_fn(image_bytes: bytes, suggested_name: str, folder: str = "figures") -> str:
    """
    Upload a PNG image to Firebase (GCS) and return a gs:// URI.

    Assumes:
      - GOOGLE_APPLICATION_CREDENTIALS is set to a service account JSON
        that has storage.objects.create on the bucket.
      - FIREBASE_STORAGE_BUCKET (optional) overrides the default bucket.

    Args:
        image_bytes: Raw PNG bytes to upload.
        suggested_name: Human-friendly identifier (used in the object name).
        folder: Storage folder prefix (e.g., "figures", "pages").

    Returns:
      e.g. 'gs://chat-ieee.firebasestorage.app/figures/<uuid>_name.png'
    """
    if not isinstance(image_bytes, (bytes, bytearray)):
        raise TypeError("image_bytes must be bytes or bytearray")

    bucket_name = DEFAULT_BUCKET_NAME
    client = _get_storage_client()
    logger.info("Uploading image to GCS bucket: %s", bucket_name)
    bucket = client.bucket(bucket_name)

    safe_name = _sanitize_name(suggested_name)
    safe_folder = _sanitize_folder(folder)
    object_name = f"{safe_folder}/{uuid.uuid4().hex}_{safe_name}"

    blob = bucket.blob(object_name)
    try:
        blob.upload_from_string(image_bytes, content_type="image/png")
    except Exception as e:
        logger.error("Failed to upload image to GCS: %s", e)
        raise

    return f"gs://{bucket_name}/{object_name}"
