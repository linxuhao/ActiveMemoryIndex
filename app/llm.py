"""The single LLM used by both Add and Search.

Competition rule: for a leaderboard run this model must be ``gpt-4o-mini``.
Every call degrades to ``None`` on failure — the service must keep serving the
raw-text channel even when the LLM is unavailable.
"""
from __future__ import annotations

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
