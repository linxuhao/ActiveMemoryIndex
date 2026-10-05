"""Explicit updates (AMI_UPDATE_DETECT / AMI_UPDATE_RENDER / AMI_UPDATE_WITHHOLD).

Detection parsing, precision of the earlier-item match on synthetic stores,
the history/date exception, relative updates, and byte-identical /search when
the switches are off. The LLM and the embedder are replaced; no network.
Run directly: python tests/test_updates.py
"""
import hashlib
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np  # noqa: E402

from app import config, embed, llm, main, store, updates  # noqa: E402

# These checks pin the round-1 detector and verifier (AMI_UPDATE_VERSION=1);
# round 2 is covered by tests/test_updates_v2.py.
config.UPDATE_VERSION = 1
ok = True


def check(cond, label):
    global ok
    print(("  PASS  " if cond else "  FAIL  ") + label)
    ok &= bool(cond)


def raw(digest, n, text, stamp=None, speaker="I"):
    prefix = f"[{stamp[:10]} {stamp[11:16]}] " if stamp else ""
    return store.Item(id=f"{digest}-r{n}", kind="raw", parent_id=None,
                      content=f"{prefix}{speaker}: {text}", created_at=stamp)


# --- parsing -------------------------------------------------------------------
turns = [raw("a" * 16, 0, 'UPDATE: replace the prior value. {"subject": "Frank Herbert", "relation": "genre", "object": "funk"}'),
         raw("a" * 16, 1, "Sure, noted. Frank Herbert's genre is now funk.", speaker="Assistant"),
         raw("a" * 16, 2, "Correction: my gym time is 6 pm, not 7 pm."),
         raw("a" * 16, 3, "I added one more coin, so I have 38 coins now.")]
entries = [
    {"turn": 0, "subject": "Frank Herbert", "attribute": "genre", "new_value": "funk", "old_value": "science fiction",
     "relative": False, "statement": "Frank Herbert's genre is funk."},
    {"turn": 1, "subject": "Frank Herbert", "attribute": "genre", "new_value": "funk", "old_value": None},
    {"turn": 2, "subject": "me", "attribute": "gym time", "new_value": "6 pm", "old_value": "7 pm", "relative": "false"},
    {"turn": 2, "subject": "me", "attribute": "gym time", "new_value": "5 pm"},
    {"turn": 3, "subject": "me", "attribute": "coin count", "new_value": "38", "relative": False},
    {"turn": "x", "subject": "me", "attribute": "a", "new_value": "b"},
    {"turn": 9, "subject": "me", "attribute": "a", "new_value": "b"},
    {"turn": 0, "subject": "", "attribute": "genre", "new_value": "funk"},
]
records = updates.parse_updates(entries, turns)
check(len(records) == 3, "assistant turn, unseen new value, bad turn and missing subject are dropped")
check(records[0]["old_value"] is None, "an old value the turn does not contain is discarded as a guess")
check(records[0]["id"] == "a" * 16 + "-r0-u0" and records[0]["item_id"] == "a" * 16 + "-r0", "record points at its turn")
check(records[1]["old_value"] == "7 pm" and records[1]["relative"] is False, "stated old value kept; 'false' string is absolute")
check(records[2]["relative"] is True, "'added one more' marks a relative update even when the model says absolute")
check(updates.parse_updates([{"turn": 0, "subject": "x", "attribute": "y", "new_value": "+2"}],
                            [raw("b" * 16, 0, "x is +2 now")])[0]["relative"], "a signed value is relative")
check(updates.detector_input([raw("c" * 16, 0, "hi", speaker="Assistant")]) is None, "no user turn: no detector call")
text = updates.detector_input([raw("c" * 16, 0, "x" * 500, speaker="Assistant"), raw("c" * 16, 1, "y" * 500)])
check(text.startswith("0 | Assistant: xxx") and text.split("\n")[0].endswith(" ...")
      and len(text.split("\n")[0]) < 220 and text.split("\n")[1].endswith("y" * 500),
      "other speakers are truncated, the user's turns are not")
check(llm._json_object('noise {"updates": []} tail') == {"updates": []} and llm._json_object("prose") is None,
      "reply parsing tolerates noise and rejects prose")

# --- question protection -------------------------------------------------------
for q in ["What was Frank Herbert's genre before the update?", "What did I previously set my gym time to?",
          "How did my team size change?", "Which party did X belong to in Jan, 1976?",
          "What is X's job title as of September 5, 2025?", "What was it on 2024-01-12?",
          "I used to go at 7, what time now?", "What was my original plan?"]:
    check(updates.protected_question(q), f"protected: {q}")
for q in ["What is the country of citizenship of Ellie Kemper?", "What genre is Frank Herbert associated with?",
          "What is my current gym time?", "What is the updated value of Frank Herbert's genre?",
          "What is the country of origin of the Fiat Panda?", "Who is the head of state of the country Ellie Kemper is a citizen of?"]:
    check(not updates.protected_question(q), f"not protected: {q}")

