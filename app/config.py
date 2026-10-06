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
# Diagnostic request log (JSON lines). Empty = off. When set, every /search
# records its query, options, any undocumented fields and the returned ids;
# every /add records message metadata (no content). It is evaluation data:
# keep it beside the database and delete it with the database.
REQUEST_LOG = _env("AMI_REQUEST_LOG")

# --- embedding model ---------------------------------------------------------
EMBED_BACKEND = _env("AMI_EMBED_BACKEND", "bge").lower()
EMBED_MODEL = _env("AMI_EMBED_MODEL", "text-embedding-v4" if EMBED_BACKEND == "openai"
                   else "BAAI/bge-small-en-v1.5")
EMBED_DEVICE = _env("AMI_EMBED_DEVICE", "cpu")
# Intra-op threads for the embedder. One is right whenever the server is already
# serving requests concurrently: the platform sends 16-64 at a time, so each of
# them opening its own OpenMP team oversubscribes the machine several times over
# and the workers spend their time in barriers. Measured on 8 cores / 16 threads,
# 16 concurrent Add-shaped calls (44 texts): 3.61/s at 8 threads, 4.53/s at 1.
# Search-shaped calls (2 texts, 32 concurrent): 70.4/s at 8, 101.8/s at 1.
EMBED_THREADS = _int("AMI_EMBED_THREADS", 1)
EMBED_BATCH = _int("AMI_EMBED_BATCH", 10 if EMBED_BACKEND == "openai" else 64)
# Separate credentials and endpoint: never inherit the LLM's OpenAI key/URL.
EMBED_API_KEY = _env("AMI_EMBED_API_KEY") or _env("DASHSCOPE_API_KEY")
EMBED_BASE_URL = _env("AMI_EMBED_BASE_URL")
EMBED_DIMENSIONS = _int("AMI_EMBED_DIMENSIONS", 1024)
# Per-attempt timeout, retries per batch, and the process-wide cap on
# text-embedding-v4 requests in flight. 40 s / 16 from rc4 (user decision after
# the lead smoke: provider tail latency produced 20 s timeouts at every
# concurrency including 4, and 16 gave 3.0-4.6x the throughput of 4 with no
# 429; bench/results/lead_smoke_time_20261005.md). Every attempt is clipped to
# the request's deadline (AMI_ADD_DEADLINE / AMI_SEARCH_DEADLINE below), so a
# longer timeout cannot push a request past the edge.
EMBED_TIMEOUT = _float("AMI_EMBED_TIMEOUT", 40.0)
EMBED_RETRIES = _int("AMI_EMBED_RETRIES", 1)
EMBED_CONCURRENCY = _int("AMI_EMBED_CONCURRENCY", 16)

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
# Zero-fact fallback (lead L5, P2; bench/results/zero_fact_fallback_preregistration.md).
# A chunk the extraction prompt returns no facts for (narration, a document, a
# table sent as messages) is read again by a third-person content prompt. One
# extra gpt-4o-mini call for such a chunk only; every other chunk is extracted
# exactly as before. Off.
EXTRACT_FALLBACK = _env("AMI_EXTRACT_FALLBACK", "0") != "0"
LLM_MAX_TOKENS_EXTRACT_FALLBACK = _int("AMI_LLM_MAX_TOKENS_EXTRACT_FALLBACK", 2400)
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
# Token budget for the returned set (app/tokens.py), on top of the character
# budget. The platform's Answer window is 128,000 tokens less 8,192 output and
# 2,048 safety = 117,760 input tokens, shared by the instructions, the question
# with its options, and the returned memories; Answer keeps a token-counted
# prefix of what does not fit. Per Search the memories get
#   (ANSWER_INPUT_TOKENS - ANSWER_PROMPT_TOKENS) / TOKEN_SAFETY - tokens(query + options)
# and each memory costs tokens(content) + ANSWER_ITEM_TOKENS. The largest
# platform answer template measured is ScriptMem's CHOICE_ANSWER_TEMPLATE at
# ~430 o200k tokens; 1,024 leaves room for chat framing and an instruction
# block we have not seen. ANSWER_ITEM_TOKENS covers "- [<ISO timestamp>] " and
# a newline (17 tokens measured). TOKEN_SAFETY 1.15 covers the tokenizer
# mismatch measured in bench/results/token_budget_20261006.md.
ANSWER_INPUT_TOKENS = _int("AMI_ANSWER_INPUT_TOKENS", 117_760)
ANSWER_PROMPT_TOKENS = _int("AMI_ANSWER_PROMPT_TOKENS", 1024)
ANSWER_ITEM_TOKENS = _int("AMI_ANSWER_ITEM_TOKENS", 20)
TOKEN_SAFETY = _float("AMI_TOKEN_SAFETY", 1.15)
TOKEN_ENCODING = _env("AMI_TOKEN_ENCODING", "o200k_base")
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
# Adaptive chunk delivery (lead L4, bench/results/adaptive_chunk_preregistration.md).
# A selected verbatim turn is delivered as its whole Add chunk -- the chunk's
# turns, verbatim, in order, joined into one memory -- when that chunk is at most
# AMI_ADAPTIVE_CHUNK characters; otherwise as the turn and its neighbours within
# AMI_WINDOW_RADIUS, added while the span stays within that size, overlapping or
# touching spans of one chunk merged into one memory. Facts are delivered as
# they are. The returned text is capped at AMI_ADAPTIVE_CHUNK_TOTAL characters
# (and always by the token budget). A turn withheld by an update or as-of rule is
# left out of the chunk or span text. Nothing is rewritten. 0 = off.
ADAPTIVE_CHUNK = _int("AMI_ADAPTIVE_CHUNK", 0)
ADAPTIVE_CHUNK_TOTAL = _int("AMI_ADAPTIVE_CHUNK_TOTAL", 120_000)

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
# memories. Measured flat on temporal (59 vs 57/59, one run; then 56.25 vs
# 58.50 x4, p=0.20) and +1.0/78 n.s. on knowledge-update
# (bench/results/lme_chrono_ku.md). Off: not a finding.
CHRONO_ORDER = _env("AMI_CHRONO_ORDER", "0") != "0"
# Newest-first inside each block: the mirror of CHRONO_ORDER, for the
# knowledge-update case where an old and a replaced value both come back and
# the reader takes the first one it meets. Measured: -9.25/78 on knowledge-update,
# p=0.029 (bench/results/lme_newest_first.md) -- the reader reads list position as
# time and takes the LAST mention as current, so newest-first pushes settled
# answers to older values. Closed; stays 0. CHRONO_ORDER wins if both set.
NEWEST_FIRST = _env("AMI_NEWEST_FIRST", "0") != "0"
# Render a returned fact that a later fact of the same user supersedes with
# that successor attached: "[superseded on <date> by: <successor>] <old>".
# Computed from the user's store, never from the query; stored text untouched;
# the old fact is kept. Closed at calibration: no cosine threshold separates a
# real update from same-topic chatter and restatements (hand-judged precision
# <= 0.20 at every tau on two stores), so it was never run end to end. Kept for
# an extractor-keyed link. bench/results/supersede_mark_calibration.md
# Add side: ask the extractor for a canonical "<subject>.<attribute>" key on
# facts that state the current value of a property that can change, store it,
# and let SUPERSEDE_MARK link by key equality instead of cosine. Measured:
# keyed marking +0.25/78 on knowledge-update, p=1.0 -- closed. The keyed
# prompt by itself moved the base +2.5 (p=0.029), unregistered, a lead only.
# bench/results/lme_fact_keys.md
FACT_KEYS = _env("AMI_FACT_KEYS", "0") != "0"
SUPERSEDE_MARK = _env("AMI_SUPERSEDE_MARK", "0") != "0"
SUPERSEDE_TAU = float(_env("AMI_SUPERSEDE_TAU", "0.90"))
# Explicit updates. All three off by default; see
# bench/results/explicit_update_preregistration.md.
# DETECT (Add): one extra gpt-4o-mini call per chunk, run beside extraction,
# finds statements in which the USER explicitly replaces or corrects a value
# ("UPDATE: replace the prior value ...", "correction: ...", "changed X from
# A to B") and stores (subject, attribute, new value, old value if stated,
# relative?) as a record. The extraction prompt is unchanged.
UPDATE_DETECT = _env("AMI_UPDATE_DETECT", "0") != "0"
# RENDER (Add, needs DETECT): also store each absolute update's current-state
# sentence ("Frank Herbert's genre is funk.") as a fact.
UPDATE_RENDER = _env("AMI_UPDATE_RENDER", "0") != "0"
# WITHHOLD (Search): leave out of the returned set the EARLIER items that state
# the value an absolute update replaced. Membership only; nothing is rewritten.
# Never for relative updates, never for history- or date-scoped questions.
UPDATE_WITHHOLD = _env("AMI_UPDATE_WITHHOLD", "0") != "0"
# Earlier items handed to the verification call per update (nearest first).
UPDATE_CANDIDATES = _int("AMI_UPDATE_CANDIDATES", 20)
LLM_MAX_TOKENS_UPDATES = _int("AMI_LLM_MAX_TOKENS_UPDATES", 600)
LLM_MAX_TOKENS_VERIFY = _int("AMI_LLM_MAX_TOKENS_VERIFY", 400)
# 2 (default): two-stage detector (intent labels with verbatim quotes, then
# extraction only for accepted replacements/corrections), user-only candidates
# for the user's own attributes, REPLACED/SAME/OTHER verifier.
# 1: the round-1 single-call detector and verifier, for reproduction.
# bench/results/explicit_update_r2_preregistration.md
# 3 (default): version 2 plus a same-language check before RENDER stores a
# sentence, facts of a confirmed-replaced turn's chunk re-verified, and a
# verifier that judges each memory against the update only
# (bench/results/explicit_update_r3_preregistration.md).
# 4 (default): version 3 plus the same-Add exclusion: nothing from the update's
# own Add request (raw turn or fact) is ever withheld
# (bench/results/explicit_update_r4_preregistration.md).
# 5 (default): version 4 with the language-dependent decisions moved to
# gpt-4o-mini: a per-Search question classifier (needs the past value? time
# scoped?) called only when withholding would change the returned set, and
# stage-2 "subject_is_user"/"relative" fields. The English patterns remain
# only as pre-filters that can add protection
# (bench/results/explicit_update_r5_preregistration.md).
# 6 (default, "round 5b"): version 5 with subject_is_user kept as its own field
# beside the subject text, and a revised router prompt. Version 5 as
# registered failed its gate (explicit_update_r5_20261005.md).
# 7 (default): version 6, but subject_is_user only narrows candidates to the
# user's turns; the subject-mention requirement is waived only when the
# subject text is the user marker ("me") itself.
UPDATE_VERSION = _int("AMI_UPDATE_VERSION", 7)
LLM_MAX_TOKENS_INTENT = _int("AMI_LLM_MAX_TOKENS_INTENT", 500)

