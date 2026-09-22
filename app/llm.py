"""The single LLM used by both Add and Search.

Competition rule: for a leaderboard run this model must be ``gpt-4o-mini``.
Every call degrades to ``None`` on failure — the service must keep serving the
raw-text channel even when the LLM is unavailable.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
import threading

from . import config

log = logging.getLogger("ami.llm")

_client = None
_lock = threading.Lock()
# The platform drives Add with up to 64 workers; cap our own fan-out at the
# provider so a burst degrades into queueing rather than into 429s.
_gate = threading.Semaphore(config.LLM_CONCURRENCY)
counters = {"calls": 0, "failures": 0, "empty_extractions": 0}

EXTRACT_SYSTEM = """You turn a chunk of a conversation into atomic memories for a personal memory index.

Rules:
1. One fact per line. Each memory must stand alone: no pronouns without a named referent, no "the above", no cross-references.
2. Keep every specific name, place, title, number, quantity and date exactly as written. Never generalise ("Rob", not "a colleague").
3. Write the memory owner's own statements in the first person ("I ..."). Attribute the other party's statements to their name when known, otherwise to "the other person".
4. Record what was said or done, including preferences, plans, opinions, feelings and events. Do not infer anything that is not supported by the text.
5. If the message carries a date, start the memory with that date in brackets, e.g. "[2023-05-20] I adopted a beagle named Ollie."
6. Do not answer questions, summarise, or editorialise. No commentary.

Return JSON only: {"facts": ["...", "..."]}. At most %d facts. Return {"facts": []} if there is nothing worth remembering."""

EXTRACT_KEYED_SYSTEM = EXTRACT_SYSTEM.replace(
    "6. Do not answer questions, summarise, or editorialise. No commentary.",
    """6. Do not answer questions, summarise, or editorialise. No commentary.
7. Give a memory a "key" only when it states the CURRENT VALUE of a property that can change later: a count, a time, a place, a status, a level, a price, a name of something owned. The key is "<subject>.<attribute>" in lower snake_case: the subject is "me" for the memory owner or the named person or thing; the attribute is a short stable noun for the property, e.g. "me.team_size", "me.gym_time", "me.instagram_followers", "rachel.location", "me.5k_personal_best". The same property must get exactly the same key every time it comes up. Events, requests, questions, opinions, feelings and plans get null.""",
).replace(
    'Return JSON only: {"facts": ["...", "..."]}. At most %d facts. Return {"facts": []} if there is nothing worth remembering.',
    'Return JSON only: {"facts": [{"text": "...", "key": "me.team_size"}, {"text": "...", "key": null}]}. At most %d facts. Return {"facts": []} if there is nothing worth remembering.',
)
assert EXTRACT_KEYED_SYSTEM != EXTRACT_SYSTEM

RECALL_SYSTEM = """You write the memory-check question a person would ask their assistant about their own past conversations.

Given a question that will be answered from someone's personal memory log, write ONE short question in that person's own first-person voice, in the register of a chat log, e.g. "Did I tell you about ...?" or "What did I say about ...?".

