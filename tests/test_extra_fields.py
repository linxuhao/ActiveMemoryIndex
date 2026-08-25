"""Guard on reporting request fields the contract does not name.

pydantic drops unknown fields silently. A caller could have been sending a
question timestamp on every search since the first evaluation and nothing in
this service would ever have said so — while 42 of the 133 temporal questions
measured in bench/results/lme_temporal_baseline.md are unanswerable without
one. These checks pin that the names are reported, that values never are, and
that a long run is not flooded with the same line.
"""
import io
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import main  # noqa: E402


def check(condition, label):
    print(("  PASS  " if condition else "  FAIL  ") + label)
    return condition


ok = True
stream = io.StringIO()
handler = logging.StreamHandler(stream)
main.log.addHandler(handler)
main._reported_extra.clear()

plain = main.SearchRequest(query="q", user_id="u", top_k=10)
main.note_extra("search", plain)
ok &= check(stream.getvalue() == "", "a request with no extra fields logs nothing")

odd = main.SearchRequest.model_validate({
    "query": "q", "user_id": "u", "top_k": 10,
    "question_date": "2023/04/01 (Sat) 08:09", "trace_id": "abc-123",
})
main.note_extra("search", odd)
first = stream.getvalue()
ok &= check("question_date" in first and "trace_id" in first,
            "undocumented field names are reported")
ok &= check("2023/04/01" not in first and "abc-123" not in first,
            "their values are NOT reported — the payload is somebody's memories")

main.note_extra("search", odd)
ok &= check(stream.getvalue() == first,
            "the same set of names is reported once, not on every request")

main.note_extra("add", odd)
ok &= check(len(stream.getvalue()) > len(first),
            "the same names on a different endpoint are still worth reporting")

# The retained fields must not disturb what the contract does name.
ok &= check((odd.query, odd.user_id, odd.top_k) == ("q", "u", 10),
            "allowing extras does not change the documented fields")
ok &= check(odd.model_extra.get("question_date") == "2023/04/01 (Sat) 08:09",
            "and the value is kept, so it can be used once the contract confirms it")

main.log.removeHandler(handler)
print("\nOK" if ok else "\nFAILED")
sys.exit(0 if ok else 1)
