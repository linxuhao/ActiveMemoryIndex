"""Explicit updates, round 3 (AMI_UPDATE_VERSION=3): the same-language check
before RENDER (rc5: stage 2's language tags), and re-verification of the facts extracted from the chunk of a
confirmed-replaced turn. LLM and embedder replaced; no network.
Run: python tests/test_updates_v3.py
"""
import hashlib
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np  # noqa: E402

from app import config, embed, llm, main, store, updates  # noqa: E402

config.UPDATE_VERSION = 3  # round 3 exactly; same-Add exclusion in test_updates_v4.py
ok = True


def check(cond, label):
    global ok
    print(("  PASS  " if cond else "  FAIL  ") + label)
    ok &= bool(cond)


# --- language check (rc5: stage 2's own language tags; no script or stopword heuristic) ---
def rec(**kw):
    return {"relative": False, "statement": "The samurai's name is Takehiro.", **kw}


check(not hasattr(updates, "same_language") and not hasattr(updates, "_STOPWORDS") and not hasattr(updates, "_SCRIPTS"),
      "no script or stopword heuristic is left")
check(updates.renderable(rec(statement_language="en", current_language="en"), ""), "equal tags: rendered")
check(updates.renderable(rec(statement_language="zh-Hans", current_language="ZH"), "")
      and updates.renderable(rec(statement_language="pt_BR", current_language="pt"), ""),
      "tags compare by primary subtag, in any case and with either separator")
before = updates.stats["render_language_fallback"]
check(not updates.renderable(rec(statement="El samurái se llama Takehiro.", statement_language="en",
                                 current_language="es"), "")
      and updates.stats["render_language_fallback"] == before + 1,
      "different tags (a translated sentence): no render, and the fallback is counted")
check(not updates.renderable(rec(statement_language="fr"), "") and not updates.renderable(rec(), ""),
      "a missing tag (or an older stage-2 reply without tags): no render")
check(not updates.renderable(rec(relative=True, statement_language="en", current_language="en"), ""),
      "relative records are never rendered")


# --- chunk facts of a confirmed-replaced turn -------------------------------------
def fake_vectors(texts, is_query=False):
    out = np.zeros((len(texts), 256), dtype=np.float32)
    for row, text in enumerate(texts):
        for word in text.lower().replace('"', " ").split():
            out[row, int(hashlib.md5(word.encode()).hexdigest(), 16) % 256] += 1
        out[row] /= max(np.linalg.norm(out[row]), 1e-6)
    return out


FACTS = {"Pedro de Valdivia": "Santiago was founded by Pedro de Valdivia.",
         "UPDATE": "I updated who founded Santiago to Roberto Marinho.",
         "Chile": "Santiago is the capital of Chile."}
calls = []


def first_pass_only_raw(update, memories):
    """Round-2 behaviour: REPLACED for the JSON line only, the prose fact judged SAME."""
    calls.append(("context" in update.lower(), len(memories)))
    if "Context:" in update:
        return [(n, "Pedro de Valdivia") for n, m in enumerate(memories) if "Pedro de Valdivia" in m]
    return [(n, "Pedro de Valdivia") for n, m in enumerate(memories) if '"object": "Pedro de Valdivia"' in m]


STREAM = [("r1", ['{"subject": "Santiago", "relation": "founded by", "object": "Pedro de Valdivia"}',
                  '{"subject": "Santiago", "relation": "country", "object": "Chile"}']),
          ("r2", ['UPDATE: replace the prior value of this subject and relation with the following fact. '
                  '{"subject": "Santiago", "relation": "founded by", "object": "Roberto Marinho"}'])]
saved = (config.DB_PATH, config.AUTH_SCHEME, config.LLM_API_KEY, config.UPDATE_DETECT, config.UPDATE_WITHHOLD,
         embed.encode, llm.extract_facts, llm.recall_question, llm.classify_update_intent, llm.extract_updates,
         llm.verify_replaced_v2, llm.classify_question)
config.AUTH_SCHEME, config.LLM_API_KEY = "none", "test-key"
embed.encode = fake_vectors
llm.extract_facts = lambda text: [f for k, f in FACTS.items() if k in text]
llm.recall_question = lambda q, o: None
llm.classify_update_intent = lambda numbered: [
    {"turn": 0, "label": "EXPLICIT_REPLACEMENT", "quote": "replace the prior value of this subject and relation"}
] if "UPDATE" in numbered else []
llm.extract_updates = lambda numbered, accepted: [
    {"statement": 0, "subject": "Santiago", "attribute": "founded by", "new_value": "Roberto Marinho",
     "old_value": None, "relative": False, "current": "Santiago was founded by Roberto Marinho."}]
llm.verify_replaced_v2 = first_pass_only_raw
llm.classify_question = lambda q, o: {"needs_past_value": False, "time_scoped": False}  # rc5: every version asks
try:
    with tempfile.TemporaryDirectory() as directory:
        for version in (2, 3):
            config.UPDATE_VERSION = version
            config.DB_PATH = os.path.join(directory, f"v{version}.sqlite3")
            config.UPDATE_DETECT, config.UPDATE_WITHHOLD = True, True
            store._conn = None
            store._cache.clear()
            updates._resolved.clear()
            store.init()
            for request_id, contents in STREAM:
                main.add(main.AddRequest.model_validate({"request_id": request_id, "user_id": "u", "session_id": "s",
                                                         "messages": [{"role": "user", "content": c} for c in contents]}))
            calls.clear()
            text = "\n".join(d["content"] for d in main.search(main.SearchRequest.model_validate(
                {"query": "Who founded Santiago?", "user_id": "u", "top_k": 100}))["data"])
            if version == 2:
                check("Santiago was founded by Pedro de Valdivia." in text,
                      "version 2: the old-value prose fact survives (the round-2 defect, reproduced)")
            else:
                check("Pedro de Valdivia" not in text, "version 3: the same chunk's old-value fact is withheld too")
                check("Santiago is the capital of Chile." in text, "a same-chunk fact without the old value is kept")
                check("Roberto Marinho" in text, "the update and its fact are kept")
                check(calls == [(False, 4), (True, 1)],
                      "one ordinary call over the 4 candidates, then one with context for the one same-chunk old-value fact")
                calls.clear()
                main.search(main.SearchRequest.model_validate({"query": "Who founded Santiago?", "user_id": "u", "top_k": 100}))
                updates._resolved.clear()
                main.search(main.SearchRequest.model_validate({"query": "Who founded Santiago?", "user_id": "u", "top_k": 100}))
                check(calls == [], "both passes' verdicts persist: no further calls")
finally:
    (config.DB_PATH, config.AUTH_SCHEME, config.LLM_API_KEY, config.UPDATE_DETECT, config.UPDATE_WITHHOLD,
     embed.encode, llm.extract_facts, llm.recall_question, llm.classify_update_intent, llm.extract_updates,
     llm.verify_replaced_v2, llm.classify_question) = saved
    store._conn = None

print("\nOK" if ok else "\nFAILED")
sys.exit(0 if ok else 1)
