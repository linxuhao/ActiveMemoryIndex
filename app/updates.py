"""Explicit updates: detected at Add, used at Search to withhold replaced values.

The reader answers the old value whenever the old value's sentence is in the
returned set, however the newer one is marked or ordered
(bench/results/supersede_drop_oracle.md, lme_fact_keys.md). So the lever is
membership: for a statement in which the user EXPLICITLY replaces a value, the
earlier items that assert the replaced value are left out of the returned set.

Precision first. An item is withheld only when every one of these holds:
  * it belongs to the same user (the index is per user) and was said before
    the update (timestamp when both have one, else Add order; inside the
    update's own chunk, an earlier turn or one of the chunk's facts);
  * it mentions the subject (any item, for the user's own attributes) and,
    when the update states the old value, contains that value;
  * it does not contain the new value;
  * gpt-4o-mini, shown the update and the candidate, says it asserts the
    replaced value of the same attribute of the same subject, and quotes that
    value, and the quote is found verbatim in the item.
Relative updates ("one more") are never used: the old value is the arithmetic's
input. History- and date-scoped questions withhold nothing.

Nothing here reads the question beyond the protection check, nothing is
rewritten, and no answer is produced: the returned set only loses items.
"""
from __future__ import annotations

import concurrent.futures
import functools
import logging
import re
import threading

import numpy as np

from . import config, llm, store

log = logging.getLogger("ami.updates")

STAMP = re.compile(r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}\] ")
# Other speakers' turns are context only; LongMemEval assistant turns average
# 1,700 characters and would otherwise dominate the call's cost.
OTHER_TURN_CHARS = 200
SELF = {"me", "i", "my", "myself", "mine", "user", "the user"}
# Relative change: the new value is defined by the old one. Words are checked
# on the whole update turn, the sign only on the value (a timestamp has dashes).
RELATIVE_WORDS = re.compile(
    r"\b(?:another|more|fewer|less|add|added|adding|plus|extra|additional|increased?|"
    r"decreased?|up by|down by|subtract(?:ed)?|minus)\b", re.I)
RELATIVE_SIGN = re.compile(r"^\s*[+-]\s*\d")
# Questions that need the replaced value: history, change, comparison. Broad on
# purpose — a false match only means nothing is withheld for that question.
# "updated"/"replaced"/"corrected" are left out: "what is the updated X" asks
# for the current value.
HISTORY_QUESTION = re.compile(
    r"\b(?:previous(?:ly)?|before|used to|original(?:ly)?|initial(?:ly)?|at first|formerly|"
    r"former|prior|earlier|old|older|change[ds]?|changing|switch(?:ed|ing)?|differ(?:ent|ence)?|"
    r"history|historical(?:ly)?|"
    r"anymore|no longer|over time|ago|since|increase[ds]?|decrease[ds]?|grew|went up|went down|"
    r"how many times|then|ever|past|last time|first time)\b", re.I)
# Explicit dates or as-of scopes. Selecting by date is Mechanism 2, which is not
# built; until it is, a dated question withholds nothing.
DATED_QUESTION = re.compile(
    r"\d{4}[-/]\d{1,2}[-/]\d{1,2}|\bas of\b|"
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?,?\s+"
    r"(?:\d{1,2}(?:st|nd|rd|th)?,?\s+)?\d{4}\b|\b(?:1[0-9]|20)\d{2}s?\b", re.I)

_executor = concurrent.futures.ThreadPoolExecutor(max_workers=max(1, config.LLM_CONCURRENCY),
                                                  thread_name_prefix="updates")
_user_locks: dict[str, threading.Lock] = {}
_user_locks_guard = threading.Lock()
# user -> ((items, records), {update id: withheld item ids}); only complete
# resolutions are cached, so a failed verification is retried next search.
_resolved: dict[str, tuple[tuple[int, int], dict[str, set[str]]]] = {}


def _norm(text: str) -> str:
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return " ".join(text.lower().split())


