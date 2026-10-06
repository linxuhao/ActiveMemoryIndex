"""Token-aware return budget (app/tokens.py): the returned set never exceeds
the Answer window's memory budget, in any delivery mode.

The platform's Answer window has 117,760 input tokens for instructions,
question, options and the returned memories; Answer keeps a token-counted
prefix of what does not fit. These tests use a small window so the bound bites.
"""
import unittest
from unittest.mock import patch

import numpy as np

from app import config, main, store, tokens


def turn(digest, position, text, created="2024-01-01T00:00:00Z"):
    return store.Item(id=f"{digest}-r{position}", kind="raw", parent_id=None, content=text, created_at=created)


def fact(digest, position, text):
    return store.Item(id=f"{digest}-f{position}", kind="fact", parent_id=None, content=text, created_at=None)


def index_of(items):
    index = store.UserIndex()
    rng = np.random.default_rng(0)
    vectors = rng.standard_normal((len(items), 8)).astype(np.float32)
    index.append(items, vectors / np.linalg.norm(vectors, axis=1, keepdims=True))
    return index


def cost(chosen):
    return sum(tokens.item_cost(item.content) for item, _ in chosen)


class TokenBudgetTests(unittest.TestCase):
    def setUp(self):
        self.window = patch.multiple(config, ANSWER_INPUT_TOKENS=3000, ANSWER_PROMPT_TOKENS=500,
                                     ANSWER_ITEM_TOKENS=20, TOKEN_SAFETY=1.15, RETURN_LIMIT=100,
                                     RETURN_CHAR_BUDGET=400000, WINDOW_RADIUS=1, ADAPTIVE_CHUNK=0)
        self.window.start()
        self.addCleanup(self.window.stop)
        tokens.count.cache_clear()

    def test_budget_formula(self):
        usable = int((3000 - 500) / 1.15)
        self.assertEqual(tokens.memory_budget("", None), usable)
        query = "What did I say about the beagle?"
        options = ["Ollie", "Rex"]
        expected = usable - tokens.count(query) - sum(tokens.count(o) + 2 for o in options)
        self.assertEqual(tokens.memory_budget(query, options), expected)

    def test_select_never_exceeds_budget(self):
        items = [turn("a" * 16, n, f"I told you about the trip number {n} " + "word " * (n % 40)) for n in range(300)]
        index = index_of(items)
        scores = np.linspace(1.0, 0.0, len(items))
        for budget in (25, 100, 700, 2173):
            with self.subTest(budget=budget):
                chosen = main.select(index, scores, 100, token_budget=budget)
                self.assertLessEqual(cost(chosen), budget)
                self.assertLessEqual(len(chosen), 100)
        chosen = main.select(index, scores, 100)  # default: the whole window, empty query
        self.assertLessEqual(cost(chosen), tokens.memory_budget())

    def test_first_memory_gets_no_exception(self):
        big = turn("b" * 16, 0, "long " * 400)
        small = turn("c" * 16, 0, "short memory")
        index = index_of([big, small])
        chosen = main.select(index, np.array([1.0, 0.5]), 100, token_budget=60)
        self.assertEqual([item.id for item, _ in chosen], [small.id],
                         "an over-budget first memory is skipped, never cut and never let through")

    def test_cjk_counts_more_tokens_than_chars_suggest(self):
        zh = "我上周末搬到了上海，通勤方便多了。" * 6
        en = "I moved to Shanghai last weekend and the commute is much easier."
        self.assertGreater(tokens.count(zh) / len(zh), tokens.count(en) / len(en) * 1.5)
        items = [turn("d" * 16, n, f"{n}: {zh}") for n in range(60)]
        index = index_of(items)
        scores = np.linspace(1.0, 0.0, len(items))
        budget = 1000
        chosen = main.select(index, scores, 100, token_budget=budget)
        self.assertLessEqual(cost(chosen), budget)
        chars = sum(len(item.content) for item, _ in chosen)
        self.assertLess(chars, budget * 4, "the token budget binds before a chars/4 rule would")

    def test_huge_query_leaves_no_room_and_search_returns_nothing(self):
        huge = "Please read the following task statement carefully. " * 1500
        self.assertLess(tokens.memory_budget(huge, None), 0)
        index = index_of([turn("e" * 16, 0, "I adopted a beagle named Ollie.")])
        request = main.SearchRequest(query=huge, user_id="u", top_k=100)
        with patch.object(main.store, "get", return_value=index), \
                patch.object(main, "rank", side_effect=AssertionError("no upstream call for a full window")):
            self.assertEqual(main._search(request), {"data": []})

    def test_large_query_leaves_little_room(self):
        query = "Which city did I move to?"
        while tokens.memory_budget(query, ["Shanghai", "Beijing"]) > 800:
            query = "Background document. " + query
        budget = tokens.memory_budget(query, ["Shanghai", "Beijing"])
        self.assertGreater(budget, 0)
        self.assertLess(budget, 1000)
        items = [turn("f" * 16, n, f"Turn {n}: I moved to Shanghai and the commute is easier now.") for n in range(200)]
        index = index_of(items)
        request = main.SearchRequest(query=query, user_id="u", top_k=100, options=["Shanghai", "Beijing"])
        with patch.object(main.store, "get", return_value=index), \
                patch.object(main, "rank", return_value=np.linspace(1.0, 0.0, len(items))):
            data = main._search(request)["data"]
        self.assertGreater(len(data), 0)
        self.assertLessEqual(sum(tokens.item_cost(d["content"]) for d in data), budget)
        self.assertLess(len(data), 100)

    def test_output_guard_cuts_a_rerendered_tail(self):
        contents = ["memory one", "memory two " * 50, "three"]
        self.assertEqual(tokens.fit(contents, tokens.item_cost(contents[0])), 1)
        self.assertEqual(tokens.fit(contents, 10_000), 3)
        self.assertEqual(tokens.fit(contents, 0), 0)

    def test_adaptive_chunk_respects_the_budget(self):
        digest = "a1" * 8
        items = [turn(digest, n, f"[2024-01-0{1 + n % 9} 10:00] I: sentence {n} " + "x " * 30) for n in range(12)]
        items += [turn("b2" * 8, n, f"I: other chunk {n} " + "y " * 30) for n in range(12)]
        index = index_of(items)
        scores = np.linspace(1.0, 0.0, len(items))
        with patch.object(config, "ADAPTIVE_CHUNK", 4000):
            chosen = main.select(index, scores, 100, token_budget=400)
            self.assertLessEqual(cost(chosen), 400)
            roomy = main.select(index, scores, 100, token_budget=100_000)
        self.assertEqual(len(roomy), 2, "two chunks, one memory each")

    def test_estimate_is_an_upper_bound_of_o200k(self):
        try:
            import tiktoken
            encoding = tiktoken.get_encoding("o200k_base")
        except Exception:  # noqa: BLE001 - the image bakes it; a bare dev env may not
            self.skipTest("tiktoken o200k_base not available")
        samples = ["I adopted a beagle named Ollie last weekend, and he loves the park.",
                   "我上周末搬到了上海，通勤方便多了。", "今日は東京で友達と会いました。",
                   "Сегодня я встретил друга в Москве.", " ".join(str(n * 7919) for n in range(200)),
                   "def f(x):\n    return {'a': [1, 2, 3]}\n"]
        for text in samples:
            with self.subTest(text=text[:20]):
                self.assertGreaterEqual(tokens.estimate(text), len(encoding.encode(text)))
        self.assertTrue(tokens.backend().startswith("tiktoken:"))


if __name__ == "__main__":
    unittest.main()
