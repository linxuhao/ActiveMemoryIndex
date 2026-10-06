"""As-of evidence selection (AMI_ASOF_SELECT), rc5: membership only; the
question is classified by gpt-4o-mini (beside the recall rewrite, cached, no
pattern gate), the times the candidates state are read by one gpt-4o-mini call
(cached per item) and compared as ISO dates by rc4's rules; refill from the
ranking; any failure withholds nothing."""
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


def by_text(**times):
    """A time reader answering by substrings of the numbered lines:
    by_text(junior=[("2025-01", "2025-06", 1)]) gives every line containing
    'junior' that span."""
    def reply(numbered):
        out = []
        for line in numbered.split("\n"):
            number = int(line.split(" | ", 1)[0])
            for needle, entries in times.items():
                if needle in line:
                    out += [[number, start, end, span] for start, end, span in entries]
        return {"times": out}
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

    def test_said_after_without_a_time_is_withheld(self):
        early = turn(0, "2025-01-14", "Maya started as a junior analyst.")
        later = turn(1, "2025-09-30", "Maya is a senior analyst these days.")
        dated = turn(2, "2025-09-30", "Back in March 2025 Maya was still junior.")
        items = [early, later, dated]
        stated = {dated.id: [((D(2025, 3, 1), D(2025, 3, 31)), False)]}
        self.assertEqual(asof.withhold(self.PERIOD, items, items, stated), {later.id})

    def test_a_time_after_the_period_does_not_keep_it(self):
        early = turn(0, "2025-01-14", "I use Free.")
        later = turn(1, "2025-09-30", "Switched to Orange this morning.")
        stated = {later.id: [((D(2025, 9, 30), D(2025, 9, 30)), False)]}
        self.assertEqual(asof.withhold(self.PERIOD, [early, later], [early, later], stated), {later.id})

    def test_relative_time_in_any_language_keeps_the_item(self):
        period = (D(2023, 9, 1), D(2023, 9, 1))
        before = turn(0, "2023-08-20", "I am planning a trip.")
        fr = turn(1, "2023-09-02", "Hier je suis rentrée de la côte.")
        ja = turn(2, "2023-09-03", "先週、海に行きました。")
        late = turn(3, "2023-12-02", "Ayer volví de la montaña.")
        stated = {fr.id: [((D(2023, 9, 1), D(2023, 9, 1)), False)], ja.id: [((D(2023, 8, 27), D(2023, 9, 2)), False)],
                  late.id: [((D(2023, 12, 1), D(2023, 12, 1)), False)]}
        items = [before, fr, ja, late]
        self.assertEqual(asof.withhold(period, items, items, stated), {late.id})

    def test_nothing_said_by_the_date_withholds_nothing_said_after(self):
        items = [turn(0, "2025-09-30", "Maya is a senior analyst."), turn(1, "2025-10-01", "Maya likes tea.")]
        self.assertEqual(asof.withhold(self.PERIOD, items, items, {}), set())

    def test_interval_rule(self):
        period = (D(1948, 1, 1), D(1948, 1, 31))
        a = turn(0, "2024-06-01", "J works for Concordia Seminary from Jan, 1949 to Jan, 1953.")
        b = turn(1, "2024-06-01", "J works for Valparaiso University from Jan, 1946 to Jan, 1949.")
        c = turn(2, "2024-06-01", "J worked at Valparaiso University.")
        d = turn(3, "2024-06-01", "J moved to Indiana in 1940.")
        items = [a, b, c, d]
        stated = {a.id: [((D(1949, 1, 1), D(1953, 1, 31)), True)], b.id: [((D(1946, 1, 1), D(1949, 1, 31)), True)],
                  d.id: [((D(1940, 1, 1), D(1940, 12, 31)), False)]}
        self.assertEqual(asof.withhold(period, items, items, stated), {a.id},
                         "a span that misses the period; a single date is never withheld by the interval rule")
        stated[b.id] = [((D(1946, 1, 1), D(1947, 1, 31)), True)]
        self.assertEqual(asof.withhold(period, items, items, stated), set(), "no span covers the period: nothing")


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
        asof._times.clear()

    def search(self, query, router, judge, rank=None, top_k=3):
        request = main.SearchRequest(query=query, user_id="u", top_k=top_k)
        with patch.object(main.store, "get", return_value=self.index), \
                patch.object(main, "rank", side_effect=rank or (lambda *a, **k: self.scores)), \
                patch.object(llm, "classify_asof", side_effect=router), \
                patch.object(llm, "asof_times", side_effect=judge):
            return [d["id"] for d in main._search(request)["data"]]

    STATE = {"kind": "as_of_state", "start": "2025-05-01", "end": "2025-05-01"}

    def test_state_question_withholds_and_refills(self):
        router, judge = Fake(self.STATE), Fake(by_text())
        ids = self.search("What was my title as of May 1, 2025?", router, judge)
        self.assertNotIn(self.items[1].id, ids)
        self.assertEqual(len(ids), 3, "the freed slot is refilled from the ranking")
        self.assertNotIn(self.items[3].id, ids, "the refill was read too (said later, no time)")
        self.assertIn(self.items[4].id, ids)
        self.assertEqual((len(router.calls), len(judge.calls)), (1, 1))
        numbered = judge.calls[0][0].split("\n")
        self.assertEqual(numbered[0], "0 | said 2025-09-30 | I'm a senior analyst at Brightline these days.",
                         "candidates in score order, with the stamp's date, without the stamp or our speaker label")

    def test_a_stated_time_in_the_period_keeps_a_later_item(self):
        judge = Fake(by_text(senior=[("2025-04", "2025-12", 0)]))
        ids = self.search("What was my title as of May 1, 2025?", Fake(self.STATE), judge)
        self.assertIn(self.items[1].id, ids)
        self.assertNotIn(self.items[3].id, ids)

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
                              (Fake(self.STATE), Fake({"times": "x"})), (Fake(self.STATE), Fake({}))):
            with self.subTest(router=router.reply, judge=judge.reply):
                asof._cache.clear()
                asof._times.clear()
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
        self.assertEqual(len(judge.calls[0][0].split("\n")), 2)
        self.assertNotIn(self.items[1].id, ids, "read, said after, no time")
        self.assertIn(self.items[3].id, ids, "the refill beyond the judged items is kept as it is")

    def test_times_are_cached_per_item(self):
        judge = Fake(by_text())
        self.search("What was my title as of May 1, 2025?", Fake(self.STATE), judge)
        self.search("Where did I work as of June 3, 2025?", Fake({"kind": "as_of_state", "start": "2025-06-03",
                                                                 "end": "2025-06-03"}), judge)
        self.assertEqual(len(judge.calls), 1, "every candidate was read by the first call")

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
                patch.object(llm, "asof_times", side_effect=Fake(by_text())):
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

    def test_times_reads_compact_entries(self):
        items = [turn(0, "2024-06-01", "A from Jan, 2001 to Mar, 2005."), turn(1, "2024-06-01", "B in 2003."),
                 turn(2, "2024-06-01", "No time."), fact_like := store.Item(id="f-0", kind="fact", parent_id=None,
                                                                         content="[2024-06-01] A from Jan, 2001 to Mar, 2005.",
                                                                         created_at=None)]
        reply = {"times": [[0, "2001-01", "2005-03", 1], [1, "2003", "2003", 0], [9, "2001", "2002", 1],
                           ["x", "2001", "2001", 0], [2, "nonsense", "2001", 0], "junk", [2, "2003"]]}
        asof._times.clear()
        sink = []
        with patch.object(llm, "asof_times", side_effect=lambda numbered: sink.append(numbered) or reply):
            out = asof.times(items)
        self.assertEqual(out[items[0].id], [((D(2001, 1, 1), D(2005, 3, 31)), True)])
        self.assertEqual(out[items[1].id], [((D(2003, 1, 1), D(2003, 12, 31)), False)])
        self.assertEqual(out[items[2].id], [])
        self.assertEqual(out[fact_like.id], out[items[0].id], "a fact repeating its turn shares the turn's line")
        self.assertEqual(len(sink[0].split("\n")), 3)

    def test_asof_times_sends_the_lines(self):
        sink = []
        client = self.client('{"times":[[0,"2023-12","2023-12",0]]}', sink)
        with patch.object(config, "LLM_API_KEY", "x"), patch.object(llm, "_get_client", return_value=client):
            payload = llm.asof_times("0 | said 2023-12-01 | x in December 2023")
        self.assertEqual(payload, {"times": [[0, "2023-12", "2023-12", 0]]})
        self.assertEqual(sink[0]["messages"][1]["content"], "0 | said 2023-12-01 | x in December 2023")

if __name__ == "__main__":
    unittest.main()