@functools.lru_cache(maxsize=4096)
def _phrase(phrase: str) -> re.Pattern | None:
    cleaned = _norm(phrase).strip(" .,;:!?\"'()[]{}")
    if not cleaned:
        return None
    return re.compile(rf"(?<![a-z0-9]){re.escape(cleaned)}(?![a-z0-9])")


def mentions(text: str, phrase: str | None) -> bool:
    """Case- and space-insensitive containment on word boundaries."""
    if not phrase:
        return False
    pattern = _phrase(phrase)
    return bool(pattern and pattern.search(_norm(text)))


def is_user_turn(item: store.Item) -> bool:
    return item.kind == "raw" and STAMP.sub("", item.content, count=1).startswith("I: ")


def protected_question(query: str) -> bool:
    return bool(HISTORY_QUESTION.search(query) or DATED_QUESTION.search(query))


# --- Add ----------------------------------------------------------------------
# --- render language check (round 3) -------------------------------------------
_SCRIPTS = (("cjk", re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")),
            ("cyrillic", re.compile(r"[\u0400-\u04ff]")), ("arabic", re.compile(r"[\u0600-\u06ff]")),
            ("latin", re.compile(r"[A-Za-z\u00c0-\u024f]")))
_STOPWORDS = {
    "en": {"the", "is", "are", "of", "and", "to", "in", "my", "i", "was", "it", "with", "for", "this", "that", "has", "have", "now"},
    "es": {"el", "la", "los", "las", "es", "de", "y", "mi", "en", "un", "una", "que", "se", "con", "por", "del", "al"},
    "fr": {"le", "la", "les", "est", "de", "et", "mon", "ma", "un", "une", "des", "du", "en", "sont", "que", "dans"},
    "de": {"der", "die", "das", "ist", "und", "mein", "meine", "ein", "eine", "ich", "nicht", "zu", "mit", "von", "im"},
    "pt": {"o", "a", "os", "as", "é", "de", "e", "meu", "minha", "um", "uma", "do", "da", "em", "que", "não"},
    "it": {"il", "lo", "la", "è", "di", "e", "mio", "mia", "un", "una", "del", "della", "che", "non", "sono"},
}


def _script(text: str) -> str | None:
    counts = {name: len(pattern.findall(text)) for name, pattern in _SCRIPTS}
    best = max(counts, key=counts.get)
    return best if counts[best] else None


def _latin_language(text: str) -> str | None:
    words = re.findall(r"[a-zà-ÿ']+", text.lower())
    hits = {lang: sum(w in stop for w in words) for lang, stop in _STOPWORDS.items()}
    best = max(hits, key=hits.get)
    ranked = sorted(hits.values(), reverse=True)
    return best if ranked[0] >= 2 and ranked[0] > ranked[1] else None


def same_language(sentence: str, source: str) -> bool:
    """False only when the two texts clearly differ: another script, or both
    Latin with a clear and different stopword language. A cheap heuristic for
    RENDER, which must not store a sentence translated away from the user's."""
    a, b = _script(sentence), _script(STAMP.sub("", source, count=1))
    if a and b and a != b:
        return False
    if a == b == "latin":
        la, lb = _latin_language(sentence), _latin_language(STAMP.sub("", source, count=1))
        if la and lb and la != lb:
            return False
    return True


def renderable(record: dict, update_turn: str) -> bool:
    """RENDER stores the current-value sentence only for an absolute record
    whose sentence is in the language of the user's turn."""
    if record["relative"] or not record.get("statement"):
        return False
    if config.UPDATE_VERSION >= 3 and not same_language(record["statement"], update_turn):
        stats["render_language_fallback"] += 1
        return False
    return True


def detector_input(raw_items: list[store.Item]) -> str | None:
    """The chunk as the detector sees it, numbered by turn. None without a user
    turn: only the user's own statements can be updates."""
    lines, has_user = [], False
    for number, item in enumerate(raw_items):
        text = item.content
        if is_user_turn(item):
            has_user = True
        elif len(text) > OTHER_TURN_CHARS:
            text = text[:OTHER_TURN_CHARS] + " ..."
        lines.append(f"{number} | {text}")
    return "\n".join(lines) if has_user else None


def _text(value, limit: int = 200) -> str | None:
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())
    return value if value and len(value) <= limit else None


