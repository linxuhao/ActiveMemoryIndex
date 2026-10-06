"""As-of evidence selection (AMI_ASOF_SELECT, lead L1).

A question that asks for the state of something at a stated date ("What was
Maya's job title as of September 5, 2025?", "截至2024年1月，他住在哪里？") is
answered wrongly when the returned set also carries later values: the reader
takes the latest one (bench/results/lead_smoke_time_20261005.md). For such a
question, items that were not valid at that date are left out of the returned
set and the freed slots are refilled from the ranking. Membership only:
nothing is rewritten, nothing is computed for the reader, no answer is given.

Two rules, over the candidates the ranking puts near the top:
  (a) interval: an item stating explicit date ranges, none of which overlaps
      the as-of period, is withheld when some returned item states a range
      that does;
  (b) said after: an item said (its stamp) after the end of the as-of period
      whose text names no year is withheld when some returned item was said
      on or before it -- unless it uses relative-time wording ("yesterday",
      "上周", "ayer") and was said within AMI_ASOF_GRACE_DAYS of the period,
      because "yesterday I came back from San Francisco" said the day after
      describes the day itself.

Who decides. A cheap, language-neutral gate first: the question must contain a
year written in digits. A multilingual date parser (ISO, English and five
other European month names, CJK and Korean year-month-day) gives a candidate
period, and the rules are tried. Only when they would change the returned set
is gpt-4o-mini asked (one call per distinct question, cached) whether the
question asks for a state as of that time, an event on that date, or neither,
and for the date itself, normalised from any language. Rule (b) is applied
only to state questions; rule (a) to state and event questions; nothing to
the rest. The router's date replaces the parser's when it gives one, so a
format the parser does not know still works once something would change.
The relative-time word list only ever keeps items (adds protection).
"""
from __future__ import annotations

import calendar
import collections
import datetime as dt
import json
import logging
import re
import threading

from . import config, llm, store

log = logging.getLogger("ami.asof")

Period = tuple[dt.date, dt.date]

YEAR = r"(1[0-9]{3}|20[0-9]{2})"
_MONTHS = {
    # English
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10,
    "nov": 11, "dec": 12,
    # Spanish
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
    # French
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7,
    "août": 8, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
    # German
    "januar": 1, "jänner": 1, "februar": 2, "märz": 3, "maerz": 3, "juni": 6, "juli": 7, "oktober": 10,
    "dezember": 12,
    # Portuguese
    "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "maio": 5, "junho": 6, "julho": 7, "setembro": 9,
    "outubro": 10, "novembro": 11, "dezembro": 12,
    # Italian
    "gennaio": 1, "febbraio": 2, "aprile": 4, "maggio": 5, "giugno": 6, "luglio": 7, "settembre": 9,
    "ottobre": 10, "dicembre": 12,
}
MON = "(" + "|".join(sorted((re.escape(m) for m in _MONTHS), key=len, reverse=True)) + r")\.?"
_OF = r"(?:\s+(?:of|de|del|di)\s+|\s*,\s*|\.\s*|\s+)"

# Most specific first; a later pattern never claims text an earlier one took.
PATTERNS = [
    ("ymd", re.compile(rf"(?<!\d){YEAR}[-/.](\d{{1,2}})[-/.](\d{{1,2}})(?!\d)")),
    ("cjk_ymd", re.compile(rf"{YEAR}\s*[年년]\s*(\d{{1,2}})\s*[月월]\s*(\d{{1,2}})\s*[日号號일]?")),
    ("cjk_ym", re.compile(rf"{YEAR}\s*[年년]\s*(\d{{1,2}})\s*[月월]")),
    ("dmy_dots", re.compile(rf"(?<![\d.])(\d{{1,2}})\.(\d{{1,2}})\.{YEAR}(?!\d)")),
    ("mdy", re.compile(rf"(?<![\w]){MON}\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+{YEAR}(?!\d)", re.I)),
    ("dmy", re.compile(rf"(?<![\w.])(\d{{1,2}})(?:st|nd|rd|th|er|º|\.)?(?:\s+de|\s+of)?\s+{MON}{_OF}{YEAR}(?!\d)", re.I)),
    ("my", re.compile(rf"(?<![\w]){MON}{_OF}{YEAR}(?!\d)", re.I)),
    ("cjk_y", re.compile(rf"{YEAR}\s*[年년]")),
    ("y", re.compile(rf"(?<![\d.,/:-]){YEAR}(?![\d/:]|\s*[年년])")),
]
ANY_YEAR = re.compile(rf"(?<!\d){YEAR}(?!\d)")
STAMP = re.compile(r"^\[(?:said )?(\d{4})-(\d{2})-(\d{2})[^\]]*\]\s*")
RANGE_JOIN = re.compile(r"^\s*(?:,\s*)?(?:to|until|till|through|thru|and|[-–—~]|到|至|～|a|al|hasta|au|jusqu'?au|bis)\s*$",
                        re.I)
