"""As-of evidence selection (AMI_ASOF_SELECT), rc5: membership only; the
question is classified by gpt-4o-mini (beside the recall rewrite, cached, no
pattern gate) and the candidates are judged by one gpt-4o-mini call; refill from
the ranking; any failure withholds nothing."""
import datetime as dt
import json
import threading
import types
import unittest
from unittest.mock import patch

import numpy as np

from app import asof, config, llm, main, store

D = dt.date


def turn(n, said, text, digest="a" * 16):
    return store.Item(id=f"{digest}-r{n}", kind="raw", parent_id=None, content=f"[{said} 10:00] I: {text}",
                      created_at=f"{said}T10:00:00Z")


class Fake:
    """An llm stand-in recording its calls; *reply* is a value, a callable or an exception."""

    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def __call__(self, *args):
        self.calls.append(args)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply(*args) if callable(self.reply) else self.reply


def by_text(**lists):
    """An item judge answering by substrings of the numbered lines."""
    def reply(query, options, period, numbered):
        out = {"valid": [], "not_valid": [], "about_period": []}
        for line in numbered.split("\n"):
            number = int(line.split(" | ", 1)[0])
            for name, needles in lists.items():
                if any(needle in line for needle in needles):
                    out[name].append(number)
        return out
    return reply


class VerdictTests(unittest.TestCase):
    def test_periods(self):
        parse = asof.parse_verdict
        self.assertEqual(parse({"kind": "as_of_state", "start": "2025-09-05", "end": "2025-09-05"}),
                         {"kind": "as_of_state", "period": (D(2025, 9, 5), D(2025, 9, 5))})
        self.assertEqual(parse({"kind": "as_of_state", "start": "2024-02", "end": "2024-02"})["period"],
                         (D(2024, 2, 1), D(2024, 2, 29)), "a month written YYYY-MM covers the month")
        self.assertEqual(parse({"kind": "event_on_date", "start": "2019", "end": None})["period"],
                         (D(2019, 1, 1), D(2019, 12, 31)), "one end given: it is both")
        self.assertEqual(parse({"kind": "as_of_state", "start": "2021-03-01", "end": "2021-03-31"})["period"],
                         (D(2021, 3, 1), D(2021, 3, 31)))

    def test_unusable(self):
        parse = asof.parse_verdict
        self.assertIsNone(parse({"kind": "event", "start": "2020"}), "rc4's kind name is not accepted")
        self.assertIsNone(parse(None))
        self.assertEqual(parse({"kind": "as_of_state", "start": None, "end": None}), {"kind": "other", "period": None},
                         "a state question without a period is other")
        self.assertEqual(parse({"kind": "as_of_state", "start": "2022-05-01", "end": "2021-01-01"})["kind"], "other")
        self.assertEqual(parse({"kind": "as_of_state", "start": "May 2022", "end": "May 2022"})["kind"], "other",
                         "only the ISO form the prompt asks for is read")
        self.assertEqual(parse({"kind": "other", "start": "2020", "end": "2020"}), {"kind": "other", "period": None})


