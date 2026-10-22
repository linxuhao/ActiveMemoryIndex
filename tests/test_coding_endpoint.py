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

# Grouped return: a semantic block, then a grep block of matches it missed.
filler = ["Refactored the logging setup to use a rotating file handler.",
          "Bumped the CI matrix to include Python 3.12 and dropped 3.8.",
          "Renamed the settings module and updated imports across the package.",
          "Documented the release process in CONTRIBUTING.md.",
          "Cached the parsed configuration to avoid re-reading it per request.",
          "Fixed flaky network test by mocking the HTTP session.",
          "Moved fixtures into conftest.py and removed duplicates.",
          "Added type hints to the public API of the client module."]
for n, text in enumerate(filler):
    add("/coding/add", "u2", f"f{n}", text)
add("/coding/add", "u2", "target", "KeyError: 'zq_merge_cursor' raised in sync/merge_cursor.py when the cursor is reset.")
calls.clear()
r = client.post("/coding/search", json={"query": "zq_merge_cursor", "user_id": "u2", "top_k": 4})
data = r.json()["data"]
ok &= check(r.status_code == 200 and len(data) == 4, "grouped search returns top_k items")
ok &= check(len({d["id"] for d in data}) == len(data), "no item appears twice")
ok &= check([d["source"] for d in data][:3] == ["semantic"] * 3 and data[3]["source"] in ("grep", "semantic"),
            "semantic block first, then the grep block")
ok &= check(all(d["content"].startswith(d["source"] + ": ") for d in data), "each item is labelled with its group")
ok &= check(any("zq_merge_cursor" in d["content"] for d in data), "the exact identifier's item is returned")
ok &= check(calls == [], "grouped search makes no LLM call")
ok &= check(all("Miso" not in d["content"] for d in data), "grep block stays inside the coding user")

# AMI_CODING_PATHS: the platform's own /add and /search serve the coding routes.
config.CODING_PATHS = True
calls.clear()
r = add("/add", "u3", "p1", "Segfault in render/blit.c fixed by checking the surface pitch.")
ok &= check(r.status_code == 200 and r.json()["user_id"] == "u3", "switched /add returns 200 and echoes the user_id")
r = client.post("/search", json={"query": "render/blit.c", "user_id": "u3", "top_k": 5})
data = r.json()["data"]
ok &= check(r.status_code == 200 and data and all(d["source"] in ("semantic", "grep") for d in data),
            "switched /search returns the labelled groups")
ok &= check(calls == [], "switched routes make no LLM call")
r = client.post("/coding/search", json={"query": "render/blit.c", "user_id": "u3", "top_k": 5})
ok &= check(any("blit.c" in d["content"] for d in r.json()["data"]), "switched /add stored under the coding namespace")
ok &= check(client.head("/add").status_code == 405, "HEAD /add is still 405 when switched")
config.CODING_PATHS = False
r = client.post("/search", json={"query": "render/blit.c", "user_id": "u3", "top_k": 5})
ok &= check(r.json()["data"] == [], "switch off: /search is the textual route again")

for path in ("/coding/add", "/coding/search"):
    ok &= check(client.head(path).status_code == 405, f"HEAD {path} is 405 like the textual routes")

sys.exit(0 if ok else 1)
