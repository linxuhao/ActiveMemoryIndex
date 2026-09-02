# Pre-registration — event dates read at Add, rendered from the store

Written 2026-09-02 before the store was built. Read this before any number.

## What is being tested

`AMI_EVENT_DATES_AT_ADD=1`: the extraction call that already runs on every
chunk also returns, for each fact and each turn, the date the described event
happened (or null), and it is stored in a new `items.event_date` column.
`AMI_EVENT_DATES_STORED=1`: at Search, memories with a stored date are rendered
exactly as the search-time arm rendered them —
`[said 2023-05-09 08:01 · happened 2023-04-10 · day 1] …` — with no LLM call.

The search-time arm (`AMI_EVENT_DATES`, `lme_temporal_baseline.md`) is the one
arm this cycle that passed its criteria: four runs each, 58.50 → 64.25,
complete separation, p = 0.029; +5.75 on the 84 questions that do not need a
present, +0.00 on the 49 that do. It could not ship: five extra calls per
search and a memory dated once per search that returns it. This is the same
rendering fed from a different reading — one call per chunk, at write time —
and **it is a different mechanism, so the +5.75 is a prediction, not a prior.**

## Store

`lme-t2`: LongMemEval-S temporal-reasoning, 133 questions, the same 6,392 Add
calls as `lme-t`, ingested with `AMI_EVENT_DATES_AT_ADD=1` and everything else
as shipped. About $5 and two hours. `lme-t` is not touched.

## Confound check, read before the arm

The extraction prompt is longer and returns a different shape, so the facts
themselves may differ from `lme-t`'s. Before the arm is read:

* retrieval `all-chunks` coverage on `lme-t2` with rendering off must be 1.000,
  as on `lme-t`;
* facts per chunk and `empty_extractions` on `lme-t2` against `lme-t`;
* `base` (rendering off) on `lme-t2`, four end-to-end runs, against `lme-t`'s
  57/58/59/60. A base mean more than two questions from 58.50 is reported as
  its own finding — the prompt change moved the floor — before anything else.

## Audit of what was stored

Share of turns and of facts that received a date; share of those dates that
differ from the said-date. The search-time reading dated 10.1% of returned
memories, 68.2% of them different from the utterance date. A write-time reading
that dates far more, or far fewer, is doing a different job and that is said
before the accuracy is.

## Decision rule

Arms on `lme-t2`, retrieval identical, differing only in `AMI_EVENT_DATES_STORED`:

* `base2` — off; `evadd` — on. Four end-to-end runs each, prefix 100, local
  judge, the platform's prompts.
* **Pass** = exact permutation test, 4 against 4, two-sided, p < 0.05, **and**
  the 49 questions that need a current date move by no more than one question
  in mean. The second clause is the specificity the search-time arm showed;
  an arm that lifts everything is a different arm and gets a different write-up.
* Wilcoxon over the questions that moved is reported alongside, as before.

## Prediction

Mean +4 to +6 on the 84 questions that do not need a present; the 49 that do,
unmoved. Retrieval unchanged (rendering happens after selection).

## If it passes

It ships as the two switches on, in production, before the September window
opens — the platform injects its data live, so the store the evaluation reads
is built with this on from its first Add or not at all. Its cost there is
extraction output tokens only.