class RuleTests(unittest.TestCase):
    PERIOD = (D(2025, 5, 1), D(2025, 5, 1))

    def verdicts(self, valid=(), not_valid=(), about=()):
        return {"valid": set(valid), "not_valid": set(not_valid), "about": set(about)}

    def test_said_after_and_not_about_the_period_is_withheld(self):
        early = turn(0, "2025-01-14", "Maya started as a junior analyst.")
        later = turn(1, "2025-09-30", "Maya is a senior analyst these days.")
        about = turn(2, "2025-09-30", "Back in spring Maya was still junior.")
        items = [early, later, about]
        self.assertEqual(asof.withhold(self.PERIOD, items, items, self.verdicts(about=[about.id])), {later.id})

    def test_relative_time_in_any_language_is_the_models_call(self):
        period = (D(2023, 9, 1), D(2023, 9, 1))
        before = turn(0, "2023-08-20", "I am planning a trip.")
        fr = turn(1, "2023-09-02", "Hier je suis rentrée de la côte.")
        ja = turn(2, "2023-09-03", "先週、海に行きました。")
        late = turn(3, "2023-12-02", "Ayer volví de la montaña.")
        items = [before, fr, ja, late]
        self.assertEqual(asof.withhold(period, items, items, self.verdicts(about=[fr.id, ja.id])), {late.id})

    def test_nothing_said_by_the_date_withholds_nothing_said_after(self):
        items = [turn(0, "2025-09-30", "Maya is a senior analyst."), turn(1, "2025-10-01", "Maya likes tea.")]
        self.assertEqual(asof.withhold(self.PERIOD, items, items, self.verdicts()), set())

    def test_not_valid_needs_a_valid_alternative(self):
        period = (D(1948, 1, 1), D(1948, 1, 31))
        a = turn(0, "2024-06-01", "J works for Concordia Seminary from Jan, 1949 to Jan, 1953.")
        b = turn(1, "2024-06-01", "J works for Valparaiso University from Jan, 1946 to Jan, 1949.")
        c = turn(2, "2024-06-01", "J worked at Valparaiso University.")
        items = [a, b, c]
        self.assertEqual(asof.withhold(period, items, items, self.verdicts(valid=[b.id], not_valid=[a.id])), {a.id})
        self.assertEqual(asof.withhold(period, items, items, self.verdicts(not_valid=[a.id])), set(),
                         "no item valid during the period: nothing withheld")

    def test_valid_is_never_withheld(self):
        early = turn(0, "2025-01-14", "I work at Brightline.")
        later = turn(1, "2025-09-30", "From April to June 2025 I was at Brightline's Lyon office.")
        items = [early, later]
        out = asof.withhold(self.PERIOD, items, items, self.verdicts(valid=[later.id], not_valid=[later.id]))
        self.assertEqual(out, set())


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.items = [turn(0, "2025-01-14", "I started as a junior analyst at Brightline."),
                      turn(1, "2025-09-30", "I'm a senior analyst at Brightline these days."),
                      turn(2, "2025-03-02", "I got promoted to analyst at Brightline."),
                      turn(3, "2025-11-03", "I bought a blue bike.", digest="b" * 16),
                      turn(4, "2025-02-01", "I like green tea.", digest="c" * 16)]
        self.index = store.UserIndex()
        self.index.append(self.items, np.eye(len(self.items), 8, dtype=np.float32))
        self.scores = np.array([0.9, 0.95, 0.8, 0.5, 0.4])
        self.config = patch.multiple(config, ASOF_SELECT=True, RETURN_LIMIT=3, WINDOW_RADIUS=0, ASOF_ITEMS=200,
                                     UPDATE_WITHHOLD=False, ADAPTIVE_CHUNK=0, RAW_FIRST=True, LLM_API_KEY="k")
        self.config.start()
        self.addCleanup(self.config.stop)
        asof._cache.clear()
        asof._item_cache.clear()

    def search(self, query, router, judge, rank=None, top_k=3):
        request = main.SearchRequest(query=query, user_id="u", top_k=top_k)
        with patch.object(main.store, "get", return_value=self.index), \
                patch.object(main, "rank", side_effect=rank or (lambda *a, **k: self.scores)), \
                patch.object(llm, "classify_asof", side_effect=router), \
                patch.object(llm, "judge_asof_items", side_effect=judge):
            return [d["id"] for d in main._search(request)["data"]]

    STATE = {"kind": "as_of_state", "start": "2025-05-01", "end": "2025-05-01"}

    def test_state_question_withholds_and_refills(self):
        router, judge = Fake(self.STATE), Fake(by_text(valid=["junior"]))
        ids = self.search("What was my title as of May 1, 2025?", router, judge)
        self.assertNotIn(self.items[1].id, ids)
        self.assertEqual(len(ids), 3, "the freed slot is refilled from the ranking")
        self.assertNotIn(self.items[3].id, ids, "the refill was judged too (said later, not about the period)")
        self.assertIn(self.items[4].id, ids)
        self.assertEqual((len(router.calls), len(judge.calls)), (1, 1))
        numbered = judge.calls[0][3].split("\n")
        self.assertEqual(numbered[0], "0 | said 2025-09-30 | I: I'm a senior analyst at Brightline these days.",
                         "candidates in score order, with the stamp's date and the text without the stamp")
        self.assertEqual(judge.calls[0][2], (D(2025, 5, 1), D(2025, 5, 1)))

    def test_no_pattern_gate_dates_in_words(self):
        """No digit in the question: the model reads the date (French, in words)."""
        router, judge = Fake(self.STATE), Fake(by_text())
        ids = self.search("Quel était mon poste le premier mai deux mille vingt-cinq ?", router, judge)
        self.assertEqual(len(router.calls), 1)
        self.assertNotIn(self.items[1].id, ids)

    def test_classifier_runs_beside_the_recall_rewrite(self):
        started = threading.Event()

        def router(query, options):
            started.set()
            return {"kind": "other", "start": None, "end": None}

        seen = {}

        def rank(*args, **kwargs):
            seen["parallel"] = started.wait(5)
            return self.scores

        self.search("What is my title?", Fake(router), Fake(by_text()), rank=rank)
        self.assertTrue(seen["parallel"], "the classification was running while rank() (the recall rewrite) ran")

    def test_cached_per_question_and_options(self):
        router = Fake({"kind": "other", "start": None, "end": None})
        self.search("What is my title?", router, Fake(by_text()))
        self.search("What is my title?", router, Fake(by_text()))
        self.assertEqual(len(router.calls), 1)
        request = main.SearchRequest(query="What is my title?", user_id="u", top_k=3, options=["A", "B"])
        with patch.object(main.store, "get", return_value=self.index), \
                patch.object(main, "rank", return_value=self.scores), \
                patch.object(llm, "classify_asof", side_effect=router):
            main._search(request)
        self.assertEqual(len(router.calls), 2, "options are part of the key")

    def test_event_and_other_questions_withhold_nothing_without_an_item_call(self):
        for reply in ({"kind": "event_on_date", "start": "2025-05-01", "end": "2025-05-01"},
                      {"kind": "other", "start": None, "end": None}):
            with self.subTest(reply=reply):
                asof._cache.clear()
                judge = Fake(by_text())
                ids = self.search("What did I do on May 1, 2025?", Fake(reply), judge)
                self.assertIn(self.items[1].id, ids)
                self.assertEqual(judge.calls, [])

    def test_failures_withhold_nothing(self):
        for router, judge in ((Fake(None), Fake(by_text())), (Fake(RuntimeError("boom")), Fake(by_text())),
                              (Fake({"kind": "as_of_state"}), Fake(by_text())),
                              (Fake(self.STATE), Fake(None)), (Fake(self.STATE), Fake(RuntimeError("boom"))),
                              (Fake(self.STATE), Fake({"valid": "x"}))):
            with self.subTest(router=router.reply, judge=judge.reply):
                asof._cache.clear()
                asof._item_cache.clear()
                asof.log.disabled = True
                try:
                    ids = self.search("What was my title as of May 1, 2025?", router, judge)
                finally:
                    asof.log.disabled = False
                self.assertIn(self.items[1].id, ids)

    def test_unjudged_items_are_never_withheld(self):
        with patch.object(config, "ASOF_ITEMS", 2):
            judge = Fake(by_text())
            ids = self.search("What was my title as of May 1, 2025?", Fake(self.STATE), judge)
        self.assertEqual(len(judge.calls[0][3].split("\n")), 2)
        self.assertNotIn(self.items[1].id, ids, "judged, said after, not about the period")
        self.assertIn(self.items[3].id, ids, "the refill beyond the judged items is kept as it is")

    def test_item_judgement_is_cached(self):
        judge = Fake(by_text())
        self.search("What was my title as of May 1, 2025?", Fake(self.STATE), judge)
        self.search("What was my title as of May 1, 2025?", Fake(self.STATE), judge)
        self.assertEqual(len(judge.calls), 1)

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
                patch.object(llm, "classify_asof", side_effect=Fake(self.STATE)), \
                patch.object(llm, "judge_asof_items", side_effect=Fake(by_text())):
            data = main._search(request)["data"]
        self.assertEqual(len(data), 1)
        self.assertIn("junior", data[0]["content"])
        self.assertNotIn("senior", data[0]["content"])


