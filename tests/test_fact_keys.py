"""AMI_FACT_KEYS: the extractor's canonical key is parsed, stored, indexed and
used by AMI_SUPERSEDE_MARK to attach the latest same-key successor to an older
fact. Unkeyed facts, different keys and raw turns are never marked. Run
directly: python tests/test_fact_keys.py
"""
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np
from app import config, llm, main, store

ok = True
def check(cond, label):
    global ok
    print(("  PASS  " if cond else "  FAIL  ") + label); ok &= bool(cond)

# --- parsing
parsed = llm._parse_keyed('{"facts": [{"text": "[2023-01-05] I lead a team of 4 engineers.", "key": "Me.Team Size"},'
                          ' {"text": "I asked for a recipe.", "key": null}, "bare string fact",'
                          ' {"text": "", "key": "me.x"}, {"text": "I have 37 coins.", "key": "None"}]}')
check(parsed[0] == ("[2023-01-05] I lead a team of 4 engineers.", "me.team_size"), "key is normalised to lower snake_case")
check(parsed[1] == ("I asked for a recipe.", None), "null key stays None")
check(parsed[2] == ("bare string fact", None), "a bare string entry is a fact with no key")
check(len(parsed) == 4 and parsed[3] == ("I have 37 coins.", None), "empty text dropped; a key spelling None is no key")
check(llm._parse_keyed('{"facts": ["old format", "still works"]}') == [("old format", None), ("still works", None)],
      "the old string-list format parses with no keys")
check(llm.normalise_key("rachel.location") == "rachel.location" and llm.normalise_key("  ") is None
      and llm.normalise_key(12) is None and llm.normalise_key("123") is None, "normalise_key edge cases")

stray = llm._parse_keyed('{"facts":[{"text":"[2023-07-11] I am planning a trip.","key":null},'
                         '{"text":"[2023-07-11] I need 125 stars.","key":"me.starbucks_gold_stars"}}]}')
check(stray == [("[2023-07-11] I am planning a trip.", None), ("[2023-07-11] I need 125 stars.", "me.starbucks_gold_stars")],
      "a stray closing brace does not lose the chunk's facts")
mixed = llm._parse_keyed('{"facts":[{"text":"[2023-06-05] I arrived in NYC."},{"text":"per_scholas.cost":"free"},'
                         '{"text":"[2023-06-05] I am looking for a job."}]}')
check(mixed == [("[2023-06-05] I arrived in NYC.", None), ("[2023-06-05] I am looking for a job.", None)],
      "malformed objects are dropped, well-formed ones kept, missing key is None")
check(llm._parse_keyed("I cannot help with that.") == [], "prose still parses to nothing")

# --- store round trip and index
def fact(n, text, stamp, key):
    return store.Item(id=f"{'a'*16}-f{n}", kind="fact", parent_id=None, content=text, created_at=stamp, fact_key=key)
items = [
    fact(0, "[2023-01-05] I lead a team of 4 engineers.", "2023-01-05T10:00:00Z", "me.team_size"),
    fact(1, "[2023-03-01] I now lead 5 engineers.", "2023-03-01T10:00:00Z", "me.team_size"),
    fact(2, "[2023-06-01] We hired one more, six engineers now.", "2023-06-01T10:00:00Z", "me.team_size"),
    fact(3, "[2023-02-01] Rachel moved to Chicago.", "2023-02-01T10:00:00Z", "rachel.location"),
    fact(4, "[2023-04-01] I asked about pasta.", "2023-04-01T10:00:00Z", None),
    store.Item(id="a"*16 + "-r0", kind="raw", parent_id=None, content="[2023-01-05] I: 4 engineers.",
               created_at="2023-01-05T10:00:00Z", fact_key="me.team_size"),
]
vecs = np.eye(len(items), 4 if len(items) < 4 else len(items), dtype=np.float32)
with tempfile.TemporaryDirectory() as directory:
    saved_db = config.DB_PATH
    config.DB_PATH = os.path.join(directory, "t.sqlite3")
    store._conn = None; store._cache.clear()
    store.init()
    store.add("u", "s", "req", items, vecs)
    store._cache.clear()
    index = store.get("u")
    config.DB_PATH = saved_db
check([index.items[r].id[-2:] for r in index.by_key["me.team_size"]] == ["f0", "f1", "f2"],
      "keys survive SQLite and by_key indexes the facts, raw excluded")
check("rachel.location" in index.by_key and None not in index.by_key, "one entry per key; unkeyed facts not indexed")
check(index.items[4].fact_key is None, "an unkeyed fact reloads with no key")

# --- linking
saved = (config.FACT_KEYS, config.SUPERSEDE_MARK)
config.FACT_KEYS = True; config.SUPERSEDE_MARK = True
marks = main.superseded(index, index.items)
config.FACT_KEYS, config.SUPERSEDE_MARK = saved
ids = [it.id for it in index.items]
check(marks.get(ids[0], "").startswith("[superseded on 2023-06-01 by: [2023-06-01] We hired one more"),
      "the oldest same-key fact is marked with the LATEST successor")
check(marks.get(ids[0], "").endswith("] [2023-01-05] I lead a team of 4 engineers."), "its own text follows")
check(ids[1] in marks and "2023-06-01" in marks[ids[1]], "the middle version is marked with the last")
check(ids[2] not in marks, "the newest version is never marked")
check(ids[3] not in marks, "a different key with no later fact is not marked")
check(ids[4] not in marks, "an unkeyed fact is never marked")
check(ids[5] not in marks, "a raw turn is never marked, even with a key")
check(index.items[0].content == "[2023-01-05] I lead a team of 4 engineers.", "stored text untouched")

print("\nOK" if ok else "\nFAILED"); sys.exit(0 if ok else 1)
