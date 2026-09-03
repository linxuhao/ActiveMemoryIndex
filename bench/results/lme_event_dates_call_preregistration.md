# Pre-registration — a dedicated dating call at Add

Written 2026-09-03 before the store was built. Read this before any number.

## The question this arm exists to answer

Three readings of the same question, "when did this memory's event happen":

| | when | how | non-trivial dates | end to end |
|---|---|---|---:|---:|
| `AMI_EVENT_DATES` | search | its own call, 20 memories | 68.3% | **+5.75**, p=0.029 |
| `AMI_EVENT_DATES_AT_ADD` | Add | folded into the extraction call | 38.6% | +2.00, p=0.086 |
| `AMI_EVENT_DATES_ADD_CALL` | Add | **its own call**, the chunk's memories | ? | ? |

The two measured arms differ in **two** things at once: when the reading happens
and whether it competes with extraction for the same call. This arm changes only
the first. Extraction keeps its original prompt, so the facts stored should match
`lme-t`'s and the confound that moved the `lme-t2` base by +1.75 is gone.

**Prediction.** If load was the cause, this recovers most of +5.75 and the
non-trivial rate returns to about 68%. If timing was the cause, it lands near
`lme-t2`'s +2.00. Either answer is worth having: the first ships, the second
closes the whole family.

## Store

`lme-t3`: LongMemEval-S temporal-reasoning, 133 questions, the same 6,392 Add
calls, `AMI_EVENT_DATES_ADD_CALL=1`, `AMI_EVENT_DATES_AT_ADD=0`, everything else
as shipped. Two LLM calls per chunk (~12,800 total), 16 ingest workers, about
$7 and three hours. `lme-t` and `lme-t2` are not touched.

## Read before the arm

1. **Base parity.** Facts per chunk and zero-fact chunks on `lme-t3` against
   `lme-t` (910 zero-fact, 62,743 facts). Extraction is byte-identical in prompt,
   so a difference beyond LLM nondeterminism means something else changed.
2. **The non-trivial rate**, which is the mechanism under test: share of dated
   memories whose event date differs from the said date. `lme-t2` scored 38.6%
   against the search-time reading's 68.3%.
3. **`t3base` (rendering off), four end-to-end runs**, against `lme-t`'s
   57/58/59/60. A base mean more than two questions from 58.50 is its own
   finding and is reported before anything else.

## Decision rule

Arms on `lme-t3`, identical but for `AMI_EVENT_DATES_STORED`: `t3base` off,
`t3call` on. Four end-to-end replicates each, prefix 100, local judge.

* **Pass** = permutation 4v4 two-sided p < 0.05 **and** the now-anchored subset
  (the rule pinned in `lme_event_dates_add_preregistration.md`, 52 of 133) moves
  by no more than one question in mean.
* Wilcoxon over the movers is reported alongside.
* **Failing either clause ends the event-date family**, not just this arm. Three
  readings of one question, one of which cannot ship on cost, is enough.

## If it passes

It ships as `AMI_EVENT_DATES_ADD_CALL=1` plus `AMI_EVENT_DATES_STORED=1` before
the September window opens — the store the evaluation reads is built from its
first Add or not at all. Cost in production is one extra `gpt-4o-mini` call per
Add, which must be checked against the Add latency budget behind Cloudflare's
~100 s cut before it is turned on.
