import os

from dotenv import load_dotenv

from src.utils.logger import setup_logger

load_dotenv()

LOGGER = setup_logger(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
ANSWER_MODEL = os.getenv("ANSWER_MODEL", "gpt-5-mini")
MAX_CONTEXT_CHARS = int(os.getenv("MAX_CONTEXT_CHARS", "8000"))

# --- Reranker envs ---
RERANK_MODEL = os.getenv("RAG_RERANK_MODEL", "gpt-5-mini")
VECTOR_K = int(os.getenv("DEFAULT_VECTOR_K", "20"))
LEXICAL_K = int(os.getenv("DEFAULT_LEXICAL_K", "20"))
TOP_K = int(os.getenv("DEFAULT_TOP_K", "10"))
DEFAULT_VERBOSITY = os.getenv("DEFAULT_VERBOSITY", "high")

# --- Ingestion envs ---
CHUNK_UPDATE_BATCH_SIZE = int(os.getenv("CHUNK_UPDATE_BATCH_SIZE", "200"))
DOCUMENT_HEADERS = [
    "IEEE Std 802-2024 IEEE Standard for Local and Metropolitan Area Networks: Overview and Architecture",
]
DOCUMENT_FOOTERS = [
    "Copyright © 2025 IEEE. All rights reserved.",
    "Authorized licensed use limited to",
    "from IEEE Xplore.",
    "Restrictions apply.",
    "Authorized licensed use limited to: Phaethon Order. Downloaded on November 13,2025 at 16:05:53 UTC from IEEE Xplore. Restrictions apply."
]
DEFAULT_BUCKET_NAME = os.getenv(
    "FIREBASE_STORAGE_BUCKET",
    "chat-ieee.firebasestorage.app"
)