# --- order -----------------------------------------------------------------------
digest_old, digest_new = "d" * 16, "e" * 16
idx = store.UserIndex()
idx.append([raw(digest_old, 0, "old", "2024-01-01T10:00:00Z"), raw(digest_new, 0, "x", "2024-01-02T10:00:00Z"),
            raw(digest_new, 1, "update", "2024-01-02T10:01:00Z"), raw(digest_new, 2, "after", "2024-01-02T10:02:00Z"),
            store.Item(id=f"{digest_new}-f0", kind="fact", parent_id=None, content="f", created_at="2024-01-02T10:00:00Z"),
            raw("f" * 16, 0, "late-added but older", "2023-12-01T10:00:00Z")],
           np.eye(6, dtype=np.float32))
check(updates.earlier(idx, 2, 0), "an older chunk is earlier")
check(updates.earlier(idx, 2, 1) and not updates.earlier(idx, 2, 3), "inside the chunk: turn order")
check(updates.earlier(idx, 2, 4), "the update chunk's own facts are candidates")
check(updates.earlier(idx, 2, 5), "timestamps decide over Add order")
idx2 = store.UserIndex()
idx2.append([raw("g" * 16, 0, "a"), raw("h" * 16, 0, "b"), raw("i" * 16, 0, "c")], np.eye(3, dtype=np.float32))
check(updates.earlier(idx2, 1, 0) and not updates.earlier(idx2, 1, 2), "no timestamps: Add order decides")


# --- end to end through /add and /search, LLM and embedder faked -----------------
def fake_vectors(texts, is_query=False):
    out = np.zeros((len(texts), 256), dtype=np.float32)
    for row, text in enumerate(texts):
        for word in text.lower().replace('"', " ").split():
            out[row, int(hashlib.md5(word.encode()).hexdigest(), 16) % 256] += 1
        out[row] /= max(np.linalg.norm(out[row]), 1e-6)
    return out


FACTS = {
    '"genre", "object": "science fiction"}': "Frank Herbert is associated with the genre of science fiction.",
    '"country of citizenship"': "Frank Herbert is a citizen of the United States of America.",
    '"Isaac Asimov"': "Isaac Asimov is associated with the genre of science fiction.",
    "UPDATE:": "I updated the value of Frank Herbert's genre to funk.",
    "coin": "I have 37 coins.",
    "one more": "I added one more coin.",
}


def fake_extract(text):
    return [fact for key, fact in FACTS.items() if key in text]


def fake_detect(numbered):
    out = []
    for line in numbered.split("\n"):
        number, _, body = line.partition(" | ")
        if "UPDATE:" in body and "Frank Herbert" in body:
            out.append({"turn": int(number), "subject": "Frank Herbert", "attribute": "genre", "new_value": "funk",
                        "old_value": None, "relative": False, "statement": "Frank Herbert's genre is funk."})
        if "one more" in body:
            out.append({"turn": int(number), "subject": "me", "attribute": "coin count", "new_value": "one more",
                        "old_value": None, "relative": True})
    return out


verify_calls = []


def attribute_aware(update, memories):
    """A verifier that gets the semantics right: genre, Frank Herbert, old value."""
    verify_calls.append(len(memories))
    return [(n, "science fiction") for n, m in enumerate(memories)
            if "Frank Herbert" in m and "genre" in m and "science fiction" in m]


def adversarial(update, memories):
    """Says every candidate is replaced and quotes whatever it likes."""
    verify_calls.append(len(memories))
    return [(n, "science fiction") for n in range(len(memories))] + [(n, "United States of America") for n in range(len(memories))]


STREAM = [
    ("r1", ['{"subject": "Frank Herbert", "relation": "genre", "object": "science fiction"}',
            '{"subject": "Frank Herbert", "relation": "country of citizenship", "object": "United States of America"}',
            '{"subject": "Isaac Asimov", "relation": "genre", "object": "science fiction"}',
            "I have 37 coins."]),
    ("r2", ['UPDATE: replace the prior value of this subject and relation with the following fact. '
            '{"subject": "Frank Herbert", "relation": "genre", "object": "funk"}',
            "I added one more coin."]),
    ("r3", ["Frank Herbert writes science fiction, I said again later."]),
]
QUERY = {"query": "What genre is Frank Herbert associated with?", "user_id": "u1", "top_k": 100}
HISTORY = {"query": "What was Frank Herbert's genre before the update?", "user_id": "u1", "top_k": 100}


def build(directory, name, detect, render=False, stream=STREAM):
    config.DB_PATH = os.path.join(directory, f"{name}.sqlite3")
    config.UPDATE_DETECT, config.UPDATE_RENDER, config.UPDATE_WITHHOLD = detect, render, False
    store._conn = None
    store._cache.clear()
    updates._resolved.clear()
    store.init()
    for request_id, contents in stream:
        main.add(main.AddRequest.model_validate({
            "request_id": request_id, "user_id": "u1", "session_id": "s",
            "messages": [{"role": "user", "content": c} for c in contents]}))


def search(body, withhold):
    config.UPDATE_WITHHOLD = withhold
    store._cache.clear()
    return main.search(main.SearchRequest.model_validate(body))


