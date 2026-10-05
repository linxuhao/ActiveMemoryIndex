"""Explicit updates, round 5 (AMI_UPDATE_VERSION=5): language-dependent
decisions moved to gpt-4o-mini. The question classifier is asked only when
withholding would change the returned set, is cached, fails safe (withhold
nothing), and the English/CJK patterns can only add protection. Stage 2's
subject_is_user and relative fields work in any language.
LLM and embedder replaced; no network. Run: python tests/test_updates_v5.py
"""
import hashlib
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np  # noqa: E402

from app import config, embed, llm, main, store, updates  # noqa: E402

config.UPDATE_VERSION = 5  # round 5 as registered; version 6 checks at the end
ok = True


def check(cond, label):
    global ok
    print(("  PASS  " if cond else "  FAIL  ") + label)
    ok &= bool(cond)


calls = []
verdicts = {}


def fake_classifier(query, options):
    calls.append((query, tuple(options or ())))
    return verdicts.get(query)


saved_cls, saved_key = llm.classify_question, config.LLM_API_KEY
llm.classify_question, config.LLM_API_KEY = fake_classifier, "test-key"
updates._scope_cache.clear()

# --- the question router ---------------------------------------------------------
check(updates.question_protected("他在1976年属于哪个党？", None) and calls == [],
      "a CJK year is caught by the pre-filter, no call (the \\b pattern misses it)")
check(updates.question_protected("What was my address before I moved?", None) and calls == [],
      "an English history wording is caught by the pre-filter, no call")
verdicts["我原来的电话号码是多少？"] = {"needs_past_value": True, "time_scoped": False}
check(updates.question_protected("我原来的电话号码是多少？", None) and len(calls) == 1,
      "a Chinese history question the patterns miss is protected by the classifier")
verdicts["现在会议几点？"] = {"needs_past_value": False, "time_scoped": False}
check(not updates.question_protected("现在会议几点？", None), "a current-value question is not protected")
verdicts["截至2025年9月他的职位？"] = {"needs_past_value": False, "time_scoped": True}
check(updates.question_protected("Which genre did I first give for X?", None), "classifier failure (None) withholds nothing")
n = len(calls)
updates.question_protected("现在会议几点？", None)
check(len(calls) == n, "verdicts are cached per query")
updates.question_protected("现在会议几点？", ["A", "B"])
check(len(calls) == n + 1, "options are part of the cache key")
failures = [len(calls)]
def timeout(q, o):
    raise TimeoutError("simulated")


llm.classify_question = timeout
updates.log.disabled = True
check(updates.question_protected("Where is my office now?", None), "a classifier exception withholds nothing")
updates.log.disabled = False
llm.classify_question = fake_classifier
config.UPDATE_VERSION = 4
check(not updates.protected_question("我原来的电话号码是多少？"),
      "version 4 (regex only) does not protect it — the round-4 behaviour")
config.UPDATE_VERSION = 5

# --- stage 2 fields ------------------------------------------------------------------
turn = store.Item(id=f"{'c' * 16}-r0", kind="raw", parent_id=None, content="I: 更正：我的健身时间改成晚上6点了。",
                  created_at=None)
rec = updates.parse_updates([{"turn": 0, "subject": "我", "attribute": "健身时间", "new_value": "晚上6点",
                              "subject_is_user": True, "relative": False}], [turn])[0]
check(rec["subject"] == "me", "subject_is_user makes a Chinese self subject the user's own")
rel = updates.parse_updates([{"turn": 0, "subject": "我", "attribute": "硬币", "new_value": "晚上6点",
                              "subject_is_user": True, "relative": True}], [turn])[0]
check(rel["relative"], "stage-2 relative flag is kept (the English word list cannot see Chinese)")
config.UPDATE_VERSION = 4
check(updates.parse_updates([{"turn": 0, "subject": "我", "attribute": "健身时间", "new_value": "晚上6点",
                              "subject_is_user": True}], [turn])[0]["subject"] == "我",
      "version 4 ignores subject_is_user (round-4 behaviour)")
config.UPDATE_VERSION = 5


# --- end to end, Chinese stream ----------------------------------------------------------
def fake_vectors(texts, is_query=False):
    out = np.zeros((len(texts), 256), dtype=np.float32)
    for row, text in enumerate(texts):
        for ch in text:
            out[row, int(hashlib.md5(ch.encode()).hexdigest(), 16) % 256] += 1
        out[row] /= max(np.linalg.norm(out[row]), 1e-6)
    return out


