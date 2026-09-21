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
LLM_MAX_TOKENS_EVENTS = _int("AMI_LLM_MAX_TOKENS_EVENTS", 900)
# The dated extraction returns a date beside every fact and turn; give it room.
LLM_MAX_TOKENS_EXTRACT_DATED = _int("AMI_LLM_MAX_TOKENS_EXTRACT_DATED", 1600)

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

# Slots held back from the first retrieval and given to a second, reflected one.
#
# AMI_AGENTIC_SEARCH already runs a second round, and on LoCoMo multi-hop
# questions it fired on 51 of 68 and changed the returned set — while the share
# of questions receiving all their evidence stayed at exactly 38 of 68. It fuses
# the two rounds into one score and selects once, so whatever the second round
# finds must still out-rank the first round's hundred. The evidence those
# questions are missing sits at a median rank of 213, and a fused score does not
# move it two hundred places.
#
# This reserves slots instead: the first round gets RETURN_LIMIT minus this many
# and the second round fills the rest from what the first did not already take.
# 0 leaves the single-round behaviour.
HOP2_SLOTS = _int("AMI_HOP2_SLOTS", 0)
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
# Return each selected fact together with the highest-scoring verbatim turns of
# the Add chunk it was extracted from — the symmetric move to WINDOW_RADIUS,
# which does this for turns but leaves facts pulling nothing.
#
# The cross-encoder arm showed why this might matter: a model scoring "does this
# passage answer the question" demotes every turn of a multi-evidence question,
# because none of them answers it alone (bench/results/locomo_rerank.md). A fact
# is a standalone claim and does not have that problem, so ranking the facts and
# letting them carry their evidence turns a multi-evidence retrieval problem into
# single-target retrieval plus a deterministic expansion.
#
# Chunk-level, not claim-level: pulling the turns that specifically support a
# fact would need the extractor to emit turn indices, and a longer extraction
# prompt is what moved the base +1.75 in bench/results/lme_event_dates_add.md.
# Like the neighbour window this spends slots from the same top_k.
#
# Measured. It PASSED its end-to-end gate on LongMemEval temporal (+5.75,
# 63/64/66/64 against 57/59/60/58, complete separation, p=0.029) with the
# gain exactly where the mechanism predicted: +4.25 on two-evidence
# questions, +2.00 on three-or-more, -0.50 on single-evidence. It then
# FAILED its pre-registered veto: LoCoMo cat1 complete@100 fell .596 to
# .543. Then LoCoMo END TO END confirmed the veto: -27 of 1540, sign test
# p=0.031, down in every category and every evidence bucket. One switch, two
# corpora, both significant, opposite signs -- the second mechanism in two
# days whose sign is set by the corpus (session length, ~10,900 chars per
# chunk on LongMemEval against ~2,600 on LoCoMo) rather than by the reader.
# Closed as a global default. A data-gated variant (expand only for long
# chunks) is the untested follow-up and would need end-to-end on BOTH corpora.
# See bench/results/lme_fact_evidence.md.
FACT_EVIDENCE = _int("AMI_FACT_EVIDENCE", 0)
# Score only extracted facts; verbatim turns stop being candidates for
# selection. On LoCoMo this had the best retrieval coverage measured anywhere in
# the project (complete@100 .904 against the shipped .850) and the worst
# accuracy of any non-degenerate arm (.5127 against .6802) — because that arm
# also *delivered* facts, and a fact is a lossy paraphrase. Paired with
# CHUNK_MEMORY it selects with facts and delivers verbatim text.
# See bench/results/locomo_lost_arms.md.
# Measured and failed its gate: paired with CHUNK_MEMORY at the shipped
# character budget it scored 51.50 against 58.50, complete separation,
# p=0.029 negative (bench/results/lme_chunk_memory.md). Fact-only selection
# has now been measured with both deliveries, lossy and verbatim. Closed.
FACT_SELECT = _env("AMI_FACT_SELECT", "0") != "0"
# Return a selected memory as the whole Add chunk it belongs to: that chunk's
# turns, verbatim and in order, joined into one memory. Chunks dedup, so many
# facts from one chunk cost one slot.
#
# The point is slot arithmetic. A returned memory costs one slot whatever its
# length and top_k counts memories, so a chunk delivered turn by turn costs ~18
# slots and a chunk delivered whole costs one. Simulated over the fact ranking,
# that is complete .558 against .904 at the same top_k=100.
#
# Permitted as evidence organisation (docs/cycle2_official_qa_zh.md, Q18) and
# the weakest possible use of that permission: no text is rewritten, so the
# query still only selects.
# Measured and failed. Uncapped it spends ~99,700 of the platform's 117,760
# Answer tokens; capped to the shipped budget it returns 7.2 memories and
# leaves 93 of the 100 slots unused, at identical evidence completeness and
# identical text, for -7.00 questions. The constraint is the size of the
# delivery unit, not the quality of selection, so no ranking change recovers
# it. See bench/results/lme_chunk_memory.md.
CHUNK_MEMORY = _env("AMI_CHUNK_MEMORY", "0") != "0"

