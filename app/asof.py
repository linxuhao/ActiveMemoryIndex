"""As-of evidence selection (AMI_ASOF_SELECT).

A question that asks for the state of something at a stated date ("What was
Maya's job title as of September 5, 2025?", "截至2024年1月，他住在哪里？") is
answered wrongly when the returned set also carries later values: the reader
takes the latest one (bench/results/lead_smoke_time_20261005.md). For such a
question, items that were not valid at that date are left out of the returned
set and the freed slots are refilled from the ranking. Membership only:
nothing is rewritten, nothing is computed for the reader, no answer is given.

No language-dependent pattern decides anything here (rc5). gpt-4o-mini reads
the language; code only compares ISO dates:

  * question side -- one call per distinct (query, options), started beside
    the recall-question rewrite so it adds no latency, cached: is this an
    as-of state question, an event-on-a-date question or neither, and which
    period (ISO start and end) does it name, in any language and any way of
    writing a date;
  * item side -- only for an as-of state question with a period: one call
    over the candidates not seen before (the items the Search would return,
    then the next ranked ones that could refill a withheld slot), each sent
    with the date it was said (our own stamp) and its text. The model gives
    every time the text states as ISO start and end -- including a time
    relative to the day it was said ("yesterday", "上周", "ayer") -- and
    whether it is a span something held over ("from X to Y"). Cached per item.

Then, as in rc4, over the judged items:
  (a) interval: an item stating spans, none of which overlaps the period, is
      withheld when some returned item states a span that does;
  (b) said after: an item said (stamp) after the end of the period whose text
      states no time that starts by the end of the period is withheld when
      some returned item was said by the end of the period. A stated time that
      does -- "in 2012", "yesterday" said the day after -- keeps it: the item
      may describe the period. ("This morning", said after it, does not.)
An event question withholds nothing (rc4's interval rule changed no event
question's list in any rc4 set). Unjudged items are never withheld, and any
failure withholds nothing.
"""
from __future__ import annotations

import calendar
import collections
import concurrent.futures
import contextvars
import datetime as dt
import json
import logging
import re
import threading

from . import config, llm, store

log = logging.getLogger("ami.asof")

Period = tuple[dt.date, dt.date]

# Our own stamp format ("[YYYY-MM-DD HH:MM] ", or the "[said ...]" re-render).
STAMP = re.compile(r"^\[(?:said )?(\d{4})-(\d{2})-(\d{2})[^\]]*\]\s*")
KINDS = ("as_of_state", "event_on_date", "other")


def _span(year: int, month: int | None = None, day: int | None = None) -> Period | None:
    try:
        if month is None:
            return dt.date(year, 1, 1), dt.date(year, 12, 31)
        if day is None:
            return dt.date(year, month, 1), dt.date(year, month, calendar.monthrange(year, month)[1])
        return dt.date(year, month, day), dt.date(year, month, day)
    except ValueError:
        return None


def parse_iso(value) -> Period | None:
    """'YYYY', 'YYYY-MM' or 'YYYY-MM-DD' (the model's format) -> the span it covers."""
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"\s*(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?\s*", value)
    if not match:
        return None
    year, month, day = match.groups()
    return _span(int(year), int(month) if month else None, int(day) if day else None)


def said(content: str) -> tuple[dt.date | None, str]:
    """(date the item was said, its text without the stamp)."""
    match = STAMP.match(content)
    if not match:
        return None, content
    try:
        day = dt.date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        day = None
    return day, content[match.end():]


_DELIVERED = re.compile(r"(.+)-(?:c0|s(\d+)-(\d+))$")  # our own chunk / span ids


