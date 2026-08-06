"""Regression tests for the write path under the platform's retry behaviour.

The platform retries Add on 408/409/425/429/5xx, so two attempts at the same
request_id can overlap. It also makes no promise that request_ids are globally
unique across users. Both were live defects; these tests pin the fixes.
"""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["AMI_DB_PATH"] = str(Path(tempfile.mkdtemp()) / "test.sqlite3")

import numpy as np  # noqa: E402

from app import store  # noqa: E402

store.init()
failures = []


def check(condition, label):
    print(("  PASS  " if condition else "  FAIL  ") + label)
    if not condition:
        failures.append(label)


def write(user_id, request_id, n_items, delay=0.0):
    """Mimic main.add(): take the gate, check for a duplicate, then do slow work."""
    with store.request_gate(request_id, user_id):
        if store.request_seen(request_id, user_id):
            return 0
        time.sleep(delay)  # stands in for the LLM call + embedding pass
        items = [
            store.Item(id=store.item_id(request_id, "raw", i, user_id), kind="raw",
                       parent_id=None, content=f"{user_id}/{request_id} item {i}", created_at=None)
            for i in range(n_items)
        ]
        vectors = np.ones((n_items, 4), dtype=np.float32)
        store.add(user_id, "s", request_id, items, vectors)
        return n_items


# 1. Overlapping retries of the same write must not double-store.
threads = [threading.Thread(target=write, args=("u1", "rid-A", 5, 0.3)) for _ in range(3)]
for t in threads:
    t.start()
for t in threads:
    t.join()
index = store.get("u1")
rows = store._conn.execute("SELECT COUNT(*) FROM items WHERE user_id='u1'").fetchone()[0]
check(rows == 5, f"overlapping retries store the chunk once in SQLite (got {rows})")
check(len(index.items) == 5, f"the in-process cache agrees with SQLite (got {len(index.items)})")
check(index.matrix.shape[0] == len(index.items), "cache vectors stay aligned with cache items")

# 2. The same request_id from a different user is a different write.
write("u2", "rid-A", 3)
u2 = store.get("u2")
check(len(u2.items) == 3, f"a colliding request_id from another user is still stored (got {len(u2.items)})")
check(len(store.get("u1").items) == 5, "the first user's rows are untouched by the collision")
ids1 = {i.id for i in store.get("u1").items}
ids2 = {i.id for i in u2.items}
check(not (ids1 & ids2), "item ids from different users never collide")
check(all("u1/" in i.content for i in store.get("u1").items), "no row moved between users")

# 3. A genuine duplicate is still a no-op.
check(write("u1", "rid-A", 5) == 0, "a later duplicate of a completed write is skipped")

print("\nOK" if not failures else f"\n{len(failures)} FAILED")
sys.exit(0 if not failures else 1)
