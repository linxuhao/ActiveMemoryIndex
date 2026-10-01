"""Vector identity and fail-closed persistence checks, entirely offline."""
from __future__ import annotations

from collections import OrderedDict
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from app import config, embed, store


class EmbeddingStoreIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temporary.name) / "identity.sqlite3")
        self.saved = (store._conn, store._cache, store._cached_items,
                      store._embedding_dimensions)
        store._conn = None
        store._cache = OrderedDict()
        store._cached_items = 0
        store._embedding_dimensions = None
        self.identity = {
            "backend": "openai", "model": "text-embedding-v4",
            "dimensions": 384, "base_url": "http://mock.invalid/v1",
            "query_preprocess": "identity",
            "chunk_strategy": "utf8-2048-bytes-byte-weighted-normalized-mean-v1",
        }
        self.path_patch = patch.object(config, "DB_PATH", self.path)
        self.identity_patch = patch.object(
            embed, "embedding_identity", side_effect=lambda: copy.deepcopy(self.identity),
            create=True)
        self.path_patch.start()
        self.identity_patch.start()

    def tearDown(self):
        if store._conn is not None:
            store._conn.close()
        store._conn, store._cache, store._cached_items, store._embedding_dimensions = self.saved
        self.identity_patch.stop()
        self.path_patch.stop()
        self.temporary.cleanup()

    def close(self):
        if store._conn is not None:
            store._conn.close()
        store._conn = None
        store._cache.clear()
        store._cached_items = 0
        store._embedding_dimensions = None

    def item(self, user="user", request="request"):
        return store.Item(store.item_id(request, "raw", 0, user), "raw", None,
                          "I adopted Ollie.", None)

    def vector(self, dimensions=384):
        result = np.zeros((1, dimensions), dtype=np.float32)
        result[0, 0] = 1
        return result

    def populate(self):
        store.init()
        item = self.item()
        store.add("user", "session", "request", [item], self.vector())
        return item

    def snapshot(self):
        return {
            "items": store._conn.execute("SELECT * FROM items ORDER BY id").fetchall(),
            "requests": store._conn.execute("SELECT * FROM requests ORDER BY user_id,request_id").fetchall(),
            "cache": [(user, tuple(i.id for i in index.items),
                       None if index.matrix is None else index.matrix.tobytes())
                      for user, index in store._cache.items()],
            "cached_items": store._cached_items,
        }

    def test_fresh_remote_store_records_exact_identity(self):
        store.init()
        saved = store._conn.execute(
            "SELECT value FROM embedding_metadata WHERE key='identity'").fetchone()[0]
        self.assertEqual(json.loads(saved), self.identity)
        self.assertEqual(store._embedding_dimensions, 384)
        self.assertEqual(store.stats(), {"users": 0, "items": 0})

    def test_reopen_same_identity_preserves_searchable_vectors(self):
        item = self.populate()
        self.close()
        store.init()
        index = store.get("user")
        self.assertEqual([i.id for i in index.items], [item.id])
        np.testing.assert_array_equal(index.matrix, self.vector())
        self.assertTrue(store.request_seen("request", "user"))

    def test_changed_same_dimension_identity_is_rejected(self):
        self.populate()
        self.close()
        original = copy.deepcopy(self.identity)
        mutations = {
            "backend": "bge", "model": "different-model",
            "base_url": "http://other.invalid/v1", "query_preprocess": "search: ",
            "chunk_strategy": "different-pooling-strategy",
        }
        for field, value in mutations.items():
            with self.subTest(field=field):
                self.identity = {**original, field: value}
                with self.assertRaisesRegex(RuntimeError, "identity differs"):
                    store.init()
                self.assertIsNone(store._conn)
                self.assertIsNone(store._embedding_dimensions)
        self.identity = original
        store.init()
        self.assertEqual(store.stats()["items"], 1)

    def test_changed_dimensions_is_rejected(self):
        self.populate()
        self.close()
        self.identity["dimensions"] = 768
        with self.assertRaisesRegex(RuntimeError, "identity differs"):
            store.init()
        self.assertIsNone(store._conn)

    def make_unlabelled_legacy(self):
        self.populate()
        store._conn.execute("DELETE FROM embedding_metadata")
        store._conn.commit()
        self.close()

    def test_unlabelled_remote_rejected_even_with_compatible_384_dimensions(self):
        self.make_unlabelled_legacy()
        with self.assertRaisesRegex(RuntimeError, "Unlabelled vector database"):
            store.init()
        self.assertIsNone(store._conn)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM items").fetchone()[0], 1)
            self.assertIsNone(db.execute("SELECT value FROM embedding_metadata").fetchone())

    def test_unlabelled_legacy_local_bge_remains_readable(self):
        self.make_unlabelled_legacy()
        self.identity = {"backend": "bge", "model": "BAAI/bge-small-en-v1.5",
                         "dimensions": 384, "query_preprocess": embed.QUERY_PREFIX}
        store.init()
        np.testing.assert_array_equal(store.get("user").matrix, self.vector())
        self.assertIsNone(store._conn.execute("SELECT value FROM embedding_metadata").fetchone())

    def test_local_fake_four_dimensional_vectors_still_work(self):
        self.identity["backend"] = "bge"
        self.identity["model"] = "BAAI/bge-small-en-v1.5"
        store.init()
        store.add("user", "session", "request", [self.item()], self.vector(4))
        store._cache.clear()
        store._cached_items = 0
        np.testing.assert_array_equal(store.get("user").matrix, self.vector(4))

    def test_wrong_blob_length_rejected_when_reopening_remote_store(self):
        self.populate()
        store._conn.execute("UPDATE items SET vec=?", (self.vector(4).tobytes(),))
        store._conn.commit()
        self.close()
        with self.assertRaisesRegex(RuntimeError, "Stored vector dimensions"):
            store.init()
        self.assertIsNone(store._conn)

    def test_failed_init_does_not_leave_connection_or_dimensions_and_can_retry(self):
        with patch.object(store, "_bind_embedding_identity", side_effect=RuntimeError("injected")):
            with self.assertRaisesRegex(RuntimeError, "injected"):
                store.init()
        self.assertIsNone(store._conn)
        self.assertIsNone(store._embedding_dimensions)
        self.assertEqual(store._cached_items, 0)
        store.init()
        self.assertEqual(store.stats()["items"], 0)

    def test_invalid_add_leaves_rows_requests_and_cache_unchanged(self):
        self.populate()
        before = self.snapshot()
        nan = self.vector(); nan[0, 1] = np.nan
        infinity = self.vector(); infinity[0, 1] = np.inf
        invalid = [self.vector(4), np.zeros((1, 384), dtype=np.float32),
                   np.zeros((2, 384), dtype=np.float32),
                   np.zeros(384, dtype=np.float32), self.vector().astype(np.float64),
                   self.vector().astype(np.int32), nan, infinity]
        for vectors in invalid:
            with self.subTest(shape=vectors.shape, dtype=str(vectors.dtype)):
                with self.assertRaises(ValueError):
                    store.add("unseen-user", "session", "bad-request",
                              [self.item("unseen-user", "bad-request")], vectors)
                self.assertEqual(self.snapshot(), before)
                self.assertFalse(store.request_seen("bad-request", "unseen-user"))

    def test_remote_load_rejects_corrupted_vectors_without_populating_cache(self):
        self.populate()
        store._cache.clear(); store._cached_items = 0
        nan = self.vector(); nan[0, 1] = np.nan
        infinity = self.vector(); infinity[0, 1] = np.inf
        for vectors in [nan, infinity, np.zeros((1, 384), dtype=np.float32), self.vector(4)]:
            with self.subTest(shape=vectors.shape, finite=bool(np.isfinite(vectors).all())):
                store._conn.execute("UPDATE items SET vec=?", (vectors.tobytes(),))
                store._conn.commit()
                with self.assertRaises((RuntimeError, ValueError)):
                    store.get("user")
                self.assertNotIn("user", store._cache)
                self.assertEqual(store._cached_items, 0)


if __name__ == "__main__":
    unittest.main()
