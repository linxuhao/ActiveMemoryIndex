"""Explicit updates, round 3 (AMI_UPDATE_VERSION=3): the same-language check
before RENDER, and re-verification of the facts extracted from the chunk of a
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


# --- language check -------------------------------------------------------------
turn = "[2023-05-10 10:50] I: The name of the dead victim, the samurai, is Takehiro, not Tajomaru."
check(not updates.same_language("El samurái se llama Takehiro y es el de la historia.", turn),
      "a Spanish sentence for an English turn is rejected")
check(not updates.same_language("会议时间是下午三点。", turn), "a CJK sentence for a Latin-script turn is rejected")
check(updates.same_language("The samurai's name is Takehiro.", turn), "an English sentence for an English turn passes")
check(updates.same_language("会议时间是下午三点。", "I: 把会议时间改成下午三点。"), "Chinese for Chinese passes")
check(updates.same_language("Rafael del Riego's country of citizenship is Ghana.",
                            'I: UPDATE: replace the prior value of this subject and relation with the following fact. '
                            '{"subject": "Rafael del Riego", "relation": "country of citizenship", "object": "Ghana"}'),
      "a name containing 'del' does not make an English sentence Spanish")
check(updates.same_language("Funk.", turn), "too little text to tell: rendered")
before = updates.stats["render_language_fallback"]
check(not updates.renderable({"relative": False, "statement": "El tipo de interfaz es GigabitEthernet y es el nuevo."},
                             "I: can you please replace FastEthernet with GigabitEthernet in the instructions?")
      and updates.stats["render_language_fallback"] == before + 1, "renderable() skips it and counts the fallback")
check(not updates.renderable({"relative": True, "statement": "I have 38 coins."}, "I: I added one more coin."),
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
         llm.verify_replaced_v2)
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
     llm.verify_replaced_v2) = saved
    store._conn = None

print("\nOK" if ok else "\nFAILED")
sys.exit(0 if ok else 1)