# Ask the model when each returned memory's event actually happened, then do
# the arithmetic in code.
#
# Numbering memories by their own timestamp was measured and rejected: it
# indexes the utterance, not the event, so a user recounting two events in one
# sitting gets the same number on both and the model believes the number over
# the dates in the prose. Finding a time in free text is reading — "the day of
# my graduation" has no digits in it — so the reader does that part, and the
# subtraction, which it does badly, is done here.
#
# Costs one LLM call per EVENT_BATCH returned memories, on every search.
EVENT_DATES = _env("AMI_EVENT_DATES", "0") != "0"
EVENT_BATCH = _int("AMI_EVENT_BATCH", 20)
# The same question asked once, at Add, of the extraction call that already
# runs on every chunk — no extra calls, and a memory is dated once rather than
# on every search that returns it. EVENT_DATES_AT_ADD stores the date beside
# the memory; EVENT_DATES_STORED renders it at search the way EVENT_DATES does.
#
# Both measured, both failed their pre-registered gates:
# lme_event_dates_add.md (merged into extraction) +2.00, p=0.086; and
# lme_event_dates_call.md (its own call at Add) -2.25, p=0.086, on a store whose
# base reproduced lme-t exactly. The three readings produce comparable dates and
# agree on 87.7% of the memories they both date, yet score +5.75, +2.00 and
# -2.25. Only the reading that sees the RETURNED SET helps, and that one costs
# ~5 calls per search. The family is closed; the switches stay, all off.
EVENT_DATES_AT_ADD = _env("AMI_EVENT_DATES_AT_ADD", "0") != "0"
EVENT_DATES_STORED = _env("AMI_EVENT_DATES_STORED", "0") != "0"
# The separation arm: the SAME dedicated dating call the search-time reading
# makes, moved to Add. Measured: -2.25 (bench/results/lme_event_dates_call.md).
# Timing, not load, was the difference, and it runs the wrong way.
EVENT_DATES_ADD_CALL = _env("AMI_EVENT_DATES_ADD_CALL", "0") != "0"
# Order the returned memories oldest-first by their timestamp rather than by
# relevance, inside whatever block RAW_FIRST has already put them in. Like
# RAW_FIRST this changes order only, never membership. Temporal questions ask
# which of two events came first, or how far apart they were; when the returned
# set arrives in time order the answer is close to readable off the page,
# whereas relevance order interleaves the two dates among a hundred other
# memories. Off by default: it is an arm under measurement, not a finding.
CHRONO_ORDER = _env("AMI_CHRONO_ORDER", "0") != "0"
# Newest-first inside each block: the mirror of CHRONO_ORDER, for the
# knowledge-update case where an old and a replaced value both come back and
# the reader takes the first one it meets. Arm under measurement
# (bench/results/newest_first_preregistration.md). CHRONO_ORDER wins if both set.
NEWEST_FIRST = _env("AMI_NEWEST_FIRST", "0") != "0"

# --- reranking ---------------------------------------------------------------
# Re-read the top candidates with a cross-encoder before selecting. Empty = off.
#
# Measured and failed its pre-registered gate (bench/results/locomo_rerank.md):
# ms-marco-MiniLM-L-6-v2 over the top 200 doubled recall@1 and took LoCoMo
# multi-hop completeness from 0.559 to 0.456. A model scoring "does this passage
# answer the question" demotes the passages of a multi-evidence question, none
# of which answers it alone. Kept as the place a different rescorer would go;
# 26 ms/pair single-threaded at 256 tokens, so 200 candidates is about 5 s.
RERANK_MODEL = _env("AMI_RERANK_MODEL", "")
RERANK_CANDIDATES = _int("AMI_RERANK_CANDIDATES", 200)
RERANK_MAX_LENGTH = _int("AMI_RERANK_MAX_LENGTH", 256)
RERANK_BATCH = _int("AMI_RERANK_BATCH", 32)

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
