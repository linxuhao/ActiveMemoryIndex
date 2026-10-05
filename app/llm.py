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


def chat_tools(messages: list[dict], tools: list[dict], max_tokens: int,
               tool_choice: str | dict | None = None) -> dict | None:
    """One chat turn with function calling. Returns {"content": str,
    "tool_calls": [{"id", "name", "arguments"}]} or None on failure. Used by
    the direct-corpus-interaction agent (app/dci.py); tests replace it."""
    if not config.llm_available():
        return None
    counters["calls"] += 1
    try:
        with _gate:
            response = _get_client().chat.completions.create(
                model=config.LLM_MODEL,
                messages=messages,
                tools=tools,
                tool_choice=tool_choice or "auto",
                temperature=0,
                max_tokens=max_tokens,
            )
        message = response.choices[0].message
        calls = []
        for call in message.tool_calls or []:
            calls.append({"id": call.id, "name": call.function.name,
                          "arguments": call.function.arguments or "{}"})
        return {"content": _strip_reasoning(message.content or ""), "tool_calls": calls}
    except Exception as exc:
        counters["failures"] += 1
        log.warning("llm tool call failed: %s", exc)
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


# --- explicit updates (AMI_UPDATE_DETECT / AMI_UPDATE_WITHHOLD) ---------------
# A separate call, not a change to EXTRACT_SYSTEM: the extraction prompt stays
# byte-identical, so the facts channel of a store built with detection on is
# the shipped one (bench/results/explicit_update_preregistration.md).
UPDATE_DETECT_SYSTEM = """You find EXPLICIT updates in a chunk of a conversation, for a personal memory index.

The turns are numbered `N | [date time] Speaker: text` (the date may be missing). "I" is the user, the owner of the memories; any other speaker is not.

An explicit update is something the USER says that replaces or corrects a value stated before, and that says so in words:
- an instruction to replace, update, overwrite or correct a stored value or fact;
- a correction: "correction: ...", "actually it's X, not Y", "I was wrong, it is X";
- a stated change: "I changed my gym time from 7 to 6", "my address is now X instead of Y", "X is no longer Y".

Not an explicit update: new information that does not say an earlier value is replaced; plans, wishes, hypotheticals and questions; anything a speaker other than "I" says.

For each explicit update give:
- "turn": the N of the turn that states it;
- "subject": whose or what property it is, exactly as written; "me" when it is the user's own;
- "attribute": a short noun phrase naming the property, e.g. "gym time", "country of citizenship", "home address";
- "new_value": the new value, copied exactly as written in the turn;
- "old_value": the replaced value copied exactly as written in the turn, or null when the turn does not state it. Never guess it;
- "relative": true when the new value is given relative to the old one ("one more", "two fewer", "added another", "+2", "increased by 10") instead of outright, else false;
- "statement": one standalone present-tense sentence stating the current value, e.g. "Frank Herbert's genre is funk." or "My gym time is 6 pm." Do not mention the old value.

Return JSON only: {"updates": [{"turn": 0, "subject": "...", "attribute": "...", "new_value": "...", "old_value": null, "relative": false, "statement": "..."}]}. Most chunks contain none: then return {"updates": []}."""

UPDATE_VERIFY_SYSTEM = """You check which earlier memories state a value that a later explicit update replaced.

You get the update (its own words, the subject, the attribute, the new value and, when known, the old value) and numbered memories `N | text` written before it.

A memory states the replaced value only when ALL of these hold:
1. It is about the same subject (for subject "me": the user themself).
2. It gives the value of the very same attribute, not a related one: a gym day is not a gym time, a birthplace is not a citizenship, a team's size is not its name.
3. That value differs from the new value; when the old value is known, it is that old value.
4. It asserts the value as true. A memory that describes the change itself, mentions the new value, asks a question, or states a plan or a wish does not count.

For each memory that qualifies, quote the replaced value exactly as it is written in that memory.

Return JSON only: {"replaced": [{"n": 0, "old_value": "exact quote"}]}; {"replaced": []} when none qualifies."""


def _json_object(raw: str | None) -> dict | None:
    if not raw:
        return None
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def detect_updates(numbered: str) -> list[dict] | None:
    """Explicit updates stated in one chunk, unvalidated. None on failure."""
    if not config.llm_available():
        return None
    payload = _json_object(_complete(UPDATE_DETECT_SYSTEM, numbered, config.LLM_MAX_TOKENS_UPDATES))
    if payload is None:
        return None
    updates = payload.get("updates")
    return [entry for entry in updates if isinstance(entry, dict)] if isinstance(updates, list) else []


