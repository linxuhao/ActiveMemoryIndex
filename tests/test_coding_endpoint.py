"""Guard on the coding-track routes (/coding/add, /coding/search).

They share the store with the textual routes, but under a namespaced user_id,
so the two tracks never see each other's data, and they make no LLM call of
any kind. The textual routes keep calling the LLM exactly as before.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app import config, llm, main  # noqa: E402


def check(condition, label):
    print(("  PASS  " if condition else "  FAIL  ") + label)
    return condition


calls = []


class _Reply:
    def __init__(self, text):
        self.choices = [type("C", (), {"message": type("M", (), {"content": text})()})()]


def fake_create(**kwargs):
    calls.append(kwargs["messages"][-1]["content"][:40])
    return _Reply("- I fixed the parser bug in tokenize.py")


ok = True
config.AUTH_SCHEME = "none"
config.LLM_API_KEY = "test-key"
llm._create = fake_create
client = TestClient(main.app)
client.__enter__()  # runs startup: opens the store


def add(path, user, request_id, text):
    return client.post(path, json={"request_id": request_id, "user_id": user, "session_id": "s1",
                                   "messages": [{"role": "user", "content": text}]})


r = add("/coding/add", "u1", "c1", "Traceback in tokenize.py: IndexError on empty input; fixed by guarding len(tokens).")
ok &= check(r.status_code == 200, "coding add returns 200")
ok &= check(r.json()["user_id"] == "u1", "coding add echoes the caller's own user_id")
ok &= check(calls == [], "coding add makes no LLM call")

r = client.post("/coding/search", json={"query": "IndexError in tokenize", "user_id": "u1", "top_k": 10})
ok &= check(r.status_code == 200 and len(r.json()["data"]) > 0, "coding search finds the coding memory")
ok &= check(any("tokenize.py" in d["content"] for d in r.json()["data"]), "coding search returns the verbatim turn")
ok &= check(calls == [], "coding search makes no LLM call")

r = client.post("/search", json={"query": "IndexError in tokenize", "user_id": "u1", "top_k": 10})
ok &= check(r.status_code == 200 and r.json()["data"] == [], "textual search cannot see coding data")
calls.clear()

r = add("/add", "u1", "t1", "I adopted a cat named Miso last spring.")
ok &= check(r.status_code == 200, "textual add returns 200")
ok &= check(len(calls) >= 1, "textual add still calls the LLM (extraction unchanged)")
ok &= check(config.llm_available(), "the switch does not leak out of a coding request")

r = client.post("/coding/search", json={"query": "cat named Miso", "user_id": "u1", "top_k": 10})
ok &= check(r.status_code == 200 and not any("Miso" in d["content"] for d in r.json()["data"]),
            "coding search cannot see textual data")

r = add("/coding/add", "u1", "c1", "Traceback in tokenize.py: IndexError on empty input; fixed by guarding len(tokens).")
ok &= check(r.status_code == 200, "a repeated coding request_id is accepted (idempotent)")

for path in ("/coding/add", "/coding/search"):
    ok &= check(client.head(path).status_code == 405, f"HEAD {path} is 405 like the textual routes")

sys.exit(0 if ok else 1)