def constituents(index: store.UserIndex, item: store.Item) -> list[store.Item]:
    """The stored items behind a returned memory: itself, or the turns of a
    chunk or span delivered by AMI_ADAPTIVE_CHUNK / AMI_CHUNK_MEMORY."""
    if item.id in index.by_id:
        return [item]
    match = _DELIVERED.match(item.id)
    if not match:
        return [item]
    digest, low, high = match.groups()
    rows = index.by_chunk.get(digest, [])
    if low is not None:
        wanted = {f"{digest}-r{p}" for p in range(int(low), int(high) + 1)}
        rows = [row for row in rows if index.items[row].id in wanted]
    return [index.items[row] for row in rows] or [item]


# --- question side ---------------------------------------------------------------
stats = collections.Counter()
_cache: "collections.OrderedDict[tuple, dict]" = collections.OrderedDict()
_cache_lock = threading.Lock()
CACHE_MAX = 10_000
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=max(1, config.LLM_CONCURRENCY),
                                                  thread_name_prefix="asof")


def parse_verdict(payload: dict | None) -> dict | None:
    """{"kind", "period": (start, end) | None}, or None for an unusable reply.
    A state or event question without a usable period is "other"."""
    if not isinstance(payload, dict) or payload.get("kind") not in KINDS:
        return None
    start, end = parse_iso(payload.get("start")), parse_iso(payload.get("end"))
    if start and not end:
        end = start
    if end and not start:
        start = end
    period = (start[0], end[1]) if start and end and start[0] <= end[1] else None
    kind = payload["kind"] if period else "other"
    return {"kind": kind, "period": period if kind != "other" else None}


def _remember(cache: collections.OrderedDict, key: tuple, value: dict) -> None:
    with _cache_lock:
        cache[key] = value
        while len(cache) > CACHE_MAX:
            cache.popitem(last=False)


def classify(query: str, options: list[str] | None) -> dict | None:
    """The question's verdict, or None when the call failed (the caller then
    withholds nothing; a failure is not cached)."""
    key = (query, tuple(str(o) for o in options or ()))
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            stats["classify_cached"] += 1
            return _cache[key]
    stats["classify_calls"] += 1
    try:
        verdict = parse_verdict(llm.classify_asof(query, options))
    except Exception:  # noqa: BLE001 - a failed classification withholds nothing
        log.exception("as-of classification failed")
        verdict = None
    if verdict is None:
        stats["classify_failures"] += 1
        return None
    stats[f"kind_{verdict['kind']}"] += 1
    _remember(_cache, key, verdict)
    return verdict


def start_classify(query: str, options: list[str] | None) -> concurrent.futures.Future:
    """classify() beside the recall-question rewrite; the Search's context (its
    deadline) goes with it."""
    return _executor.submit(contextvars.copy_context().run, classify, query, options)


def result(future: concurrent.futures.Future | None) -> dict | None:
    if future is None:
        return None
    try:
        return future.result()
    except Exception:  # noqa: BLE001 - includes a deadline: withhold nothing
        log.exception("as-of classification failed")
        return None


# --- item side -------------------------------------------------------------------
_times: "collections.OrderedDict[str, list[tuple[Period, bool]]]" = collections.OrderedDict()
TIMES_MAX = 200_000


