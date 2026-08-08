"""Add / Search service implementing the Agent Memory Leaderboard contract."""
from __future__ import annotations

import datetime as dt
import hmac
import logging

import numpy as np
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from . import config, embed, llm, store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("ami")

app = FastAPI(title="ActiveMemoryIndex", version="1.0.0")


# --- contract models ---------------------------------------------------------
class Message(BaseModel):
    role: str
    content: str
    timestamp: int | None = None


class AddRequest(BaseModel):
    request_id: str
    messages: list[Message] = Field(min_length=1)
    user_id: str
    session_id: str


class AddResponse(BaseModel):
    success: bool
    request_id: str
    user_id: str
    session_id: str


class SearchRequest(BaseModel):
    query: str
    user_id: str
    top_k: int
    options: list[str] | None = None


# --- helpers -----------------------------------------------------------------
def check_auth(authorization: str | None, x_api_key: str | None) -> None:
    """Accept the secret under any documented scheme.

    The declared scheme is `AMI_AUTH_SCHEME`, but accepting only that one turns
    a caller's harmless scheme or casing difference into a 100% failure rate
    with no partial credit. Any of Bearer / Token / X-Api-Key carrying the
    right secret is honoured; anything else is rejected.
    """
    if config.AUTH_SCHEME == "none":
        return
    supplied = []
    if authorization:
        parts = authorization.split(None, 1)
        if len(parts) == 2 and parts[0].lower() in {"bearer", "token"}:
            supplied.append(parts[1].strip())
        else:
            supplied.append(authorization.strip())
    if x_api_key:
        supplied.append(x_api_key.strip())
    if config.AUTH_TOKEN and any(hmac.compare_digest(config.AUTH_TOKEN, s) for s in supplied):
        return
    raise HTTPException(status_code=401, detail={"reason": "invalid credentials"})


