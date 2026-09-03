"""Guard on the dedicated dating call at Add.

The merged version — dates asked as part of the extraction call — dated as many
memories as the search-time reading but answered "it happened the day it was
said" 61% of the time against the dedicated call's 32%. This arm moves the
dedicated call to Add instead. These checks pin that it is the same call over
the chunk's own memories, that extraction keeps its original prompt, and that a
failure leaves the store exactly as the switch being off would.
"""
import os
import sys
import tempfile
from pathlib import Path

import numpy as np

os.environ["AMI_DB_PATH"] = str(Path(tempfile.mkdtemp()) / "test.sqlite3")
os.environ["AMI_AUTH_SCHEME"] = "none"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config, embed, llm, main, store  # noqa: E402


def check(condition, label):
    print(("  PASS  " if condition else "  FAIL  ") + label)
    return condition


ok = True
store.init()
seen_systems, seen_batches = [], []


def fake_complete(system, user, max_tokens):
    seen_systems.append(system)
    return '{"facts": ["I met my mentor Rachel on April 10th", "I prefer window seats"]}'


def fake_event_dates(batch):
    seen_batches.append(list(batch))
    return {0: "2023-04-10", 2: "2023-04-10"}      # turn 0 and fact 0; the rest declined


saved = (llm._complete, llm.event_dates, embed.encode, config.LLM_API_KEY,
         config.AUTH_SCHEME, config.EVENT_DATES_ADD_CALL, config.EVENT_DATES_AT_ADD)
llm._complete = fake_complete
llm.event_dates = fake_event_dates
embed.encode = lambda texts, is_query=False: np.zeros((len(texts), 4), dtype=np.float32)
config.LLM_API_KEY = "test"
config.AUTH_SCHEME = "none"
config.EVENT_DATES_ADD_CALL = True
config.EVENT_DATES_AT_ADD = False
try:
    main.add(main.AddRequest(request_id="r1", user_id="u1", session_id="s", messages=[
        main.Message(role="user", content="my mentor Rachel, who I met on April 10th", timestamp=1683619260000),
        main.Message(role="user", content="I prefer window seats", timestamp=1683619320000),
    ]))
    items = store.get("u1").items
    ok &= check(len(seen_systems) == 1 and seen_systems[0].startswith("You turn a chunk"),
                "extraction keeps its original prompt, one call")
    ok &= check("happened" not in seen_systems[0], "and is not asked for dates")
    ok &= check(len(seen_batches) == 1, "one dedicated dating call for the chunk")
    ok &= check(seen_batches[0] == [("2023-05-09", "I: my mentor Rachel, who I met on April 10th"),
                                    ("2023-05-09", "I: I prefer window seats"),
                                    ("2023-05-09", "I met my mentor Rachel on April 10th"),
                                    ("2023-05-09", "I prefer window seats")],
                "it sees the chunk's turns AND its facts, said-date beside each")
    ok &= check([i.kind for i in items] == ["raw", "raw", "fact", "fact"], "two turns and two facts stored")
    ok &= check([i.event_date for i in items] == ["2023-04-10", None, "2023-04-10", None],
                "the dates land on the memories the reader named, and only those")
    store._cache.clear(); store._cached_items = 0
    ok &= check([i.event_date for i in store.get("u1").items] == ["2023-04-10", None, "2023-04-10", None],
                "and survive a reload from SQLite")

    # A failed dating call must leave the write intact and undated.
    llm.event_dates = lambda batch: {}
    main.add(main.AddRequest(request_id="r2", user_id="u2", session_id="s", messages=[
        main.Message(role="user", content="I met Rachel on April 10th", timestamp=1683619260000)]))
    u2 = store.get("u2").items
    ok &= check(len(u2) == 3 and all(i.event_date is None for i in u2),
                "a dating failure still stores the memories, undated")

    # Off is off.
    config.EVENT_DATES_ADD_CALL = False
    called = []
    llm.event_dates = lambda batch: called.append(1) or {}
    main.add(main.AddRequest(request_id="r3", user_id="u3", session_id="s", messages=[
        main.Message(role="user", content="I met Rachel on April 10th", timestamp=1683619260000)]))
    ok &= check(not called, "with the switch off no dating call is made")
finally:
    (llm._complete, llm.event_dates, embed.encode, config.LLM_API_KEY,
     config.AUTH_SCHEME, config.EVENT_DATES_ADD_CALL, config.EVENT_DATES_AT_ADD) = saved

print("\nOK" if ok else "\nFAILED")
sys.exit(0 if ok else 1)