RANGE_OPEN = re.compile(r"(?:from|between|从|自|desde|entre|de|du|von)\s*$", re.I)
# Relative-time wording: may only KEEP an item (protection), never withhold one.
RELATIVE = re.compile(
    r"\b(?:yesterday|last (?:night|week|weekend|month|year|monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
    r"the other day|(?:a few|two|three|couple of) (?:days|weeks) ago|days? ago|weeks? ago|recently|earlier this "
    r"(?:week|month)|ayer|la semana pasada|el mes pasado|hier|la semaine derni[eè]re|le mois dernier|gestern|"
    r"letzte woche|letzten monat|ontem|semana passada|ieri|la settimana scorsa)\b"
    r"|昨天|前天|上周|上星期|上个月|上個月|前几天|前幾天|最近|昨日|先週|先月|어제|지난주|지난달", re.I)


def _span(year: int, month: int | None = None, day: int | None = None) -> Period | None:
    try:
        if month is None:
            return dt.date(year, 1, 1), dt.date(year, 12, 31)
        if day is None:
            return dt.date(year, month, 1), dt.date(year, month, calendar.monthrange(year, month)[1])
        return dt.date(year, month, day), dt.date(year, month, day)
    except ValueError:
        return None


def _month(name: str) -> int:
    return _MONTHS[name.lower().rstrip(".")]


def dates(text: str) -> list[tuple[int, int, Period]]:
    """Date expressions carrying a year, as (start, end, period), in text order."""
    found: list[tuple[int, int, Period]] = []
    taken: list[tuple[int, int]] = []
    for kind, pattern in PATTERNS:
        for match in pattern.finditer(text):
            a, b = match.span()
            if any(a < y and x < b for x, y in taken):
                continue
            g = match.groups()
            try:
                if kind in ("ymd", "cjk_ymd"):
                    span = _span(int(g[0]), int(g[1]), int(g[2]))
                elif kind == "cjk_ym":
                    span = _span(int(g[0]), int(g[1]))
                elif kind == "dmy_dots":
                    span = _span(int(g[2]), int(g[1]), int(g[0]))
                elif kind == "mdy":
                    span = _span(int(g[2]), _month(g[0]), int(g[1]))
                elif kind == "dmy":
                    span = _span(int(g[2]), _month(g[1]), int(g[0]))
                elif kind == "my":
                    span = _span(int(g[1]), _month(g[0]))
                else:
                    span = _span(int(g[0]))
            except (KeyError, ValueError):
                span = None
            if span:
                found.append((a, b, span))
                taken.append((a, b))
    return sorted(found)


def candidate(query: str) -> Period | None:
    """The first dated period the question names, or None (no year in digits)."""
    if not ANY_YEAR.search(query or ""):
        return None
    found = dates(query)
    return found[0][2] if found else None


def parse_iso(value) -> Period | None:
    """'YYYY', 'YYYY-MM' or 'YYYY-MM-DD' (the router's format) -> period."""
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"\s*(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?\s*", value)
    if not match:
        return None
    year, month, day = match.groups()
    return _span(int(year), int(month) if month else None, int(day) if day else None)


def ranges(text: str) -> list[Period]:
    """Explicit date ranges: 'from X to Y', 'between X and Y', 'X - Y', '从X到Y', 'X至Y'."""
    found = dates(text)
    out = []
    for (a1, b1, s1), (a2, _, s2) in zip(found, found[1:]):
        joiner = text[b1:a2]
        if RANGE_JOIN.match(joiner):
            if joiner.strip().lower() in ("and", "a", "al") and not RANGE_OPEN.search(text[max(0, a1 - 12):a1]):
                continue  # "X and Y" is a range only after "between"
            out.append((s1[0], s2[1]))
    return out


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


def combine(parsed: Period, routed: Period | None) -> Period:
    """The period to apply. The router normalises any language, but tends to
    write a month as its first day ("August 2025" -> "2025-08-01"), so it may
    not narrow a period the parser read at month or day precision. It decides
    when the parser found only a year, or when the two disagree."""
    if routed is None:
        return parsed
    year_only = parsed == _span(parsed[0].year)
    inside = parsed[0] <= routed[0] and routed[1] <= parsed[1]
    return parsed if inside and not year_only else routed


