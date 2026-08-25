"""Guard on the agentic second round.

Switching `AMI_AGENTIC_SEARCH` on used to change three things at once: it
merged two already-selected lists and re-sorted them by score, which undid
raw-first ordering, and it applied a looser character budget than select()
does. An arm that changes three things cannot be read, so the second round now
fuses at the score level and runs the ordinary selection once.

These checks pin that: the second round may change *which* memories come back,
and must not change how the returned set is ordered or capped.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config, llm, main, store  # noqa: E402


def check(condition, label):
    print(("  PASS  " if condition else "  FAIL  ") + label)
    return condition


def build_index():
    """Four verbatim turns and two facts, in one chunk."""
    items, contents = [], []
    for position in range(4):
        items.append(store.Item(id=f"aaaaaaaaaaaaaaaa-r{position}", kind="raw",
                                parent_id=None, content=f"turn {position}", created_at=None))
        contents.append(f"turn {position}")
    for number in range(2):
        items.append(store.Item(id=f"aaaaaaaaaaaaaaaa-f{number}", kind="fact",
                                parent_id=None, content=f"fact {number}", created_at=None))
    index = store.UserIndex()
    index.append(items, np.zeros((len(items), 4), dtype=np.float32))
    return index


ok = True
index = build_index()

# Round 1 ranks the facts highest and turn 3 lowest; round 2 — the reflection's
# targeted question — is the only one that finds turn 3.
ROUND_1 = np.array([0.30, 0.20, 0.10, 0.01, 0.90, 0.80], dtype=np.float32)
ROUND_2 = np.array([0.05, 0.05, 0.05, 0.95, 0.05, 0.05], dtype=np.float32)

original = (main.rank, llm.reflect_gap, store.get, config.AGENTIC_SEARCH,
            config.llm_available, config.WINDOW_RADIUS)
main.rank = lambda index, query, options, recall_question=None: (
    ROUND_2 if recall_question else ROUND_1)
llm.reflect_gap = lambda query, options, top_memories: {
    "status": "INCOMPLETE", "question": "which turn covers the second event"}
store.get = lambda user_id: index
config.llm_available = lambda: True
# This file exercises selection, not the auth surface, which test-drives itself
# through the endpoint signature; test_ordering owns the ordering rules.
config.AUTH_SCHEME = "none"
# The window is exercised by test_ordering; keep it out of the way so this file
# measures the second round and nothing else.
config.WINDOW_RADIUS = 0

# top_k=4 of six memories, so the two rounds genuinely disagree about which
# four come back. At top_k=6 everything is returned either way and the
# comparison below would be vacuous.
request = main.SearchRequest(query="q", user_id="u", top_k=4)

config.AGENTIC_SEARCH = False
without = [row["id"] for row in main.search(request, None, None)["data"]]

config.AGENTIC_SEARCH = True
with_agentic = [row["id"] for row in main.search(request, None, None)["data"]]

main.rank, llm.reflect_gap, store.get, config.AGENTIC_SEARCH, config.llm_available, \
    config.WINDOW_RADIUS = original

print("without agentic:", without)
print("with agentic:   ", with_agentic)

kinds = ["r" if "-r" in ident else "f" for ident in with_agentic]
ok &= check(kinds == sorted(kinds, key=lambda k: k != "r"),
            "raw-first survives the second round")
ok &= check(len(with_agentic) <= request.top_k, "the top_k cap still binds")
ok &= check(len(with_agentic) == len(set(with_agentic)), "no memory is returned twice")

# The point of the second round: an item only its question reaches must arrive.
# Element-wise max keeps turn 3 at 0.95; a mean would have averaged it to 0.48
# and left it below the facts.
ok &= check("aaaaaaaaaaaaaaaa-r3" in with_agentic,
            "evidence only the reflection's question reaches is included")

# And the arm must change the *set*, not merely its order, or it measures nothing.
ok &= check(set(with_agentic) - set(without) == {"aaaaaaaaaaaaaaaa-r3"},
            "the second round adds exactly the memory the first round missed")
ok &= check("aaaaaaaaaaaaaaaa-r3" not in without,
            "and the first round on its own does not reach it")

print("\n" + ("OK" if ok else "FAILURES"))
sys.exit(0 if ok else 1)
