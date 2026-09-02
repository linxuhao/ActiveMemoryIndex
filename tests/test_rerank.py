"""Guard on cross-encoder rescoring.

rescore() must (1) order the candidate pool by the cross-encoder alone, (2) keep
everything outside the pool beneath it in its original order, and (3) leave the
scores untouched when AMI_RERANK_MODEL is empty. select() then reads the result
like any other score array, so the pool comes out first.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config, main, rerank, store  # noqa: E402


def check(condition, label):
    print(("  PASS  " if condition else "  FAIL  ") + label)
    return condition


items = [store.Item(id=f"aaaaaaaaaaaaaaaa-f{p}", kind="fact", parent_id=None,
                    content=f"fact {p}", created_at=None) for p in range(10)]
index = store.UserIndex()
index.append(items, np.zeros((len(items), 4), dtype=np.float32))
BI = np.array([.9, .8, .7, .6, .5, .4, .3, .2, .1, .0], dtype=np.float32)

saved = (rerank.score_pairs, config.RERANK_CANDIDATES, config.RERANK_MODEL, config.WINDOW_RADIUS)
# The cross-encoder disagrees with the bi-encoder: within the pool, later is better.
rerank.score_pairs = lambda q, passages: np.array([float(p.split()[-1]) for p in passages], dtype=np.float32)
config.RERANK_CANDIDATES = 4
config.WINDOW_RADIUS = 0
ok = True
try:
    out = rerank.rescore(index, "q", BI)
    ranking = [int(i) for i in np.argsort(-out)]
    ok &= check(ranking[:4] == [3, 2, 1, 0], "pool ordered by the cross-encoder, not the bi-encoder")
    ok &= check(ranking[4:] == [4, 5, 6, 7, 8, 9], "rest keeps its bi-encoder order beneath the pool")
    ok &= check(float(out[3]) > 0 > float(out[4]), "pool and rest never interleave")

    chosen = main.select(index, out, 10)
    ok &= check([it.id for it, _ in chosen][:4] == [items[i].id for i in (3, 2, 1, 0)],
                "select() draws the pool first, in cross-encoder order")

    config.RERANK_CANDIDATES = 50
    out = rerank.rescore(index, "q", BI)
    ok &= check([int(i) for i in np.argsort(-out)] == list(range(9, -1, -1)),
                "pool larger than the index reranks everything")

    config.RERANK_CANDIDATES = 0
    ok &= check(rerank.rescore(index, "q", BI) is BI, "zero candidates is a no-op")
finally:
    rerank.score_pairs, config.RERANK_CANDIDATES, config.RERANK_MODEL, config.WINDOW_RADIUS = saved

sys.exit(0 if ok else 1)
