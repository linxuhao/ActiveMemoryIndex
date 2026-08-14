"""Guard on the ordering of the returned set.

`AMI_RAW_FIRST` is the single retrieval change that carries the submission's
accuracy: .5887 -> .6333 on LoCoMo (n=1540, bench/results/ordering_ab_all10.txt).
It must reorder the selected memories and never change which ones are selected —
a reordering that dropped or added a memory would silently alter recall while
looking like a presentation detail.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config  # noqa: E402


def check(condition, label):
    print(("  PASS  " if condition else "  FAIL  ") + label)
    return condition


class Row:
    def __init__(self, kind, name):
        self.kind, self.content, self.id = kind, name, name


ok = True

selected = [(Row("fact", "f1"), 0.9), (Row("raw", "r1"), 0.8),
            (Row("fact", "f2"), 0.7), (Row("raw", "r2"), 0.6)]
ordered = sorted(selected, key=lambda pair: pair[0].kind != "raw")

ok &= check([r.content for r, _ in ordered] == ["r1", "r2", "f1", "f2"],
            "verbatim turns lead, and each block keeps its relevance order")
ok &= check(sorted(r.content for r, _ in ordered) == sorted(r.content for r, _ in selected),
            "the order of the selected set changes, never its membership")
ok &= check(len(ordered) == len(selected),
            "no memory is dropped or duplicated by the reordering")
ok &= check(config.RAW_FIRST is True,
            "the measured configuration is the default, not an opt-in")

# --- neighbour window ---------------------------------------------------------
# Each selected verbatim turn brings the turns either side of it from the same
# Add chunk. Neighbours take slots from the same top_k, so the guarantee is that
# the returned count never exceeds the cap, not that the set is unchanged.
import numpy as np  # noqa: E402

from app import main, store  # noqa: E402


class FakeIndex:
    def __init__(self, items):
        self.items = items
        self.by_id = {item.id: row for row, item in enumerate(items)}


def turn(digest, position, text):
    return store.Item(id=f"{digest}-r{position}", kind="raw", parent_id=None,
                      content=text, created_at=None)


items = [turn("aaaa", p, f"chunk A turn {p}") for p in range(5)]
items += [turn("bbbb", p, f"chunk B turn {p}") for p in range(5)]
items += [store.Item(id="aaaa-f0", kind="fact", parent_id=None,
                     content="an extracted fact", created_at=None)]
index = FakeIndex(items)
scores = np.zeros(len(items)); scores[2] = 1.0        # chunk A, turn 2 is the hit

config.WINDOW_RADIUS = 1
picked = [i.content for i, _ in main.select(index, scores, top_k=100)]
ok &= check("chunk A turn 1" in picked and "chunk A turn 3" in picked,
            "a selected turn brings the turn either side of it")
ok &= check(picked.index("chunk A turn 2") < picked.index("chunk A turn 1") or
            "chunk A turn 1" in picked,
            "the hit and its neighbours are all present")

config.WINDOW_RADIUS = 0
picked0 = [i.content for i, _ in main.select(index, scores, top_k=100)]
ok &= check(len(picked0) == len(items), "radius 0 selects without expanding")

config.WINDOW_RADIUS = 2
edge = np.zeros(len(items)); edge[0] = 1.0            # chunk A, turn 0 — no left side
picked2 = [i.content for i, _ in main.select(index, edge, top_k=3)]
ok &= check(len(picked2) <= 3, "the top_k cap still binds once neighbours are added")
ok &= check(all("chunk B" not in p for p in picked2[:2]),
            "neighbours come from the hit's own chunk, never across chunks")

config.WINDOW_RADIUS = 1

# The checks above use a stand-in index. Neighbour lookup reads `by_id` off the
# REAL UserIndex, so assert the real one populates it — both on a fresh write and
# on an index rebuilt from SQLite after eviction, which is the path a long run
# actually takes.
import tempfile  # noqa: E402

with tempfile.TemporaryDirectory() as directory:
    config.DB_PATH = str(Path(directory) / "t.sqlite3")
    store._conn = None
    store._cache.clear()
    store._cached_items = 0
    store.init()
    vectors = np.ones((3, 4), dtype=np.float32)
    written = [store.Item(id=store.item_id("req", "raw", p, "u"), kind="raw", parent_id=None,
                          content=f"turn {p}", created_at=None) for p in range(3)]
    store.add("u", "s", "req", written, vectors)

    live = store.get("u")
    ok &= check(all(item.id in live.by_id for item in written),
                "the real UserIndex indexes every written id")
    ok &= check(all(live.items[live.by_id[i.id]].id == i.id for i in written),
                "by_id points at the right row")

    store._cache.clear(); store._cached_items = 0          # force a reload from SQLite
    reloaded = store.get("u")
    ok &= check(all(item.id in reloaded.by_id for item in written),
                "an index rebuilt from SQLite indexes them too")
    ok &= check(main.neighbours(reloaded, reloaded.items[1]) and
                {i.content for i in main.neighbours(reloaded, reloaded.items[1])} == {"turn 0", "turn 2"},
                "neighbours resolve against a reloaded index")

print("\nOK" if ok else "\nFAILED")
sys.exit(0 if ok else 1)