class PromptTests(unittest.TestCase):
    def test_prompts_name_no_benchmark_people(self):
        names = ["Caroline", "Melanie", "Dave", "Calvin", "Joanna", "Nate", "Gina", "Jon", "Audrey", "Andrew",
                 "Deborah", "Jolene", "Evan", "Sam", "Tim", "John", "Maria", "James"]
        for name in names:
            self.assertNotIn(name, llm.ASOF_SCOPE_SYSTEM)
            self.assertNotIn(name, llm.ASOF_ITEMS_SYSTEM)

    def client(self, content, sink):
        reply = types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=content))])

        def create(**kwargs):
            sink.append(kwargs)
            return reply
        return types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)))

    def test_classify_asof_parses_json(self):
        sink = []
        client = self.client(json.dumps({"kind": "as_of_state", "start": "2024-01", "end": "2024-01"}), sink)
        with patch.object(config, "LLM_API_KEY", "x"), patch.object(llm, "_get_client", return_value=client):
            payload = llm.classify_asof("截至2024年1月，他住在哪里？", None)
        self.assertEqual(asof.parse_verdict(payload), {"kind": "as_of_state", "period": (D(2024, 1, 1), D(2024, 1, 31))})
        self.assertEqual(sink[0]["messages"][1]["content"], "Question: 截至2024年1月，他住在哪里？")

    def test_judge_asof_items_sends_the_period(self):
        sink = []
        client = self.client('{"valid": [0], "not_valid": [], "about_period": []}', sink)
        with patch.object(config, "LLM_API_KEY", "x"), patch.object(llm, "_get_client", return_value=client):
            payload = llm.judge_asof_items("Q?", None, (D(2024, 1, 1), D(2024, 1, 31)), "0 | said 2023-12-01 | x")
        self.assertEqual(payload, {"valid": [0], "not_valid": [], "about_period": []})
        self.assertIn("Period: 2024-01-01 to 2024-01-31", sink[0]["messages"][1]["content"])


if __name__ == "__main__":
    unittest.main()
