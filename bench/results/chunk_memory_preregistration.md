# Pre-registration — facts select, the whole source is delivered as one memory

Written 2026-09-21 before the switches were implemented. Read this before any number.

## Where this came from

The fact-evidence arm (`fact_evidence_preregistration.md`) could not fire in its
smoke because facts rarely outrank turns. Looking for how often that happens
turned up nine LoCoMo runs from cycle 1 that this repository never recorded.
They are written up in `locomo_lost_arms.md`; two of them decide this arm.

**`all10_factonly` — facts select, facts are delivered.** End to end **0.5127**
against the shipped window's 0.6802. But its *coverage* is the best measured
anywhere: complete@100 **0.904** against 0.850, and on questions needing three
or more evidence turns **0.732 against 0.497**. It picks the right chunks and
then hands the reader a lossy paraphrase of them.

**`all10_parent` — whole chunks delivered as single memories.** End to end
**0.7114**, the highest number in the whole set, 3.1pp above the shipped
config, at 23.9 memories and 61,531 characters per question.

This arm is the diagonal neither of them occupies: **`factonly`'s selection with
`parent`'s delivery.**

## Why delivery is where the slots are

A returned memory costs one slot whatever its length, and `top_k` counts
memories, not turns. Delivering a chunk one turn at a time therefore costs about
eighteen slots; delivering it as one organised memory costs one. Simulated over
`all10_factonly`'s own ranking, that is the difference between:

| slots spent as | complete | chunks reached |
|---|---:|---:|
| one turn each, 100 slots | 0.558 | 5.3 |
| one turn each, 400 slots | 0.885 | 22.2 |
| **one chunk each** | **0.904** | 24.6 |

and the capped middle ground has an *oracle* ceiling of 0.900 at three turns per
chunk — barely above what the shipped config already achieves with no oracle at
all. The slot arithmetic, not the ranking, is what bounds that family.

Q18 of the official Q&A permits this delivery explicitly: summarising,
structuring or organising memories that were legitimately written is allowed
within a declared method. Concatenating a chunk's own turns, verbatim and in
order, is the weakest possible use of that permission — **no text is rewritten**,
so the project invariant holds: the query selects, it never changes the text.

## What changes

Two switches, so the two halves can be attributed separately:

* `AMI_FACT_SELECT` — score only extracted facts; verbatim turns are not
  candidates for selection.
* `AMI_CHUNK_MEMORY` — a selected item is returned as its whole Add chunk: that
  chunk's turns, verbatim, in order, joined into one memory with id
  `{digest}-c0`. Chunks dedup, so many facts from one chunk cost one slot.

`take()` is unchanged, so `AMI_RETURN_LIMIT` and `AMI_RETURN_CHAR_BUDGET` still
bound the response. Neighbour expansion and fact expansion are skipped when
`AMI_CHUNK_MEMORY` is on — the chunk already contains its own neighbours.

## Store

**None is built.** `lme-t` as it stands (LongMemEval-S temporal-reasoning, 133
questions, 6,392 Add calls). No Add calls, no extraction spend. The LoCoMo
`all10` store no longer exists — it was overwritten by the LongMemEval stores —
so the numbers above are read from its retained `retrieval.json` files and are
not re-runnable without a rebuild.

## Arms

Against the existing base replicates 57 / 58 / 59 / 60 (mean **58.50**):

| tag | switches | isolates |
|---|---|---|
| `chunkmem` | `AMI_CHUNK_MEMORY=1` | delivery alone, selection unchanged |
| `factsel` | `AMI_FACT_SELECT=1` + `AMI_CHUNK_MEMORY=1` | the arm |

Four end-to-end replicates each, prefix 100, permutation 4v4 two-sided.

## Read before any accuracy number

1. **Characters and memories per question**, from `report`. The shipped config
   sends about 14k characters on LoCoMo; `parent` sent 61k. This is the number
   that decides whether the arm is serveable at all, and it is read first.
2. **`complete_turn` and `complete_chunk`.** A chunk memory contains its turns
   verbatim, so for once the strict per-turn measure and the generous chunk
   measure should nearly agree. If they do not, the join is wrong.
3. **How many memories come back.** If `factsel` returns far fewer than the
   limit, the fact ranking ran out of distinct chunks and the arm is smaller
   than it looks.

## Decision rule

* **Gate:** permutation 4v4 two-sided **p < 0.05** in the positive direction
  against base.
* **Veto — the answer budget.** The platform allows 117,760 input tokens for
  Answer, and Q18 warns that returned content over the limit may be truncated.
  An arm whose characters per question would not fit that budget with margin
  does not ship whatever it scores, because on the evaluation it would be
  silently cut. `AMI_RETURN_CHAR_BUDGET` (400,000) is the enforced bound; the
  arm must come in under it without being clipped by it.
* **Attribution:** if `factsel` passes but `chunkmem` alone passes by the same
  margin, the gain is delivery and fact selection is not carrying it. Report
  that rather than shipping both.
* Never gated on recall@k (`bench/README.md`).

## Prediction

`chunkmem` gains and `factsel` gains slightly more. I expect most of the effect
to be delivery, not selection, because `parent` bought 3.1pp with an ordinary
embedding ranker while `factonly`'s far better coverage bought −16.8pp.

Recorded with the standing caveat: this project has made **three** written
predictions about ranking and salience changes and all three were wrong. Two
hours ago I called `parent`'s result an artifact of sending more text; the
platform's own answer budget says the text fits, so that dismissal was wrong and
is retracted in `locomo_lost_arms.md`.

## If it fails

`AMI_FACT_SELECT` closes with it — fact-only selection will then have been
measured with both deliveries, lossy and verbatim. `AMI_CHUNK_MEMORY` does not:
it would still be untested against the shipped config on LoCoMo, where `parent`
won, and LoCoMo is the instrument that disagreed.
