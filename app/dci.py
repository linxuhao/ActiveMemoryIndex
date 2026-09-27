"""Direct corpus interaction: a gpt-4o-mini agent greps and reads the user's
stored memories and names the ids to return.

Pre-registered in bench/results/dci_search_preregistration.md. The agent sees
the store as files — one per Add chunk, holding that chunk's verbatim turns in
order, plus one file of extracted facts — and has three tools: grep, read,
finish. It never emits memory text: the only thing it can hand back is a list
of ids of items that already exist, so /search still returns stored text
selected for the question, as it does today.
"""
from __future__ import annotations

import json
import logging
import re
import time

from . import config, llm, store

log = logging.getLogger("ami.dci")
counters = {"searches": 0, "fallbacks": 0, "empty": 0, "tool_calls": 0, "refused": 0, "seconds": 0.0}

SYSTEM = """You are a search agent over one person's memory. The memory is a set of files: one file per conversation chunk, each line a verbatim message between the person ("I") and their assistant, prefixed with the line's id and timestamp, in order; plus a file named facts holding first-person facts extracted from those conversations, each prefixed with its id and the date it was said.

Your job is to find the lines a reader would need in order to answer the question. You do NOT answer the question and must not try to.

Tools: grep(pattern, context) searches every line with a case-insensitive regular expression and shows the matching lines with `context` neighbouring lines from the same file. read(file, start, end) shows lines start..end of one file. finish(ids) ends the search with the ids to return, most important first.

Guidance:
- Start from the distinctive words of the question; if nothing matches, try synonyms, numbers, dates, or names, and use context to see what a pronoun refers to.
- Values change over time. If the same thing was stated more than once, read the timestamps: return the latest statement and leave out superseded ones — unless the question asks about the past, or the later statement is relative to the earlier one (e.g. "one more"), in which case return both.
- Include the neighbouring turns needed to understand a line (what "it", "them", "there" refer to; the assistant's reply that confirms a detail).
- Prefer verbatim message lines over facts lines when both say the same thing; include a facts line when it states something the messages only imply.
{stopping}"""

STOP_EARLY = "- Stop as soon as you have the evidence. Call finish with at most {limit} ids. If you truly find nothing relevant, call finish with the closest lines you saw rather than an empty list."
PERSIST = "- Do not stop at the first match. After every hit, grep again for the subject of that hit (its noun, name, number, or a synonym) with context, to find later restatements or updates of the same thing; read around a hit when a pronoun is unresolved. Finish only once the value you found has been checked for later updates. You have {budget} tool calls; use as many as the question needs. Call finish with at most {limit} ids. If you truly find nothing relevant, call finish with the closest lines you saw rather than an empty list."
REFUSED = "Not yet: {done} of at least {need} searches done. Grep the subject of your best hit again, with context, to check for a later restatement or update; then finish."

TOOLS = [
    {"type": "function", "function": {
        "name": "grep",
        "description": "Case-insensitive regular-expression search over every line of every file.",
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string", "description": "Python regular expression."},
            "context": {"type": "integer", "description": "Neighbouring lines to show on each side of a hit, from the same file. 0-3.", "default": 0},
        }, "required": ["pattern"]},
    }},
    {"type": "function", "function": {
        "name": "read",
        "description": "Show lines start..end (inclusive line numbers) of one file.",
        "parameters": {"type": "object", "properties": {
            "file": {"type": "string", "description": "File name as listed (the chunk id, or 'facts')."},
            "start": {"type": "integer"},
            "end": {"type": "integer"},
        }, "required": ["file", "start", "end"]},
    }},
    {"type": "function", "function": {
        "name": "finish",
        "description": "End the search and return the ids of the lines to hand to the reader, most important first.",
        "parameters": {"type": "object", "properties": {
            "ids": {"type": "array", "items": {"type": "string"}},
        }, "required": ["ids"]},
    }},
]
FINISH_ONLY = [TOOLS[2]]
FORCE_FINISH = {"type": "function", "function": {"name": "finish"}}

_ITEM_ID = re.compile(r"([0-9a-f]{16})-([rf])(\d+)")
LINE_CHARS = 320


def _line(item: store.Item, chars: int = LINE_CHARS) -> str:
    text = item.content.replace("\n", " ")
    if len(text) > chars:
        text = text[:chars] + "…"
    return f"{item.id} · {text}"


