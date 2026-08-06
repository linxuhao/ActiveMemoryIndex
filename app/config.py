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
LLM_TIMEOUT = _float("AMI_LLM_TIMEOUT", 60.0)
LLM_RETRIES = _int("AMI_LLM_RETRIES", 2)
LLM_MAX_FACTS = _int("AMI_LLM_MAX_FACTS", 24)
LLM_CONCURRENCY = _int("AMI_LLM_CONCURRENCY", 16)
# Reasoning models spend tokens before answering; raise these when developing
# against one. gpt-4o-mini never needs the headroom, and unused caps cost nothing.
LLM_MAX_TOKENS_EXTRACT = _int("AMI_LLM_MAX_TOKENS_EXTRACT", 1200)
LLM_MAX_TOKENS_QUERY = _int("AMI_LLM_MAX_TOKENS_QUERY", 200)

# Feature switches: with no API key both fall back to the raw-text-only path.
EXTRACT_ENABLED = os.environ.get("AMI_EXTRACT", "1") != "0"
RECALL_QUERY_ENABLED = os.environ.get("AMI_RECALL_QUERY", "1") != "0"
# Local reasoning models (Qwen3, etc.): inject <<DISABLE_THINKING>> into the system
# message so the gateway's thinking.jinja pre-fills a closed <think> tag. vLLM drops
# chat_template_kwargs, so this secret-code workaround is the only reliable path.
# Has no effect on gpt-4o-mini (the OpenAI API ignores it).
DISABLE_THINKING = os.environ.get("AMI_LLM_DISABLE_THINKING", "0") != "0"

# --- retrieval ---------------------------------------------------------------
# Weight of the user-voice recall question channel in the fused score.
RECALL_WEIGHT = _float("AMI_RECALL_WEIGHT", 0.5)
# We may return fewer than top_k (the contract only caps the count). Long
# contexts dilute the fixed answer model, so the returned set is bounded.
RETURN_LIMIT = _int("AMI_RETURN_LIMIT", 100)
RETURN_CHAR_BUDGET = _int("AMI_RETURN_CHAR_BUDGET", 400000)
# Agentic search: after the first retrieval, gpt-4o-mini checks whether the
# evidence is complete and may fire a second targeted recall question. Each
# round costs one extra LLM call + one extra embed pass.
AGENTIC_SEARCH = os.environ.get("AMI_AGENTIC_SEARCH", "1") != "0"
AGENTIC_MAX_ROUNDS = _int("AMI_AGENTIC_MAX_ROUNDS", 2)  # 2 = one reflection after the initial pass

# --- auth (the platform smoke path uses none) --------------------------------
AUTH_SCHEME = os.environ.get("AMI_AUTH_SCHEME", "none").lower()  # none|bearer|token|x-api-key
AUTH_TOKEN = os.environ.get("AMI_AUTH_TOKEN", "")


def llm_available() -> bool:
    return bool(LLM_API_KEY)
