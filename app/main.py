"""Add / Search service implementing the Agent Memory Leaderboard contract."""
from __future__ import annotations

import asyncio
import collections
import datetime as dt
import hmac
import itertools
import json
import logging
import re
import threading
import time

import numpy as np
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from . import asof, config, dci, deadline, embed, llm, rerank, store, tokens, updates

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("ami")

app = FastAPI(title="ActiveMemoryIndex", version="1.0.0")

_log_lock = threading.Lock()


def record(kind: str, **fields) -> None:
    """Append one JSON line to AMI_REQUEST_LOG; never fails the request."""
    if not config.REQUEST_LOG:
        return
    try:
        line = json.dumps({"kind": kind, "at": dt.datetime.now(dt.timezone.utc).isoformat(),
                           **fields}, ensure_ascii=False, default=str)
        with _log_lock, open(config.REQUEST_LOG, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except Exception:  # noqa: BLE001 - diagnostics must not affect serving
        log.exception("request log write failed")


# --- admission valve ---------------------------------------------------------
valve_counters = {"add_admitted": 0, "add_rejected": 0, "search_admitted": 0, "search_rejected": 0,
                  "upstream_429": 0, "upstream_503": 0, "deadline_503": 0}


def _limit(path: str | None) -> int:
    return {"/add": config.ADD_MAX_INFLIGHT, "/search": config.SEARCH_MAX_INFLIGHT}.get(path or "", 0)


class AdmissionValve:
    """Bound concurrent /add and /search work; shed the rest as 429 + Retry-After.

    Pure ASGI and async, so a waiting or rejected request holds no worker
    thread and never reaches the endpoint: a rejected Add has run no auth, no
    LLM call, no embedding and no write. Admission is first come, first served
    (tickets), and a request still waiting after AMI_ADMISSION_WAIT seconds is
    rejected. Everything runs on the event loop thread, so the counters need no
    lock. With both limits 0 this is a pass-through.
    """

    def __init__(self, app):
        self.app = app
        self.inflight = {"/add": 0, "/search": 0}
        self.queues = {"/add": collections.deque(), "/search": collections.deque()}
        self.tickets = itertools.count()

    async def __call__(self, scope, receive, send):
        path = scope.get("path") if scope["type"] == "http" and scope.get("method") == "POST" else None
        if path is not None:
            # The request deadline (app/deadline.py) counts from here, so time
            # spent waiting for admission is part of it.
            scope["ami_arrival"] = time.monotonic()
        limit = _limit(path)
        if limit <= 0:
            await self.app(scope, receive, send)
            return
        queue, ticket = self.queues[path], next(self.tickets)
        admit_by = time.monotonic() + config.ADMISSION_WAIT
        queue.append(ticket)
        try:
            while not (queue[0] == ticket and self.inflight[path] < limit):
                if time.monotonic() >= admit_by:
                    valve_counters[f"{path[1:]}_rejected"] += 1
                    await _overloaded(send, config.RETRY_AFTER)
                    return
                await asyncio.sleep(0.02)
        finally:
            queue.remove(ticket)
        self.inflight[path] += 1
        valve_counters[f"{path[1:]}_admitted"] += 1
        try:
            await self.app(scope, receive, send)
        finally:
            self.inflight[path] -= 1


async def _overloaded(send, retry_after: int) -> None:
    body = json.dumps({"detail": {"reason": f"overloaded; retry after {retry_after} s"}}).encode()
    await send({"type": "http.response.start", "status": 429,
                "headers": [(b"content-type", b"application/json"),
                            (b"retry-after", str(retry_after).encode()),
                            (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


app.add_middleware(AdmissionValve)


@app.exception_handler(llm.UpstreamUnavailable)
async def upstream_unavailable(_request, exc: llm.UpstreamUnavailable) -> JSONResponse:
    """429/503 + Retry-After for a transient provider failure.

    Raised only before persistence: on Add by the extraction call (with
    AMI_EXTRACT_REQUIRED) or the embedding call, both of which precede
    store.add; on Search, where nothing is written. The platform retries both
    statuses, so the retry of an Add is a clean first write.
    """
    valve_counters[f"upstream_{exc.status}"] += 1
    return JSONResponse({"detail": {"reason": exc.reason}}, status_code=exc.status,
                        headers={"Retry-After": str(exc.retry_after)})


@app.exception_handler(deadline.DeadlineExceeded)
async def deadline_exceeded(_request, exc: deadline.DeadlineExceeded) -> JSONResponse:
    """503 + Retry-After: the request's deadline left no time for an upstream
    call. Raised before persistence, like UpstreamUnavailable."""
    valve_counters["deadline_503"] += 1
    return JSONResponse({"detail": {"reason": exc.reason}}, status_code=503,
                        headers={"Retry-After": str(exc.retry_after)})


def encode_or_unavailable(texts: list[str], **kwargs) -> np.ndarray:
    """embed.encode, with a transient provider failure surfaced as UpstreamUnavailable."""
    try:
        return embed.encode(texts, **kwargs)
    except Exception as exc:
        mapped = llm.transient(exc)
        if mapped is None:
            raise
        raise mapped from exc


# --- contract models ---------------------------------------------------------
# extra="allow" throughout: pydantic drops unknown fields silently, so a field
# the caller has been sending all along would never surface anywhere. One of
# them matters a great deal — a question timestamp would answer 42 of the 133
# temporal questions this project cannot currently reach (see
# bench/results/lme_temporal_baseline.md). Retaining them costs nothing and
# note_extra() reports the names.
class Message(BaseModel):
    model_config = ConfigDict(extra="allow")
    role: str
    content: str
    timestamp: int | None = None


class AddRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
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
    model_config = ConfigDict(extra="allow")
    query: str
    user_id: str
    top_k: int
    options: list[str] | None = None


_reported_extra: set[tuple[str, ...]] = set()


def note_extra(endpoint: str, *models: BaseModel) -> None:
    """Log the names of fields the caller sent that the contract does not name.

    Names only, never values: the payload is somebody's memories, and this line
    goes to a log file. Once per distinct set of names, so a 72-hour run does
    not repeat itself eighteen thousand times.
    """
    names: set[str] = set()
    for model in models:
        names |= set(getattr(model, "model_extra", None) or ())
    if not names:
        return
    key = (endpoint, *sorted(names))
    if key in _reported_extra:
        return
    _reported_extra.add(key)
    log.info("UNDOCUMENTED FIELDS on /%s: %s", endpoint, sorted(names))


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


STAMPED = re.compile(r"^\[(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})\] ")


def event_indexed(items: list[store.Item]) -> dict[str, str]:
    """Map item id -> content re-rendered with the event's date and day number.

    Only memories the reader could actually date are touched. A memory it
    declined to date is left exactly as it was: an index on everything, when
    everything shares an utterance date, is what broke ordering questions the
    last time this was tried.
    """
    stamped = [(item, match) for item in items for match in [STAMPED.match(item.content)] if match]
    if not stamped:
        return {}
    found: dict[int, str] = {}
    if config.EVENT_DATES_STORED:
        for position, (item, _) in enumerate(stamped):
            if item.event_date:
                found[position] = item.event_date
    if config.EVENT_DATES:
        pending = [(position, item, m) for position, (item, m) in enumerate(stamped) if position not in found]
        for start in range(0, len(pending), config.EVENT_BATCH):
            block = pending[start: start + config.EVENT_BATCH]
            batch = [(m.group(1), item.content[m.end():]) for _, item, m in block]
            for offset, iso in llm.event_dates(batch).items():
                found[block[offset][0]] = iso

    dated = []
    for position, iso in found.items():
        try:
            dated.append((position, dt.date.fromisoformat(iso)))
        except ValueError:
            continue
    if not dated:
        return {}
    first = min(day for _, day in dated)
    out: dict[str, str] = {}
    for position, day in dated:
        item, match = stamped[position]
        out[item.id] = (f"[said {match.group(1)} {match.group(2)} \u00b7 happened {day.isoformat()} "
                        f"\u00b7 day {(day - first).days + 1}] " + item.content[match.end():])
    return out


def date_items(items: list[store.Item]) -> int:
    """Ask the reader when each stamped memory's event happened; store it.

    Exactly the call ``event_indexed`` makes at search time, over a chunk's own
    memories instead of over a returned set. Failure leaves every date None,
    which is the same as the switch being off. Returns how many were dated.
    """
    stamped = [(item, match) for item in items for match in [STAMPED.match(item.content)] if match]
    dated = 0
    for start in range(0, len(stamped), config.EVENT_BATCH):
        block = stamped[start: start + config.EVENT_BATCH]
        batch = [(m.group(1), item.content[m.end():]) for item, m in block]
        for offset, iso in llm.event_dates(batch).items():
            block[offset][0].event_date = iso
            dated += 1
    return dated


def build_items(request: AddRequest) -> tuple[list[store.Item], list[str]]:
    """Raw messages (verbatim, timestamped) plus the lines handed to the LLM, one per item."""
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
    return items, lines


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
    vectors = encode_or_unavailable(texts, is_query=True)
    scores = index.matrix @ vectors[0]
    if recall_question:
        weight = config.RECALL_WEIGHT
        scores = (1.0 - weight) * scores + weight * (index.matrix @ vectors[1])
    if config.FACT_SELECT:
        # Verbatim turns stop being candidates and facts do the selecting. The
        # turns still reach the reader, through the chunk their fact belongs to.
        turns = np.fromiter((item.kind != "fact" for item in index.items), bool, len(index.items))
        scores = np.where(turns, -np.inf, scores)
    return scores


RAW_ID = re.compile(r"(.+)-r(\d+)$")


def neighbours(index: store.UserIndex, item: store.Item) -> list[store.Item]:
    """The turns either side of *item* within the Add chunk it came from.

    Item ids are "<chunk digest>-r<position>" (see store.item_id), so a
    neighbour is the same digest at position +/- k. Positions that were empty at
    write time simply do not exist and are skipped.
    """
    match = RAW_ID.match(item.id)
    if not match or config.WINDOW_RADIUS <= 0:
        return []
    prefix, position = match.group(1), int(match.group(2))
    out = []
    for offset in range(-config.WINDOW_RADIUS, config.WINDOW_RADIUS + 1):
        if offset == 0:
            continue
        row = index.by_id.get(f"{prefix}-r{position + offset}")
        if row is not None:
            out.append(index.items[row])
    return out


def evidence(index: store.UserIndex, item: store.Item, scores: np.ndarray) -> list[store.Item]:
    """The highest-scoring turns of the Add chunk *item* was extracted from.

    The symmetric move to ``neighbours``, which does this for turns and leaves
    facts pulling nothing. A fact is a standalone claim, so it survives the kind
    of relevance scoring that demotes every turn of a multi-evidence question —
    none of which answers it alone (bench/results/locomo_rerank.md).
    """
    if config.FACT_EVIDENCE <= 0 or item.kind != "fact":
        return []
    rows = index.by_chunk.get(item.id.rsplit("-", 1)[0], [])
    best = sorted(rows, key=lambda row: -scores[row])[: config.FACT_EVIDENCE]
    return [index.items[row] for row in best]


def chunk_memory(index: store.UserIndex, item: store.Item) -> store.Item:
    """*item*'s whole Add chunk as one memory: its turns, verbatim, in order.

    One slot instead of eighteen. Nothing is rewritten — the content is the
    stored turns concatenated — so the query still only selects.
    """
    digest = item.id.rsplit("-", 1)[0]
    rows = index.by_chunk.get(digest)
    if not rows:
        return item
    turns = [index.items[row] for row in rows]
    return store.Item(id=f"{digest}-c0", kind="chunk", parent_id=None,
                      content="\n".join(turn.content for turn in turns),
                      created_at=turns[0].created_at)


def content_key(item: store.Item) -> str:
    return " ".join(item.content.lower().split())[:120]


def superseded(index: store.UserIndex, chosen: list[store.Item]) -> dict[str, str]:
    """Map fact id -> rendering with its successor attached, for returned
    facts that a strictly later fact of the same user resembles at cosine >=
    SUPERSEDE_TAU. The successor is the latest such fact. A function of the
    store only: the query chose the fact, it does not choose the marker."""
    out: dict[str, str] = {}
    if config.FACT_KEYS:
        # By key equality: the latest strictly-later fact carrying the same
        # canonical key. Unkeyed facts are never marked. The cosine path below
        # is closed (bench/results/supersede_mark_calibration.md).
        for item in chosen:
            if item.kind != "fact" or not item.fact_key or not item.created_at:
                continue
            later = [index.items[row] for row in index.by_key.get(item.fact_key, ())
                     if (index.items[row].created_at or "") > item.created_at]
            if later:
                successor = max(later, key=lambda it: it.created_at)
                out[item.id] = (f"[superseded on {successor.created_at[:10]} by: "
                                f"{successor.content}] {item.content}")
        return out
    if index.matrix is None:
        return out
    facts = [row for row, item in enumerate(index.items) if item.kind == "fact" and item.created_at]
    if not facts:
        return out
    fact_rows = np.asarray(facts)
    stamps = [index.items[row].created_at for row in facts]
    for item in chosen:
        if item.kind != "fact" or not item.created_at:
            continue
        row = index.by_id.get(item.id)
        if row is None:
            continue
        later = np.fromiter((stamp > item.created_at for stamp in stamps), bool, len(stamps))
        if not later.any():
            continue
        sims = index.matrix[fact_rows[later]] @ index.matrix[row]
        hits = np.nonzero(sims >= config.SUPERSEDE_TAU)[0]
        if hits.size == 0:
            continue
        candidates = fact_rows[later][hits]
        successor = index.items[max(candidates, key=lambda r: index.items[r].created_at)]
        out[item.id] = (f"[superseded on {successor.created_at[:10]} by: "
                        f"{successor.content}] {item.content}")
    return out


def order(chosen: list[tuple[store.Item, float]]) -> None:
    """Sort the selected set in place. Reorders, never adds or drops."""
    if config.NEWEST_FIRST:
        # Stable, so the block sort below keeps each block newest-first inside.
        chosen.sort(key=lambda pair: pair[0].created_at or "", reverse=True)
    if config.RAW_FIRST or config.CHRONO_ORDER:
        chosen.sort(key=lambda pair: (
            (pair[0].kind not in ("raw", "chunk")) if config.RAW_FIRST else False,
            (pair[0].created_at or "9999") if config.CHRONO_ORDER else "",
        ))


# Consecutive candidates skipped for not fitting the token budget before the
# scan stops: past this, the remaining budget is smaller than what the ranking
# is turning up, and walking a large user's whole store finds nothing.
TOKEN_MISSES = 50


def select(index: store.UserIndex, scores: np.ndarray, top_k: int,
           limit_override: int | None = None, exclude: set[str] | None = None,
           budget_override: int | None = None,
           withheld: set[str] | None = None,
           token_budget: int | None = None) -> list[tuple[store.Item, float]]:
    """The returned set, in delivery order.

    Bounded three ways: at most *limit* memories (top_k, AMI_RETURN_LIMIT),
    at most the character budget, and at most *token_budget* counted tokens
    (app/tokens.py; default: the whole Answer window with an empty query). A
    memory that does not fit the token budget is skipped, never cut, and the
    first memory gets no exception: the token budget is never exceeded.
    """
    limit = min(top_k, config.RETURN_LIMIT) if limit_override is None else limit_override
    chosen: list[tuple[store.Item, float]] = []
    seen: set[str] = set(exclude or ())
    budget = config.RETURN_CHAR_BUDGET if budget_override is None else budget_override
    tokens_left = tokens.memory_budget() if token_budget is None else token_budget
    if limit <= 0 or budget <= 0 or tokens_left <= 0:
        return chosen
    if config.ADAPTIVE_CHUNK > 0 and not config.CHUNK_MEMORY:
        chosen = select_adaptive(index, scores, limit, seen, budget, tokens_left, withheld or set())
        order(chosen)
        return chosen
    misses = 0

    def take(item: store.Item, score: float) -> bool:
        """Append one memory if it is new and affordable. True when full."""
        nonlocal budget, tokens_left, misses
        if withheld and item.id in withheld:
            return False
        key = content_key(item)
        if key in seen:
            return False
        if len(item.content) > budget and chosen:
            return False
        cost = tokens.item_cost(item.content)
        if cost > tokens_left:
            misses += 1
            return misses >= TOKEN_MISSES
        misses = 0
        seen.add(key)
        budget -= len(item.content)
        tokens_left -= cost
        chosen.append((item, score))
        return len(chosen) >= limit or budget <= 0 or tokens_left <= config.ANSWER_ITEM_TOKENS

    for position in np.argsort(-scores):
        item = index.items[int(position)]
        score = float(scores[int(position)])
        # A score of -inf means the item was ruled out of selection, and
        # argsort puts every one of them last: nothing below here is a
        # candidate, so stop rather than fill the limit with excluded items.
        if score == float("-inf"):
            break
        if config.CHUNK_MEMORY:
            # The chunk carries its own neighbours and its own evidence, so
            # neither expansion runs: they would only re-add what is inside it.
            if take(chunk_memory(index, item), score):
                break
            continue
        if take(item, score):
            break
        # A verbatim turn brings its neighbours, and a fact brings the best
        # turns of the chunk it was extracted from. Both take slots from the
        # same top_k — breadth of sources traded for context, not extra text.
        full = False
        for extra in neighbours(index, item) + evidence(index, item, scores):
            if take(extra, score):
                full = True
                break
        if full:
            break
    # Verbatim turns first, extracted facts after, each block keeping its
    # relevance order — the reader attends to the head of the context, and a
    # verbatim turn is the primary source while a fact is a lossy paraphrase.
    order(chosen)
    return chosen


def select_adaptive(index: store.UserIndex, scores: np.ndarray, limit: int, seen: set[str],
                    budget: int, tokens_left: int, withheld: set[str]) -> list[tuple[store.Item, float]]:
    """AMI_ADAPTIVE_CHUNK delivery, in relevance order (the caller orders).

    A verbatim hit becomes its whole Add chunk when the chunk's text is at most
    S = AMI_ADAPTIVE_CHUNK characters, else a span: the hit turn (always whole)
    and its neighbours within AMI_WINDOW_RADIUS, each added only while the span
    stays within S. A span that overlaps or touches an already chosen span of
    the same chunk is merged into it, in that span's place. Facts are taken as
    they are. Withheld turns are never part of a chunk or span: a chunk is the
    stored turns that remain, concatenated in order. Each memory costs one slot.
    """
    items = index.items
    radius = max(0, config.WINDOW_RADIUS)
    size = config.ADAPTIVE_CHUNK
    mems: list[dict] = []
    whole: set[str] = set()
    misses = 0

    def text(rows: list[int]) -> str:
        return "\n".join(items[row].content for row in rows)

    def span_rows(digest: str, positions) -> list[int]:
        rows = [index.by_id.get(f"{digest}-r{p}") for p in sorted(positions)]
        return [row for row in rows if row is not None and items[row].id not in withheld]

    for position in np.argsort(-scores):
        item = items[int(position)]
        score = float(scores[int(position)])
        if score == float("-inf"):
            break
        if item.id in withheld:
            continue
        match = RAW_ID.match(item.id) if item.kind == "raw" else None
        replaced: list[dict] = []
        if match:
            digest, hit = match.group(1), int(match.group(2))
            if digest in whole:
                continue
            rows = [row for row in index.by_chunk.get(digest, []) if items[row].id not in withheld]
            content = text(rows)
            if rows and len(content) <= size:
                entry = {"kind": "chunk", "digest": digest, "rows": rows}
            else:
                positions, length = {hit}, len(item.content)
                for offset in range(1, radius + 1):
                    for other, inner in ((hit - offset, hit - offset + 1), (hit + offset, hit + offset - 1)):
                        row = index.by_id.get(f"{digest}-r{other}")
                        # Contiguous only: a turn joins when the one between it
                        # and the hit has joined.
                        if row is None or items[row].id in withheld or inner not in positions:
                            continue
                        if length + 1 + len(items[row].content) <= size:
                            positions.add(other)
                            length += 1 + len(items[row].content)
                low, high = min(positions), max(positions)
                replaced = [m for m in mems if m["kind"] == "span" and m["digest"] == digest
                            and min(m["positions"]) - 1 <= high and low <= max(m["positions"]) + 1]
                for m in replaced:
                    positions |= m["positions"]
                rows = span_rows(digest, positions)
                content = text(rows)
                entry = {"kind": "span", "digest": digest, "rows": rows, "positions": positions}
        else:
            content = item.content
            entry = {"kind": "item", "item": item}
        key = content_key(store.Item(id="", kind="", parent_id=None, content=content, created_at=None))
        if key in seen and not replaced:
            continue
        cost = tokens.item_cost(content)
        delta_chars = len(content) - sum(len(m["content"]) for m in replaced)
        delta_tokens = cost - sum(m["cost"] for m in replaced)
        if replaced and delta_chars <= 0:
            continue
        if (delta_chars > budget and mems) or delta_tokens > tokens_left:
            misses += 1
            if misses >= TOKEN_MISSES:
                break
            continue
        misses = 0
        entry.update(content=content, cost=cost, score=score)
        seen.add(key)
        budget -= delta_chars
        tokens_left -= delta_tokens
        if replaced:
            place = mems.index(replaced[0])
            entry["score"] = replaced[0]["score"]
            mems[place] = entry
            for m in replaced[1:]:
                mems.remove(m)
        else:
            mems.append(entry)
        if entry["kind"] == "chunk":
            whole.add(entry["digest"])
        if len(mems) >= limit or budget <= 0 or tokens_left <= config.ANSWER_ITEM_TOKENS:
            break

    out: list[tuple[store.Item, float]] = []
    for m in mems:
        if m["kind"] == "item":
            out.append((m["item"], m["score"]))
            continue
        rows = m["rows"]
        ident = (f"{m['digest']}-c0" if m["kind"] == "chunk"
                 else f"{m['digest']}-s{min(m['positions'])}-{max(m['positions'])}")
        out.append((store.Item(id=ident, kind="chunk", parent_id=None, content=m["content"],
                               created_at=items[rows[0]].created_at), m["score"]))
    return out


# --- endpoints ---------------------------------------------------------------
@app.on_event("startup")
def startup() -> None:
    problem = config.auth_misconfigured()
    if problem:
        # Refusing to start is louder than 401-ing every request forever, which
        # looks to the caller like their credentials are wrong.
        raise RuntimeError(problem)
    store.init()
    embed.warm_up()
    if config.RERANK_MODEL:
        rerank.warm_up()
    if config.AUTH_SCHEME == "none":
        log.warning("auth is DISABLED (AMI_AUTH_SCHEME=none): anyone who can reach this "
                    "service can read and write any user_id")
    elif config.AUTH_SCHEME not in {"bearer", "token", "x-api-key"}:
        log.warning("AMI_AUTH_SCHEME=%r is not a documented scheme; a secret is still "
                    "required, but check your configuration", config.AUTH_SCHEME)
    log.info(
        "ready: auth=%s embed=%s llm=%s(%s) return_limit=%d recall_weight=%.2f agentic=%s raw_first=%s window=%d fact_evidence=%d fact_select=%s chunk_memory=%s rerank=%s event_dates=%s cache_max=%d embed_threads=%d",
        config.AUTH_SCHEME,
        config.EMBED_MODEL,
        config.LLM_MODEL if config.llm_available() else "disabled",
        "key set" if config.llm_available() else "no key — raw-text fallback",
        config.RETURN_LIMIT,
        config.RECALL_WEIGHT,
        "on" if config.AGENTIC_SEARCH else "off",
        "on" if config.RAW_FIRST else "off",
        config.WINDOW_RADIUS,
        config.FACT_EVIDENCE,
        "on" if config.FACT_SELECT else "off",
        "on" if config.CHUNK_MEMORY else "off",
        config.RERANK_MODEL or "off",
        f"add:{int(config.EVENT_DATES_AT_ADD)}/addcall:{int(config.EVENT_DATES_ADD_CALL)}/stored:{int(config.EVENT_DATES_STORED)}/llm:{int(config.EVENT_DATES)}",
        config.CACHE_MAX_ITEMS,
        config.EMBED_THREADS,
    )
    log.info("budget: answer_input=%d prompt=%d item=%d safety=%.2f counter=%s; deadlines add=%.0fs search=%.0fs; "
             "embed timeout=%.0fs retries=%d concurrency=%d; adaptive_chunk=%d",
             config.ANSWER_INPUT_TOKENS, config.ANSWER_PROMPT_TOKENS, config.ANSWER_ITEM_TOKENS,
             config.TOKEN_SAFETY, tokens.backend(), config.ADD_DEADLINE, config.SEARCH_DEADLINE,
             config.EMBED_TIMEOUT, config.EMBED_RETRIES, config.EMBED_CONCURRENCY,
             config.ADAPTIVE_CHUNK)


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
    counters.update({f"dci_{key}": value for key, value in dci.counters.items()})
    counters.update({f"valve_{key}": value for key, value in valve_counters.items()})
    counters.update({f"asof_{key}": value for key, value in asof.stats.items()})
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
    http: Request = None,
) -> AddResponse:
    check_auth(authorization, x_api_key)
    note_extra("add", request, *request.messages)
    started = time.monotonic()
    deadline.start(config.ADD_DEADLINE, http.scope.get("ami_arrival") if http is not None else None)
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
            record("add", request_id=request.request_id, user_id=request.user_id, duplicate=True)
            return echo

        items, lines = build_items(request)
        detection = (updates.start_detection(items)
                     if lines and config.UPDATE_DETECT and config.llm_available() else None)
        records: list[dict] = []
        if lines:
            prefix = chunk_prefix(request)
            if config.EVENT_DATES_AT_ADD:
                # One call for both: the facts, and when each fact's and each
                # turn's event happened. Turn n is items[n]: build_items keeps
                # the two lists aligned.
                facts, turn_dates = llm.extract_dated(lines)
                keys = [None] * len(facts)
                for position, iso in turn_dates.items():
                    if position < len(items):
                        items[position].event_date = iso
            elif config.FACT_KEYS:
                keyed = llm.extract_keyed("\n".join(lines))
                facts = [(fact, None) for fact, _ in keyed]
                keys = [key for _, key in keyed]
            else:
                facts = [(fact, None) for fact in llm.extract_facts("\n".join(lines))]
            for position, (fact, happened) in enumerate(facts):
                content = fact if fact.startswith("[") else f"{prefix}{fact}"
                items.append(
                    store.Item(
                        id=store.item_id(request.request_id, "fact", position, request.user_id),
                        kind="fact",
                        parent_id=None,
                        content=content,
                        created_at=items[0].created_at if items else None,
                        event_date=happened,
                        fact_key=keys[position] if config.FACT_KEYS else None,
                    )
                )
        if detection is not None:
            records = detection.result()
            if config.UPDATE_RENDER:
                # The update's current value as a plain statement, beside the
                # extracted facts; numbered after them so ids never collide.
                position = sum(1 for item in items if item.kind == "fact")
                turns = {item.id: item.content for item in items if item.kind == "raw"}
                for found in records:
                    if not updates.renderable(found, turns.get(found["item_id"], "")):
                        continue
                    statement = found["statement"]
                    items.append(store.Item(
                        id=store.item_id(request.request_id, "fact", position, request.user_id),
                        kind="fact", parent_id=None,
                        content=statement if statement.startswith("[") else f"{prefix}{statement}",
                        created_at=items[0].created_at if items else None))
                    position += 1
        if items and config.EVENT_DATES_ADD_CALL:
            # One dedicated call per chunk, asking only for dates.
            date_items(items)
        if items:
            vectors = encode_or_unavailable([item.content for item in items])
            store.add(request.user_id, request.session_id, request.request_id, items, vectors,
                      updates=records)
        stamps = [m.timestamp for m in request.messages if m.timestamp is not None]
        record("add", request_id=request.request_id, user_id=request.user_id,
               session_id=request.session_id, messages=len(request.messages),
               roles=sorted({m.role for m in request.messages}),
               timestamps=len(stamps), first_ts=min(stamps, default=None),
               last_ts=max(stamps, default=None),
               chars=sum(len(m.content) for m in request.messages),
               facts=sum(1 for item in items if item.kind == "fact"),
               extra=sorted(set(request.model_extra or ())
                            | {k for m in request.messages for k in (m.model_extra or ())}),
               ms=round((time.monotonic() - started) * 1000))
    return echo


@app.post("/search")
def search(
    request: SearchRequest,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
    http: Request = None,
) -> dict:
    check_auth(authorization, x_api_key)
    note_extra("search", request)
    started = time.monotonic()
    deadline.start(config.SEARCH_DEADLINE, http.scope.get("ami_arrival") if http is not None else None)
    result = _search(request)
    if config.REQUEST_LOG:
        data = result["data"]
        record("search", user_id=request.user_id, top_k=request.top_k,
               query=request.query, options=request.options,
               extra={k: v for k, v in (request.model_extra or {}).items()},
               returned=len(data), chars=sum(len(d["content"]) for d in data),
               ids=[d["id"] for d in data],
               ms=round((time.monotonic() - started) * 1000))
    return result


def _search(request: SearchRequest) -> dict:
    if request.top_k <= 0:
        return {"data": []}
    index = store.get(request.user_id)
    if index.matrix is None or not index.items:
        return {"data": []}
    # Counted tokens this Search's memories may use in the Answer window,
    # after the question and its options (app/tokens.py).
    token_budget = tokens.memory_budget(request.query, request.options)
    if token_budget <= config.ANSWER_ITEM_TOKENS:
        return {"data": []}

    # Round 1: standard fused retrieval. With slots reserved for a second round
    # it takes fewer, so the second round is not competing for the same places.
    reserved = 0
    if config.HOP2_SLOTS > 0 and config.llm_available():
        reserved = max(0, min(config.HOP2_SLOTS, min(request.top_k, config.RETURN_LIMIT) - 1))
    # As-of classification (app/asof.py) runs beside the recall-question
    # rewrite inside rank(), so it adds no latency of its own.
    asof_future = (asof.start_classify(request.query, request.options)
                   if config.ASOF_SELECT and config.llm_available() else None)
    scores1 = rank(index, request.query, request.options)
    if config.RERANK_MODEL:
        scores1 = rerank.rescore(index, request.query, scores1)

    # Earlier items stating a value the user explicitly replaced. Empty unless
    # AMI_UPDATE_WITHHOLD is on and this user has update records.
    withheld = (updates.withheld(index, request.user_id, request.query)
                if config.UPDATE_WITHHOLD else set())
    if withheld:
        # Ask whether the question needs the old value only when withholding
        # would change what is returned; otherwise it is a no-op anyway.
        trial = select(index, scores1, request.top_k,
                       limit_override=min(request.top_k, config.RETURN_LIMIT) - reserved if reserved else None,
                       token_budget=token_budget)
        if not any(item.id in withheld for item, _ in trial) or \
                updates.question_protected(request.query, request.options):
            withheld = set()
    verdict = asof.result(asof_future)
    if verdict is not None and verdict["kind"] == "as_of_state":
        # Items not valid at the question's as-of period (app/asof.py), judged
        # against the set that would otherwise be returned; withheld slots are
        # refilled from the ranking by the selection below.
        returned = select(index, scores1, request.top_k,
                          limit_override=min(request.top_k, config.RETURN_LIMIT) - reserved if reserved else None,
                          withheld=withheld, token_budget=token_budget)
        withheld = withheld | asof.select_withheld(
            index, scores1, request.query, request.options, verdict,
            [turn for item, _ in returned for turn in asof.constituents(index, item)])
    chosen1 = select(index, scores1, request.top_k,
                     limit_override=min(request.top_k, config.RETURN_LIMIT) - reserved if reserved else None,
                     withheld=withheld, token_budget=token_budget)

    if reserved:
        reflection = llm.reflect_gap(request.query, request.options,
                                     [item.content for item, _ in chosen1[:15]])
        if reflection and reflection.get("status") == "INCOMPLETE" and reflection.get("question"):
            scores2 = rank(index, request.query, request.options,
                           recall_question=reflection["question"])
            # The second round fills its own slots out of what the first did not
            # take. Fusing the two scores instead — which is what
            # AMI_AGENTIC_SEARCH does — leaves the second round's finds to
            # out-rank the first round's hundred, and the evidence these
            # questions miss sits two hundred places down.
            spent = sum(len(item.content) for item, _ in chosen1)
            chosen1 += select(index, scores2, request.top_k,
                              limit_override=reserved,
                              exclude={content_key(item) for item, _ in chosen1},
                              budget_override=config.RETURN_CHAR_BUDGET - spent,
                              withheld=withheld,
                              token_budget=token_budget - sum(tokens.item_cost(item.content)
                                                              for item, _ in chosen1))
            order(chosen1)

    # Agentic round: reflect → maybe a second retrieval
    if config.AGENTIC_SEARCH and config.llm_available():
        top_contents = [item.content for item, _ in chosen1[:15]]
        reflection = llm.reflect_gap(request.query, request.options, top_contents)
        if reflection and reflection.get("status") == "INCOMPLETE":
            ref_question = reflection.get("question", "")
            if ref_question:
                scores2 = rank(index, request.query, request.options,
                               recall_question=ref_question)
                # Fuse the two rounds at the score level, then run the ordinary
                # selection once. Merging two already-selected lists instead
                # re-sorted them by score, which silently undid raw-first, and
                # applied a looser character budget than select() does — so
                # turning this switch on changed three things at once and the
                # arm could not be read. Now it changes what is scored, and
                # nothing else.
                #
                # Element-wise max, not mean: the second question exists to
                # reach evidence the first one missed, and averaging would
                # dilute exactly those items back below the cut.
                chosen1 = select(index, np.maximum(scores1, scores2), request.top_k, withheld=withheld,
                                 token_budget=token_budget)

    # Direct corpus interaction: an agent greps and reads the store and names
    # the ids to return. It replaces the selection above (arm `dci`) or leads
    # it (arm `dcifill`); on any failure the selection above stands.
    if config.DCI_SEARCH and config.llm_available():
        limit = min(request.top_k, config.RETURN_LIMIT)
        picked = dci.run(index, request.query, request.options, limit)
        if picked is None:
            dci.counters["fallbacks"] += 1
        else:
            agent = [(item, 1.0 - position / 1000.0) for position, item in enumerate(picked)
                     if item.id not in withheld]
            if config.DCI_FILL and len(agent) < limit:
                spent = sum(len(item.content) for item, _ in agent)
                fill = select(index, scores1, request.top_k,
                              limit_override=limit - len(agent),
                              exclude={content_key(item) for item, _ in agent},
                              budget_override=config.RETURN_CHAR_BUDGET - spent,
                              withheld=withheld,
                              token_budget=token_budget - sum(tokens.item_cost(item.content)
                                                              for item, _ in agent))
                order(fill)
                chosen1 = agent + fill
            else:
                chosen1 = agent

    # Re-rendered on the way out; the stored text is never rewritten, so turning
    # this off returns exactly what it returned before.
    redated = (event_indexed([item for item, _ in chosen1])
               if config.EVENT_DATES or config.EVENT_DATES_STORED else {})
    if config.SUPERSEDE_MARK:
        redated.update(superseded(index, [item for item, _ in chosen1]))
    data = [
        {
            "id": item.id,
            "content": redated.get(item.id, item.content),
            "score": score,
            **({"created_at": item.created_at} if item.created_at else {}),
        }
        for item, score in chosen1
    ]
    # Every path above is bounded by the token budget; this is the guarantee
    # for what is re-rendered on the way out (event dates, supersession marks)
    # and for the agent's own picks. The returned order is kept and only a
    # tail that would not fit is dropped -- what Answer would drop anyway.
    return {"data": data[: tokens.fit([d["content"] for d in data], token_budget)]}