# As-of evidence selection (lead L1, app/asof.py,
# bench/results/asof_selection_preregistration.md). For a question that asks
# for a state at a stated date, returned items not valid at that date (an
# explicit date range that misses it; said after it without naming a year) are
# withheld and their slots refilled from the ranking. gpt-4o-mini decides
# whether the question is such a question, one call per distinct question,
# only when the rules would change the returned set. Membership only. Off.
ASOF_SELECT = _env("AMI_ASOF_SELECT", "0") != "0"
# Candidates the rules are applied to: the top of the ranking plus whatever
# the returned set carries (window neighbours).
ASOF_POOL = _int("AMI_ASOF_POOL", 400)
# An item said up to this many days after the as-of period that uses
# relative-time wording ("yesterday", "上周") is kept: it describes the period.
ASOF_GRACE_DAYS = _int("AMI_ASOF_GRACE_DAYS", 31)
LLM_MAX_TOKENS_ASOF = _int("AMI_LLM_MAX_TOKENS_ASOF", 80)

# --- direct corpus interaction ------------------------------------------------
# Replace the embedding selection with a gpt-4o-mini agent that greps and reads
# the user's stored turns and facts, then names the memory ids to return. The
# agent never emits text; /search still returns stored items only. Arm
# pre-registered in bench/results/dci_search_preregistration.md.
DCI_SEARCH = _env("AMI_DCI_SEARCH", "0") != "0"
# 0: return exactly the agent's ids. 1: the agent's ids first, then the
# ordinary embedding selection fills the remaining slots.
DCI_FILL = _env("AMI_DCI_FILL", "0") != "0"
# Tool calls the agent may make before it is told to finish.
DCI_BUDGET = _int("AMI_DCI_BUDGET", 12)
# Persistent searcher (bench/results/dci_persistent_preregistration.md): with
# N > 0 the early-stop instruction is dropped and a finish before N tool calls
# is refused (the refusal counts toward the budget). 0 = finish whenever.
DCI_MIN_CALLS = _int("AMI_DCI_MIN_CALLS", 0)
DCI_GREP_HITS = _int("AMI_DCI_GREP_HITS", 20)
DCI_READ_LINES = _int("AMI_DCI_READ_LINES", 40)
DCI_MAX_TOKENS = _int("AMI_DCI_MAX_TOKENS", 600)

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

