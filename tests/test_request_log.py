"""Guard on the diagnostic request log (AMI_REQUEST_LOG).

Off by default; when on, every /search line carries the query, options,
undocumented fields and returned ids, so a Smoke can be read per question and
we can see whether the caller sends the question's own time anywhere. A broken
log path must never fail a request.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config, main  # noqa: E402


def check(condition, label):
    print(("  PASS  " if condition else "  FAIL  ") + label)
    return condition


ok = True
config.AUTH_SCHEME = "none"
canned = {"data": [{"id": "a-r0", "content": "hello"}, {"id": "a-f0", "content": "fact"}]}
main._search = lambda request: canned

request = main.SearchRequest.model_validate({
    "query": "Today is 2024/03/01. What did I adopt?", "user_id": "u", "top_k": 100,
    "options": ["(A) dog", "(B) cat"], "question_date": "2024/03/01",
})

config.REQUEST_LOG = ""
ok &= check(main.search(request) == canned, "off by default: result unchanged")

path = Path(tempfile.mkdtemp()) / "requests.jsonl"
config.REQUEST_LOG = str(path)
ok &= check(main.search(request) == canned, "on: result unchanged")
line = json.loads(path.read_text().splitlines()[-1])
ok &= check(line["kind"] == "search" and line["query"].startswith("Today is"), "query is recorded")
ok &= check(line["options"] == ["(A) dog", "(B) cat"], "options are recorded")
ok &= check(line["extra"] == {"question_date": "2024/03/01"}, "undocumented fields and values are recorded")
ok &= check("2024/03/01" in line["time_hints"] and "Today" in line["time_hints"], "time hints are detected")
ok &= check(line["ids"] == ["a-r0", "a-f0"] and line["returned"] == 2 and line["chars"] == 9,
            "returned ids, count and size are recorded")

config.REQUEST_LOG = str(Path(tempfile.mkdtemp()) / "missing-dir" / "x.jsonl")
ok &= check(main.search(request) == canned, "an unwritable log path does not fail the request")

sys.exit(0 if ok else 1)