saved = (config.DB_PATH, config.AUTH_SCHEME, config.LLM_API_KEY, config.UPDATE_DETECT, config.UPDATE_RENDER,
         config.UPDATE_WITHHOLD, embed.encode, llm.extract_facts, llm.recall_question, llm.detect_updates,
         llm.verify_replaced)
config.AUTH_SCHEME, config.LLM_API_KEY = "none", "test-key"
embed.encode = fake_vectors
llm.extract_facts, llm.recall_question, llm.detect_updates = fake_extract, (lambda q, o: None), fake_detect
llm.verify_replaced = attribute_aware
try:
    with tempfile.TemporaryDirectory() as directory:
        build(directory, "plain", detect=False)
        tables = {r[0] for r in store._conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        check("updates" not in tables, "switches off: the store keeps exactly the shipped schema")
        plain = json.dumps(search(QUERY, False), sort_keys=True)
        config.UPDATE_WITHHOLD = True
        store._conn = None
        store.init()
        check(json.dumps(search(QUERY, True), sort_keys=True) == plain,
              "withholding on over a store with no records: /search is byte-identical")

        build(directory, "detect", detect=True)
        recs = store.get_updates("u1")
        check(len(recs) == 2 and sum(r["relative"] for r in recs) == 1, "Add stored one absolute and one relative record")
        check(store.get_updates("someone-else") == [], "records are per user")
        off = json.dumps(search(QUERY, False), sort_keys=True)
        check(off == plain, "detection on, withholding off: /search is byte-identical to a store built without detection")

        on = search(QUERY, True)
        ids = {d["content"]: d["id"] for d in on["data"]}
        text = "\n".join(d["content"] for d in on["data"])
        check('I: {"subject": "Frank Herbert", "relation": "genre", "object": "science fiction"}' not in ids
              and "Frank Herbert is associated with the genre of science fiction." not in ids,
              "the earlier raw turn and fact stating the replaced genre are withheld")
        check("funk" in text and "UPDATE:" in text, "the update and the current value are kept")
        check("United States of America" in text and "Isaac Asimov" in text,
              "same subject other attribute, and same attribute other subject, are kept")
        check("said again later" in text, "a later restatement of the old value is never withheld")
        check("I have 37 coins." in text, "a relative update withholds nothing")
        check(len(on["data"]) == len(json.loads(off)["data"]) - 2, "exactly two items left out, nothing else changed")
        calls = len(verify_calls)
        search(QUERY, True)
        check(len(verify_calls) == calls, "verdicts persist: a second search makes no verification call")
        check(json.dumps(search(HISTORY, True), sort_keys=True) == json.dumps(search(HISTORY, False), sort_keys=True),
              "a history question withholds nothing")
        check(json.dumps(search({**QUERY, "user_id": "u2"}, True)) == json.dumps(search({**QUERY, "user_id": "u2"}, False)),
              "a user with no records is unaffected")

        llm.verify_replaced = adversarial
        build(directory, "adversarial", detect=True)
        text = "\n".join(d["content"] for d in search(QUERY, True)["data"])
        check("Isaac Asimov" in text, "an adversarial verifier cannot reach another subject (lexical subject guard)")
        check("said again later" in text and "funk" in text, "nor later items, nor items carrying the new value")
        check("United States of America" not in text,
              "LIMIT, documented: with the old value unstated, a same-subject other-attribute item rests on the verifier")

        stated = [("r1", STREAM[0][1]), ("r2", ["Correction: Frank Herbert's genre is funk, not science fiction."])]
        llm.detect_updates = lambda numbered: [
            {"turn": 0, "subject": "Frank Herbert", "attribute": "genre", "new_value": "funk",
             "old_value": "science fiction", "relative": False}] if "Correction" in numbered else []
        build(directory, "stated", detect=True, stream=stated)
        text = "\n".join(d["content"] for d in search(QUERY, True)["data"])
        check("United States of America" in text and "Isaac Asimov" in text,
              "with the old value stated, even an adversarial verifier cannot reach other attributes or subjects")
        check("Correction" in text, "the correction itself is kept")

        llm.verify_replaced = lambda update, memories: None
        build(directory, "failing", detect=True)
        check(json.dumps(search(QUERY, True), sort_keys=True) == json.dumps(search(QUERY, False), sort_keys=True),
              "a failing verifier withholds nothing")

        llm.verify_replaced = attribute_aware
        llm.detect_updates = fake_detect
        build(directory, "render", detect=True, render=True)
        text = "\n".join(d["content"] for d in search(QUERY, False)["data"])
        check("Frank Herbert's genre is funk." in text and text.count("one more") == 2,
              "RENDER stores the absolute update's statement as a fact, never a relative one")
finally:
    (config.DB_PATH, config.AUTH_SCHEME, config.LLM_API_KEY, config.UPDATE_DETECT, config.UPDATE_RENDER,
     config.UPDATE_WITHHOLD, embed.encode, llm.extract_facts, llm.recall_question, llm.detect_updates,
     llm.verify_replaced) = saved
    store._conn = None

print("\nOK" if ok else "\nFAILED")
sys.exit(0 if ok else 1)