def stamp(timestamp: int | None) -> tuple[str | None, str]:
    """Return (ISO created_at, display prefix) for a Unix-millisecond timestamp."""
    if timestamp is None:
        return None, ""
    # The contract says Unix milliseconds. A sender using seconds would
    # otherwise silently stamp every memory 1970 — and that wrong date is
    # embedded in the stored text and fed to the extractor.
    if 0 < timestamp < 100_000_000_000:
        log.warning("timestamp %s looks like seconds, not milliseconds; scaling", timestamp)
        timestamp *= 1000
    try:
        moment = dt.datetime.fromtimestamp(timestamp / 1000, tz=dt.timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None, ""
    return moment.isoformat().replace("+00:00", "Z"), moment.strftime("[%Y-%m-%d %H:%M] ")


def build_items(request: AddRequest) -> tuple[list[store.Item], str]:
    """Raw messages (verbatim, timestamped) plus the chunk text handed to the LLM."""
    items: list[store.Item] = []
    lines: list[str] = []
    for position, message in enumerate(request.messages):
        content = (message.content or "").strip()
        if not content:
            continue
        created_at, prefix = stamp(message.timestamp)
        speaker = "I" if message.role == "user" else (message.role or "other").capitalize()
        items.append(
            store.Item(
                id=store.item_id(request.request_id, "raw", position, request.user_id),
                kind="raw",
                parent_id=None,
                content=f"{prefix}{speaker}: {content}",
                created_at=created_at,
            )
        )
        lines.append(f"{prefix}{message.role}: {content}")
    return items, "\n".join(lines)


def chunk_prefix(request: AddRequest) -> str:
    for message in request.messages:
        if message.timestamp is not None:
            return stamp(message.timestamp)[1]
    return ""


def rank(index: store.UserIndex, query: str, options: list[str] | None,
         recall_question: str | None = None) -> np.ndarray:
    """Fuse the original query with a user-voice recall question.

    When *recall_question* is given it is used directly; otherwise one is
    generated from *query* and *options*.
    """
    if recall_question is None:
        recall_question = llm.recall_question(query, options) if config.llm_available() else None
    texts = [query] + ([recall_question] if recall_question else [])
    vectors = embed.encode(texts, is_query=True)
    scores = index.matrix @ vectors[0]
    if recall_question:
        weight = config.RECALL_WEIGHT
        scores = (1.0 - weight) * scores + weight * (index.matrix @ vectors[1])
    return scores


def fuse_lexical(index: store.UserIndex, scores: np.ndarray, user_id: str, query: str) -> np.ndarray:
    """Fuse the dense ranking with BM25 by reciprocal rank.

    Rank fusion rather than score fusion: cosine is bounded in [-1, 1] while
    BM25 is unbounded and corpus-dependent, so any fixed weighting of the two
    raw scores is set by their accidental scales. Every row keeps a dense rank,
    so a query that matches nothing lexically degrades exactly to dense-only.
    """
    if not config.HYBRID:
        return scores
    hits = store.lexical(user_id, query, config.HYBRID_CANDIDATES)
    if not hits:
        return scores
    k = config.HYBRID_RRF_K
    total = len(scores)
    fused = np.empty(total, dtype=np.float64)
    fused[np.argsort(-scores)] = 1.0 / (k + np.arange(1, total + 1))
    weight = config.HYBRID_LEX_WEIGHT
    for position, item_id in enumerate(hits):
        row = index.positions.get(item_id)
        if row is not None:
            fused[row] += weight / (k + position + 1)
    return fused


def select(index: store.UserIndex, scores: np.ndarray, top_k: int) -> list[tuple[store.Item, float]]:
    limit = min(top_k, config.RETURN_LIMIT)
    chosen: list[tuple[store.Item, float]] = []
    seen: set[str] = set()
    budget = config.RETURN_CHAR_BUDGET
    for position in np.argsort(-scores):
        item = index.items[int(position)]
        key = " ".join(item.content.lower().split())[:120]
        if key in seen:
            continue
        if len(item.content) > budget and chosen:
            continue
        seen.add(key)
        budget -= len(item.content)
        chosen.append((item, float(scores[int(position)])))
        if len(chosen) >= limit or budget <= 0:
            break
    if config.RAW_FIRST:
        # Verbatim turns first, extracted facts after, each block keeping its
        # relevance order. The selected set is untouched — only its order — but
        # the reader attends to the head of the context, and a verbatim turn is
        # the primary source while a fact is a lossy paraphrase of it.
        chosen.sort(key=lambda pair: pair[0].kind != "raw")
    return chosen


# --- endpoints ---------------------------------------------------------------
@app.on_event("startup")
def startup() -> None:
    problem = config.auth_misconfigured()
    if problem:
        # Refusing to start is louder than 401-ing every request forever, which
        # looks to the caller like their credentials are wrong.
        raise RuntimeError(problem)
    store.init()
    backfilled = store.backfill_fts()
    if backfilled:
        log.info("lexical index backfilled for %d rows", backfilled)
    embed.warm_up()
    if config.AUTH_SCHEME == "none":
        log.warning("auth is DISABLED (AMI_AUTH_SCHEME=none): anyone who can reach this "
                    "service can read and write any user_id")
    elif config.AUTH_SCHEME not in {"bearer", "token", "x-api-key"}:
        log.warning("AMI_AUTH_SCHEME=%r is not a documented scheme; a secret is still "
                    "required, but check your configuration", config.AUTH_SCHEME)
    log.info(
        "ready: auth=%s embed=%s llm=%s(%s) return_limit=%d recall_weight=%.2f agentic=%s raw_first=%s hybrid=%s",
        config.AUTH_SCHEME,
        config.EMBED_MODEL,
        config.LLM_MODEL if config.llm_available() else "disabled",
        "key set" if config.llm_available() else "no key — raw-text fallback",
        config.RETURN_LIMIT,
        config.RECALL_WEIGHT,
        "on" if config.AGENTIC_SEARCH else "off",
        "on" if config.RAW_FIRST else "off",
        (f"on(k={config.HYBRID_RRF_K},cand={config.HYBRID_CANDIDATES},"
         f"kinds={config.HYBRID_KINDS},lex_weight={config.HYBRID_LEX_WEIGHT:g})")
        if config.HYBRID else "off",
    )


@app.get("/health")
def health(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> dict:
    # Liveness is unauthenticated by contract ("any 2xx means healthy"), but the
    # store's size is not liveness — it tells an anonymous caller how much
    # evaluation data we hold. Details require the same secret as Search.
    try:
        check_auth(authorization, x_api_key)
    except HTTPException:
        return {"status": "ok"}
    counters = dict(llm.counters)
    calls, failures = counters["calls"], counters["failures"]
    # "llm: true" only says a key is configured. A key that 401s on every call
    # reported healthy right through a quota outage, so say so out loud.
    degraded = calls >= 5 and failures / calls > 0.5
    return {
        "status": "degraded" if degraded else "ok",
        **store.stats(),
        "llm": config.llm_available(),
        **counters,
    }


@app.post("/add", response_model=AddResponse)
def add(
    request: AddRequest,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> AddResponse:
    check_auth(authorization, x_api_key)
    echo = AddResponse(
        success=True,
        request_id=request.request_id,
        user_id=request.user_id,
        session_id=request.session_id,
    )
    # One writer per (request_id, user_id): a retry that overlaps the original
    # waits here and then observes the completed write, instead of racing it.
    with store.request_gate(request.request_id, request.user_id):
        if store.request_seen(request.request_id, request.user_id):
            return echo

        items, chunk_text = build_items(request)
        if chunk_text:
            prefix = chunk_prefix(request)
            for position, fact in enumerate(llm.extract_facts(chunk_text)):
                content = fact if fact.startswith("[") else f"{prefix}{fact}"
                items.append(
                    store.Item(
                        id=store.item_id(request.request_id, "fact", position, request.user_id),
                        kind="fact",
                        parent_id=None,
                        content=content,
                        created_at=items[0].created_at if items else None,
                    )
                )
        if items:
            vectors = embed.encode([item.content for item in items])
            store.add(request.user_id, request.session_id, request.request_id, items, vectors)
    return echo


@app.post("/search")
def search(
    request: SearchRequest,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> dict:
    check_auth(authorization, x_api_key)
    if request.top_k <= 0:
        return {"data": []}
    index = store.get(request.user_id)
    if index.matrix is None or not index.items:
        return {"data": []}

    # Round 1: standard fused retrieval
    scores1 = rank(index, request.query, request.options)
    scores1 = fuse_lexical(index, scores1, request.user_id, request.query)
    chosen1 = select(index, scores1, request.top_k)

    # Agentic round: reflect → maybe a second retrieval
    if config.AGENTIC_SEARCH and config.llm_available():
        top_contents = [item.content for item, _ in chosen1[:15]]
        reflection = llm.reflect_gap(request.query, request.options, top_contents)
        if reflection and reflection.get("status") == "INCOMPLETE":
            ref_question = reflection.get("question", "")
            if ref_question:
                scores2 = rank(index, request.query, request.options,
                               recall_question=ref_question)
                scores2 = fuse_lexical(index, scores2, request.user_id, ref_question)
                chosen2 = select(index, scores2, request.top_k)
                # Merge: combine, deduplicate by content key, keep best score
                merged: dict[str, tuple[store.Item, float]] = {}
                for item, score in chosen1 + chosen2:
                    key = " ".join(item.content.lower().split())[:120]
                    if key not in merged or score > merged[key][1]:
                        merged[key] = (item, score)
                # Re-sort, then re-apply BOTH caps. Slicing on RETURN_LIMIT
                # alone let the merged set exceed top_k — a contract violation.
                merged_sorted = sorted(merged.values(), key=lambda x: -x[1])
                limit = min(request.top_k, config.RETURN_LIMIT)
                budget = config.RETURN_CHAR_BUDGET
                chosen1 = []
                for item, score in merged_sorted:
                    if len(chosen1) >= limit or budget <= 0:
                        break
                    budget -= len(item.content)
                    chosen1.append((item, score))

    data = [
        {
            "id": item.id,
            "content": item.content,
            "score": score,
            **({"created_at": item.created_at} if item.created_at else {}),
        }
        for item, score in chosen1
    ]
    return {"data": data}