Rules:
1. First person, the user's own voice. Never address the user as "you".
2. Name the concrete entities, people, places and time expressions that the memory would contain.
3. Ask about the memory, do not answer the question and do not guess the answer.
4. If answer options are given, treat them only as a source of topic words; never assume any option is true.
5. One line, no preamble, no quotes."""


_REASONING = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


def _strip_reasoning(text: str) -> str:
    """Drop a reasoning block. gpt-4o-mini emits none; local dev models do."""
    text = _REASONING.sub("", text)
    return "" if "<think>" in text else text.strip()


def _get_client():
    global _client
    if _client is None:
        with _lock:
            if _client is None:
                from openai import OpenAI

                _client = OpenAI(
                    api_key=config.LLM_API_KEY,
                    base_url=config.LLM_BASE_URL,
                    timeout=config.LLM_TIMEOUT,
                    max_retries=config.LLM_RETRIES,
                )
    return _client


def _complete(system: str, user: str, max_tokens: int) -> str | None:
    if not config.llm_available():
        return None
    # Gateway secret code: <<DISABLE_THINKING>> in the system message tells the
    # serving layer's thinking.jinja to pre-fill a closed <think> tag, forcing the
    # model to skip reasoning and answer directly. Has no effect on OpenAI API.
    if config.DISABLE_THINKING and "<<DISABLE_THINKING>>" not in system:
        system = "<<DISABLE_THINKING>>\n" + system
    counters["calls"] += 1
    try:
        with _gate:
            response = _get_client().chat.completions.create(
                model=config.LLM_MODEL,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=0,
                max_tokens=max_tokens,
            )
        return _strip_reasoning(response.choices[0].message.content or "")
    except Exception as exc:  # network, quota, provider error — degrade, never fail Add
        counters["failures"] += 1
        log.warning("llm call failed: %s", exc)
        return None


def _parse_facts(text: str) -> list[str]:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            payload = json.loads(match.group(0))
            facts = payload.get("facts", [])
            if isinstance(facts, list):
                return [str(f).strip() for f in facts if str(f).strip()]
        except json.JSONDecodeError:
            pass
    # Fallback for a bare list. Deliberately narrow: only bulleted, numbered or
    # timestamped lines qualify. Prose is a sign the model answered something
    # else entirely, and storing that prose as memories poisons retrieval
    # silently — an empty return is the safe reading.
    facts = []
    for line in text.splitlines():
        stripped = line.strip()
        if not re.match(r"^(?:[-*]|\d+[.)]|\[)", stripped):
            continue
        cleaned = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", stripped).strip(' "')
        if len(cleaned) > 3:
            facts.append(cleaned)
    return facts[: config.LLM_MAX_FACTS]


_KEY_JUNK = re.compile(r"[^a-z0-9._]+")
_KEYED_OBJECT = re.compile(
    r'\{\s*"text"\s*:\s*"(?:[^"\\]|\\.)*"\s*(?:,\s*"key"\s*:\s*(?:null|"(?:[^"\\]|\\.)*"))?\s*\}')


def normalise_key(key) -> str | None:
    """Lower snake_case '<subject>.<attribute>' or None. Anything that is not a
    string with letters in it, or that spells null, is no key."""
    if not isinstance(key, str):
        return None
    cleaned = _KEY_JUNK.sub("_", key.strip().lower()).strip("_.")
    if not cleaned or cleaned in ("null", "none", "n_a", "na") or not re.search(r"[a-z]", cleaned):
        return None
    return cleaned


def _parse_keyed(text: str) -> list[tuple[str, str | None]]:
    """The keyed format: {"facts": [{"text": ..., "key": ...}, ...]}. Entries that
    are plain strings, or replies in the old format, come back with no key."""
    text = _strip_reasoning(text)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            payload = json.loads(match.group(0))
            facts = payload.get("facts", [])
            if isinstance(facts, list):
                out = []
                for entry in facts:
                    if isinstance(entry, dict):
                        body = str(entry.get("text") or entry.get("fact") or "").strip()
                        if body:
                            out.append((body, normalise_key(entry.get("key"))))
                    elif str(entry).strip():
                        out.append((str(entry).strip(), None))
                return out
        except json.JSONDecodeError:
            pass
    # Salvage: gpt-4o-mini sometimes closes the list with a stray brace
    # ("}}]}") or mixes malformed objects into an otherwise good reply. Each
    # well-formed {"text": ..., "key": ...} object is taken on its own.
    salvaged = []
    for piece in _KEYED_OBJECT.finditer(text):
        try:
            entry = json.loads(piece.group(0))
        except json.JSONDecodeError:
            continue
        body = str(entry.get("text") or "").strip()
        if body:
            salvaged.append((body, normalise_key(entry.get("key"))))
    if salvaged:
        return salvaged
    return [(fact, None) for fact in _parse_facts(text)]


def extract_keyed(chunk_text: str) -> list[tuple[str, str | None]]:
    """Add path with AMI_FACT_KEYS: (memory, canonical key or None)."""
    if not config.EXTRACT_ENABLED:
        return []
    raw = _complete(EXTRACT_KEYED_SYSTEM % config.LLM_MAX_FACTS, chunk_text, config.LLM_MAX_TOKENS_EXTRACT)
    if raw is None:
        return []
    facts = _parse_keyed(raw)[: config.LLM_MAX_FACTS]
    if raw and not facts:
        counters["empty_extractions"] += 1
        log.warning("keyed extraction returned no usable facts from a %d-char reply", len(raw))
    return facts


def extract_facts(chunk_text: str) -> list[str]:
    """Add path: atomic, self-contained, timestamped memories."""
    if not config.EXTRACT_ENABLED:
        return []
    raw = _complete(EXTRACT_SYSTEM % config.LLM_MAX_FACTS, chunk_text, config.LLM_MAX_TOKENS_EXTRACT)
    if raw is None:
        return []
    facts = _parse_facts(raw)[: config.LLM_MAX_FACTS]
    if raw and not facts:
        # The call succeeded but nothing parsed — usually a reply truncated by
        # the token cap. Without this the whole fact channel for the chunk
        # vanishes with no counter, no log line, and a 200 response.
        counters["empty_extractions"] += 1
        log.warning("extraction returned no usable facts from a %d-char reply", len(raw))
    return facts


EXTRACT_DATED_SYSTEM = EXTRACT_SYSTEM.replace(
    'Return JSON only: {"facts": ["...", "..."]}. At most %d facts. Return {"facts": []} if there is nothing worth remembering.',
    """The turns are numbered `N | [date and time it was said] role: text`.