def parse_updates(entries: list[dict], raw_items: list[store.Item]) -> list[dict]:
    """Validated records. An entry is dropped unless it points at a user turn
    that contains its new value verbatim; an old value the turn does not
    contain is discarded as a guess. An entry carrying "quote" (round 2) has
    the relative check applied to that quote instead of the whole turn."""
    records = []
    for number, entry in enumerate(entries):
        try:
            turn = int(entry.get("turn"))
        except (TypeError, ValueError):
            continue
        if not 0 <= turn < len(raw_items) or not is_user_turn(raw_items[turn]):
            continue
        item = raw_items[turn]
        subject, attribute, new = (_text(entry.get(k)) for k in ("subject", "attribute", "new_value"))
        if not (subject and attribute and new) or not mentions(item.content, new):
            continue
        old = _text(entry.get("old_value"))
        if old and (not mentions(item.content, old) or _norm(old) == _norm(new)):
            old = None
        flag = entry.get("relative")
        span = entry.get("quote") or STAMP.sub("", item.content, count=1)
        relative = (flag is True or (isinstance(flag, str) and flag.strip().lower() == "true")
                    or bool(RELATIVE_SIGN.match(new)) or bool(RELATIVE_WORDS.search(new))
                    or bool(RELATIVE_WORDS.search(span)))
        records.append({
            "id": f"{item.id}-u{number}", "item_id": item.id, "subject": subject,
            "attribute": attribute, "new_value": new, "old_value": old, "relative": relative,
            "statement": _text(entry.get("statement"), 400), "created_at": item.created_at,
        })
    return records


ACCEPTED_INTENTS = {"EXPLICIT_REPLACEMENT", "CORRECTION"}
# Round-2 call accounting, read by the bench (and /health is untouched).
stats = {"chunks": 0, "stage1": 0, "accepted": 0, "stage2": 0, "records": 0, "render_language_fallback": 0}


def _ws(text: str) -> str:
    return " ".join(text.split())


def accept_statements(statements: list[dict], raw_items: list[store.Item]) -> list[tuple[int, str]]:
    """Stage-1 statements kept: label EXPLICIT_REPLACEMENT or CORRECTION and a
    quote that is a substring of one of the chunk's USER turns after
    whitespace normalisation (nothing else is normalised). The turn is the
    one the model named when the quote is in it, else the first user turn
    that contains the quote; the model's turn numbers are not reliable."""
    kept: list[tuple[int, str]] = []
    for entry in statements:
        if str(entry.get("label", "")).strip().upper() not in ACCEPTED_INTENTS:
            continue
        quote = entry.get("quote")
        if not isinstance(quote, str) or not _ws(quote):
            continue
        quote = _ws(quote)
        found = [n for n, item in enumerate(raw_items) if is_user_turn(item) and quote in _ws(item.content)]
        if not found:
            continue
        try:
            named = int(entry.get("turn"))
        except (TypeError, ValueError):
            named = -1
        turn = named if named in found else found[0]
        if (turn, quote) not in kept:
            kept.append((turn, quote))
    return kept


def detect_or_none(raw_items: list[store.Item]) -> list[dict] | None:
    """Records for one chunk; None when a model call failed."""
    numbered = detector_input(raw_items)
    if numbered is None:
        return []
    stats["chunks"] += 1
    if config.UPDATE_VERSION == 1:
        entries = llm.detect_updates(numbered)
        return None if entries is None else parse_updates(entries, raw_items)
    stats["stage1"] += 1
    statements = llm.classify_update_intent(numbered)
    if statements is None:
        return None
    accepted = accept_statements(statements, raw_items)
    if not accepted:
        return []
    stats["accepted"] += 1
    stats["stage2"] += 1
    extracted = llm.extract_updates(numbered, accepted)
    if extracted is None:
        return None
    entries = []
    for entry in extracted:
        try:
            turn, quote = accepted[int(str(entry.get("statement", "")).lstrip("Ss"))]
        except (TypeError, ValueError, IndexError):
            continue
        entries.append({**entry, "turn": turn, "quote": quote, "statement": entry.get("current")})
    records = parse_updates(entries, raw_items)
    stats["records"] += len(records)
    return records


