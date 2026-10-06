"""Request deadlines (app/deadline.py) against a fake slow upstream.

The edge in front of the public endpoint cuts a request at ~100 s. An Add
makes extraction/detection calls and several embedding batches; with a 40 s
embedding timeout and one retry, four sequential batches alone could take
320 s. These tests drive the real ASGI app with fake providers that honour the
per-request `timeout` the service passes, on a time scale of 1/20 (deadline
85 s -> 4.25 s, embedding timeout 40 s -> 2 s, LLM timeout 25 s -> 1.25 s).
"""
import asyncio
from collections import OrderedDict
from pathlib import Path
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch

import httpx
import numpy as np
import openai

from app import config, deadline, embed, llm, main, store

SCALE = 20.0
DIM = 16


def timeout_error():
    return openai.APITimeoutError(request=httpx.Request("POST", "http://upstream/v1"))


class SlowEmbeddings:
    """client.embeddings stand-in: answers after *delay* seconds, or raises the
    SDK's timeout error once the request's own timeout has passed."""

    def __init__(self, delay):
        self.delay, self.calls, self.lock = delay, [], threading.Lock()
        self.embeddings = self
        self.active = self.peak = 0

    def create(self, **kw):
        with self.lock:
            self.calls.append((time.monotonic(), kw.get("timeout")))
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            delay = self.delay(len(self.calls)) if callable(self.delay) else self.delay
            if kw.get("timeout") is not None and delay > kw["timeout"]:
                time.sleep(kw["timeout"])
                raise timeout_error()
            time.sleep(delay)
            data = []
            for position, _ in enumerate(kw["input"]):
                vector = [0.0] * DIM
                vector[position % DIM] = 1.0
                data.append(types.SimpleNamespace(index=position, embedding=vector))
            return types.SimpleNamespace(data=data)
        finally:
            with self.lock:
                self.active -= 1


class SlowChat:
    def __init__(self, delay, reply='{"facts": ["I adopted a beagle."]}'):
        self.delay, self.reply, self.calls = delay, reply, []
        self.chat = self
        self.completions = self

    def create(self, **kw):
        self.calls.append(kw.get("timeout"))
        if kw.get("timeout") is not None and self.delay > kw["timeout"]:
            time.sleep(kw["timeout"])
            raise timeout_error()
        time.sleep(self.delay)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(
            message=types.SimpleNamespace(content=self.reply))])


def add_body(request_id, n_messages=40, user="u1"):
    return {"request_id": request_id, "user_id": user, "session_id": "s",
            "messages": [{"role": "user" if k % 2 == 0 else "assistant",
                          "content": f"message {k} about the beagle", "timestamp": 1_700_000_000_000 + k}
                         for k in range(n_messages)]}


class DeadlineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = store._conn, store._cache, store._cached_items, store._embedding_dimensions
        store._conn, store._cache, store._cached_items, store._embedding_dimensions = None, OrderedDict(), 0, None
        self.patches = [
            patch.multiple(config, DB_PATH=str(Path(self.tmp.name) / "t.sqlite3"), AUTH_SCHEME="none",
                           LLM_API_KEY="", RETRY_AFTER=4, EMBED_BACKEND="openai", EMBED_MODEL="text-embedding-v4",
                           EMBED_API_KEY="k", EMBED_BASE_URL="https://embed.example/v1", EMBED_DIMENSIONS=DIM,
                           EMBED_BATCH=10, EMBED_TIMEOUT=40 / SCALE, EMBED_RETRIES=1, EMBED_CONCURRENCY=16,
                           LLM_TIMEOUT=25 / SCALE, LLM_RETRIES=1,
                           ADD_DEADLINE=85 / SCALE, SEARCH_DEADLINE=85 / SCALE, ADMISSION_WAIT=45 / SCALE),
            patch.object(embed, "REMOTE_DIMENSIONS", frozenset({DIM})),
            patch.object(embed, "embedding_identity", return_value={"backend": "fake"}),
        ]
        for p in self.patches:
            p.start()
        store.init()
        for key in main.valve_counters:
            main.valve_counters[key] = 0

    def tearDown(self):
        store._conn.close()
        store._conn, store._cache, store._cached_items, store._embedding_dimensions = self.saved
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def use_embeddings(self, fake):
        gate = threading.BoundedSemaphore(config.EMBED_CONCURRENCY)
        p = patch.object(embed, "_get_remote_client", return_value=(fake, gate))
        p.start()
        self.addCleanup(p.stop)
        return fake

    def post(self, *calls):
        async def go():
            transport = httpx.ASGITransport(app=main.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://t", timeout=60) as client:
                async def one(delay, path, body):
                    await asyncio.sleep(delay)
                    started = time.monotonic()
                    response = await client.post(path, json=body)
                    return response, time.monotonic() - started
                return await asyncio.gather(*(one(*call) for call in calls))
        return asyncio.run(go())

    def persisted(self, request_id):
        return store._conn.execute("SELECT COUNT(*) FROM items WHERE request_id=?", (request_id,)).fetchone()[0]

    # --- embedding fan-out ------------------------------------------------------
    def test_batches_of_one_add_run_side_by_side(self):
        fake = self.use_embeddings(SlowEmbeddings(0.3))
        started = time.monotonic()
        vectors = embed.encode([f"text {n}" for n in range(40)])
        wall = time.monotonic() - started
        self.assertEqual(vectors.shape, (40, DIM))
        self.assertEqual(len(fake.calls), 4)
        self.assertEqual(fake.peak, 4)
        self.assertLess(wall, 0.9, "four 0.3 s batches in about 0.3 s, not 1.2 s")

    def test_without_a_deadline_every_retry_is_made(self):
        fake = self.use_embeddings(SlowEmbeddings(10.0))
        deadline.clear()
        with self.assertRaises(openai.APITimeoutError):
            embed.encode(["one text"])
        self.assertEqual(len(fake.calls), 1 + config.EMBED_RETRIES)
        self.assertTrue(all(abs(t - config.EMBED_TIMEOUT) < 1e-9 for _, t in fake.calls))

    def test_attempts_are_clipped_to_the_deadline(self):
        fake = self.use_embeddings(SlowEmbeddings(10.0))
        deadline.start(2.0)
        try:
            started = time.monotonic()
            with self.assertRaises(deadline.DeadlineExceeded):
                embed.encode(["one text"])
            wall = time.monotonic() - started
        finally:
            deadline.clear()
        self.assertLess(wall, 2.0)
        self.assertLessEqual(fake.calls[0][1], 2.0 - deadline.RESERVE + 1e-6)
        self.assertEqual(len(fake.calls), 1, "no retry once the deadline leaves no time for one")

    def test_retry_is_made_when_time_allows(self):
        fake = self.use_embeddings(SlowEmbeddings(lambda n: 10.0 if n == 1 else 0.05))
        deadline.start(85 / SCALE)
        try:
            vectors = embed.encode(["one text"])
        finally:
            deadline.clear()
        self.assertEqual(vectors.shape, (1, DIM))
        self.assertEqual(len(fake.calls), 2)

    # --- Add ------------------------------------------------------------------------
    def test_worst_case_add_answers_503_within_the_deadline_and_persists_nothing(self):
        self.use_embeddings(SlowEmbeddings(1000.0))  # never answers in time
        ((response, wall),) = self.post((0, "/add", add_body("w1")))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.headers.get("retry-after"), "4")
        self.assertLess(wall, config.ADD_DEADLINE + 0.5,
                        "the scaled worst case stays inside the deadline (85 s -> 4.25 s here)")
        self.assertEqual(self.persisted("w1"), 0)
        self.assertFalse(store.request_seen("w1", "u1"))

    def test_slow_extraction_and_slow_embedding_together_stay_inside_the_deadline(self):
        self.use_embeddings(SlowEmbeddings(1000.0))
        chat = SlowChat(1000.0)
        with patch.object(config, "LLM_API_KEY", "x"), patch.object(llm, "_get_client", return_value=chat), \
                patch.object(config, "RECALL_QUERY_ENABLED", False):
            ((response, wall),) = self.post((0, "/add", add_body("w2")))
        self.assertEqual(response.status_code, 503)
        self.assertLess(wall, config.ADD_DEADLINE + 0.5)
        self.assertEqual(self.persisted("w2"), 0)
        self.assertGreaterEqual(len(chat.calls), 1)

    def test_retry_after_the_deadline_is_a_clean_first_write(self):
        fake = self.use_embeddings(SlowEmbeddings(1000.0))
        ((first, _),) = self.post((0, "/add", add_body("w3")))
        self.assertEqual(first.status_code, 503)
        fake.delay = 0.01
        ((retry, _),) = self.post((0, "/add", add_body("w3")))
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(self.persisted("w3"), 40)

    def test_admission_wait_counts_toward_the_deadline(self):
        self.use_embeddings(SlowEmbeddings(lambda n: 1.4 if n <= 4 else 1.4))
        with patch.object(config, "ADD_MAX_INFLIGHT", 1), patch.object(config, "ADD_DEADLINE", 2.0), \
                patch.object(config, "ADMISSION_WAIT", 5.0):
            (a, wall_a), (b, wall_b) = self.post((0, "/add", add_body("q1")), (0.05, "/add", add_body("q2")))
        self.assertEqual(a.status_code, 200)
        self.assertEqual(b.status_code, 503, "admitted after ~1.4 s of a 2 s deadline: no time for a 1.4 s call")
        self.assertLess(wall_b, 2.0 + 0.5)
        self.assertEqual(self.persisted("q2"), 0)

    # --- Search ---------------------------------------------------------------------
    def test_search_with_a_slow_upstream_answers_503_within_the_deadline(self):
        fake = self.use_embeddings(SlowEmbeddings(0.01))
        ((added, _),) = self.post((0, "/add", add_body("s1", n_messages=4)))
        self.assertEqual(added.status_code, 200)
        fake.delay = 1000.0
        chat = SlowChat(1000.0)
        with patch.object(config, "LLM_API_KEY", "x"), patch.object(llm, "_get_client", return_value=chat):
            ((response, wall),) = self.post((0, "/search", {"query": "beagle?", "user_id": "u1", "top_k": 5}))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.headers.get("retry-after"), "4")
        self.assertLess(wall, config.SEARCH_DEADLINE + 0.5)

    def test_slow_recall_rewrite_alone_degrades_not_fails(self):
        self.use_embeddings(SlowEmbeddings(0.01))
        ((added, _),) = self.post((0, "/add", add_body("s2", n_messages=4)))
        self.assertEqual(added.status_code, 200)
        chat = SlowChat(1000.0)  # the LLM attempt times out at its own 1.25 s
        with patch.object(config, "LLM_API_KEY", "x"), patch.object(llm, "_get_client", return_value=chat), \
                patch.object(config, "LLM_RETRIES", 0):
            ((response, wall),) = self.post((0, "/search", {"query": "beagle?", "user_id": "u1", "top_k": 5}))
        self.assertEqual(response.status_code, 200, "time was left for the embedding: no recall question, still served")
        self.assertGreater(len(response.json()["data"]), 0)
        self.assertLess(wall, config.SEARCH_DEADLINE)

    def test_production_numbers_fit_under_the_edge(self):
        """The shipped defaults, unscaled: every path is bounded by the deadline."""
        self.assertEqual(config.EMBED_TIMEOUT * SCALE, 40)
        import importlib.util
        spec = importlib.util.spec_from_file_location("fresh_config", Path(config.__file__))
        fresh = importlib.util.module_from_spec(spec)
        with patch.dict("os.environ", {}, clear=True):
            spec.loader.exec_module(fresh)
        self.assertEqual((fresh.EMBED_TIMEOUT, fresh.EMBED_CONCURRENCY, fresh.EMBED_RETRIES), (40.0, 16, 1))
        self.assertLessEqual(fresh.ADD_DEADLINE, 90)
        self.assertLessEqual(fresh.SEARCH_DEADLINE, 90)


if __name__ == "__main__":
    unittest.main()
