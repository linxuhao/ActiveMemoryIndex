"""AMI_ADAPTIVE_CHUNK (lead L4): a selected turn is delivered as its whole Add
chunk when the chunk is small, else as a merged span of neighbours; nothing is
rewritten, withheld turns stay out, and every bound still holds."""
import unittest
from unittest.mock import patch

import numpy as np

from app import config, main, store, tokens

SMALL, LARGE, OTHER = "a" * 16, "b" * 16, "c" * 16


def turn(digest, position, text):
    return store.Item(id=f"{digest}-r{position}", kind="raw", parent_id=None,
                      content=f"[2024-01-01 10:{position:02d}] I: {text}", created_at=f"2024-01-01T10:{position:02d}:00Z")


def fact(digest, position, text):
    return store.Item(id=f"{digest}-f{position}", kind="fact", parent_id=None, content=text, created_at=None)


def build(items):
    index = store.UserIndex()
    vectors = np.eye(len(items), 8, dtype=np.float32) + 0.01
    index.append(items, vectors / np.linalg.norm(vectors, axis=1, keepdims=True))
    return index


class AdaptiveChunkTests(unittest.TestCase):
    def setUp(self):
        self.small = [turn(SMALL, n, f"small chunk turn {n}") for n in range(5)]
        self.large = [turn(LARGE, n, f"large chunk turn {n} " + "z" * 900) for n in range(10)]
        self.other = [turn(OTHER, n, f"other chunk turn {n}") for n in range(3)]
        self.facts = [fact(SMALL, 0, "I like small chunks."), fact(LARGE, 0, "I like large chunks.")]
        self.items = self.small + self.large + self.other + self.facts
        self.index = build(self.items)
        self.config = patch.multiple(config, ADAPTIVE_CHUNK=4000, WINDOW_RADIUS=1,
                                     RETURN_LIMIT=100, RETURN_CHAR_BUDGET=400_000, RAW_FIRST=True,
                                     CHUNK_MEMORY=False, CHRONO_ORDER=False, NEWEST_FIRST=False)
        self.config.start()
        self.addCleanup(self.config.stop)

    def scores(self, ranked_ids):
        """Scores that rank *ranked_ids* first, in that order; everything else after."""
        out = np.full(len(self.items), -np.inf)
        for position, ident in enumerate(ranked_ids):
            out[self.index.by_id[ident]] = 1.0 - position / 100
        return out

    def ids(self, chosen):
        return [item.id for item, _ in chosen]

    def test_off_by_default(self):
        with patch.object(config, "ADAPTIVE_CHUNK", 0):
            chosen = main.select(self.index, self.scores([f"{SMALL}-r2"]), 3)
        self.assertEqual(self.ids(chosen)[0], f"{SMALL}-r2", "shipped turn-by-turn delivery")

    def test_small_chunk_is_one_memory_of_its_turns_verbatim(self):
        chosen = main.select(self.index, self.scores([f"{SMALL}-r2", f"{SMALL}-r4"]), 2)
        item = chosen[0][0]
        self.assertEqual(item.id, f"{SMALL}-c0")
        self.assertEqual(item.kind, "chunk")
        self.assertEqual(item.content, "\n".join(t.content for t in self.small), "stored turns, in order, unchanged")
        self.assertNotIn(f"{SMALL}-c0", self.ids(chosen)[1:], "a second hit in the same chunk costs nothing")
        self.assertEqual(item.created_at, self.small[0].created_at)

    def test_large_chunk_becomes_a_contiguous_span_within_the_size(self):
        chosen = main.select(self.index, self.scores([f"{LARGE}-r5"]), 1)
        item = chosen[0][0]
        self.assertEqual(item.id, f"{LARGE}-s4-6")
        self.assertEqual(item.content, "\n".join(t.content for t in self.large[4:7]))
        self.assertLessEqual(len(item.content), 4000)
        with patch.object(config, "ADAPTIVE_CHUNK", 1500):
            (only,) = main.select(self.index, self.scores([f"{LARGE}-r5"]), 1)
        self.assertEqual(only[0].id, f"{LARGE}-s5-5", "neighbours join only while the span fits; the hit always")

    def test_touching_spans_of_one_chunk_merge_in_place(self):
        chosen = main.select(self.index, self.scores([f"{LARGE}-r2", f"{OTHER}-r1", f"{LARGE}-r5"]), 3)
        ids = self.ids(chosen)
        self.assertIn(f"{LARGE}-s1-6", ids, "spans 1-3 and 4-6 touch, so they are one memory")
        self.assertEqual(sum(i.startswith(LARGE) for i in ids), 1)
        merged = next(item for item, _ in chosen if item.id == f"{LARGE}-s1-6")
        self.assertEqual(merged.content, "\n".join(t.content for t in self.large[1:7]))

    def test_withheld_turns_stay_out_of_chunks_and_spans(self):
        withheld = {f"{SMALL}-r1", f"{LARGE}-r4"}
        chosen = main.select(self.index, self.scores([f"{SMALL}-r2", f"{LARGE}-r5", f"{SMALL}-r1"]), 3,
                             withheld=withheld)
        text = "\n".join(item.content for item, _ in chosen)
        for ident in withheld:
            self.assertNotIn(self.items[self.index.by_id[ident]].content, text)
        chunk = next(item for item, _ in chosen if item.id == f"{SMALL}-c0")
        self.assertEqual(chunk.content, "\n".join(t.content for t in self.small if t.id not in withheld))
        self.assertIn(f"{LARGE}-s5-6", self.ids(chosen), "the span does not reach across a withheld turn")

    def test_bounds_hold(self):
        ranked = [f"{LARGE}-r{n}" for n in range(0, 10, 3)] + [f"{OTHER}-r0", f"{SMALL}-r0"]
        self.assertLessEqual(len(main.select(self.index, self.scores(ranked), 2)), 2)
        with patch.object(config, "RETURN_CHAR_BUDGET", 2500):
            chosen = main.select(self.index, self.scores(ranked), 100)
            self.assertLessEqual(sum(len(i.content) for i, _ in chosen), 2500)
        chosen = main.select(self.index, self.scores(ranked), 100, token_budget=300)
        self.assertLessEqual(sum(tokens.item_cost(i.content) for i, _ in chosen), 300)

    def test_no_separate_total_cap(self):
        """rc5: no 120,000-character cap of its own; the general budgets bound it."""
        self.assertFalse(hasattr(config, "ADAPTIVE_CHUNK_TOTAL"))
        words = " ".join(f"word{k}" for k in range(150))
        items = [turn(f"{n:016x}", p, f"chunk {n} turn {p} {words}") for n in range(60) for p in range(3)]
        index = build(items)
        scores = np.linspace(1.0, 0.5, len(items))
        chosen = main.select(index, scores, 100)
        delivered = sum(len(i.content) for i, _ in chosen)
        self.assertEqual(len(chosen), 60, "every chunk fits: one memory each")
        self.assertGreater(delivered, 120_000)
        self.assertLessEqual(sum(tokens.item_cost(i.content) for i, _ in chosen), tokens.memory_budget())
        chosen = main.select(index, scores, 100, token_budget=20_000)
        self.assertLessEqual(sum(tokens.item_cost(i.content) for i, _ in chosen), 20_000)

    def test_turns_first_then_facts(self):
        chosen = main.select(self.index, self.scores([self.facts[0].id, f"{OTHER}-r1", self.facts[1].id]), 10)
        kinds = [item.kind for item, _ in chosen]
        self.assertEqual(kinds[:1], ["chunk"])
        self.assertEqual(kinds[-2:], ["fact", "fact"])

    def test_every_delivered_line_is_a_stored_turn(self):
        stored = {item.content for item in self.items}
        rng = np.random.default_rng(3)
        for _ in range(20):
            chosen = main.select(self.index, rng.random(len(self.items)), 100,
                                 withheld={f"{LARGE}-r{int(rng.integers(10))}"})
            for item, _ in chosen:
                if item.kind == "chunk":
                    for line in item.content.split("\n"):
                        self.assertIn(line, stored)


if __name__ == "__main__":
    unittest.main()
