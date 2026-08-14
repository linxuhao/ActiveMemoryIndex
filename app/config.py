"""Runtime configuration, all through environment variables."""
from __future__ import annotations

import os


def _env(name: str, default: str = "") -> str:
    """Read an environment variable, tolerating inline comments.

    `docker run --env-file` passes `KEY=value  # comment` through verbatim, so a
    hand-copied .env silently turns every value into prose. Reading defensively
    here makes every launch path — compose, --env-file, plain -e — agree.
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.split(" #", 1)[0].split("\t#", 1)[0].strip().strip('"').strip("'")


def _int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


# --- storage -----------------------------------------------------------------
DB_PATH = _env("AMI_DB_PATH", "/data/memory.sqlite3")

# --- embedding model ---------------------------------------------------------
EMBED_MODEL = _env("AMI_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
EMBED_DEVICE = _env("AMI_EMBED_DEVICE", "cpu")
# Intra-op threads for the embedder. One is right whenever the server is already
# serving requests concurrently: the platform sends 16-64 at a time, so each of
# them opening its own OpenMP team oversubscribes the machine several times over
# and the workers spend their time in barriers. Measured on 8 cores / 16 threads,
# 16 concurrent Add-shaped calls (44 texts): 3.61/s at 8 threads, 4.53/s at 1.
# Search-shaped calls (2 texts, 32 concurrent): 70.4/s at 8, 101.8/s at 1.
EMBED_THREADS = _int("AMI_EMBED_THREADS", 1)
EMBED_BATCH = _int("AMI_EMBED_BATCH", 64)

# --- LLM (competition rule: must be gpt-4o-mini for a leaderboard run) --------
LLM_MODEL = _env("AMI_LLM_MODEL", "gpt-4o-mini")
LLM_BASE_URL = _env("OPENAI_BASE_URL") or None
LLM_API_KEY = _env("OPENAI_API_KEY", "")
# The public endpoint sits behind Cloudflare, which cuts the origin at ~100 s
# regardless of the platform's 1200 s allowance. timeout x (retries+1) must
# stay well under that, or the edge manufactures the retries that then race
# each other at the same request_id.
LLM_TIMEOUT = _float("AMI_LLM_TIMEOUT", 25.0)
LLM_RETRIES = _int("AMI_LLM_RETRIES", 1)
LLM_MAX_FACTS = _int("AMI_LLM_MAX_FACTS", 24)
# Matches the server threadpool: a smaller gate only adds queueing on top of
# the provider's own limits, and queueing is what pushes a request past the edge.
LLM_CONCURRENCY = _int("AMI_LLM_CONCURRENCY", 40)
# Reasoning models spend tokens before answering; raise these when developing
# against one. gpt-4o-mini never needs the headroom, and unused caps cost nothing.
LLM_MAX_TOKENS_EXTRACT = _int("AMI_LLM_MAX_TOKENS_EXTRACT", 1200)
LLM_MAX_TOKENS_QUERY = _int("AMI_LLM_MAX_TOKENS_QUERY", 200)

# Feature switches: with no API key both fall back to the raw-text-only path.
EXTRACT_ENABLED = _env("AMI_EXTRACT", "1") != "0"
RECALL_QUERY_ENABLED = _env("AMI_RECALL_QUERY", "1") != "0"
# Local reasoning models (Qwen3, etc.): inject <<DISABLE_THINKING>> into the system
# message so the gateway's thinking.jinja pre-fills a closed <think> tag. vLLM drops
# chat_template_kwargs, so this secret-code workaround is the only reliable path.
# Has no effect on gpt-4o-mini (the OpenAI API ignores it).
DISABLE_THINKING = _env("AMI_LLM_DISABLE_THINKING", "0") != "0"

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
AGENTIC_SEARCH = _env("AMI_AGENTIC_SEARCH", "0") != "0"
# Order the returned memories verbatim-turns-first, extracted-facts-second,
# each block still in relevance order. This changes only the order of the set
# already selected, never which memories are returned.
RAW_FIRST = _env("AMI_RAW_FIRST", "1") != "0"
# Return each selected verbatim turn together with the turns either side of it,
# from the same Add chunk. A single message is often not self-contained — the
# pronoun's antecedent, the other speaker's reply and the session's date all sit
# in the neighbouring turns — and the answer model cannot recover what was never
# sent. Neighbours consume slots from the same top_k, so this trades breadth of
# sources for local context rather than returning more text: measured on LoCoMo
# it moves 26.2 distinct source chunks to 20.9 and adds 8% characters.
# Radius 1, 2 and 3 were statistically indistinguishable from one another
# (.6802 / .6695 / .6763, paired p=0.16 and p=0.69); all three beat radius 0
# (.6333) decisively. 1 is shipped because it keeps the most breadth per slot.
WINDOW_RADIUS = _int("AMI_WINDOW_RADIUS", 1)

# --- memory ------------------------------------------------------------------
# Upper bound on rows held in the per-user vector cache, across all users. The
# cache is a read-through of SQLite, so eviction costs a reload, never a result.
# Without a bound, a suite whose datasets carry one user_id per question — a
# hundred thousand rows is 0.15 GB of vectors plus roughly as much again in
# Python objects — grows until the process is killed, and a 72-hour evaluation
# is a bad place to discover that.
#
# Sizing: one row costs 384 float32 (1.5 kB) plus roughly 0.5 kB of Python
# object, so a million rows is about 2 GB. The default suits an 8 GB host; raise
# it on a larger one. Where the host has zram, raising it is close to free — the
# kernel compresses cold pages instead of the process dying, and a search that
# touches a swapped-out user pays one decompression of a few megabytes. Note the
# vectors themselves barely compress; the text does.
CACHE_MAX_ITEMS = _int("AMI_CACHE_MAX_ITEMS", 1_000_000)

# --- auth (the platform smoke path uses none) --------------------------------
# Fail closed. A memory service reachable from the internet with auth off by
# default is the worst available default, and a launch path that forgets to set
# a scheme must not silently open the service. Set AMI_AUTH_SCHEME=none
# deliberately for local testing.
AUTH_SCHEME = _env("AMI_AUTH_SCHEME", "bearer").lower()  # none|bearer|token|x-api-key
AUTH_TOKEN = _env("AMI_AUTH_TOKEN", "")
PLACEHOLDER_TOKENS = {"", "change-me", "changeme", "your-token-here"}


def auth_misconfigured() -> str | None:
    """Return a reason string when the auth configuration cannot be honoured."""
    if AUTH_SCHEME == "none":
        return None
    if AUTH_TOKEN in PLACEHOLDER_TOKENS:
        return (
            f"AMI_AUTH_SCHEME={AUTH_SCHEME} requires a real AMI_AUTH_TOKEN; got "
            f"{'an empty value' if not AUTH_TOKEN else 'a known placeholder value'}. "
            "Generate one with: python3 -c \"import secrets; print(secrets.token_hex(32))\" "
            "— or set AMI_AUTH_SCHEME=none for local testing."
        )
    return None


def llm_available() -> bool:
    return bool(LLM_API_KEY)
