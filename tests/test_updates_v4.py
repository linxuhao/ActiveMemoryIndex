"""Explicit updates, round 4 (AMI_UPDATE_VERSION=4): the same-Add exclusion.
Nothing from the update's own Add request — verbatim turn or extracted fact —
is ever withheld; "earlier" means an earlier Add. Verdicts stored under an
earlier version never reach the update's own Add either. LLM and embedder
replaced; no network. Run: python tests/test_updates_v4.py
"""
import hashlib
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np  # noqa: E402

from app import config, embed, llm, main, store, updates  # noqa: E402

config.UPDATE_VERSION = 4
ok = True


def check(cond, label):
    global ok
    print(("  PASS  " if cond else "  FAIL  ") + label)
    ok &= bool(cond)


def raw(digest, n, text, stamp=None):
    return store.Item(id=f"{digest}-r{n}", kind="raw", parent_id=None, content=f"I: {text}", created_at=stamp)


same, other = "a" * 16, "b" * 16
index = store.UserIndex()
index.append([raw(other, 0, "older Add"), raw(same, 0, "earlier line, same Add"), raw(same, 1, "the update"),
              store.Item(id=f"{same}-f0", kind="fact", parent_id=None, content="same-Add fact", created_at=None)],
             np.eye(4, dtype=np.float32))
check(updates.earlier(index, 2, 0), "an earlier Add is earlier")
check(not updates.earlier(index, 2, 1) and not updates.earlier(index, 2, 3),
      "version 4: an earlier turn or a fact of the update's own Add is not")
config.UPDATE_VERSION = 3
check(updates.earlier(index, 2, 1) and updates.earlier(index, 2, 3), "version 3 (round 3) still treats them as earlier")
config.UPDATE_VERSION = 4


def fake_vectors(texts, is_query=False):
    out = np.zeros((len(texts), 256), dtype=np.float32)
    for row, text in enumerate(texts):
        for word in text.lower().replace('"', " ").split():
            out[row, int(hashlib.md5(word.encode()).hexdigest(), 16) % 256] += 1
        out[row] /= max(np.linalg.norm(out[row]), 1e-6)
    return out


calls = []


def adversarial(update, memories):
    """DIFFERENT for every candidate that names the old coffee maker."""
    calls.append(len(memories))
    return [(n, "old coffee maker") for n, m in enumerate(memories) if "old coffee maker" in m]


STREAM = [
    ("r1", ["I make coffee with my old coffee maker every morning."]),
    ("r2", ["My old coffee maker broke last month.",
            "Correction: I replaced my old coffee maker with a new pour-over set."]),
]
FACTS = {"every morning": "I make coffee with my old coffee maker every morning.",
         "Correction": "I replaced my old coffee maker about three weeks ago."}
QUERY = {"query": "What do I make coffee with?", "user_id": "u", "top_k": 100}
saved = (config.DB_PATH, config.AUTH_SCHEME, config.LLM_API_KEY, config.UPDATE_DETECT, config.UPDATE_WITHHOLD,
         config.UPDATE_VERSION, embed.encode, llm.extract_facts, llm.recall_question, llm.classify_update_intent,
         llm.extract_updates, llm.verify_replaced_v2)
config.AUTH_SCHEME, config.LLM_API_KEY = "none", "test-key"
embed.encode = fake_vectors
llm.extract_facts = lambda text: [f for k, f in FACTS.items() if k in text]
llm.recall_question = lambda q, o: None
llm.classify_update_intent = lambda numbered: [
    {"turn": 1, "label": "CORRECTION", "quote": "I replaced my old coffee maker with a new pour-over set."}
] if "Correction" in numbered else []
llm.extract_updates = lambda numbered, accepted: [
    {"statement": 0, "subject": "me", "attribute": "coffee maker", "new_value": "a new pour-over set",
     "old_value": "old coffee maker", "relative": False, "current": "I make coffee with a new pour-over set."}]
llm.verify_replaced_v2 = adversarial


def run(directory, name, version, fresh=True):
    config.UPDATE_VERSION = version
    if fresh:
        config.DB_PATH = os.path.join(directory, f"{name}.sqlite3")
        config.UPDATE_DETECT, config.UPDATE_WITHHOLD = True, True
        store._conn = None
        store._cache.clear()
        store.init()
        for request_id, contents in STREAM:
            main.add(main.AddRequest.model_validate({"request_id": request_id, "user_id": "u", "session_id": "s",
                                                     "messages": [{"role": "user", "content": c} for c in contents]}))
    updates._resolved.clear()
    store._cache.clear()
    return "\n".join(d["content"] for d in main.search(main.SearchRequest.model_validate(QUERY))["data"])


try:
    with tempfile.TemporaryDirectory() as directory:
        text = run(directory, "v4", 4)
        check("I: I make coffee with my old coffee maker every morning." not in text,
              "the older Add's turn stating the old value is withheld")
        check("My old coffee maker broke last month." in text, "an earlier turn of the update's own Add is kept (raw)")
        check("I replaced my old coffee maker about three weeks ago." in text,
              "a fact of the update's own Add describing the change is kept (fact)")
        check(calls == [2], "the update's own Add never reaches the verifier: one call, older Add's turn and fact only")

        calls.clear()
        text3 = run(directory, "v3", 3)
        check("My old coffee maker broke last month." not in text3,
              "version 3 withheld the same-Add earlier turn (the round-3 behaviour)")
        calls.clear()
        text4 = run(directory, "v3", 4, fresh=False)
        check("My old coffee maker broke last month." in text4 and calls == [],
              "verdicts stored under version 3 are not applied to the update's own Add under version 4, no new call")
finally:
    (config.DB_PATH, config.AUTH_SCHEME, config.LLM_API_KEY, config.UPDATE_DETECT, config.UPDATE_WITHHOLD,
     config.UPDATE_VERSION, embed.encode, llm.extract_facts, llm.recall_question, llm.classify_update_intent,
     llm.extract_updates, llm.verify_replaced_v2) = saved
    store._conn = None

print("\nOK" if ok else "\nFAILED")
sys.exit(0 if ok else 1)
