"""Guards on the lexical channel: the two ways hybrid retrieval fails quietly.

1. FTS5's MATCH argument is a query language. A raw question containing `?`,
   `-` or `(` raises `fts5: syntax error`, which would turn every Search into a
   500 at evaluation time.
2. RRF must degrade to exactly the dense order when the lexical channel returns
   nothing, or a corpus with no lexical overlap silently reorders at random.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sqlite3  # noqa: E402

from app import store  # noqa: E402

RAW_QUESTION = "Where did I go with Melanie? (the museum -- Warhol?) 2023-05-02"


def check(condition, label):
    print(("  PASS  " if condition else "  FAIL  ") + label)
    return condition


ok = True

# --- 1. the expression is valid FTS5, whatever the question looks like -------
expression = store.match_expression(RAW_QUESTION)
connection = sqlite3.connect(":memory:")
connection.execute("CREATE VIRTUAL TABLE t USING fts5(content, tokenize='porter unicode61')")
connection.execute("INSERT INTO t(content) VALUES ('I went to the Warhol Museum with Melanie')")
connection.execute("INSERT INTO t(content) VALUES ('unrelated text about bread')")
try:
    hits = [r[0] for r in connection.execute(
        "SELECT rowid FROM t WHERE t MATCH ? ORDER BY bm25(t)", (expression,))]
    syntax_ok = True
except sqlite3.OperationalError:
    hits, syntax_ok = [], False
ok &= check(syntax_ok, "punctuation in a question does not raise fts5 syntax error")
ok &= check(hits and hits[0] == 1, "the matching row is found and ranked first")
ok &= check(store.match_expression("?? -- ()") == "",
            "a question with no word characters yields an empty expression, not a broken one")
ok &= check(store.match_expression("the THE The") == '"the"',
            "repeated terms are emitted once, case-folded")
ok &= check(len(store.match_expression(" ".join(str(n) for n in range(200))).split(" OR ")) == 32,
            "the term count is capped")

# --- 2. RRF properties -------------------------------------------------------
from app import config, main  # noqa: E402

config.HYBRID = True


class FakeIndex:
    def __init__(self, ids):
        self.positions = {item_id: position for position, item_id in enumerate(ids)}


index = FakeIndex(["a", "b", "c", "d"])
dense = np.array([0.9, 0.8, 0.7, 0.1])

store.lexical = lambda user_id, query, limit: []
unchanged = main.fuse_lexical(index, dense, "u", "anything")
ok &= check(np.array_equal(unchanged, dense),
            "no lexical hit leaves the dense scores untouched, not zeroed")

# Adjacent dense ranks differ by ~1/61 - 1/64, so on a small index a single
# lexical hit outweighs the whole dense ordering. That is RRF working as
# specified — the property to guard is not "dense still wins" but "agreement
# between the channels wins".
store.lexical = lambda user_id, query, limit: ["d"]
fused = main.fuse_lexical(index, dense, "u", "anything")
ok &= check(int(np.argmax(fused)) == 3,
            "a row dense ranks last is promoted when BM25 ranks it first")
ok &= check(list(np.argsort(-fused))[1:] == [0, 1, 2],
            "the dense ordering survives intact underneath the promotion")

store.lexical = lambda user_id, query, limit: ["a", "d"]
fused = main.fuse_lexical(index, dense, "u", "anything")
ok &= check(int(np.argmax(fused)) == 0,
            "a row both channels rank first beats a row only BM25 ranks highly")

store.lexical = lambda user_id, query, limit: ["zzz-not-in-this-user"]
fused = main.fuse_lexical(index, dense, "u", "anything")
ok &= check(list(np.argsort(-fused)) == [0, 1, 2, 3],
            "an id absent from the user index is ignored, not an IndexError")

config.HYBRID = False
ok &= check(np.array_equal(main.fuse_lexical(index, dense, "u", "q"), dense),
            "the flag is honoured: hybrid off is exactly dense")

print("\nOK" if ok else "\nFAILED")
sys.exit(0 if ok else 1)
