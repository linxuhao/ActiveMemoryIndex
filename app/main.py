"""Add / Search service implementing the Agent Memory Leaderboard contract."""
from __future__ import annotations

import datetime as dt
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
    scheme = config.AUTH_SCHEME
    if scheme == "none":
        return
    if scheme in {"bearer", "token"}:
        prefix = "Bearer " if scheme == "bearer" else "Token "
        supplied = authorization[len(prefix):] if authorization and authorization.startswith(prefix) else None
    elif scheme == "x-api-key":
        supplied = x_api_key
    else:
        return
    if not supplied or supplied != config.AUTH_TOKEN:
        raise HTTPException(status_code=401, detail={"reason": "invalid credentials"})


def stamp(timestamp: int | None) -> tuple[str | None, str]:
    """Return (ISO created_at, display prefix) for a Unix-millisecond timestamp."""
    if timestamp is None:
        return None, ""
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
                id=store.item_id(request.request_id, "raw", position),
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


def rank(index: store.UserIndex, query: str, options: list[str] | None) -> np.ndarray:
    """Fuse the original query with the user-voice recall question."""
    question = llm.recall_question(query, options) if config.llm_available() else None
    texts = [query] + ([question] if question else [])
    vectors = embed.encode(texts, is_query=True)
    scores = index.matrix @ vectors[0]
    if question:
        weight = config.RECALL_WEIGHT
        scores = (1.0 - weight) * scores + weight * (index.matrix @ vectors[1])
    return scores


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
    return chosen


# --- endpoints ---------------------------------------------------------------
@app.on_event("startup")
def startup() -> None:
    store.init()
    embed.warm_up()
    log.info(
        "ready: embed=%s llm=%s(%s) return_limit=%d recall_weight=%.2f",
        config.EMBED_MODEL,
        config.LLM_MODEL if config.llm_available() else "disabled",
        "key set" if config.llm_available() else "no key — raw-text fallback",
        config.RETURN_LIMIT,
        config.RECALL_WEIGHT,
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok", **store.stats(), "llm": config.llm_available()}


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
    if store.request_seen(request.request_id):
        return echo

    items, chunk_text = build_items(request)
    if chunk_text:
        prefix = chunk_prefix(request)
        for position, fact in enumerate(llm.extract_facts(chunk_text)):
            content = fact if fact.startswith("[") else f"{prefix}{fact}"
            items.append(
                store.Item(
                    id=store.item_id(request.request_id, "fact", position),
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

    scores = rank(index, request.query, request.options)
    data = [
        {
            "id": item.id,
            "content": item.content,
            "score": score,
            **({"created_at": item.created_at} if item.created_at else {}),
        }
        for item, score in select(index, scores, request.top_k)
    ]
    return {"data": data}
