"""Explicit updates, round 5b (AMI_UPDATE_VERSION=6): stage 2's subject_is_user
is kept beside the subject text (round 5 replaced the subject with "me" and
the verifier then rejected the true old values of third-party updates), the
column is added to older stores, and the revised router prompt is used.
LLM and embedder replaced; no network. Run: python tests/test_updates_v6.py
"""
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np  # noqa: E402

from app import config, llm, store, updates  # noqa: E402

config.UPDATE_VERSION = 6  # round 5b; version 7 checks at the end
ok = True


def check(cond, label):
    global ok
    print(("  PASS  " if cond else "  FAIL  ") + label)
    ok &= bool(cond)


def raw(digest, n, text, speaker="I"):
    return store.Item(id=f"{digest}-r{n}", kind="raw", parent_id=None, content=f"{speaker}: {text}", created_at=None)


turn = raw("u" * 16, 0, "Please replace what I told you before: association football's country of origin is now Hong Kong.")
entry = {"turn": 0, "subject": "association football", "attribute": "country of origin", "new_value": "Hong Kong",
         "subject_is_user": True, "relative": False}
rec = updates.parse_updates([entry], [turn])[0]
check(rec["subject"] == "association football" and rec["subject_is_user"] is True,
      "version 6 keeps the subject text and records subject_is_user beside it")
config.UPDATE_VERSION = 5
check(updates.parse_updates([entry], [turn])[0]["subject"] == "me", "version 5 (as registered) replaced it with 'me'")
config.UPDATE_VERSION = 6

old = raw("o" * 16, 0, "association football's country of origin is England.")
other = raw("o" * 16, 1, "Noted: association football's country of origin is England.", speaker="Assistant")
index = store.UserIndex()
index.append([old, other, turn], np.eye(3, dtype=np.float32))
rows = updates.candidates(index, rec)
check(rows == [0], "an own-flagged record only takes the user's turns as candidates")
seen = []
saved = llm.verify_replaced_v2
llm.verify_replaced_v2 = lambda update, memories: seen.append(update) or [(0, "England")]
with tempfile.TemporaryDirectory() as directory:
    path = os.path.join(directory, "old.sqlite3")
    legacy = sqlite3.connect(path)
    legacy.executescript(store.SCHEMA)
    legacy.execute("CREATE TABLE updates (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, request_id TEXT, item_id TEXT NOT NULL, "
                   "subject TEXT NOT NULL, attribute TEXT NOT NULL, new_value TEXT NOT NULL, old_value TEXT, "
                   "relative INTEGER NOT NULL, statement TEXT, created_at TEXT)")
    legacy.commit()
    legacy.close()
    saved_cfg = (config.DB_PATH, config.UPDATE_DETECT)
    config.DB_PATH, config.UPDATE_DETECT = path, True
    store._conn = None
    store._cache.clear()
    store.init()
    columns = {r[1] for r in store._conn.execute("PRAGMA table_info(updates)")}
    check("subject_is_user" in columns, "a store made before round 5b gets the column on start")
    store.add_updates("u", "r", [rec])
    back = store.get_updates("u")[0]
    check(back["subject_is_user"] == 1 and back["subject"] == "association football", "the flag round-trips through SQLite")
    found, _ = updates.resolve(index, "u", [back])
    check(found[rec["id"]] == {old.id} and "Subject: association football" in seen[0],
          "the verifier is told the real subject, and the true old value is withheld")
    store._conn = None
    config.DB_PATH, config.UPDATE_DETECT = saved_cfg
llm.verify_replaced_v2 = saved

prompts = []
saved_complete, saved_key = llm._complete, config.LLM_API_KEY
llm._complete = lambda system, user, max_tokens: prompts.append(system) or '{"needs_past_value": false, "time_scoped": false}'
config.LLM_API_KEY = "test-key"
llm.classify_question("会议原来在3号房间，现在在哪里？", None)
config.UPDATE_VERSION = 5
llm.classify_question("会议原来在3号房间，现在在哪里？", None)
check(prompts[0] is llm.QUESTION_SCOPE2_SYSTEM and prompts[1] is llm.QUESTION_SCOPE_SYSTEM,
      "version 6 uses the revised router prompt, version 5 the registered one")
llm._complete, config.LLM_API_KEY = saved_complete, saved_key
config.UPDATE_VERSION = 6



# --- version 7: the flag no longer waives the subject mention ------------------------
config.UPDATE_VERSION = 7
step = raw("s" * 16, 0, "Step 2 is no longer necessary, remember?")
unrelated = raw("q" * 16, 0, "I am not sure if I have the necessary qualifications.")
mentioned = raw("q" * 16, 1, "Step 2 is necessary for the setup.")
idx7 = store.UserIndex()
idx7.append([unrelated, mentioned, step], np.eye(3, dtype=np.float32))
flagged = {"id": "x", "item_id": step.id, "subject": "Step 2", "attribute": "necessity",
           "new_value": "no longer necessary", "old_value": None, "relative": False, "subject_is_user": True}
check(updates.candidates(idx7, flagged) == [1],
      "version 7: a wrongly flagged third-party subject must still be mentioned (the 'Step 2' false withhold)")
config.UPDATE_VERSION = 6
check(updates.candidates(idx7, flagged) == [0, 1] or updates.candidates(idx7, flagged) == [1, 0],
      "version 6 reproduces it: the flag waived the mention")
config.UPDATE_VERSION = 7
zh_turn = raw("z" * 16, 0, "更正：我的健身时间改成晚上6点了。")
zh_old = raw("y" * 16, 0, "我的健身时间是晚上7点。")
zh_asst = raw("y" * 16, 1, "好的，你的健身时间是晚上7点。", speaker="Assistant")
idx_zh = store.UserIndex()
idx_zh.append([zh_old, zh_asst, zh_turn], np.eye(3, dtype=np.float32))
zh_rec = {"id": "z", "item_id": zh_turn.id, "subject": "我", "attribute": "健身时间", "new_value": "晚上6点",
          "old_value": None, "relative": False, "subject_is_user": True}
check(updates.candidates(idx_zh, zh_rec) == [0],
      "version 7, Chinese self subject: user turns only, and '我' is mentioned in them")
me_rec = {**zh_rec, "subject": "me"}
check(updates.candidates(idx_zh, me_rec) == [0], "subject 'me' (stage 2's marker) waives the mention, user turns only")
print("\nOK" if ok else "\nFAILED")
sys.exit(0 if ok else 1)