def verify_replaced(update: str, memories: list[str]) -> list[tuple[int, str]] | None:
    """[(memory number, quoted old value)] the reader says the update replaced.
    None on failure, which the caller treats as "nothing replaced" and retries
    on a later search."""
    if not config.llm_available() or not memories:
        return None
    numbered = "\n".join(f"{n} | {text}" for n, text in enumerate(memories))
    payload = _json_object(_complete(UPDATE_VERIFY_SYSTEM, f"{update}\n\nMemories:\n{numbered}",
                                     config.LLM_MAX_TOKENS_VERIFY))
    if payload is None:
        return None
    out = []
    for entry in payload.get("replaced") or []:
        if not isinstance(entry, dict):
            continue
        try:
            number = int(entry.get("n"))
        except (TypeError, ValueError):
            continue
        quote = entry.get("old_value")
        if isinstance(quote, str) and quote.strip() and 0 <= number < len(memories):
            out.append((number, quote.strip()))
    return out


# --- explicit updates, round 2 (AMI_UPDATE_VERSION=2) --------------------------
# Two stages, each with one job: stage 1 labels the intent of the user's
# value-bearing statements and quotes them; stage 2 runs only when stage 1
# accepted a replacement or correction, and extracts the update from the quote.
UPDATE_INTENT_SYSTEM = """You read a chunk of a conversation and label what the user is doing when they state a value that may already be on record.

The turns are numbered `N | [date time] Speaker: text`; the date may be missing. "I" is the user, the owner of the memories; any other speaker is not. Statements can be in any language.

List at most 8 of the user's statements that state a value someone could store and later need to update: a name, number, date, time, place, status, choice, or a fact about a person or thing. Give each exactly one label:
- EXPLICIT_REPLACEMENT: the user says in words that an earlier value is replaced, overwritten or changed, and gives the new one. "Please change my delivery address to 5 Elm Road." "Update my gym time: it's 6 pm from now on." "把会议时间改成下午三点。" "Mi número ya no es el anterior; ahora es 555-0199."
- CORRECTION: the user says an earlier value was wrong and gives the right one. "Sorry, I misspoke — the dog's name is Biscuit, not Bandit." "不对，我的生日是五月二号。" "Correction: the meeting is in room 4."
- RESTATEMENT: the user says again something that may have been said before, in the same or other words, without changing it.
- NEW_INFO: information with no words saying an earlier value is replaced or wrong, even if it differs from something said earlier. "I now lead a team of five." "I have 1,300 followers."
- RELATIVE_CHANGE: a change given relative to the old value. "I added one more coin." "我的预算又增加了两百元。"
- PLAN: an intention, wish, consideration or choice among options. "I think I'll go with the blue one." "I might move to Denver."
- HISTORY: narration of the past. "I used to wake up at 8:30." "以前我住在上海。"

For each statement give the turn number and copy, character for character, the shortest span of that turn that shows its intent ("quote"). The quote must appear in the turn exactly as you write it: no "..." or other added marks, no words left out or changed, spelling mistakes kept. Never translate or paraphrase it.

Return JSON only: {"statements": [{"turn": 0, "label": "NEW_INFO", "quote": "..."}]}. Return {"statements": []} when the user states no such value."""

UPDATE_EXTRACT_SYSTEM = """You extract the value change stated by a user's statement, for a personal memory index.

You get a chunk of a conversation (turns numbered `N | [date time] Speaker: text`, "I" is the user) and one or more numbered statements the user made in it, each quoted from a turn. Statements can be in any language.

For each statement give:
- "statement": its number;
- "subject": whose or what property changes, exactly as written; "me" when it is the user's own;
- "attribute": a short noun phrase naming the property;
- "new_value": the new value, copied exactly as written in the turn;
- "old_value": the replaced value copied exactly as written in the turn, or null when the turn does not state it. Never guess it;
- "relative": true when the new value is given relative to the old one instead of outright, else false;
- "current": one standalone present-tense sentence stating the current value, without the old value, written in the same language as the quoted statement: an English statement gets an English sentence, a Chinese statement a Chinese one. Never translate.

Return JSON only: {"updates": [{"statement": 0, "subject": "...", "attribute": "...", "new_value": "...", "old_value": null, "relative": false, "current": "..."}]}. Leave out a statement that changes no value."""