7. For each fact, and for each turn, also say WHEN the event it describes actually happened. The date it was said is not the date it happened: "I went to the museum yesterday" said on 2023-05-09 happened on 2023-05-08; "I met Rachel on April 10th" said on 2023-05-09 happened on 2023-04-10. Something ongoing, a plan, a preference or no event at all has no event date. Use null whenever the text and the said-date together do not fix a specific day. Do not guess.

Return JSON only: {"facts": [{"text": "...", "happened": "YYYY-MM-DD" or null}, ...], "turns": {"N": "YYYY-MM-DD" or null, ...}} with one "turns" key per turn number given. At most %d facts. Return {"facts": [], "turns": {}} if there is nothing worth remembering.""")

_ISO_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


def _iso_or_none(value) -> str | None:
    """A real calendar day as YYYY-MM-DD, or None. 2023-13-45 is not a date."""
    if not isinstance(value, str) or not _ISO_DAY.fullmatch(value.strip()):
        return None
    try:
        dt.date.fromisoformat(value.strip())
    except ValueError:
        return None
    return value.strip()


def _parse_dated(text: str) -> tuple[list[tuple[str, str | None]], dict[int, str]]:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return [], {}
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return [], {}
    facts: list[tuple[str, str | None]] = []
    for entry in payload.get("facts", []) if isinstance(payload.get("facts"), list) else []:
        if isinstance(entry, dict):
            body = str(entry.get("text", "")).strip()
            if body:
                facts.append((body, _iso_or_none(entry.get("happened"))))
        elif isinstance(entry, str) and entry.strip():
            facts.append((entry.strip(), None))
    turns: dict[int, str] = {}
    for key, value in (payload.get("turns") or {}).items() if isinstance(payload.get("turns"), dict) else []:
        iso = _iso_or_none(value)
        try:
            position = int(key)
        except (TypeError, ValueError):
            continue
        if iso and position >= 0:
            turns[position] = iso
    return facts[: config.LLM_MAX_FACTS], turns


def extract_dated(lines: list[str]) -> tuple[list[tuple[str, str | None]], dict[int, str]]:
    """Add path with event dates: facts as (text, happened) and {turn: happened}.

    One call, the same one extract_facts() makes; the reading that
    event_dates() does at search time is done here once per chunk instead of
    once per search that returns the memory. Failure degrades to no facts and
    no dates, exactly as extract_facts() does.
    """
    if not config.EXTRACT_ENABLED:
        return [], {}
    numbered = "\n".join(f"{n} | {line}" for n, line in enumerate(lines))
    raw = _complete(EXTRACT_DATED_SYSTEM % config.LLM_MAX_FACTS, numbered, config.LLM_MAX_TOKENS_EXTRACT_DATED)
    if raw is None:
        return [], {}
    facts, turns = _parse_dated(raw)
    if raw and not facts:
        counters["empty_extractions"] += 1
        log.warning("dated extraction returned no usable facts from a %d-char reply", len(raw))
    return facts, turns


def recall_question(query: str, options: list[str] | None) -> str | None:
    """Search path: the same question in the log's own first-person register."""
    if not config.RECALL_QUERY_ENABLED:
        return None
    user = f"Question: {query}"
    if options:
        user += "\nAnswer options: " + " | ".join(str(o) for o in options[:10])
    raw = _complete(RECALL_SYSTEM, user, config.LLM_MAX_TOKENS_QUERY)
    if not raw:
        return None
    return raw.splitlines()[0].strip(' "')


