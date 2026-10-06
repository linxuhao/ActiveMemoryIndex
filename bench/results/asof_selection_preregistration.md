# Pre-registration — as-of evidence selection (AMI_ASOF_SELECT), confirmation

Written 2026-10-06 before any validation call. Code under test: commit
`99cba0e` (`app/asof.py`, router prompt `ASOF_SCOPE_SYSTEM` in `app/llm.py`),
branch `release/rc4-20261006`. Harness: `bench/rc4_study.py`; data builder:
`bench/rc4_asof_data.py`. Read this before any number.

## Where this comes from

Lead smoke L1 (`lead_smoke_time_20261005.md`, prototype `bench/asof_filter.py`
on branch `research/lead-smoke-time-20261005`): a rule filter over rc2's
returned list took TempReason L2 from 131 to 150 of 150 and synthetic dated
profiles en +42.5 / zh +17.5 points, with zero losses; LongMemEval-S firing 0 of
500. One risk: on LoCoMo dated *event* questions the "said after the date" rule
withheld evidence said the day after ("yesterday I came back from …"), −1 of 60
post hoc. The smoke had no refill.

## What changed against the smoke prototype (the mechanism under test)

1. Rule (b) "said after the as-of period without naming a year" applies only
   to questions gpt-4o-mini classifies as **as-of state** questions; rule (a)
   (explicit date ranges, none overlapping) applies to state and **event**
   questions; neither to anything else.
2. Grace window: an item using relative-time wording ("yesterday", "last
   week", "上周", "ayer", …; a fixed multilingual list) said within 31 days
   after the period is kept. The list can only keep items.
3. Refill: withheld slots are refilled from the ranking (the selection runs
   with the withheld ids excluded), and the rules apply to the refill too
   (evaluated over the top 400 of the ranking plus the returned set).
4. Dates: a language-neutral gate (a year written in digits) and a parser for
   ISO, English, Spanish, French, German, Portuguese and Italian month names,
   dotted European dates and CJK/Korean year-month-day. The router is called
   only when the rules, at the parsed period, would change the returned set; its
   own normalised date (any language) then replaces the parsed one.
5. Not an English-only decider: the decision to withhold is the router's, in
   any language; the regex only finds the year and proposes a period.

Membership only: nothing is rewritten, nothing computed, no answer produced
(Q18 evidence selection). One gpt-4o-mini call per distinct dated question at
most, only when something would be withheld; cached per (query, options).

## Arms

* **B** — rc4 as it would ship with production-like settings: update
  detect/render/withhold on (`AMI_UPDATE_VERSION=7`), raw-first, window 1,
  return limit 100, token budget on, `AMI_ASOF_SELECT=0`.
* **P** — B + `AMI_ASOF_SELECT=1` (pool 400, grace 31 days).

Both arms run in-process (`app.main._search`) on the same store; every model
call goes through `bench/llm_proxy.py`, so recall questions and router calls
are shared and both arms of a question see the same ranking. A question whose
returned list is byte-identical in both arms is identical by construction and
gets B's verdict; only changed lists are answered for P.

## Sets

| set | n | store | role |
|---|---:|---|---|
| TempReason L2, fresh | 200 | new, text-embedding-v4 | **as-of** (primary) |
| synthetic dated profiles, NEW templates (`rc4_asof_data.py`), dated questions | 100 (50 en, 50 zh) | new, v4 | **as-of** (primary) |
| synthetic, "now" questions | 20 | same | non-dated control (reported) |
| TempReason L3, fresh | 100 | new, v4 | relation questions without dates (reported) |
| LoCoMo, every category 1–4 question `asof.candidate()` accepts | 194 | the fresh v4 LoCoMo store of `adaptive_chunk_preregistration.md` | **guard** (event-date questions) |
| LongMemEval-S knowledge-update | 78 | BGE guard store (rc2 guard store copy with v7 update records) | **guard** |

TempReason: public test files (`test_l2.json`, `test_l3.json`), sampled with
`random.Random(20261006)` after removing all 300 ids the smoke sampled. One
user per question; the question's `fact_context` sentences are Added as user
turns of one session stamped 2024-06-01, exactly as in the smoke. Synthetic: 10
English and 10 Chinese streams with new attributes (phone carrier, car,
manager, rent, club), new wording and new date formats ("Feb. 13, 2022",
"2022/02/13", "13 February 2022", "2023年2月14日那天", "到…为止", "截至…");
values stated without years and without correction words; 5 dated questions
and 1 "now" question per stream, golds fixed by the template.

Deviation, stated: KU uses the BGE research store (re-ingesting LongMemEval
into v4 is not budgeted); the other sets use text-embedding-v4.

## Metric

Platform answer and judge prompts (LongMemEval-S pipeline for TempReason,
synthetic and KU, LoCoMo-refined pipeline for LoCoMo), gpt-4o-mini,
temperature 0, one replicate. Per-question paired comparison; exact two-sided
sign test on discordant questions.

## Gate (all three)

1. **As-of sets**, TempReason L2 fresh + synthetic dated pooled (n = 300):
   P − B > 0 with sign-test p < 0.05.
2. **LoCoMo dated guard** (194): P − B ≥ −1 question.
3. **KU guard** (78): P − B ≥ −1 question.

Pass → recommend `AMI_ASOF_SELECT=1` for production (the shipped default stays
0). Fail → the flag ships off and is reported as failed. Each as-of set is
also reported on its own, with router calls, firing rates and the
withheld-item counts; those do not change the decision.

## Router development (before validation)

The router prompt is frozen at `99cba0e`. If a check on the smoke's own data
(its TempReason L2 sample, its synthetic streams) or on hand-written examples
shows the prompt misclassifying, a revised prompt may be committed **before
any validation set above is searched**, recorded here as an amendment with the
commit. No validation question is used to develop it, and LoCoMo text is never
put in the prompt.

## Budget

≈ 1.3M gpt-4o-mini tokens to ingest TempReason and synthetic streams (with
update detection on), ≈ 4–6M for answering and judging changed lists, ≈ 0.1M
for router calls; text-embedding-v4 < 0.5M. Counted by the proxy ledger.
