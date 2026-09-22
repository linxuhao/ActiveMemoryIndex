"""AMI_SUPERSEDE_MARK: a returned fact that a later, similar fact of the same
user supersedes is rendered with that successor attached. Store text is never
rewritten, raw turns are never marked, the newest version is never marked, and
the successor is the latest one above the threshold, not the most similar.
Run directly: python tests/test_supersede.py
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np
from app import config, main, store

ok = True
def check(cond, label):
    global ok
    print(("  PASS  " if cond else "  FAIL  ") + label); ok &= bool(cond)

def unit(*xs):
    v = np.array(xs, dtype=np.float32); return v / np.linalg.norm(v)

def fact(digest, n, text, stamp):
    return store.Item(id=f"{digest}-f{n}", kind="fact", parent_id=None, content=text, created_at=stamp)

items = [
    fact("a"*16, 0, "[2023-01-05] I lead a team of 4 engineers.", "2023-01-05T10:00:00Z"),
    fact("b"*16, 0, "[2023-03-01] I now lead 5 engineers.", "2023-03-01T10:00:00Z"),
    fact("c"*16, 0, "[2023-06-01] We hired one more, so six engineers.", "2023-06-01T10:00:00Z"),
    fact("d"*16, 0, "[2023-02-01] I adopted a cat.", "2023-02-01T10:00:00Z"),
    store.Item(id="a"*16 + "-r0", kind="raw", parent_id=None,
               content="[2023-01-05] I: I lead a team of 4 engineers.", created_at="2023-01-05T10:00:00Z"),
]
# team facts point one way, the cat another; the raw turn shares the team direction
vecs = np.vstack([unit(1, 0.05), unit(1, 0.10), unit(1, 0.30), unit(0, 1), unit(1, 0.05)])
index = store.UserIndex(); index.append(items, vecs)

saved = (config.SUPERSEDE_MARK, config.SUPERSEDE_TAU)
config.SUPERSEDE_MARK = True
config.SUPERSEDE_TAU = 0.95
marks = main.superseded(index, items)
config.SUPERSEDE_MARK, config.SUPERSEDE_TAU = saved

a, b, c, d, r = (it.id for it in items)
check(a in marks and marks[a].startswith("[superseded on 2023-06-01 by: [2023-06-01] We hired one more"),
      "oldest team fact is marked with the LATEST successor above tau, not the nearest")
check(marks[a].endswith("] [2023-01-05] I lead a team of 4 engineers."), "the old fact's own text follows the marker")
check(b in marks and "2023-06-01" in marks[b], "the middle version is marked with the last one")
check(c not in marks, "the newest version is never marked")
check(d not in marks, "an unrelated fact (cosine 0) is not marked")
check(r not in marks, "raw turns are never marked")
check(items[0].content == "[2023-01-05] I lead a team of 4 engineers.", "stored text is untouched")

config.SUPERSEDE_TAU = 0.999
marks_tight = main.superseded(index, items)
config.SUPERSEDE_TAU = saved[1]
check(marks_tight == {}, "above every similarity nothing is marked")

print("\nOK" if ok else "\nFAILED"); sys.exit(0 if ok else 1)