STREAM = [("r1", [("user", "我的健身时间是晚上7点。"), ("assistant", "好的，你的健身时间是晚上7点。")]),
          ("r2", [("user", "更正：我的健身时间改成晚上6点了。")]),
          ("r3", [("user", "我有三十七枚硬币。")]),
          ("r4", [("user", "我又买了一枚硬币，现在是三十八枚。")])]


def stage1(numbered):
    if "改成" in numbered:
        return [{"turn": 0, "label": "CORRECTION", "quote": "我的健身时间改成晚上6点了"}]
    if "又买了" in numbered:
        return [{"turn": 0, "label": "EXPLICIT_REPLACEMENT", "quote": "我又买了一枚硬币，现在是三十八枚"}]
    return []


def stage2(numbered, accepted):
    if "改成" in numbered:
        return [{"statement": 0, "subject": "我", "subject_is_user": True, "attribute": "健身时间",
                 "new_value": "晚上6点", "old_value": None, "relative": False, "current": "我的健身时间是晚上6点。"}]
    return [{"statement": 0, "subject": "我", "subject_is_user": True, "attribute": "硬币数量",
             "new_value": "三十八枚", "old_value": None, "relative": True, "current": "我有三十八枚硬币。"}]


def verifier(update, memories):
    return [(n, "晚上7点" if "7点" in m else "三十七枚") for n, m in enumerate(memories) if "7点" in m or "三十七" in m]


saved = (config.DB_PATH, config.AUTH_SCHEME, config.UPDATE_DETECT, config.UPDATE_WITHHOLD, embed.encode,
         llm.extract_facts, llm.recall_question, llm.classify_update_intent, llm.extract_updates, llm.verify_replaced_v2)
config.AUTH_SCHEME = "none"
embed.encode = fake_vectors
llm.extract_facts = lambda text: []
llm.recall_question = lambda q, o: None
llm.classify_update_intent, llm.extract_updates, llm.verify_replaced_v2 = stage1, stage2, verifier


def search(query, withhold):
    config.UPDATE_WITHHOLD = withhold
    store._cache.clear()
    return main.search(main.SearchRequest.model_validate({"query": query, "user_id": "u", "top_k": 100}))


try:
    with tempfile.TemporaryDirectory() as directory:
        config.DB_PATH = os.path.join(directory, "v5.sqlite3")
        config.UPDATE_DETECT = True
        store._conn = None
        store._cache.clear()
        store.init()
        for request_id, messages in STREAM:
            main.add(main.AddRequest.model_validate({"request_id": request_id, "user_id": "u", "session_id": "s",
                                                     "messages": [{"role": r, "content": c} for r, c in messages]}))
        recs = store.get_updates("u")
        check([r["subject"] for r in recs] == ["me", "me"] and [r["relative"] for r in recs] == [False, True],
              "records: Chinese self subjects stored as the user's own; the coin update is relative")
        verdicts["我现在几点去健身？"] = {"needs_past_value": False, "time_scoped": False}
        calls.clear()
        text = "\n".join(d["content"] for d in search("我现在几点去健身？", True)["data"])
        check("I: 我的健身时间是晚上7点。" not in text, "current question: the user's own earlier 7点 turn is withheld")
        check("Assistant: 好的，你的健身时间是晚上7点。" in text,
              "the assistant's turn is not a candidate for the user's own attribute")
        check("我有三十七枚硬币" in text, "a Chinese relative update withholds nothing")
        check(len(calls) == 1, "one classifier call, because withholding changed the returned set")
        verdicts["我原来几点去健身？"] = {"needs_past_value": True, "time_scoped": False}
        check(json.dumps(search("我原来几点去健身？", True), sort_keys=True)
              == json.dumps(search("我原来几点去健身？", False), sort_keys=True),
              "history question (classifier): byte-identical to withholding off")
        calls.clear()
        config.UPDATE_WITHHOLD = True
        main.search(main.SearchRequest.model_validate({"query": "我的健身时间？", "user_id": "nobody", "top_k": 100}))
        check(calls == [], "a user without records never triggers a call")
        saved_withheld = updates.withheld
        updates.withheld = lambda index, user_id, query: {"not-in-the-returned-set"}
        calls.clear()
        search("我的健身时间是多少？", True)
        updates.withheld = saved_withheld
        check(calls == [], "withheld items outside the returned set: no classifier call")
finally:
    (config.DB_PATH, config.AUTH_SCHEME, config.UPDATE_DETECT, config.UPDATE_WITHHOLD, embed.encode,
     llm.extract_facts, llm.recall_question, llm.classify_update_intent, llm.extract_updates,
     llm.verify_replaced_v2) = saved
    llm.classify_question, config.LLM_API_KEY = saved_cls, saved_key
    store._conn = None

print("\nOK" if ok else "\nFAILED")
sys.exit(0 if ok else 1)