UPDATE_VERIFY2_SYSTEM = """You check which earlier memories state a value that a later explicit update replaced.

You get the update (its own words, the subject, the attribute, the new value and, when known, the old value) and numbered memories `N | text` written before it. Memories can be in any language.

Give each memory one verdict:
- REPLACED: it asserts, as true, a value of the very same attribute of the same subject (for subject "me": the user themself), and that value differs from the new value; when the old value is known, it is that old value. A gym day is not a gym time; a birthplace is not a citizenship.
- SAME: it states the same value as the new value in any wording, or it describes the change itself.
- OTHER: anything else: another subject or attribute, a question, a plan, a wish, a passing mention.

For REPLACED, quote the replaced value exactly as it is written in that memory.

Return JSON only: {"verdicts": [{"n": 0, "verdict": "REPLACED", "old_value": "exact quote"}]}, listing only memories that are REPLACED or SAME; {"verdicts": []} when none is."""

UPDATE_VERIFY3_SYSTEM = """You check which earlier memories state a value that a later explicit update replaced.

You get the update (its own words, the subject, the attribute, the new value and, when known, the old value) and numbered memories `N | text` written before it. Memories can be in any language. Judge each memory on its own, only against the update.

For each memory that gives a value for the very same attribute of the same subject (for subject "me": the user themself), report:
- "value": that value, quoted exactly as written in the memory;
- "compared_to_new": how that value relates to the new value:
  - "DIFFERENT": a different value, the one the update replaced (when the old value is known, it is that old value). Several memories can state it in different words or formats; each of them is DIFFERENT.
  - "SAME": the same value as the new value, in any wording ("did not pass away" against "did not end up dying").
  - "LESS_DETAIL": the new value with less detail ("February" against "February 10th"; "a hotel in Downtown LA" against "the Hilton in Downtown LA").
  - "MORE_DETAIL": the new value with more detail.
  - "PART": it describes the change itself, or repeats part of what the update says.
Leave out memories about another subject or another attribute (a gym day is not a gym time; a birthplace is not a citizenship), questions, plans, wishes and passing mentions.

Return JSON only: {"memories": [{"n": 0, "value": "exact quote", "compared_to_new": "DIFFERENT"}]}; {"memories": []} when none qualifies."""


def classify_update_intent(numbered: str) -> list[dict] | None:
    """Stage 1: [{"turn", "label", "quote"}], unvalidated. None on failure."""
    if not config.llm_available():
        return None
    payload = _json_object(_complete(UPDATE_INTENT_SYSTEM, numbered, config.LLM_MAX_TOKENS_INTENT))
    if payload is None:
        return None
    statements = payload.get("statements")
    return [s for s in statements if isinstance(s, dict)] if isinstance(statements, list) else []


def extract_updates(numbered: str, statements: list[tuple[int, str]]) -> list[dict] | None:
    """Stage 2 over accepted (turn, quote) statements. None on failure."""
    if not config.llm_available() or not statements:
        return None
    listed = "\n".join(f"S{k} | turn {turn} | {quote}" for k, (turn, quote) in enumerate(statements))
    payload = _json_object(_complete(UPDATE_EXTRACT_SYSTEM, f"Chunk:\n{numbered}\n\nStatements:\n{listed}",
                                     config.LLM_MAX_TOKENS_UPDATES))
    if payload is None:
        return None
    updates = payload.get("updates")
    return [u for u in updates if isinstance(u, dict)] if isinstance(updates, list) else []


def verify_replaced_v2(update: str, memories: list[str]) -> list[tuple[int, str]] | None:
    """[(memory number, quoted old value)] judged REPLACED; SAME and OTHER are
    dropped. None on failure."""
    if not config.llm_available() or not memories:
        return None
    numbered = "\n".join(f"{n} | {text}" for n, text in enumerate(memories))
    if config.UPDATE_VERSION >= 3:
        # Round 3: the model quotes the value, then says how it relates to
        # the new value; only DIFFERENT is a replaced value.
        payload = _json_object(_complete(UPDATE_VERIFY3_SYSTEM, f"{update}\n\nMemories:\n{numbered}",
                                         config.LLM_MAX_TOKENS_VERIFY))
        if payload is None:
            return None
        entries = [{"n": e.get("n"), "old_value": e.get("value")} for e in payload.get("memories") or []
                   if isinstance(e, dict) and str(e.get("compared_to_new", "")).upper() == "DIFFERENT"]
    else:
        payload = _json_object(_complete(UPDATE_VERIFY2_SYSTEM, f"{update}\n\nMemories:\n{numbered}",
                                         config.LLM_MAX_TOKENS_VERIFY))
        if payload is None:
            return None
        entries = [e for e in payload.get("verdicts") or []
                   if isinstance(e, dict) and str(e.get("verdict", "")).upper() == "REPLACED"]
    out = []
    for entry in entries:
        try:
            number = int(entry.get("n"))
        except (TypeError, ValueError):
            continue
        quote = entry.get("old_value")
        if isinstance(quote, str) and quote.strip() and 0 <= number < len(memories):
            out.append((number, quote.strip()))
    return out