# --- admission (overload valve) -------------------------------------------------
# The platform drives Add at 16-64 concurrent requests and Search at 16-256
# (track contract options max_add_concurrency / search_concurrency), while our
# upstream gates admit far fewer (AMI_LLM_CONCURRENCY, AMI_EMBED_CONCURRENCY).
# Without a valve the excess queues inside the process, latency grows with the
# queue, and past the edge's ~100 s cut the caller sees a 524 for an Add that is
# still running. The API Guide sanctions 429 + Retry-After instead: Add retries
# 429 up to 32 attempts and honours Retry-After up to 60 s.
#
# With a limit set, at most that many requests of the endpoint run at once; a
# request that cannot get a slot within AMI_ADMISSION_WAIT seconds is answered
# 429 with Retry-After: AMI_RETRY_AFTER before any of its work starts, so a
# rejected Add persisted nothing and its retry is an ordinary first attempt.
# 0 = off (the request waits for a worker thread, as before).
ADD_MAX_INFLIGHT = _int("AMI_ADD_MAX_INFLIGHT", 0)
# Wall-clock deadline per request, from its arrival at the app (admission wait
# included), for all its upstream calls (app/deadline.py). An upstream call the
# deadline leaves no time for is not made and the request is answered 503 +
# Retry-After before anything is persisted. 85 s keeps a request inside the
# ~100 s edge cut with room to persist and respond. 0 = no deadline.
ADD_DEADLINE = _float("AMI_ADD_DEADLINE", 85.0)
SEARCH_DEADLINE = _float("AMI_SEARCH_DEADLINE", 85.0)
SEARCH_MAX_INFLIGHT = _int("AMI_SEARCH_MAX_INFLIGHT", 0)
ADMISSION_WAIT = _float("AMI_ADMISSION_WAIT", 30.0)
RETRY_AFTER = _int("AMI_RETRY_AFTER", 10)
# Extraction is normally best-effort: a failed gpt-4o-mini call stores the
# verbatim turns without facts and Add still returns 200, permanently. With
# this set, an extraction call that failed upstream (rate limit, timeout,
# connection, 5xx after the SDK's own retries) fails the Add with 429/503 +
# Retry-After before anything is persisted, so the platform's retry re-runs
# the extraction. The trade: a long provider outage then exhausts the
# platform's 32 attempts instead of degrading. Off by default.
EXTRACT_REQUIRED = _env("AMI_EXTRACT_REQUIRED", "0") != "0"

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
