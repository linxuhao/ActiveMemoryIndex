"""Admission valve and upstream-failure mapping: 429/503 + Retry-After, nothing persisted.

Drives the real ASGI app in-process (httpx.ASGITransport, no network). The
provider clients are fakes: embed.encode is patched, and the LLM client raises
the OpenAI SDK's own exception types.
"""
import asyncio
import contextlib
from collections import OrderedDict
from pathlib import Path
import tempfile
import json
import threading
import types
import unittest
from unittest.mock import patch

import httpx
import numpy as np
import openai

from app import config, embed, llm, main, store, updates

DIM = 8


def fake_vectors(texts, **_):
    rng = np.random.default_rng(len(texts))
    out = rng.standard_normal((len(texts), DIM)).astype(np.float32) + 0.1
    return out / np.linalg.norm(out, axis=1, keepdims=True)


def add_body(request_id, user="u1", text="I adopted a beagle named Ollie.", ts=1_700_000_000_000):
    return {"request_id": request_id, "user_id": user, "session_id": "s",
            "messages": [{"role": "user", "content": text, "timestamp": ts}]}


def status_error(cls, status, headers=None):
    response = httpx.Response(status, headers=headers or {}, request=httpx.Request("POST", "http://upstream/v1"))
    return cls("fake upstream error", response=response, body=None)


class FailingChat:
    """Stands in for OpenAI().chat.completions with a fixed exception."""

    def __init__(self, exc):
        self.exc = exc
        self.chat = self
        self.completions = self

    def create(self, **_):
        raise self.exc


def completion(text):
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=text))])


def timeout_error():
    return openai.APITimeoutError(request=httpx.Request("POST", "http://upstream/v1"))


class RoutedChat:
    """OpenAI().chat.completions stand-in that answers by which prompt it is given.

    routes maps a prompt name to a JSON-able reply, or to an exception to raise.
    """

    PROMPTS = {"extract": "EXTRACT_SYSTEM", "stage1": "UPDATE_INTENT_SYSTEM", "stage2": "UPDATE_EXTRACT5_SYSTEM",
               "router": "QUESTION_SCOPE2_SYSTEM", "verifier": "UPDATE_VERIFY3_SYSTEM"}

    def __init__(self, routes):
        self.routes = routes
        self.chat = self
        self.completions = self
        self.calls = []

    def create(self, **kw):
        system = kw["messages"][0]["content"]
        name = next((n for n, const in self.PROMPTS.items() if system.startswith(getattr(llm, const)[:60])), "other")
        self.calls.append(name)
        reply = self.routes.get(name)
        if isinstance(reply, Exception):
            raise reply
        return completion(json.dumps(reply if reply is not None else {}))


GYM_OLD = "My gym time is 7 pm."
GYM_NEW = "Update: my gym time is now 6 pm."
STAGE1 = {"statements": [{"turn": 0, "label": "EXPLICIT_REPLACEMENT", "quote": "Update: my gym time is now 6 pm"}]}
STAGE2 = {"updates": [{"statement": 0, "subject": "me", "subject_is_user": True, "attribute": "gym time",
                       "new_value": "6 pm", "old_value": None, "relative": False,
                       "current": "My gym time is 6 pm."}]}