REFLECT_SYSTEM = """You check whether retrieved memories contain enough evidence to answer a question.

Given the question and what was found, decide if anything important is still missing. You are looking
for gaps — not evaluating whether the answer is correct.

What to look for:
1. Missing time references (dates, sequences, "when" information)
2. Missing named entities (people, places, items mentioned in the question or options)
3. Missing personal details (preferences, plans, opinions that would answer the question)

If the evidence looks complete enough to answer, return {"status": "COMPLETE"}.
If evidence is clearly missing, return {"status": "INCOMPLETE", "question": "..."} where the question
is ONE targeted recall question in the user's own first-person voice that would find the missing piece.

Return JSON only."""


EVENT_DATE_SYSTEM = """You read memories from a personal memory index and say WHEN the event each one describes actually happened.

Each memory is given as `N | <the date and time it was said> | <text>`.

The date it was said is not the date it happened. "I went to the museum yesterday"
said on 2023-05-09 happened on 2023-05-08. "I met Rachel on April 10th" said on
2023-05-09 happened on 2023-04-10. A memory that describes something ongoing, a
plan, a preference or no event at all has no event date.

For each memory return the date the described event happened, as YYYY-MM-DD, or
null when the text does not pin one down. Do not guess: null is the right answer
whenever the text and the said-date together do not fix a specific day.

Return JSON only, of the form {"0": "2023-04-10", "1": null, ...}, one key per
memory number you were given."""


def event_dates(memories: list[tuple[str, str]]) -> dict[int, str]:
    """Ask when each memory's event happened. Returns {position: YYYY-MM-DD}.

    A regular expression can find "2023-04-10" but not "the day of my
    graduation", and it cannot tell an utterance date from an event date at
    all — numbering memories by the envelope's timestamp was measured to break
    ordering questions, because a user recounting two events in one sitting
    gives every memory the same day. Finding the time is reading, so a reader
    does it; the arithmetic afterwards is exact, so code does that.

    Failure is silent and total for the batch: no dates is the same as no
    feature, which is the behaviour without a key.
    """
    if not config.llm_available() or not memories:
        return {}
    lines = "\n".join(f"{i} | {said} | {text[:300]}" for i, (said, text) in enumerate(memories))
    raw = _complete(EVENT_DATE_SYSTEM, lines, config.LLM_MAX_TOKENS_EVENTS)
    if not raw:
        return {}
    try:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return {}
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    out: dict[int, str] = {}
    for key, value in payload.items():
        if not isinstance(value, str):
            continue
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()):
            continue
        try:
            position = int(key)
        except (TypeError, ValueError):
            continue
        if 0 <= position < len(memories):
            out[position] = value.strip()
    return out


def reflect_gap(query: str, options: list[str] | None, top_memories: list[str]) -> dict | None:
    """Check whether retrieved evidence is complete; if not, produce a targeted
    follow-up recall question.  Returns None on failure (degrade gracefully)."""
    if not config.llm_available():
        return None
    snippets = "\n".join(f"- {m[:200]}" for m in top_memories[:15])
    user = f"Original question: {query}\n"
    if options:
        user += f"Answer options: {' | '.join(str(o) for o in options[:10])}\n"
    user += f"\nRetrieved evidence:\n{snippets}"
    raw = _complete(REFLECT_SYSTEM, user, 200)
    if not raw:
        return None
    try:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            return json.loads(match.group(0))
    except json.JSONDecodeError:
        pass
    return None
