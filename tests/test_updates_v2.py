"""Explicit updates, round 2 (AMI_UPDATE_VERSION=2): stage-1 acceptance
(labels, verbatim quotes, user turns, any language), stage 2 only after an
accepted statement, user-only candidates for the user's own attributes, the
REPLACED/SAME verifier, and byte-identical /search with the switches off.
LLM and embedder are replaced; no network. Run: python tests/test_updates_v2.py
"""
import hashlib
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np  # noqa: E402

from app import config, embed, llm, main, store, updates  # noqa: E402

config.UPDATE_VERSION = 2
ok = True


def check(cond, label):
    global ok
    print(("  PASS  " if cond else "  FAIL  ") + label)
    ok &= bool(cond)


def raw(n, text, speaker="I", digest="a" * 16):
    return store.Item(id=f"{digest}-r{n}", kind="raw", parent_id=None, content=f"{speaker}: {text}", created_at=None)


# --- stage-1 acceptance -------------------------------------------------------
turns = [raw(0, "Hi there."), raw(1, "Sorry, I misspoke —  the dog's name is   Biscuit, not Bandit."),
         raw(2, "Your gym time is 7 pm.", speaker="Assistant"), raw(3, "把会议时间改成下午三点。"),
         raw(4, "I now lead a team of five.")]
statements = [
    {"turn": 1, "label": "CORRECTION", "quote": "the dog's name is Biscuit, not Bandit"},       # spaces differ: kept
    {"turn": 1, "label": "correction", "quote": "the dog's name is Biscuit, not Bandit"},       # duplicate: once
    {"turn": 1, "label": "EXPLICIT_REPLACEMENT", "quote": "把会议时间改成下午三点"},                  # Chinese, wrong turn: found in 3
    {"turn": 2, "label": "CORRECTION", "quote": "Your gym time is 7 pm."},                       # not the user
    {"turn": 4, "label": "NEW_INFO", "quote": "I now lead a team of five."},                     # wrong label
    {"turn": 4, "label": "EXPLICIT_REPLACEMENT", "quote": "I now lead a team of six."},          # not verbatim
    {"turn": 1, "label": "CORRECTION", "quote": "the Dog's name is Biscuit"},                    # case differs
    {"turn": 9, "label": "CORRECTION", "quote": "x"}, {"turn": "a", "label": "CORRECTION", "quote": "Hello"},
    {"turn": 0, "label": "CORRECTION", "quote": "   "},
    {"turn": 0, "label": "CORRECTION", "quote": "...the dog's name is Biscuit"},                 # added mark
    {"turn": 0, "label": "CORRECTION", "quote": "Your gym time is 7 pm."},                       # assistant only
]
kept = updates.accept_statements(statements, turns)
check(kept == [(1, "the dog's name is Biscuit, not Bandit"), (3, "把会议时间改成下午三点")],
      "only replacement/correction labels with quotes found verbatim (whitespace-normalised only) in a user turn are kept")

# --- stage 2 runs only after an accepted statement ---------------------------
calls = {"stage1": 0, "stage2": 0}


def stage1(numbered):
    calls["stage1"] += 1
    return statements if "Biscuit" in numbered else [{"turn": 0, "label": "NEW_INFO", "quote": "Hi there."}]


def stage2(numbered, accepted):
    calls["stage2"] += 1
    return [{"statement": 0, "subject": "my dog", "attribute": "name", "new_value": "Biscuit", "old_value": "Bandit",
             "relative": False, "current": "My dog's name is Biscuit."},
            {"statement": "S1", "subject": "会议", "attribute": "时间", "new_value": "下午三点", "old_value": None,
             "relative": False, "current": "会议时间是下午三点。"},
            {"statement": 7, "subject": "x", "attribute": "y", "new_value": "z"}]


saved_llm = (llm.classify_update_intent, llm.extract_updates, config.LLM_API_KEY)
llm.classify_update_intent, llm.extract_updates, config.LLM_API_KEY = stage1, stage2, "test-key"
records = updates.detect(turns)
check(calls == {"stage1": 1, "stage2": 1}, "one stage-1 and one stage-2 call for a chunk with an accepted statement")
check([(r["item_id"][-2:], r["new_value"], r["old_value"], r["statement"]) for r in records]
      == [("r1", "Biscuit", "Bandit", "My dog's name is Biscuit."), ("r3", "下午三点", None, "会议时间是下午三点。")],
      "stage-2 entries map to their statement's turn; an unknown statement number is dropped; Chinese works")
check(updates.detect([raw(0, "Hi there.", digest="b" * 16)]) == [] and calls == {"stage1": 2, "stage2": 1},
      "no accepted statement: no stage-2 call, no record")
llm.classify_update_intent = lambda numbered: None
check(updates.detect_or_none(turns) is None and updates.detect(turns) == [], "a failed stage-1 call is None, Add sees []")
rel = updates.parse_updates([{"turn": 0, "subject": "me", "attribute": "coins", "new_value": "38",
                              "quote": "I added one more coin, so 38"}],
                            [raw(0, "Big week. I added one more coin, so 38 now. More news later!")])
