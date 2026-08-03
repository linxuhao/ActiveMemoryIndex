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
    try:
        response = _get_client().chat.completions.create(
            model=config.LLM_MODEL,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0,
            max_tokens=max_tokens,
        )
        return (response.choices[0].message.content or "").strip()
    except Exception as exc:  # network, quota, provider error — degrade, never fail Add
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
    # Fallback: a bare list of lines.
    lines = [re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", line).strip(' "') for line in text.splitlines()]
    return [line for line in lines if len(line) > 3][: config.LLM_MAX_FACTS]


def extract_facts(chunk_text: str) -> list[str]:
    """Add path: atomic, self-contained, timestamped memories."""
    if not config.EXTRACT_ENABLED:
        return []
    raw = _complete(EXTRACT_SYSTEM % config.LLM_MAX_FACTS, chunk_text, max_tokens=1200)
    if raw is None:
        return []
    return _parse_facts(raw)[: config.LLM_MAX_FACTS]


def recall_question(query: str, options: list[str] | None) -> str | None:
    """Search path: the same question in the log's own first-person register."""
    if not config.RECALL_QUERY_ENABLED:
        return None
    user = f"Question: {query}"
    if options:
        user += "\nAnswer options: " + " | ".join(str(o) for o in options[:10])
    raw = _complete(RECALL_SYSTEM, user, max_tokens=120)
    if not raw:
        return None
    return raw.splitlines()[0].strip(' "')
