"""Guard on reserving slots for a second retrieval round.

AMI_AGENTIC_SEARCH fuses two rounds into one score and selects once. On LoCoMo
multi-hop questions it fired on 51 of 68 and changed the returned set, while the
number receiving all their evidence stayed at exactly 38 — because what the
second round finds still has to out-rank the first round's hundred, and the
evidence these questions miss sits at a median rank of 213. Reserving slots is
the difference. These checks pin that the reservation is real: the first round
gets fewer places, the second round's picks are not ones the first already took,
and the contract's cap still binds over the two together.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config, llm, main, store  # noqa: E402


def check(condition, label):
    print(("  PASS  " if condition else "  FAIL  ") + label)
    return condition


items = [store.Item(id=f"aaaaaaaaaaaaaaaa-r{p}", kind="raw", parent_id=None,
                    content=f"turn {p}", created_at=None) for p in range(10)]
index = store.UserIndex()
index.append(items, np.zeros((len(items), 4), dtype=np.float32))
# Round 1 likes the low-numbered turns; only round 2 reaches turns 8 and 9.
ROUND_1 = np.array([.99, .98, .97, .96, .95, .94, .93, .92, .01, .00], dtype=np.float32)
ROUND_2 = np.array([.01, .01, .01, .01, .01, .01, .01, .01, .99, .98], dtype=np.float32)

saved = (main.rank, llm.reflect_gap, store.get, config.llm_available,
         config.HOP2_SLOTS, config.AGENTIC_SEARCH, config.WINDOW_RADIUS, config.AUTH_SCHEME)
main.rank = lambda idx, q, o, recall_question=None: ROUND_2 if recall_question else ROUND_1
llm.reflect_gap = lambda q, o, mem: {"status": "INCOMPLETE", "question": "the other thing"}
store.get = lambda uid: index
config.llm_available = lambda: True
config.AGENTIC_SEARCH, config.WINDOW_RADIUS, config.AUTH_SCHEME = False, 0, "none"
request = main.SearchRequest(query="q", user_id="u", top_k=6)

config.HOP2_SLOTS = 0
without = [r["id"] for r in main.search(request, None, None)["data"]]
config.HOP2_SLOTS = 2
withhop = [r["id"] for r in main.search(request, None, None)["data"]]
(main.rank, llm.reflect_gap, store.get, config.llm_available,
 config.HOP2_SLOTS, config.AGENTIC_SEARCH, config.WINDOW_RADIUS, config.AUTH_SCHEME) = saved

ok = True
print("without reserved slots:", without)
print("with 2 reserved:       ", withhop)
ok &= check("aaaaaaaaaaaaaaaa-r8" not in without and "aaaaaaaaaaaaaaaa-r9" not in without,
            "a single round never reaches what only the second query scores")
ok &= check({"aaaaaaaaaaaaaaaa-r8", "aaaaaaaaaaaaaaaa-r9"} <= set(withhop),
            "the reserved slots deliver exactly those memories")
ok &= check(len(withhop) == 6 and len(set(withhop)) == 6,
            "the two rounds together still respect top_k, with no duplicates")
ok &= check(len([i for i in withhop if i in set(without)]) == 4,
            "the first round keeps top_k minus the reservation, and no more")
print("\nOK" if ok else "\nFAILED")
sys.exit(0 if ok else 1)