class Corpus:
    """The store as the agent sees it: files of turns, and a facts file."""

    def __init__(self, index: store.UserIndex) -> None:
        self.files: dict[str, list[store.Item]] = {}
        self.facts: list[store.Item] = []
        self.by_id: dict[str, store.Item] = {}
        for item in index.items:
            self.by_id[item.id] = item
            match = _ITEM_ID.fullmatch(item.id)
            if item.kind == "fact" or (match and match.group(2) == "f"):
                self.facts.append(item)
            elif match:
                self.files.setdefault(match.group(1), []).append(item)
        for turns in self.files.values():
            turns.sort(key=lambda it: int(_ITEM_ID.fullmatch(it.id).group(3)))
        # Files in the order they were written, which is the order of the store.
        self.order = list(self.files)

    def listing(self, cap: int = 300) -> str:
        rows = []
        for name in self.order[:cap]:
            turns = self.files[name]
            first = (turns[0].created_at or "")[:10] or "-"
            last = (turns[-1].created_at or "")[:10] or "-"
            rows.append(f"{name}  {first} → {last}  {len(turns)} lines")
        if len(self.order) > cap:
            rows.append(f"… {len(self.order) - cap} more files")
        rows.append(f"facts  {len(self.facts)} lines")
        return "\n".join(rows)

    def grep(self, pattern: str, context: int = 0) -> str:
        try:
            regex = re.compile(pattern[:200], re.IGNORECASE)
        except re.error as exc:
            return f"invalid regular expression: {exc}"
        context = max(0, min(int(context or 0), 3))
        out: list[str] = []
        hits = 0
        shown: set[str] = set()
        for name in self.order:
            turns = self.files[name]
            for position, item in enumerate(turns):
                if not regex.search(item.content):
                    continue
                hits += 1
                if hits > config.DCI_GREP_HITS:
                    continue
                lo, hi = max(0, position - context), min(len(turns), position + context + 1)
                for neighbour in turns[lo:hi]:
                    if neighbour.id in shown:
                        continue
                    shown.add(neighbour.id)
                    prefix = "" if neighbour is item else "  "
                    out.append(prefix + _line(neighbour))
        for item in self.facts:
            if regex.search(item.content):
                hits += 1
                if hits <= config.DCI_GREP_HITS and item.id not in shown:
                    shown.add(item.id)
                    out.append(_line(item))
        if not hits:
            return "no matches"
        if hits > config.DCI_GREP_HITS:
            out.append(f"… {hits - config.DCI_GREP_HITS} more matching lines not shown; narrow the pattern")
        return "\n".join(out)

    def read(self, name: str, start: int, end: int) -> str:
        if name == "facts":
            lines = self.facts
        else:
            key = next((f for f in self.order if f == name or f.startswith(name)), None) if name else None
            if key is None:
                return "no such file"
            lines = self.files[key]
        try:
            start, end = int(start), int(end)
        except (TypeError, ValueError):
            return "start and end must be integers"
        start = max(0, start)
        end = min(len(lines) - 1, end, start + config.DCI_READ_LINES - 1)
        if start > end:
            return "empty range"
        return "\n".join(_line(item, 600) for item in lines[start:end + 1])


def _args(raw: str) -> dict:
    try:
        parsed = json.loads(raw or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _assistant_message(reply: dict) -> dict:
    message: dict = {"role": "assistant", "content": reply["content"] or None}
    if reply["tool_calls"]:
        message["tool_calls"] = [
            {"id": c["id"], "type": "function",
             "function": {"name": c["name"], "arguments": c["arguments"]}}
            for c in reply["tool_calls"]]
    return message


def system_prompt(limit: int) -> str:
    stopping = PERSIST if config.DCI_MIN_CALLS > 0 else STOP_EARLY
    return (SYSTEM.replace("{stopping}", stopping)
            .replace("{limit}", str(limit)).replace("{budget}", str(config.DCI_BUDGET)))


def run(index: store.UserIndex, query: str, options: list[str] | None, limit: int) -> list[store.Item] | None:
    """Return the items the agent chose, in its order, or None when the agent
    could not run (API failure, no finish): the caller falls back."""
    counters["searches"] += 1
    started = time.monotonic()
    corpus = Corpus(index)
    question = query if not options else query + "\nOptions:\n" + "\n".join(options)
    messages = [
        {"role": "system", "content": system_prompt(limit)},
        {"role": "user", "content": f"Files:\n{corpus.listing()}\n\nQuestion: {question}"},
    ]
    calls = 0
    nudged = False
    try:
        while True:
            forced = calls >= config.DCI_BUDGET
            reply = llm.chat_tools(messages, FINISH_ONLY if forced else TOOLS, config.DCI_MAX_TOKENS,
                                   tool_choice=FORCE_FINISH if forced else None)
            if reply is None:
                return None
            messages.append(_assistant_message(reply))
            if not reply["tool_calls"]:
                if nudged or forced:
                    return None
                nudged = True
                messages.append({"role": "user", "content": "Use the tools. When you have the evidence, call finish with the ids."})
                continue
            for call in reply["tool_calls"]:
                args = _args(call["arguments"])
                if call["name"] == "finish":
                    if not forced and calls < config.DCI_MIN_CALLS:
                        # Persistent searcher: too few probes yet. The refusal
                        # counts toward the budget so the loop still ends.
                        calls += 1
                        counters["refused"] += 1
                        messages.append({"role": "tool", "tool_call_id": call["id"],
                                         "content": REFUSED.format(done=calls - 1, need=config.DCI_MIN_CALLS)})
                        continue
                    ids = args.get("ids") or []
                    picked: list[store.Item] = []
                    seen: set[str] = set()
                    for item_id in ids:
                        item = corpus.by_id.get(str(item_id))
                        if item is not None and item.id not in seen:
                            seen.add(item.id)
                            picked.append(item)
                        if len(picked) >= limit:
                            break
                    if not picked:
                        counters["empty"] += 1
                    return picked
                calls += 1
                counters["tool_calls"] += 1
                if call["name"] == "grep":
                    result = corpus.grep(str(args.get("pattern", "")), args.get("context", 0))
                elif call["name"] == "read":
                    result = corpus.read(str(args.get("file", "")), args.get("start", 0), args.get("end", 0))
                else:
                    result = f"unknown tool {call['name']}"
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
    finally:
        counters["seconds"] += time.monotonic() - started