plain = updates.parse_updates([{"turn": 0, "subject": "me", "attribute": "gym time", "new_value": "6 pm",
                                "quote": "Update my gym time: it's 6 pm"}],
                              [raw(0, "Update my gym time: it's 6 pm. I'd love more tips on stretching.")])
check(rel[0]["relative"] and not plain[0]["relative"],
      "relative words are read in the quote, not in the rest of the turn")
llm.classify_update_intent, llm.extract_updates, config.LLM_API_KEY = saved_llm


# --- search side, end to end ------------------------------------------------------
def fake_vectors(texts, is_query=False):
    out = np.zeros((len(texts), 256), dtype=np.float32)
    for row, text in enumerate(texts):
        for word in text.lower().split():
            out[row, int(hashlib.md5(word.encode()).hexdigest(), 16) % 256] += 1
        out[row] /= max(np.linalg.norm(out[row]), 1e-6)
    return out


def fake_stage1(numbered):
    return [{"turn": int(line.split(" | ")[0]), "label": "CORRECTION", "quote": "my gym time is 6 pm"}
            for line in numbered.split("\n") if "my gym time is 6 pm" in line]


def fake_stage2(numbered, accepted):
    return [{"statement": 0, "subject": "me", "attribute": "gym time", "new_value": "6 pm", "old_value": None,
             "relative": False, "current": "My gym time is 6 pm."}]


def verifier(update, memories):
    """REPLACED for 7 pm statements; the SAME/OTHER ones are what the real call drops."""
    return [(n, "7 pm") for n, m in enumerate(memories) if "7 pm" in m]


STREAM = [
    ("r1", [("user", "I go to the gym at 7 pm on weekdays."), ("assistant", "Noted: your gym time is 7 pm."),
            ("user", "My yoga class is at 8 pm.")]),
    ("r2", [("user", "Sorry, my gym time is 6 pm, I said it wrong before.")]),
]
QUERY = {"query": "What time do I go to the gym?", "user_id": "u1", "top_k": 100}


def build(directory, name, detect, render=False):
    config.DB_PATH = os.path.join(directory, f"{name}.sqlite3")
    config.UPDATE_DETECT, config.UPDATE_RENDER, config.UPDATE_WITHHOLD = detect, render, False
    store._conn = None
    store._cache.clear()
    updates._resolved.clear()
    store.init()
    for request_id, messages in STREAM:
        main.add(main.AddRequest.model_validate({
            "request_id": request_id, "user_id": "u1", "session_id": "s",
            "messages": [{"role": role, "content": c} for role, c in messages]}))


def search(withhold):
    config.UPDATE_WITHHOLD = withhold
    store._cache.clear()
    return main.search(main.SearchRequest.model_validate(QUERY))


saved = (config.DB_PATH, config.AUTH_SCHEME, config.LLM_API_KEY, config.UPDATE_DETECT, config.UPDATE_RENDER,
         config.UPDATE_WITHHOLD, embed.encode, llm.extract_facts, llm.recall_question,
         llm.classify_update_intent, llm.extract_updates, llm.verify_replaced_v2)
config.AUTH_SCHEME, config.LLM_API_KEY = "none", "test-key"
embed.encode = fake_vectors
llm.extract_facts = lambda text: []
llm.recall_question = lambda q, o: None
llm.classify_update_intent, llm.extract_updates, llm.verify_replaced_v2 = fake_stage1, fake_stage2, verifier
try:
    with tempfile.TemporaryDirectory() as directory:
        build(directory, "plain", detect=False)
        plain = json.dumps(search(False), sort_keys=True)
        build(directory, "detect", detect=True)
        check(json.dumps(search(False), sort_keys=True) == plain,
              "detection on, withholding off: /search byte-identical to a store built without detection")
        text = "\n".join(d["content"] for d in search(True)["data"])
        check("I go to the gym at 7 pm" not in text, "the user's own earlier 7 pm turn is withheld")
        check("Assistant: Noted: your gym time is 7 pm." in text,
              "another speaker's turn is never a candidate for the user's own attribute")
        check("yoga class is at 8 pm" in text and "6 pm" in text, "other attributes and the update are kept")
        llm.verify_replaced_v2 = lambda update, memories: []   # what SAME/OTHER verdicts come to
        build(directory, "same", detect=True)
        check(json.dumps(search(True), sort_keys=True) == plain, "verdicts other than REPLACED withhold nothing")
        llm.verify_replaced_v2 = verifier
        build(directory, "render", detect=True, render=True)
        check("My gym time is 6 pm." in "\n".join(d["content"] for d in search(False)["data"]),
              "RENDER stores the stage-2 current-value sentence")
finally:
    (config.DB_PATH, config.AUTH_SCHEME, config.LLM_API_KEY, config.UPDATE_DETECT, config.UPDATE_RENDER,
     config.UPDATE_WITHHOLD, embed.encode, llm.extract_facts, llm.recall_question,
     llm.classify_update_intent, llm.extract_updates, llm.verify_replaced_v2) = saved
    store._conn = None

print("\nOK" if ok else "\nFAILED")
sys.exit(0 if ok else 1)
