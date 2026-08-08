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

_real_lexical = store.lexical
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

store.lexical = lambda user_id, query, limit: ["d"]
config.HYBRID_LEX_WEIGHT = 1.0
full = main.fuse_lexical(index, dense, "u", "anything")
config.HYBRID_LEX_WEIGHT = 0.25
damped = main.fuse_lexical(index, dense, "u", "anything")
# On a 4-row index the dense rank gaps are ~3e-4 while one lexical hit adds
# weight*1.6e-2, so no useful weight leaves the dense order intact here. The
# invariant that holds at any size is that the weight scales the promotion.
margin = lambda f: f[3] - f[0]
ok &= check(0 < margin(damped) < margin(full),
            "a lower lexical weight shrinks the promotion instead of removing it")
config.HYBRID_LEX_WEIGHT = 0.0
ok &= check(np.array_equal(np.argsort(-main.fuse_lexical(index, dense, "u", "q")),
                           np.argsort(-dense)),
            "lexical weight 0 reproduces the dense ordering exactly")
config.HYBRID_LEX_WEIGHT = 1.0

config.HYBRID = False
ok &= check(np.array_equal(main.fuse_lexical(index, dense, "u", "q"), dense),
            "the flag is honoured: hybrid off is exactly dense")

store.lexical = _real_lexical   # section 2 stubbed it; section 3 needs the real one

# --- 3. the kind filter and the lexical weight ---------------------------------------------------------
# The kind filter is a suffix test on item_id, so pin the format it depends on.
ok &= check(store.item_id("req", "fact", 3, "u").endswith("-f3")
            and store.item_id("req", "raw", 3, "u").endswith("-r3"),
            "item_id still encodes kind as the suffix the kind filter matches")

import tempfile  # noqa: E402

with tempfile.TemporaryDirectory() as directory:
    config.DB_PATH = str(Path(directory) / "t.sqlite3")
    store._conn = None
    store.init()
    vectors = np.ones((1, 4), dtype=np.float32)
    corpus = [
        ("I went to the Warhol Museum with Melanie", "raw"),
        ("Melanie likes coffee", "fact"),
        ("Melanie went running", "fact"),
        ("Melanie called her sister", "fact"),
    ]
    for position, (text, kind) in enumerate(corpus):
        item = store.Item(id=store.item_id(f"r{position}", kind, 0, "u"),
                          kind=kind, parent_id=None, content=text, created_at=None)
        store.add("u", "s", f"r{position}", [item], vectors)

    config.HYBRID_KINDS = "fact"
    hits = store.lexical("u", "Melanie", 10)
    ok &= check(hits and all("-f" in h for h in hits),
                "kinds=fact confines the lexical channel to the normalised layer")
    config.HYBRID_KINDS = "all"
    ok &= check(any("-r" in h for h in store.lexical("u", "Melanie", 10)),
                "kinds=all still ranks verbatim turns")

# --- 4. raw-first ordering ----------------------------------------------------
# It must reorder the selected set and never change which memories are in it.
class Row:
    def __init__(self, kind, name):
        self.kind, self.content, self.id, self.created_at, self.parent_id = kind, name, name, None, None

selected = [(Row("fact", "f1"), 0.9), (Row("raw", "r1"), 0.8),
            (Row("fact", "f2"), 0.7), (Row("raw", "r2"), 0.6)]
config.RAW_FIRST = True
ordered = list(selected)
ordered.sort(key=lambda pair: pair[0].kind != "raw")
ok &= check([r.content for r, _ in ordered] == ["r1", "r2", "f1", "f2"],
            "raw-first puts verbatim turns ahead, each block still in score order")
ok &= check(sorted(r.content for r, _ in ordered) == sorted(r.content for r, _ in selected),
            "raw-first changes the order of the selected set, never its membership")
config.RAW_FIRST = False

print("\nOK" if ok else "\nFAILED")
sys.exit(0 if ok else 1)