def detect(raw_items: list[store.Item]) -> list[dict]:
    """Detection over a chunk's verbatim turns. Failure: no records."""
    try:
        return detect_or_none(raw_items) or []
    except Exception:  # noqa: BLE001 - detection must never fail Add
        log.exception("update detection failed")
        return []


def start_detection(raw_items: list[store.Item]) -> concurrent.futures.Future:
    """Run detect() beside the extraction call so Add waits for the slower one."""
    return _executor.submit(detect, list(raw_items))


# --- Search -------------------------------------------------------------------
def _chunk(item_id: str) -> tuple[str, str]:
    digest, _, tail = item_id.rpartition("-")
    return digest, tail


def earlier(index: store.UserIndex, update_row: int, row: int) -> bool:
    update, item = index.items[update_row], index.items[row]
    update_digest, update_tail = _chunk(update.id)
    digest, tail = _chunk(item.id)
    if digest == update_digest:
        if config.UPDATE_VERSION >= 4:
            # Round 4: "earlier" means an earlier Add. Nothing from the
            # update's own Add request is withheld, raw turn or fact; in
            # round 3 these were mostly facts describing the change itself.
            return False
        if item.kind == "raw":
            return int(tail[1:]) < int(update_tail[1:])
        # The chunk's facts were extracted from all its turns, earlier and later.
        return item.kind == "fact"
    if update.created_at and item.created_at:
        return item.created_at < update.created_at
    return row < update_row


def candidates(index: store.UserIndex, record: dict) -> list[int]:
    """Rows that may state the replaced value, nearest to the update first."""
    update_row = index.by_id.get(record["item_id"])
    if update_row is None or index.matrix is None:
        return []
    own = _norm(record["subject"]) in SELF
    rows = []
    for row, item in enumerate(index.items):
        if row == update_row or item.kind not in ("raw", "fact"):
            continue
        if not earlier(index, update_row, row):
            continue
        if mentions(item.content, record["new_value"]):
            continue
        if record["old_value"] and not mentions(item.content, record["old_value"]):
            continue
        if not own and not mentions(item.content, record["subject"]):
            continue
        if own and item.kind == "raw" and config.UPDATE_VERSION >= 2 and not is_user_turn(item):
            continue  # the user's own attribute: only the user's own turns
        rows.append(row)
    if not rows:
        return []
    similarity = index.matrix[rows] @ index.matrix[update_row]
    return [rows[i] for i in np.argsort(-similarity, kind="stable")[: config.UPDATE_CANDIDATES]]


def describe(record: dict, update: store.Item) -> str:
    words = update.content if len(update.content) <= 600 else update.content[:600] + " ..."
    return (f"Update, in its own words: {words}\nSubject: {record['subject']}\n"
            f"Attribute: {record['attribute']}\nNew value: {record['new_value']}\n"
            f"Old value: {record['old_value'] or 'not stated'}")


def accept(record: dict, item: store.Item, quote: str) -> bool:
    if not mentions(item.content, quote) or mentions(quote, record["new_value"]):
        return False
    old = record["old_value"]
    return not old or mentions(quote, old) or mentions(old, quote)


