#!/usr/bin/env python3
"""Caching, metering, capped proxy for OpenAI chat completions and embeddings (stdlib only).

Every model call of an experiment — the service's extraction, detection,
verification and recall-question calls, and the bench's reader and judge —
goes through one of these, so that:

  * identical requests get identical replies. Two arms that differ only in
    what Search withholds then share their recall question, and a question
    whose returned set is byte-identical in two arms gets the same answer and
    the same verdict. A client separates replicates with an `X-Cache-Salt`
    header, which is part of the cache key;
  * every fresh call is metered (prompt and completion tokens, by purpose) in
    a JSON-lines ledger;
  * a hard cap on fresh tokens refuses further calls with 429 instead of
    spending past the budget, and upstream concurrency is bounded.

Only `gpt-4o-mini` is forwarded. The upstream key is read from the
environment here and never handed to the service container.

rc4: POST /v1/embeddings is forwarded too (only `text-embedding-v4`), to
--embed-upstream with EMBED_API_KEY, cached the same way and metered against
its own cap (--embed-cap, usage.total_tokens). GET / reports both counters.

    OPENAI_API_KEY=... EMBED_API_KEY=... python3 bench/llm_proxy.py --dir RUN_DIR --port 8099 \
        --cap 40000000 --embed-cap 15000000 --embed-upstream https://.../compatible-mode/v1/embeddings
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PURPOSES = (
    ("You turn a chunk of a conversation", "extract"),
    ("You turn a chunk of content", "fallback"),
    ("You read a question that will be answered from a person's memory log and say how it uses a date", "asof"),
    ("You find EXPLICIT updates", "detect"),
    ("You read a chunk of a conversation and label", "stage1"),
    ("You extract the value change", "stage2"),
    ("You read a question that will be answered", "scope"),
    ("You check which earlier memories", "verify"),
    ("You write the memory-check question", "recall"),
    ("You are asked to answer a question", "answer"),
    ("Your task is to label an answer", "judge"),
)


def purpose_of(body: dict) -> str:
    messages = body.get("messages") or []
    first = str(messages[0].get("content", "")) if messages else ""
    for prefix, name in PURPOSES:
        if first.lstrip().startswith(prefix):
            return name
    return "other"


class State:
    def __init__(self, directory: Path, cap: int, concurrency: int, upstream: str, key: str,
                 embed_cap: int = 0, embed_upstream: str = "", embed_key: str = "") -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(directory / "llm_cache.sqlite3"), check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, body TEXT NOT NULL)")
        self.db.commit()
        self.ledger = directory / "llm_ledger.jsonl"
        self.lock = threading.Lock()
        self.gate = threading.Semaphore(concurrency)
        self.cap, self.upstream, self.key = cap, upstream, key
        self.embed_cap, self.embed_upstream, self.embed_key = embed_cap, embed_upstream, embed_key
        self.embed_gate = threading.Semaphore(concurrency)
        self.fresh = 0
        self.embed_fresh = 0
        if self.ledger.exists():
            for line in self.ledger.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                if not row.get("cached"):
                    if row.get("purpose") == "embed":
                        self.embed_fresh += row.get("total_tokens", 0)
                    else:
                        self.fresh += row.get("prompt_tokens", 0) + row.get("completion_tokens", 0)

    def get(self, key: str) -> str | None:
        with self.lock:
            row = self.db.execute("SELECT body FROM cache WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def put(self, key: str, body: str) -> None:
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO cache (key, body) VALUES (?, ?)", (key, body))
            self.db.commit()

    def log(self, **row) -> None:
        with self.lock:
            if not row.get("cached"):
                if row.get("purpose") == "embed":
                    self.embed_fresh += row.get("total_tokens", 0)
                else:
                    self.fresh += row.get("prompt_tokens", 0) + row.get("completion_tokens", 0)
            with self.ledger.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"at": time.time(), **row}) + "\n")


def make_handler(state: State):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:  # quiet
            pass

        def reply(self, status: int, payload: str) -> None:
            data = payload.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            self.reply(200, json.dumps({"fresh_tokens": state.fresh, "cap": state.cap,
                                        "embed_fresh_tokens": state.embed_fresh, "embed_cap": state.embed_cap}))

        def do_POST(self) -> None:
            raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            try:
                body = json.loads(raw)
            except json.JSONDecodeError:
                return self.reply(400, json.dumps({"error": {"message": "bad json"}}))
            if self.path.rstrip("/").endswith("/embeddings"):
                return self.embeddings(body)
            if body.get("model") != "gpt-4o-mini":
                return self.reply(400, json.dumps({"error": {"message": "only gpt-4o-mini is allowed"}}))
            salt = self.headers.get("X-Cache-Salt", "")
            canonical = json.dumps(body, sort_keys=True, ensure_ascii=False)
            key = hashlib.sha256(f"{salt}\x00{canonical}".encode("utf-8")).hexdigest()
            purpose = purpose_of(body)
            cached = state.get(key)
            if cached is not None:
                state.log(key=key, cached=True, purpose=purpose, salt=salt)
                return self.reply(200, cached)
            if state.fresh >= state.cap:
                return self.reply(429, json.dumps({"error": {"message": "experiment token cap reached"}}))
            last = ""
            for attempt in range(6):
                request = urllib.request.Request(
                    state.upstream, data=json.dumps(body).encode("utf-8"), method="POST",
                    headers={"Content-Type": "application/json", "Authorization": f"Bearer {state.key}"})
                try:
                    with state.gate, urllib.request.urlopen(request, timeout=120) as response:
                        text = response.read().decode("utf-8")
                    usage = json.loads(text).get("usage") or {}
                    state.put(key, text)
                    state.log(key=key, cached=False, purpose=purpose, salt=salt,
                              prompt_tokens=usage.get("prompt_tokens", 0),
                              completion_tokens=usage.get("completion_tokens", 0))
                    return self.reply(200, text)
                except urllib.error.HTTPError as error:
                    last = f"HTTP {error.code}"
                    if error.code not in (408, 409, 429, 500, 502, 503, 504):
                        return self.reply(error.code, json.dumps({"error": {"message": last}}))
                except Exception as error:  # noqa: BLE001
                    last = type(error).__name__
                time.sleep(min(3 * 2 ** attempt, 60))
            return self.reply(502, json.dumps({"error": {"message": f"upstream failed: {last}"}}))

        def embeddings(self, body: dict) -> None:
            if body.get("model") != "text-embedding-v4" or not state.embed_upstream:
                return self.reply(400, json.dumps({"error": {"message": "only text-embedding-v4 is allowed"}}))
            canonical = json.dumps(body, sort_keys=True, ensure_ascii=False)
            key = "embed:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            cached = state.get(key)
            if cached is not None:
                state.log(key=key, cached=True, purpose="embed")
                return self.reply(200, cached)
            if state.embed_fresh >= state.embed_cap:
                return self.reply(429, json.dumps({"error": {"message": "embedding token cap reached"}}))
            request = urllib.request.Request(
                state.embed_upstream, data=json.dumps(body).encode("utf-8"), method="POST",
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {state.embed_key}"})
            try:
                with state.embed_gate, urllib.request.urlopen(request, timeout=60) as response:
                    text = response.read().decode("utf-8")
            except urllib.error.HTTPError as error:
                return self.reply(error.code, json.dumps({"error": {"message": f"HTTP {error.code}"}}))
            except Exception as error:  # noqa: BLE001 - the service retries
                return self.reply(504, json.dumps({"error": {"message": type(error).__name__}}))
            usage = json.loads(text).get("usage") or {}
            state.put(key, text)
            state.log(key=key, cached=False, purpose="embed",
                      total_tokens=usage.get("total_tokens", usage.get("prompt_tokens", 0)))
            return self.reply(200, text)

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", required=True)
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument("--cap", type=int, default=40_000_000)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--upstream", default="https://api.openai.com/v1/chat/completions")
    parser.add_argument("--embed-cap", type=int, default=0)
    parser.add_argument("--embed-upstream", default="")
    args = parser.parse_args()
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        raise SystemExit("OPENAI_API_KEY is not set")
    state = State(Path(args.dir), args.cap, args.concurrency, args.upstream, key,
                  args.embed_cap, args.embed_upstream, os.environ.get("EMBED_API_KEY", ""))
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(state))
    print(f"proxy on 127.0.0.1:{args.port}, fresh tokens so far {state.fresh}, cap {args.cap}; "
          f"embedding {state.embed_fresh} of {args.embed_cap}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
