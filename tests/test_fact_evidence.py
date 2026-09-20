"""Guard on a fact bringing its own evidence.

evidence() must (1) fire only for facts, (2) pull the highest-scoring verbatim
turns of the fact's own chunk and no other chunk's, (3) respect the count, and
(4) be a no-op at zero. select() then spends real top_k slots on what it pulls,
so the expansion trades breadth of sources for evidence exactly the way the
neighbour window does — never returning more text than the limit allows.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config, main, store  # noqa: E402


def check(condition, label):
    print(("  PASS  " if condition else "  FAIL  ") + label)
    return condition


A, B = "a" * 16, "b" * 16
# Two chunks, each one fact over three turns. Chunk A's turns are deliberately
# scored below chunk B's fact, so without the expansion they never get returned.
items = [
    store.Item(id=f"{A}-f0", kind="fact", parent_id=None, content="A fact", created_at=None),
    store.Item(id=f"{A}-r0", kind="raw", parent_id=None, content="A turn zero", created_at=None),
    store.Item(id=f"{A}-r1", kind="raw", parent_id=None, content="A turn one", created_at=None),
    store.Item(id=f"{A}-r2", kind="raw", parent_id=None, content="A turn two", created_at=None),
    store.Item(id=f"{B}-f0", kind="fact", parent_id=None, content="B fact", created_at=None),
    store.Item(id=f"{B}-r0", kind="raw", parent_id=None, content="B turn zero", created_at=None),
]
index = store.UserIndex()
index.append(items, np.zeros((len(items), 4), dtype=np.float32))
#             A-f0  A-r0  A-r1  A-r2  B-f0  B-r0
S = np.array([0.90, 0.10, 0.50, 0.30, 0.80, 0.70], dtype=np.float32)

saved = (config.FACT_EVIDENCE, config.WINDOW_RADIUS, config.RAW_FIRST)
config.WINDOW_RADIUS = 0   # isolate the expansion from the neighbour window
config.RAW_FIRST = False   # and from the final reorder
ok = True
try:
    ok &= check(index.by_chunk[A] == [1, 2, 3], "by_chunk indexes a chunk's turns, facts excluded")
    ok &= check(B in index.by_chunk and index.by_chunk[B] == [5], "each chunk is indexed separately")

    config.FACT_EVIDENCE = 0
    ok &= check(main.evidence(index, items[0], S) == [], "zero is a no-op")

    config.FACT_EVIDENCE = 2
    pulled = [it.id for it in main.evidence(index, items[0], S)]
    ok &= check(pulled == [f"{A}-r1", f"{A}-r2"], "pulls its chunk's best turns, best first")
    ok &= check(f"{A}-r0" not in pulled, "the chunk's worst turn is left behind at count 2")
    ok &= check(all(not i.startswith(B) for i in pulled), "never reaches into another chunk")

    ok &= check(main.evidence(index, items[1], S) == [], "a verbatim turn pulls nothing")

    config.FACT_EVIDENCE = 9
    ok &= check(len(main.evidence(index, items[0], S)) == 3, "a count past the chunk takes all of it")

    # End to end: A's turns outscore nothing, so only the expansion can seat them.
    config.FACT_EVIDENCE = 0
    base = [it.id for it, _ in main.select(index, S, 3)]
    ok &= check(base == [f"{A}-f0", f"{B}-f0", f"{B}-r0"], "without it, three slots go to the two chunks' heads")

    config.FACT_EVIDENCE = 2
    arm = [it.id for it, _ in main.select(index, S, 3)]
    ok &= check(arm == [f"{A}-f0", f"{A}-r1", f"{A}-r2"], "with it, the fact seats its own evidence first")
    ok &= check(len(arm) == 3, "the expansion spends slots from top_k, it does not add any")
finally:
    config.FACT_EVIDENCE, config.WINDOW_RADIUS, config.RAW_FIRST = saved

sys.exit(0 if ok else 1)