VERIFIED = {"memories": [{"n": 0, "value": "7 pm", "compared_to_new": "DIFFERENT"}]}


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = store._conn, store._cache, store._cached_items, store._embedding_dimensions
        store._conn, store._cache, store._cached_items, store._embedding_dimensions = None, OrderedDict(), 0, None
        self.patches = [
            patch.object(config, "DB_PATH", str(Path(self.tmp.name) / "t.sqlite3")),
            patch.object(config, "AUTH_SCHEME", "none"),
            patch.object(config, "LLM_API_KEY", ""),
            patch.object(config, "ADMISSION_WAIT", 0.3),
            patch.object(config, "RETRY_AFTER", 4),
            patch.object(embed, "embedding_identity", return_value={"backend": "local"}),
            patch.object(embed, "encode", side_effect=fake_vectors),
        ]
        for p in self.patches:
            p.start()
        store.init()
        store._conn.executescript(store.UPDATE_SCHEMA)  # what init() adds when an update switch is on
        for key in main.valve_counters:
            main.valve_counters[key] = 0

    def tearDown(self):
        store._conn.close()
        store._conn, store._cache, store._cached_items, store._embedding_dimensions = self.saved
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def run_requests(self, *calls):
        async def go():
            transport = httpx.ASGITransport(app=main.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
                tasks = []
                for delay, path, body in calls:
                    async def one(delay=delay, path=path, body=body):
                        await asyncio.sleep(delay)
                        return await client.post(path, json=body)
                    tasks.append(one())
                return await asyncio.gather(*tasks)
        return asyncio.run(go())

    def rows(self, request_id, user="u1"):
        items = store._conn.execute("SELECT COUNT(*) FROM items WHERE request_id=? AND user_id=?",
                                    (request_id, user)).fetchone()[0]
        seen = store.request_seen(request_id, user)
        return items, seen

    def slow_encode(self, release: threading.Event):
        def encode(texts, **kw):
            release.wait(5)
            return fake_vectors(texts, **kw)
        return encode

    def test_off_by_default_is_pass_through(self):
        with patch.object(config, "ADD_MAX_INFLIGHT", 0), patch.object(config, "SEARCH_MAX_INFLIGHT", 0):
            add, search = self.run_requests((0, "/add", add_body("r0")),
                                            (0.2, "/search", {"query": "beagle?", "user_id": "u1", "top_k": 5}))
        self.assertEqual(add.status_code, 200)
        self.assertEqual(search.status_code, 200)
        self.assertEqual(main.valve_counters["add_admitted"], 0)
        self.assertEqual(self.rows("r0"), (1, True))

    def test_overload_rejects_before_any_work_and_retry_is_clean(self):
        release = threading.Event()
        threading.Timer(1.0, release.set).start()
        with patch.object(config, "ADD_MAX_INFLIGHT", 1), patch.object(embed, "encode", side_effect=self.slow_encode(release)):
            first, second = self.run_requests((0, "/add", add_body("r1")), (0.1, "/add", add_body("r2")))
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second.headers.get("retry-after"), "4")
        self.assertIn("overloaded", second.json()["detail"]["reason"])
        self.assertEqual(self.rows("r2"), (0, False), "a rejected Add persisted nothing")
        self.assertEqual(main.valve_counters["add_rejected"], 1)
        with patch.object(config, "ADD_MAX_INFLIGHT", 1):
            (retry,) = self.run_requests((0, "/add", add_body("r2")))
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry.json()["request_id"], "r2")
        self.assertEqual(self.rows("r2"), (1, True))

    def test_waiter_within_admission_wait_is_admitted_in_order(self):
        release = threading.Event()
        threading.Timer(0.3, release.set).start()
        with patch.object(config, "ADD_MAX_INFLIGHT", 1), patch.object(config, "ADMISSION_WAIT", 5.0), \
                patch.object(embed, "encode", side_effect=self.slow_encode(release)):
            responses = self.run_requests(*[(0.05 * n, "/add", add_body(f"q{n}")) for n in range(4)])
        self.assertEqual([r.status_code for r in responses], [200] * 4)
        seqs = [store._conn.execute("SELECT MIN(seq) FROM items WHERE request_id=?", (f"q{n}",)).fetchone()[0]
                for n in range(4)]
        self.assertEqual(seqs, sorted(seqs), "admission is first come, first served")
        self.assertEqual(main.valve_counters["add_rejected"], 0)

    def test_search_limit_is_independent_of_add(self):
        self.run_requests((0, "/add", add_body("s0")))
        release = threading.Event()
        threading.Timer(1.0, release.set).start()
        with patch.object(config, "SEARCH_MAX_INFLIGHT", 1), patch.object(config, "ADD_MAX_INFLIGHT", 0), \
                patch.object(embed, "encode", side_effect=self.slow_encode(release)):
            s1, s2, a = self.run_requests((0, "/search", {"query": "q", "user_id": "u1", "top_k": 3}),
                                          (0.1, "/search", {"query": "q", "user_id": "u1", "top_k": 3}),
                                          (0.1, "/add", add_body("s1")))
        self.assertEqual((s1.status_code, s2.status_code, a.status_code), (200, 429, 200))
        self.assertEqual(s2.headers.get("retry-after"), "4")

    def test_embedding_rate_limit_maps_to_429_with_upstream_retry_after(self):
        error = status_error(openai.RateLimitError, 429, {"retry-after": "7"})
        with patch.object(embed, "encode", side_effect=error):
            (response,) = self.run_requests((0, "/add", add_body("e1")))
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers.get("retry-after"), "7")
        self.assertEqual(self.rows("e1"), (0, False))
        (retry,) = self.run_requests((0, "/add", add_body("e1")))
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(self.rows("e1"), (1, True))
        (again,) = self.run_requests((0, "/add", add_body("e1")))
        self.assertEqual(again.status_code, 200)
        self.assertEqual(self.rows("e1"), (1, True), "idempotent replay after recovery")

    def test_embedding_timeout_and_5xx_map_to_503(self):
        timeout = openai.APITimeoutError(request=httpx.Request("POST", "http://upstream/v1"))
        for n, error in enumerate((timeout, status_error(openai.InternalServerError, 502))):
            with patch.object(embed, "encode", side_effect=error):
                (response,) = self.run_requests((0, "/add", add_body(f"t{n}")))
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.headers.get("retry-after"), "4")
            self.assertEqual(self.rows(f"t{n}"), (0, False))
        self.assertEqual(main.valve_counters["upstream_503"], 2)

    def test_search_embedding_failure_maps_to_503(self):
        self.run_requests((0, "/add", add_body("se")))
        timeout = openai.APITimeoutError(request=httpx.Request("POST", "http://upstream/v1"))
        with patch.object(embed, "encode", side_effect=timeout):
            (response,) = self.run_requests((0, "/search", {"query": "q", "user_id": "u1", "top_k": 3}))
        self.assertEqual(response.status_code, 503)

    def test_non_transient_embedding_error_still_500(self):
        with patch.object(embed, "encode", side_effect=ValueError("bad vectors")):
            async def go():
                transport = httpx.ASGITransport(app=main.app, raise_app_exceptions=False)
                async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
                    return await client.post("/add", json=add_body("v1"))
            response = asyncio.run(go())
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.rows("v1"), (0, False))

    def test_extraction_failure_degrades_unless_required(self):
        error = status_error(openai.RateLimitError, 429)
        with patch.object(config, "LLM_API_KEY", "x"), patch.object(llm, "_get_client", return_value=FailingChat(error)), \
                patch.object(config, "RECALL_QUERY_ENABLED", False):
            with patch.object(config, "EXTRACT_REQUIRED", False):
                (degraded,) = self.run_requests((0, "/add", add_body("x0")))
            with patch.object(config, "EXTRACT_REQUIRED", True):
                (strict,) = self.run_requests((0, "/add", add_body("x1")))
        self.assertEqual(degraded.status_code, 200)
        self.assertEqual(self.rows("x0"), (1, True), "default: raw turn stored without facts")
        self.assertEqual(strict.status_code, 429)
        self.assertEqual(strict.headers.get("retry-after"), "4")
        self.assertEqual(self.rows("x1"), (0, False), "required extraction failure persists nothing")

    def test_bad_request_from_llm_is_not_transient(self):
        error = status_error(openai.BadRequestError, 400)
        self.assertIsNone(llm.transient(error))
        self.assertIsNone(llm.transient(ValueError("x")))
        self.assertEqual(llm.transient(status_error(openai.RateLimitError, 429, {"retry-after": "600"})).retry_after, 60)

    # --- explicit-update calls: optional, never fail an Add -------------------
    def with_chat(self, chat):
        stack = contextlib.ExitStack()
        for p in (patch.object(llm, "_get_client", return_value=chat), patch.object(config, "LLM_API_KEY", "x"),
                  patch.object(config, "UPDATE_DETECT", True), patch.object(config, "UPDATE_WITHHOLD", True),
                  patch.object(config, "RECALL_QUERY_ENABLED", False)):
            stack.enter_context(p)
        return stack

    def update_rows(self, user="u1"):
        return len(store.get_updates(user))

    def test_update_call_timeout_is_tolerated_on_add(self):
        facts = {"facts": ["I go to the gym at 6 pm."]}
        cases = {"stage1": {"extract": facts, "stage1": timeout_error()},
                 "stage2": {"extract": facts, "stage1": STAGE1, "stage2": timeout_error()}}
        n = 0
        for required in (False, True):
            for stage, routes in cases.items():
                n += 1
                with self.subTest(stage=stage, extract_required=required):
                    chat = RoutedChat(routes)
                    with patch.object(llm, "_get_client", return_value=chat), patch.object(config, "LLM_API_KEY", "x"), \
                            patch.object(config, "UPDATE_DETECT", True), patch.object(config, "EXTRACT_REQUIRED", required), \
                            patch.object(config, "RECALL_QUERY_ENABLED", False):
                        (response,) = self.run_requests((0, "/add", add_body(f"ut{n}", text=GYM_NEW)))
                    self.assertEqual(response.status_code, 200)
                    self.assertIn(stage, chat.calls, "the update call was made")
                    self.assertEqual(self.rows(f"ut{n}"), (2, True), "turn and extracted fact stored")
                    self.assertEqual(self.update_rows(), 0, "update detection skipped, no partial record")
                    self.assertEqual(main.valve_counters["upstream_503"], 0)

    def test_extraction_failure_still_maps_when_update_calls_work(self):
        routes = {"extract": timeout_error(), "stage1": STAGE1, "stage2": STAGE2}
        with patch.object(llm, "_get_client", return_value=RoutedChat(routes)), patch.object(config, "LLM_API_KEY", "x"), \
                patch.object(config, "UPDATE_DETECT", True), patch.object(config, "EXTRACT_REQUIRED", True), \
                patch.object(config, "RECALL_QUERY_ENABLED", False):
            (failed,) = self.run_requests((0, "/add", add_body("ue1", text=GYM_NEW)))
        self.assertEqual(failed.status_code, 503)
        self.assertEqual(failed.headers.get("retry-after"), "4")
        self.assertEqual(self.rows("ue1"), (0, False))
        self.assertEqual(self.update_rows(), 0, "a failed Add stores no update record")
        routes["extract"] = {"facts": ["I go to the gym at 6 pm."]}
        with patch.object(llm, "_get_client", return_value=RoutedChat(routes)), patch.object(config, "LLM_API_KEY", "x"), \
                patch.object(config, "UPDATE_DETECT", True), patch.object(config, "EXTRACT_REQUIRED", True), \
                patch.object(config, "RECALL_QUERY_ENABLED", False):
            (retry,) = self.run_requests((0, "/add", add_body("ue1", text=GYM_NEW)))
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(self.update_rows(), 1, "the retry is a clean first attempt and detects the update")

    def test_search_router_and_verifier_failures_withhold_nothing_and_never_500(self):
        working = {"extract": {"facts": []}, "stage1": STAGE1, "stage2": STAGE2,
                   "router": {"needs_past_value": False, "time_scoped": False}, "verifier": VERIFIED}
        with self.with_chat(RoutedChat(working)):
            for request_id, text, ts in (("sr1", GYM_OLD, 1_700_000_000_000), ("sr2", GYM_NEW, 1_700_100_000_000)):
                (added,) = self.run_requests((0, "/add", add_body(request_id, text=text, ts=ts)))
                self.assertEqual(added.status_code, 200)
        self.assertEqual(self.update_rows(), 1)
        query = {"user_id": "u1", "top_k": 10}

        def search(text, routes):
            updates._resolved.clear()
            updates._scope_cache.clear()
            with self.with_chat(RoutedChat(routes)):
                (response,) = self.run_requests((0, "/search", {**query, "query": text}))
            self.assertEqual(response.status_code, 200)
            return " ".join(d["content"] for d in response.json()["data"])

        # Order matters: a verifier verdict is persisted once given, so the
        # failing verifier cases run before any search that gets a verdict.
        for failing in ("verifier", "router"):
            for error in (timeout_error(), status_error(openai.InternalServerError, 502)):
                with self.subTest(failing=failing, error=type(error).__name__):
                    text = search("When do I go to the gym?", {**working, failing: error})
                    self.assertIn("7 pm", text, "a failed call withholds nothing")
                    self.assertIn("6 pm", text)
        text = search("What time do I go to the gym?", working)
        self.assertNotIn("7 pm", text, "control: with both calls working the replaced turn is withheld")
        self.assertIn("6 pm", text)


if __name__ == "__main__":
    unittest.main()
