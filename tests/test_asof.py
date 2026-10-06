"""As-of evidence selection (AMI_ASOF_SELECT): membership only, router-decided,
multilingual dates, relative-time grace, refill from the ranking."""
import datetime as dt
import json
import types
import unittest
from unittest.mock import patch

import numpy as np

from app import asof, config, llm, main, store

D = dt.date


def turn(n, said, text, digest="a" * 16):
    return store.Item(id=f"{digest}-r{n}", kind="raw", parent_id=None, content=f"[{said} 10:00] I: {text}",
                      created_at=f"{said}T10:00:00Z")


class Router:
    """llm.classify_asof stand-in recording its calls."""

    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def __call__(self, query, options):
        self.calls.append(query)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


class ParsingTests(unittest.TestCase):
    def test_formats(self):
        cases = {
            "What was Maya's job title as of September 5, 2025?": (D(2025, 9, 5), D(2025, 9, 5)),
            "Where did she live on 5th Sept. 2025?": (D(2025, 9, 5), D(2025, 9, 5)),
            "Which party did he belong to in Jan, 1976?": (D(1976, 1, 1), D(1976, 1, 31)),
            "Where did she live in March 2025?": (D(2025, 3, 1), D(2025, 3, 31)),
            "Status on 2024-02-29?": (D(2024, 2, 29), D(2024, 2, 29)),
            "截至2025年9月5日，他的职位是什么？": (D(2025, 9, 5), D(2025, 9, 5)),
            "2024年1月时他住在哪里？": (D(2024, 1, 1), D(2024, 1, 31)),
            "2019年他在哪家公司？": (D(2019, 1, 1), D(2019, 12, 31)),
            "2023년 5월 8일에 그는 어디에 살았나요?": (D(2023, 5, 8), D(2023, 5, 8)),
            "¿Dónde vivía en marzo de 2019?": (D(2019, 3, 1), D(2019, 3, 31)),
            "¿Cuál era su cargo el 3 de julio de 2023?": (D(2023, 7, 3), D(2023, 7, 3)),
            "Quel était son poste en janvier 1976 ?": (D(1976, 1, 1), D(1976, 1, 31)),
            "Wo wohnte sie am 5. Januar 1976?": (D(1976, 1, 5), D(1976, 1, 5)),
            "Onde ele morava em março de 2020?": (D(2020, 3, 1), D(2020, 3, 31)),
            "Dove viveva il 12.03.2021?": (D(2021, 3, 12), D(2021, 3, 12)),
            "What did I do in 2019?": (D(2019, 1, 1), D(2019, 12, 31)),
        }
        for query, want in cases.items():
            with self.subTest(query=query):
                self.assertEqual(asof.candidate(query), want)

    def test_no_year_no_candidate(self):
        for query in ("How many days ago did I buy the plant?", "What was my title last March?",
                      "我上个月住在哪里？", "I bought 1,250 followers' worth"):
            with self.subTest(query=query):
                self.assertIsNone(asof.candidate(query))

    def test_ranges(self):
        self.assertEqual(asof.ranges("X works for A from Jan, 1946 to Jan, 1949."), [(D(1946, 1, 1), D(1949, 1, 31))])
        self.assertEqual(asof.ranges("他从2019年3月到2021年6月在北京工作。"), [(D(2019, 3, 1), D(2021, 6, 30))])
        self.assertEqual(asof.ranges("between 2001 and 2003"), [(D(2001, 1, 1), D(2003, 12, 31))])
        self.assertEqual(asof.ranges("I met Ann in 2001 and Bob in 2003"), [])

    def test_router_cannot_narrow_a_parsed_month(self):
        month = (D(2025, 8, 1), D(2025, 8, 31))
        self.assertEqual(asof.combine(month, (D(2025, 8, 1), D(2025, 8, 1))), month)
        year = (D(2019, 1, 1), D(2019, 12, 31))
        self.assertEqual(asof.combine(year, (D(2019, 3, 1), D(2019, 3, 31))), (D(2019, 3, 1), D(2019, 3, 31)))
        self.assertEqual(asof.combine(month, (D(2024, 1, 1), D(2024, 1, 31))), (D(2024, 1, 1), D(2024, 1, 31)),
                         "when they disagree, the router read the whole question")
        self.assertEqual(asof.combine(month, None), month)

    def test_router_dates(self):
        self.assertEqual(asof.parse_iso("2024-03"), (D(2024, 3, 1), D(2024, 3, 31)))
        self.assertEqual(asof.parse_iso("2024"), (D(2024, 1, 1), D(2024, 12, 31)))
        self.assertIsNone(asof.parse_iso("March 2024"))
        self.assertEqual(asof.parse_verdict({"kind": "event", "as_of": "2023-09-01"})["as_of"][0], D(2023, 9, 1))
        self.assertIsNone(asof.parse_verdict({"kind": "maybe"}))


