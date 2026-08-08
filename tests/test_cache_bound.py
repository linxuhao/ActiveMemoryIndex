"""The per-user vector cache must not grow without bound.

A suite whose datasets carry one user_id per question can produce hundreds of
thousands of rows. The cache is a read-through of SQLite, so eviction may cost a
reload but must never cost a result: whatever was written is still returned.
"""
import sys, tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config, store  # noqa: E402


def check(condition, label):
    print(("  PASS  " if condition else "  FAIL  ") + label)
    return condition


ok = True
with tempfile.TemporaryDirectory() as directory:
    config.DB_PATH = str(Path(directory) / "t.sqlite3")
    config.CACHE_MAX_ITEMS = 50
    store._conn = None
    store._cache.clear()
    store._cached_items = 0
    store.init()

    vectors = np.ones((1, 4), dtype=np.float32)
    for u in range(40):                      # 40 users x 1 row = 40 rows, under the cap
        user = f"u{u}"
        item = store.Item(id=store.item_id(f"r{u}", "raw", 0, user), kind="raw",
                          parent_id=None, content=f"memory for user {u}", created_at=None)
        store.add(user, "s", f"r{u}", [item], vectors)

    ok &= check(len(store._cache) == 40, "under the cap nothing is evicted")

    for u in range(40, 100):                 # push well past it
        user = f"u{u}"
        item = store.Item(id=store.item_id(f"r{u}", "raw", 0, user), kind="raw",
                          parent_id=None, content=f"memory for user {u}", created_at=None)
        store.add(user, "s", f"r{u}", [item], vectors)

    ok &= check(store._cached_items <= config.CACHE_MAX_ITEMS,
                "the cache stays within AMI_CACHE_MAX_ITEMS")
    ok &= check(len(store._cache) < 100, "older users were actually dropped")

    # the whole point: an evicted user must still be searchable
    revived = store.get("u0")
    ok &= check(len(revived.items) == 1 and revived.items[0].content == "memory for user 0",
                "an evicted user reloads from SQLite with its memory intact")
    ok &= check(revived.matrix is not None and revived.matrix.shape == (1, 4),
                "its vectors come back too, correctly shaped")

    latest = store.get("u99")
    ok &= check(len(latest.items) == 1, "the most recent user is still served")
    ok &= check(store._cached_items == sum(len(v.items) for v in store._cache.values()),
                "the row counter agrees with the cache it is meant to bound")

print("\nOK" if ok else "\nFAILED")
sys.exit(0 if ok else 1)