def resolve(index: store.UserIndex, user_id: str, records: list[dict]) -> tuple[dict[str, set[str]], bool]:
    """{update id: ids of the earlier items it replaced}, and whether every
    verification needed succeeded. Verdicts are persisted, so each (update,
    item) pair is put to the model once."""
    checks = store.get_checks(user_id)
    complete = True
    for record in records:
        update_row = index.by_id.get(record["item_id"])
        if update_row is None:
            continue
        pending = [row for row in candidates(index, record)
                   if (record["id"], index.items[row].id) not in checks]
        if not pending:
            continue
        verify = llm.verify_replaced if config.UPDATE_VERSION == 1 else llm.verify_replaced_v2
        verdicts = verify(describe(record, index.items[update_row]),
                          [index.items[row].content[:1200] for row in pending])
        if verdicts is None:
            complete = False
            continue
        chosen: dict[int, str] = {}
        for number, quote in verdicts:
            if accept(record, index.items[pending[number]], quote):
                chosen[number] = quote
        new = [(record["id"], index.items[row].id, number in chosen, chosen.get(number))
               for number, row in enumerate(pending)]
        store.add_checks(user_id, new)
        checks.update({(u, i): (r, q) for u, i, r, q in new})
    if config.UPDATE_VERSION >= 3:
        complete &= _chunk_facts(index, user_id, records, checks)
    out: dict[str, set[str]] = {record["id"]: set() for record in records}
    update_chunk = {record["id"]: record["item_id"].rsplit("-", 1)[0] for record in records}
    for (update_id, item_id), (replaced, _) in checks.items():
        base = update_id.split("#", 1)[0]
        if not replaced or base not in out:
            continue
        if config.UPDATE_VERSION >= 4 and item_id.rsplit("-", 1)[0] == update_chunk[base]:
            continue  # a verdict stored under an earlier version never reaches the update's own Add
        out[base].add(item_id)
    return out, complete


def _chunk_facts(index: store.UserIndex, user_id: str, records: list[dict],
                 checks: dict) -> bool:
    """Round 3: when an earlier verbatim turn is confirmed REPLACED, the facts
    extracted from that same Add chunk become candidates too — those that
    contain the replaced value (the confirmed quote, or the stated old value)
    and not the new one — and go to the verifier again, told which turn they
    came from. Checks are kept under "<update id>#chunk"."""
    complete = True
    for record in records:
        update_row = index.by_id.get(record["item_id"])
        if update_row is None:
            continue
        own = _norm(record["subject"]) in SELF
        confirmed = [(item_id, quote) for (update_id, item_id), (replaced, quote) in list(checks.items())
                     if update_id == record["id"] and replaced and item_id.rsplit("-", 1)[1].startswith("r")]
        for raw_id, quote in confirmed:
            digest = raw_id.rsplit("-", 1)[0]
            old = record["old_value"] or quote
            rows = [row for row, item in enumerate(index.items)
                    if item.kind == "fact" and item.id.rsplit("-", 1)[0] == digest
                    and not checks.get((record["id"], item.id), (False,))[0]
                    and (f"{record['id']}#chunk", index.items[row].id) not in checks
                    and earlier(index, update_row, row)
                    and (own or mentions(index.items[row].content, record["subject"]))
                    and mentions(index.items[row].content, old)
                    and not mentions(index.items[row].content, record["new_value"])]
            if not rows:
                continue
            context = (f"{describe(record, index.items[update_row])}\n"
                       f"Context: each memory below was extracted from the same earlier message as this one, "
                       f"which was confirmed to state the replaced value: {index.items[index.by_id[raw_id]].content[:600]}")
            verdicts = llm.verify_replaced_v2(context, [index.items[row].content[:1200] for row in rows])
            if verdicts is None:
                complete = False
                continue
            chosen = {n: q for n, q in verdicts if accept(record, index.items[rows[n]], q)}
            new = [(f"{record['id']}#chunk", index.items[row].id, n in chosen, chosen.get(n))
                   for n, row in enumerate(rows)]
            store.add_checks(user_id, new)
            checks.update({(u, i): (r, q) for u, i, r, q in new})
    return complete


def _lock(user_id: str) -> threading.Lock:
    with _user_locks_guard:
        return _user_locks.setdefault(user_id, threading.Lock())


def withheld(index: store.UserIndex, user_id: str, query: str) -> set[str]:
    """Item ids to leave out of this search's returned set."""
    if protected_question(query):
        return set()
    records = [r for r in store.get_updates(user_id) if not r["relative"]]
    if not records:
        return set()
    with _lock(user_id):
        key = (len(index.items), len(records))
        cached = _resolved.get(user_id)
        if cached and cached[0] == key:
            per_update = cached[1]
        else:
            per_update, complete = resolve(index, user_id, records)
            if complete:
                _resolved[user_id] = (key, per_update)
    return set().union(*per_update.values()) if per_update else set()