def times(items: list[store.Item]) -> dict[str, list[tuple[Period, bool]]] | None:
    """Item id -> the times its text states, [(period, span)] ([] = none), or
    None when the call failed. One gpt-4o-mini call over the items not seen
    before (each with its stamp date, for relative references); cached per item."""
    with _cache_lock:
        pending = [item for item in items if item.id not in _times]
    if pending:
        # One line per distinct (said date, text): a fact often repeats its turn
        # word for word, and the model tends to skip a repeated line.
        lines, line_of = [], {}
        for item in pending:
            when, body = said(item.content)
            if item.kind == "raw":
                body = body.partition(": ")[2] or body  # our own speaker label ("I: ")
            text = " ".join(body.split())
            if len(text) > config.ASOF_ITEM_CHARS:
                text = text[: config.ASOF_ITEM_CHARS] + " ..."
            key = (when, text)
            if key not in line_of:
                line_of[key] = len(lines)
                lines.append(f"{len(lines)} | said {when.isoformat() if when else 'unknown'} | {text}")
            line_of[item.id] = line_of[key]
        stats["times_calls"] += 1
        stats["times_items"] += len(lines)
        try:
            payload = llm.asof_times("\n".join(lines))
        except Exception:  # noqa: BLE001
            log.exception("as-of time extraction failed")
            payload = None
        if not isinstance(payload, dict) or not isinstance(payload.get("times"), list):
            stats["times_failures"] += 1
            return None
        found: dict[int, list[tuple[Period, bool]]] = {number: [] for number in range(len(lines))}
        for entry in payload["times"]:
            if not isinstance(entry, list) or len(entry) != 4:
                continue
            try:
                number = int(entry[0])
            except (TypeError, ValueError):
                continue
            start, end = parse_iso(entry[1]), parse_iso(entry[2])
            if number in found and start and end and start[0] <= end[1]:
                found[number].append(((start[0], end[1]), entry[3] in (1, True)))
        with _cache_lock:
            for item in pending:
                _times[item.id] = found[line_of[item.id]]
            while len(_times) > TIMES_MAX:
                _times.popitem(last=False)
    with _cache_lock:
        return {item.id: _times.get(item.id, []) for item in items}


def overlaps(a: Period, b: Period) -> bool:
    return a[0] <= b[1] and a[1] >= b[0]


def withhold(period: Period, judged: list[store.Item], returned: list[store.Item],
             stated: dict[str, list[tuple[Period, bool]]]) -> set[str]:
    """Ids among *judged* to leave out, by rules (a) and (b) of the module doc."""
    def spans(item):
        return [p for p, span in stated.get(item.id, []) if span]

    any_valid_span = any(overlaps(p, period) for item in returned for p in spans(item))
    any_early = any((when := said(item.content)[0]) is not None and when <= period[1] for item in returned)
    out = set()
    for item in judged:
        own = spans(item)
        if any_valid_span and own and not any(overlaps(p, period) for p in own):
            out.add(item.id)  # (a)
            continue
        when = said(item.content)[0]
        if (any_early and when is not None and when > period[1]
                and not any(time[0] <= period[1] for time, _ in stated.get(item.id, []))):
            out.add(item.id)  # (b)
    return out


def select_withheld(index: store.UserIndex, scores, query: str, options: list[str] | None,
                    verdict: dict | None, returned: list[store.Item]) -> set[str]:
    """Item ids to leave out of this Search for its as-of period. Empty unless
    *verdict* is an as-of state question with a period."""
    if not verdict or verdict["kind"] != "as_of_state" or not verdict["period"]:
        return set()
    period = verdict["period"]
    stats["state_questions"] += 1
    import numpy as np  # local: keeps this module importable without numpy for tools

    limit = max(1, config.ASOF_ITEMS)
    rows: list[int] = []
    seen: set[int] = set()
    # What the Search would return first (by score), then the next ranked items
    # that could refill a withheld slot.
    first = sorted({index.by_id[item.id] for item in returned if item.id in index.by_id},
                   key=lambda row: -float(scores[row]))
    for row in first + [int(r) for r in np.argsort(-scores)]:
        if len(rows) >= limit:
            break
        if row in seen or not np.isfinite(scores[row]):
            continue
        seen.add(row)
        rows.append(row)
    judged = [index.items[row] for row in rows]
    if not judged:
        return set()
    stated = times(judged)
    if stated is None:
        return set()
    out = withhold(period, judged, returned, stated)
    returned_ids = {item.id for item in returned}
    stats["applied"] += bool(out & returned_ids)
    stats["withheld"] += len(out & returned_ids)
    return out


def dumps(verdict: dict | None) -> str:
    """For logs: periods as ISO strings."""
    if verdict is None:
        return "null"
    period = verdict.get("period")
    return json.dumps({"kind": verdict["kind"],
                       "period": [period[0].isoformat(), period[1].isoformat()] if period else None})
