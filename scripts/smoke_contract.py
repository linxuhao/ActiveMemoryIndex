"""Contract smoke test: run it against a live server before submitting.

    python scripts/smoke_contract.py http://127.0.0.1:8000

Checks every hard requirement of the Add / Search contract: synchronous
persistence, exact ID echo, response shape, top_k bound, and user isolation.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")

# Auth: read from the same env vars the service uses so we can smoke-test
# a protected deployment without dropping auth to "none".
_AUTH_SCHEME = os.environ.get("AMI_AUTH_SCHEME", "none").lower()
_AUTH_TOKEN = os.environ.get("AMI_AUTH_TOKEN", "")
_AUTH_HEADER: dict[str, str] = {}
if _AUTH_SCHEME == "bearer":
    _AUTH_HEADER["Authorization"] = f"Bearer {_AUTH_TOKEN}"
elif _AUTH_SCHEME == "token":
    _AUTH_HEADER["Authorization"] = f"Token {_AUTH_TOKEN}"
elif _AUTH_SCHEME == "x-api-key":
    _AUTH_HEADER["X-API-Key"] = _AUTH_TOKEN
USER = "smoke:user-0"
OTHER = "smoke:user-1"
SESSION = "smoke:session-0"

SESSIONS = [
    (
        "smoke:req-0",
        [
            ("user", 1684540800000, "I adopted a beagle puppy named Ollie last Saturday from the shelter in Malmo."),
            ("assistant", 1684540860000, "Congratulations! How is Ollie settling in?"),
            ("user", 1684540920000, "He chewed my running shoes, so I bought new Asics on Tuesday."),
        ],
    ),
    (
        "smoke:req-1",
        [
            ("user", 1687219200000, "My sister Mei is getting married in Kyoto in October and I am the photographer."),
            ("assistant", 1687219260000, "That sounds like a big responsibility."),
            ("user", 1687219320000, "I am saving for a 35mm lens; my budget is about 900 euros."),
        ],
    ),
]

QUERIES = [
    ("What is the name of the dog?", "Ollie"),
    ("Where is the wedding taking place?", "Kyoto"),
    ("How much does the user plan to spend on a lens?", "900"),
]

failures: list[str] = []


def check(condition: bool, label: str) -> None:
    print(("  PASS  " if condition else "  FAIL  ") + label)
    if not condition:
        failures.append(label)


def call(path: str, payload: dict | None = None) -> tuple[int, dict]:
    url = f"{BASE}{path}"
    headers = {"User-Agent": "AMI-SmokeTest/1.0", **_AUTH_HEADER}
    if payload is None:
        request = urllib.request.Request(url, method="GET", headers=headers)
    else:
        headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        return error.code, {"error": error.read().decode("utf-8", "replace")}


print(f"target {BASE}")
status, body = call("/health")
check(200 <= status < 300, f"GET /health returns 2xx (got {status})")

for request_id, messages in SESSIONS:
    payload = {
        "request_id": request_id,
        "messages": [{"role": r, "timestamp": t, "content": c} for r, t, c in messages],
        "user_id": USER,
        "session_id": SESSION,
    }
    status, body = call("/add", payload)
    check(status == 200, f"POST /add {request_id} returns 200 (got {status})")
    check(body.get("success") is True, f"{request_id}: success is boolean true")
    check(body.get("request_id") == request_id, f"{request_id}: request_id echoed exactly")
    check(body.get("user_id") == USER, f"{request_id}: user_id echoed exactly")
    check(body.get("session_id") == SESSION, f"{request_id}: session_id echoed exactly")
    check("memory_ids" not in body, f"{request_id}: no memory_ids in response")

status, body = call("/add", {
    "request_id": SESSIONS[0][0],
    "messages": [{"role": r, "timestamp": t, "content": c} for r, t, c in SESSIONS[0][1]],
    "user_id": USER,
    "session_id": SESSION,
})
check(status == 200 and body.get("success") is True, "re-sending the same request_id is idempotent and still 200")

for query, needle in QUERIES:
    status, body = call("/search", {"query": query, "user_id": USER, "top_k": 100})
    data = body.get("data")
    check(status == 200, f"POST /search returns 200 for {query!r} (got {status})")
    check(isinstance(data, list), "response has a top-level data array")
    if not isinstance(data, list):
        continue
    check(len(data) <= 100, "result count does not exceed top_k")
    check(all(isinstance(d.get("id"), str) and d["id"] for d in data), "every item has a non-empty string id")
    check(all(isinstance(d.get("content"), str) and d["content"] for d in data), "every item has non-empty content")
    check(len({d["id"] for d in data}) == len(data), "item ids are unique")
    joined = " ".join(d["content"] for d in data)
    check(needle.lower() in joined.lower(), f"retrieval finds {needle!r} for {query!r} (searchable right after add)")

status, body = call("/search", {"query": "What is the name of the dog?", "user_id": OTHER, "top_k": 10})
check(status == 200 and body.get("data") == [], "an unknown user_id returns an empty data array (isolation)")

status, body = call("/search", {"query": "anything", "user_id": USER, "top_k": 3})
check(len(body.get("data", [])) <= 3, "small top_k is respected")

status, body = call("/add", {"request_id": "bad", "messages": [], "user_id": USER, "session_id": SESSION})
check(status == 422, f"malformed add (empty messages) is rejected with 422 (got {status})")

print()
if failures:
    print(f"{len(failures)} FAILED:")
    for item in failures:
        print(f"  - {item}")
    sys.exit(1)
print("all contract checks passed")