def overlaps(a: Period, b: Period) -> bool:
    return a[0] <= b[1] and a[1] >= b[0]


def withhold(period: Period, pool: list[store.Item], returned: list[store.Item],
             state: bool) -> set[str]:
    """Ids among *pool* not valid at *period*. The conditions ("some returned
    item states an overlapping range", "some returned item was said by the
    end of the period") are read from *returned*, the set as it would be
    returned without this rule. Rule (b) only when *state*."""
    parsed = {}

    def info(item):
        if item.id not in parsed:
            when, body = said(item.content)
            parsed[item.id] = (when, body, ranges(body))
        return parsed[item.id]

    any_valid_range = any(any(overlaps(r, period) for r in info(item)[2]) for item in returned)
    any_early = any(info(item)[0] is not None and info(item)[0] <= period[1] for item in returned)
    grace = dt.timedelta(days=max(0, config.ASOF_GRACE_DAYS))
    out = set()
    for item in pool:
        when, body, spans = info(item)
        if any_valid_range and spans and not any(overlaps(r, period) for r in spans):
            out.add(item.id)
            continue
        if (state and any_early and when is not None and when > period[1] and not ANY_YEAR.search(body)
                and not (RELATIVE.search(body) and when <= period[1] + grace)):
            out.add(item.id)
    return out


_DELIVERED = re.compile(r"(.+)-(?:c0|s(\d+)-(\d+))$")


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


# --- router ---------------------------------------------------------------------
stats = collections.Counter()
_cache: "collections.OrderedDict[tuple, dict | None]" = collections.OrderedDict()
_cache_lock = threading.Lock()
CACHE_MAX = 10_000


def classify(query: str, options: list[str] | None) -> dict | None:
    """{"kind": "as_of_state" | "event" | "other", "as_of": period | None}, or
    None when the call failed (the caller then withholds nothing)."""
    key = (query, tuple(str(o) for o in options or ()))
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    stats["router_calls"] += 1
    verdict = parse_verdict(llm.classify_asof(query, options))
    if verdict is None:
        stats["router_failures"] += 1
        return None
    with _cache_lock:
        _cache[key] = verdict
        while len(_cache) > CACHE_MAX:
            _cache.popitem(last=False)
    return verdict


def select_withheld(index: store.UserIndex, scores, query: str, options: list[str] | None,
                    returned: list[store.Item]) -> set[str]:
    """Item ids to leave out of this Search for its as-of date. Empty unless the
    question names a dated period, the rules would change *returned*, and the
    router says the question is about that time."""
    period = candidate(query)
    if period is None:
        return set()
    stats["dated_questions"] += 1
    import numpy as np  # local: keeps this module importable without numpy for tools

    order = np.argsort(-scores)[: max(config.ASOF_POOL, 1)]
    rows = {int(row) for row in order if np.isfinite(scores[int(row)])}
    # The returned set also carries window neighbours that may rank far lower.
    for item in returned:
        row = index.by_id.get(item.id)
        if row is not None:
            rows.add(row)
    pool = [index.items[row] for row in sorted(rows)]
    returned_ids = {item.id for item in returned}
    trial = withhold(period, pool, returned, state=True)
    if not trial & returned_ids:
        return set()
    stats["would_change"] += 1
    try:
        verdict = classify(query, options)
    except Exception:  # noqa: BLE001 - a failed router withholds nothing
        log.exception("as-of classification failed")
        verdict = None
    if verdict is None or verdict["kind"] == "other":
        return set()
    period = combine(period, verdict.get("as_of"))
    out = withhold(period, pool, returned, state=verdict["kind"] == "as_of_state")
    stats["applied"] += bool(out & returned_ids)
    stats["withheld"] += len(out & returned_ids)
    return out


def parse_verdict(payload: dict | None) -> dict | None:
    if not isinstance(payload, dict):
        return None
    kind = payload.get("kind")
    if kind not in ("as_of_state", "event", "other"):
        return None
    return {"kind": kind, "as_of": parse_iso(payload.get("as_of"))}


def dumps(verdict: dict | None) -> str:
    """For logs: periods as ISO strings."""
    if verdict is None:
        return "null"
    period = verdict.get("as_of")
    return json.dumps({"kind": verdict["kind"],
                       "as_of": [period[0].isoformat(), period[1].isoformat()] if period else None})