class RuleTests(unittest.TestCase):
    PERIOD = (D(2025, 5, 1), D(2025, 5, 1))

    def test_said_after_without_a_year_is_withheld_for_state_questions_only(self):
        early = turn(0, "2025-01-14", "Maya started as a junior analyst.")
        later = turn(1, "2025-09-30", "Maya is a senior analyst these days.")
        dated = turn(2, "2025-09-30", "Back in March 2025 Maya was still junior.")
        items = [early, later, dated]
        self.assertEqual(asof.withhold(self.PERIOD, items, items, state=True), {later.id})
        self.assertEqual(asof.withhold(self.PERIOD, items, items, state=False), set())

    def test_relative_wording_inside_the_grace_window_is_kept(self):
        period = (D(2023, 9, 1), D(2023, 9, 1))
        before = turn(0, "2023-08-20", "I am planning a trip.")
        yesterday = turn(1, "2023-09-02", "Yesterday I came back from the coast.")
        zh = turn(2, "2023-09-03", "我上周去了海边。")
        late = turn(3, "2023-12-02", "Yesterday I came back from the mountains.")
        items = [before, yesterday, zh, late]
        self.assertEqual(asof.withhold(period, items, items, state=True), {late.id})

    def test_nothing_said_by_the_date_withholds_nothing(self):
        items = [turn(0, "2025-09-30", "Maya is a senior analyst."), turn(1, "2025-10-01", "Maya likes tea.")]
        self.assertEqual(asof.withhold(self.PERIOD, items, items, state=True), set())

    def test_interval_rule(self):
        period = (D(1948, 1, 1), D(1948, 1, 31))
        a = turn(0, "2024-06-01", "J works for Concordia Seminary from Jan, 1949 to Jan, 1953.")
        b = turn(1, "2024-06-01", "J works for Valparaiso University from Jan, 1946 to Jan, 1949.")
        c = turn(2, "2024-06-01", "J worked at Valparaiso University.")
        self.assertEqual(asof.withhold(period, [a, b, c], [a, b, c], state=False), {a.id})


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.items = [turn(0, "2025-01-14", "I started as a junior analyst at Brightline."),
                      turn(1, "2025-09-30", "I'm a senior analyst at Brightline these days."),
                      turn(2, "2025-03-02", "I got promoted to analyst at Brightline."),
                      turn(3, "2025-11-03", "I bought a blue bike.", digest="b" * 16),
                      turn(4, "2025-02-01", "I like green tea.", digest="c" * 16)]
        self.index = store.UserIndex()
        vectors = np.eye(len(self.items), 8, dtype=np.float32)
        self.index.append(self.items, vectors)
        self.scores = np.array([0.9, 0.95, 0.8, 0.5, 0.4])
        self.config = patch.multiple(config, ASOF_SELECT=True, RETURN_LIMIT=3, WINDOW_RADIUS=0,
                                     UPDATE_WITHHOLD=False, ADAPTIVE_CHUNK=0, RAW_FIRST=True)
        self.config.start()
        self.addCleanup(self.config.stop)
        asof._cache.clear()

    def search(self, query, router):
        request = main.SearchRequest(query=query, user_id="u", top_k=3)
        with patch.object(main.store, "get", return_value=self.index), \
                patch.object(main, "rank", return_value=self.scores), \
                patch.object(llm, "classify_asof", side_effect=router):
            return [d["id"] for d in main._search(request)["data"]]

    def test_state_question_withholds_and_refills(self):
        router = Router({"kind": "as_of_state", "as_of": "2025-05-01"})
        ids = self.search("What was my title as of May 1, 2025?", router)
        self.assertNotIn(self.items[1].id, ids)
        self.assertEqual(len(ids), 3, "the freed slot is refilled from the ranking")
        self.assertNotIn(self.items[3].id, ids, "the refill obeys the rule too (said later, no year)")
        self.assertIn(self.items[4].id, ids)
        self.assertEqual(len(router.calls), 1)

    def test_event_question_keeps_said_after_items(self):
        router = Router({"kind": "event", "as_of": "2025-05-01"})
        ids = self.search("What did I do on May 1, 2025?", router)
        self.assertIn(self.items[1].id, ids)

    def test_router_failure_or_other_withholds_nothing(self):
        for reply in (None, {"kind": "other", "as_of": None}, RuntimeError("boom")):
            with self.subTest(reply=reply):
                asof._cache.clear()
                ids = self.search("What was my title as of May 1, 2025?", Router(reply))
                self.assertIn(self.items[1].id, ids)

    def test_router_not_called_when_nothing_would_change(self):
        router = Router({"kind": "as_of_state", "as_of": "2026-01-01"})
        ids = self.search("What was my title as of January 1, 2026?", router)
        self.assertEqual(router.calls, [], "every returned item was said before the date")
        self.assertIn(self.items[1].id, ids)
        router = Router({"kind": "as_of_state", "as_of": "2025-05-01"})
        self.search("What is my current title?", router)
        self.assertEqual(router.calls, [], "no year in the question, no call")

    def test_router_date_replaces_the_parsed_one(self):
        # The parser reads only the year here; an item said in 2026 makes the
        # year-level rule change the set, so the router is asked, and its
        # month-level date withholds more.
        self.items[3] = turn(3, "2026-01-05", "I'm a principal analyst now.", digest="b" * 16)
        self.index = store.UserIndex()
        self.index.append(self.items, np.eye(len(self.items), 8, dtype=np.float32))
        self.scores = np.array([0.9, 0.85, 0.8, 0.95, 0.4])
        router = Router({"kind": "as_of_state", "as_of": "2025-02-10"})
        ids = self.search("¿Cuál era mi cargo en 2025, en el mes 2?", router)
        self.assertEqual(len(router.calls), 1)
        self.assertNotIn(self.items[3].id, ids)
        self.assertNotIn(self.items[2].id, ids, "said 2025-03-02, after the router's 2025-02-10")
        self.assertNotIn(self.items[1].id, ids)

    def test_off_by_default(self):
        self.config.stop()
        try:
            self.assertFalse(config.ASOF_SELECT)
        finally:
            self.config.start()

    def test_adaptive_chunks_leave_the_withheld_turn_out(self):
        items = [turn(0, "2025-01-14", "I started as a junior analyst at Brightline."),
                 turn(1, "2025-09-30", "I'm a senior analyst at Brightline these days.")]
        index = store.UserIndex()
        index.append(items, np.eye(2, 8, dtype=np.float32))
        request = main.SearchRequest(query="What was my title as of May 1, 2025?", user_id="u", top_k=3)
        with patch.object(config, "ADAPTIVE_CHUNK", 4000), patch.object(main.store, "get", return_value=index), \
                patch.object(main, "rank", return_value=np.array([0.5, 0.9])), \
                patch.object(llm, "classify_asof", side_effect=Router({"kind": "as_of_state", "as_of": "2025-05-01"})):
            data = main._search(request)["data"]
        self.assertEqual(len(data), 1)
        self.assertIn("junior", data[0]["content"])
        self.assertNotIn("senior", data[0]["content"])


class PromptTests(unittest.TestCase):
    def test_router_prompt_names_no_benchmark_people(self):
        names = ["Caroline", "Melanie", "Dave", "Calvin", "Joanna", "Nate", "Gina", "Jon", "Audrey", "Andrew",
                 "Deborah", "Jolene", "Evan", "Sam", "Tim", "John", "Maria", "James"]
        for name in names:
            self.assertNotIn(name, llm.ASOF_SCOPE_SYSTEM)

    def test_classify_asof_parses_json(self):
        reply = types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(
            content=json.dumps({"kind": "as_of_state", "as_of": "2024-01"})))])
        chat = types.SimpleNamespace(create=lambda **_: reply)
        client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=chat))
        with patch.object(config, "LLM_API_KEY", "x"), patch.object(llm, "_get_client", return_value=client):
            payload = llm.classify_asof("截至2024年1月，他住在哪里？", None)
        self.assertEqual(asof.parse_verdict(payload), {"kind": "as_of_state", "as_of": (D(2024, 1, 1), D(2024, 1, 31))})


if __name__ == "__main__":
    unittest.main()
