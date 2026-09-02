"""Guard on dating memories at Add, from the extraction call, and rendering them
from the store at Search.

The search-time arm dated a memory on every search that returned it, with five
extra calls per search. Here the same reading happens once, inside the
extraction call every chunk already pays for. These checks pin: the dated
payload parses and a malformed date is dropped; a store built before the column
existed gains it; the date lands on the right turn and the right fact and
survives a reload from SQLite; and with EVENT_DATES_STORED the rendering at
Search needs no LLM at all.
"""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import numpy as np

DB = Path(tempfile.mkdtemp()) / "test.sqlite3"
os.environ["AMI_DB_PATH"] = str(DB)
os.environ["AMI_AUTH_SCHEME"] = "none"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config, embed, llm, main, store  # noqa: E402


def check(condition, label):
    print(("  PASS  " if condition else "  FAIL  ") + label)
    return condition


ok = True

# --- the payload -------------------------------------------------------------
facts, turns = llm._parse_dated('''{"facts": [
    {"text": "[2023-05-09] I met my mentor Rachel on April 10th", "happened": "2023-04-10"},
    {"text": "[2023-05-09] I prefer window seats", "happened": null},
    "a bare string is still a fact",
    {"text": "[2023-05-09] bad date", "happened": "April 10"}],
  "turns": {"0": "2023-04-10", "1": null, "2": "2023-13-45", "x": "2023-01-01"}}''')
ok &= check([f[0][:14] for f in facts] == ["[2023-05-09] I", "[2023-05-09] I", "a bare string ", "[2023-05-09] b"],
            "every fact parses, with or without a date")
ok &= check([f[1] for f in facts] == ["2023-04-10", None, None, None],
            "a fact's date is kept when well-formed and dropped when not")
ok &= check(turns == {0: "2023-04-10"}, "turn dates: null, malformed and non-numeric keys are all dropped")
ok &= check(llm._parse_dated("no json here") == ([], {}), "prose is not a payload")

# --- migration ---------------------------------------------------------------
old = sqlite3.connect(DB)
old.executescript("""CREATE TABLE items (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, session_id TEXT,
    request_id TEXT, kind TEXT NOT NULL, parent_id TEXT, content TEXT NOT NULL, created_at TEXT,
    seq INTEGER, vec BLOB NOT NULL);
    CREATE TABLE requests (request_id TEXT NOT NULL, user_id TEXT NOT NULL, PRIMARY KEY (request_id, user_id));""")
old.execute("INSERT INTO items VALUES ('legacy-r0','u0',NULL,'r','raw',NULL,'[2023-01-01 00:00] I: hi','2023-01-01T00:00:00Z',0,?)",
            (np.zeros(4, dtype=np.float32).tobytes(),))
old.commit(); old.close()
store.init()
columns = {row[1] for row in store._conn.execute("PRAGMA table_info(items)")}
ok &= check("event_date" in columns, "a store built before the column existed gains it on init")
ok &= check(store.get("u0").items[0].event_date is None, "and its old rows read back undated")

# --- the Add path --------------------------------------------------------------
CANNED = '''{"facts": [{"text": "I met my mentor Rachel on April 10th", "happened": "2023-04-10"},
                       {"text": "I prefer window seats", "happened": null},
                       {"text": "[2023-05-09] I said Rachel is my mentor", "happened": "2023-04-10"}],
            "turns": {"0": "2023-04-10", "1": null}}'''
seen_prompts = []


def fake_complete(system, user, max_tokens):
    seen_prompts.append((system, user))
    return CANNED


saved = (llm._complete, embed.encode, config.EVENT_DATES_AT_ADD, config.LLM_API_KEY, config.AUTH_SCHEME)
llm._complete = fake_complete
embed.encode = lambda texts, is_query=False: np.zeros((len(texts), 4), dtype=np.float32)
config.EVENT_DATES_AT_ADD = True
config.LLM_API_KEY = "test"
config.AUTH_SCHEME = "none"
try:
    request = main.AddRequest(request_id="req-1", user_id="u1", session_id="s1", messages=[
        main.Message(role="user", content="my mentor Rachel, who I met on April 10th", timestamp=1683619260000),
        main.Message(role="user", content="I prefer window seats", timestamp=1683619320000),
    ])
    main.add(request)
    items = store.get("u1").items
    ok &= check(len(seen_prompts) == 1, "one LLM call for the chunk, not one per memory")
    ok &= check("0 | [2023-05-09" in seen_prompts[0][1] and "\n1 | [2023-05-09" in seen_prompts[0][1],
                "the turns go to the model numbered, with the date they were said")
    ok &= check([i.kind for i in items] == ["raw", "raw", "fact", "fact", "fact"], "two turns and three facts stored")
    ok &= check([i.event_date for i in items] == ["2023-04-10", None, "2023-04-10", None, "2023-04-10"],
                "the date lands on the right turn and the right facts; the undated stay None")
    store._cache.clear(); store._cached_items = 0
    reloaded = store.get("u1").items
    ok &= check([i.event_date for i in reloaded] == ["2023-04-10", None, "2023-04-10", None, "2023-04-10"],
                "the dates survive a reload from SQLite")

    # --- rendering from the store, no LLM ---------------------------------------
    llm.event_dates = lambda batch: (_ for _ in ()).throw(AssertionError("LLM called"))
    config.EVENT_DATES, config.EVENT_DATES_STORED = False, True
    out = main.event_indexed(reloaded)
    ok &= check(set(out) == {reloaded[0].id, reloaded[2].id}, "only the stored-dated memories are re-rendered")
    # A fact the extractor stamped itself carries "[YYYY-MM-DD]" without a time,
    # which the render regex does not match — the measured search-time arm left
    # those alone too, and parity with it is the point of this arm.
    ok &= check(reloaded[4].id not in out, "a fact stamped [date] by the extractor is left as it was, as before")
    ok &= check(out[reloaded[0].id].startswith("[said 2023-05-09 08:01 · happened 2023-04-10 · day 1] "),
                "rendered exactly as the search-time arm rendered, without a call")
    config.EVENT_DATES_STORED = False
    ok &= check(main.event_indexed(reloaded) == {}, "with both switches off nothing is touched")
finally:
    llm._complete, embed.encode, config.EVENT_DATES_AT_ADD, config.LLM_API_KEY, config.AUTH_SCHEME = saved
    config.EVENT_DATES, config.EVENT_DATES_STORED = False, False

print("\nOK" if ok else "\nFAILED")
sys.exit(0 if ok else 1)
