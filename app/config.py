"""Runtime configuration, all through environment variables."""
from __future__ import annotations

import os


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


# --- storage -----------------------------------------------------------------
DB_PATH = os.environ.get("AMI_DB_PATH", "/data/memory.sqlite3")

# --- embedding model ---------------------------------------------------------
EMBED_MODEL = os.environ.get("AMI_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
EMBED_DEVICE = os.environ.get("AMI_EMBED_DEVICE", "cpu")
EMBED_BATCH = _int("AMI_EMBED_BATCH", 64)

# --- LLM (competition rule: must be gpt-4o-mini for a leaderboard run) --------
LLM_MODEL = os.environ.get("AMI_LLM_MODEL", "gpt-4o-mini")
LLM_BASE_URL = os.environ.get("OPENAI_BASE_URL", "") or None
LLM_API_KEY = os.environ.get("OPENAI_API_KEY", "")
LLM_TIMEOUT = _float("AMI_LLM_TIMEOUT", 30.0)
LLM_RETRIES = _int("AMI_LLM_RETRIES", 2)
LLM_MAX_FACTS = _int("AMI_LLM_MAX_FACTS", 24)
LLM_CONCURRENCY = _int("AMI_LLM_CONCURRENCY", 16)

# Feature switches: with no API key both fall back to the raw-text-only path.
EXTRACT_ENABLED = os.environ.get("AMI_EXTRACT", "1") != "0"
RECALL_QUERY_ENABLED = os.environ.get("AMI_RECALL_QUERY", "1") != "0"

# --- retrieval ---------------------------------------------------------------
# Weight of the user-voice recall question channel in the fused score.
RECALL_WEIGHT = _float("AMI_RECALL_WEIGHT", 0.5)
# We may return fewer than top_k (the contract only caps the count). Long
# contexts dilute the fixed answer model, so the returned set is bounded.
RETURN_LIMIT = _int("AMI_RETURN_LIMIT", 40)
RETURN_CHAR_BUDGET = _int("AMI_RETURN_CHAR_BUDGET", 12000)

# --- auth (the platform smoke path uses none) --------------------------------
AUTH_SCHEME = os.environ.get("AMI_AUTH_SCHEME", "none").lower()  # none|bearer|token|x-api-key
AUTH_TOKEN = os.environ.get("AMI_AUTH_TOKEN", "")


def llm_available() -> bool:
    return bool(LLM_API_KEY)
