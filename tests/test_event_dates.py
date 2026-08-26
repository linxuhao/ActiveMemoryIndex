"""Guard on dating a memory by its event rather than by when it was said.

The previous attempt numbered memories by their own timestamp. A user who
recounts two events in one sitting gives every memory the same number, and the
answer model believed that number over the dates written in the prose — three
ordering questions it had answered correctly went wrong. These checks pin the
distinction that fixes: two memories said on the same day, describing events a
month apart, must come out with different day numbers.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config, llm, main, store  # noqa: E402


def check(condition, label):
    print(("  PASS  " if condition else "  FAIL  ") + label)
    return condition


def memory(ident, stamp, text):
    return store.Item(id=ident, kind="raw", parent_id=None,
                      content=f"[{stamp}] {text}", created_at=None)


ok = True
# All said on 2023-05-09 — the case that broke the timestamp version.
items = [
    memory("a", "2023-05-09 08:01", "I: my mentor Rachel, who I met on April 10th"),
    memory("b", "2023-05-09 12:13", "I: after attending the pride parade"),
    memory("c", "2023-05-09 15:00", "I: I prefer window seats"),
    store.Item(id="d", kind="fact", parent_id=None, content="likes jazz", created_at=None),
]

saved_batch, saved_call = config.EVENT_BATCH, llm.event_dates
config.EVENT_BATCH = 20
seen_batches = []


def fake_event_dates(batch):
    seen_batches.append(batch)
    return {0: "2023-04-10", 1: "2023-05-01"}      # c is declined, as null


llm.event_dates = fake_event_dates
out = main.event_indexed(items)
llm.event_dates = saved_call
config.EVENT_BATCH = saved_batch


def day_of(ident):
    return int(out[ident].split("day ")[1].split("]")[0])


ok &= check(set(out) == {"a", "b"},
            "only the memories the reader could date are re-rendered")
ok &= check(day_of("b") - day_of("a") == 21,
            "two memories said the same day, 21 days apart in fact, are 21 apart")
ok &= check(day_of("a") == 1, "the earliest event is day 1, not the earliest utterance")
ok &= check(out["a"] == "[said 2023-05-09 08:01 · happened 2023-04-10 · day 1] "
                        "I: my mentor Rachel, who I met on April 10th",
            "the utterance time is kept beside the event date, and the text is untouched")
ok &= check("c" not in out and "d" not in out,
            "an undated memory and an unstamped fact are left exactly as they were")
ok &= check(seen_batches and seen_batches[0][0] == ("2023-05-09", "I: my mentor Rachel, who I met on April 10th"),
            "the reader is given the said-date alongside the text, not the text alone")

# A reader that returns nothing usable must leave everything alone.
llm.event_dates = lambda batch: {}
ok &= check(main.event_indexed(items) == {},
            "no dates back is the same as the feature being off")
llm.event_dates = lambda batch: {0: "not-a-date", 1: "2023-13-45"}
ok &= check(main.event_indexed(items) == {},
            "a malformed date is dropped rather than rendered")
llm.event_dates = saved_call

print("\nOK" if ok else "\nFAILED")
sys.exit(0 if ok else 1)
