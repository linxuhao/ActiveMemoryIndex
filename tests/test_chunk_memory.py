"""Guard on fact-only selection and whole-chunk delivery.

FACT_SELECT must rule verbatim turns out of *selection* without ruling them out
of the *response* -- they come back inside their chunk. CHUNK_MEMORY must return
each selected memory's whole chunk, verbatim and in order, as one slot, and must
dedup so several facts from one chunk do not return it several times.

The invariant under test: the content returned is the stored text concatenated.
Nothing is rewritten, so the query still only selects.
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
items = [
    store.Item(id=f"{A}-r0", kind="raw", parent_id=None, content="A zero", created_at="t0"),
    store.Item(id=f"{A}-r1", kind="raw", parent_id=None, content="A one", created_at="t1"),
    store.Item(id=f"{A}-f0", kind="fact", parent_id=None, content="A fact one", created_at="t0"),
    store.Item(id=f"{A}-f1", kind="fact", parent_id=None, content="A fact two", created_at="t0"),
    store.Item(id=f"{B}-r0", kind="raw", parent_id=None, content="B zero", created_at="t2"),
    store.Item(id=f"{B}-f0", kind="fact", parent_id=None, content="B fact", created_at="t2"),
]
index = store.UserIndex()
index.append(items, np.zeros((len(items), 4), dtype=np.float32))
#             A-r0  A-r1  A-f0  A-f1  B-r0  B-f0
S = np.array([0.95, 0.90, 0.60, 0.55, 0.85, 0.50], dtype=np.float32)

saved = (config.FACT_SELECT, config.CHUNK_MEMORY, config.WINDOW_RADIUS,
         config.FACT_EVIDENCE, config.RAW_FIRST)
config.WINDOW_RADIUS = 0
config.FACT_EVIDENCE = 0
config.RAW_FIRST = False
ok = True
try:
    config.FACT_SELECT = False
    config.CHUNK_MEMORY = True
    got = main.select(index, S, 10)
    ids = [it.id for it, _ in got]
    ok &= check(ids == [f"{A}-c0", f"{B}-c0"], "chunk delivery dedups: six items become two chunks")
    ok &= check(got[0][0].content == "A zero\nA one", "the chunk is its turns, verbatim and in order")
    ok &= check(got[0][0].kind == "chunk" and got[0][0].created_at == "t0",
                "kind and created_at come from the chunk's first turn")
    ok &= check("A fact one" not in got[0][0].content, "facts are not folded into the chunk text")

    ok &= check([it.id for it, _ in main.select(index, S, 1)] == [f"{A}-c0"],
                "a chunk costs exactly one slot, so top_k=1 returns one chunk")

    config.FACT_SELECT = True
    # rank() applies this mask itself, but it needs a live embedder; the mask is
    # the whole of what FACT_SELECT does to the scores, so apply it directly.
    masked = np.where(np.fromiter((i.kind != "fact" for i in index.items), bool, len(items)), -np.inf, S)
    got = main.select(index, masked, 10)
    ok &= check([it.id for it, _ in got] == [f"{A}-c0", f"{B}-c0"],
                "fact selection still reaches both chunks")
    ok &= check(got[0][0].content == "A zero\nA one",
                "and delivers verbatim turns, which selection had excluded")

    config.CHUNK_MEMORY = False
    got = main.select(index, masked, 10)
    ok &= check([it.id for it, _ in got] == [f"{A}-f0", f"{A}-f1", f"{B}-f0"],
                "fact selection alone returns only facts, never a turn")
    ok &= check(len(got) == 3, "excluded items do not fill the remaining limit")
finally:
    (config.FACT_SELECT, config.CHUNK_MEMORY, config.WINDOW_RADIUS,
     config.FACT_EVIDENCE, config.RAW_FIRST) = saved

sys.exit(0 if ok else 1)
