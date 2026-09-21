# A fact brings its own evidence — passed its gate, failed its veto, does not ship

Read `fact_evidence_preregistration.md` first, including the note added
2026-09-21. Both were written before any number below existed.

## The gate: passed

LongMemEval-S temporal-reasoning, 133 questions, `lme-t` unchanged, prefix 100,
four replicates. `AMI_FACT_EVIDENCE=2` against the shipped configuration.

| arm | replicates | mean | vs base |
|---|---|---:|---:|
| `base` | 57 · 59 · 60 · 58 | 58.50 | — |
| `factev` | 63 · 64 · 66 · 64 | **64.25** | **+5.75** |

Complete separation — the worst `factev` run beats the best `base` run.
Permutation 4v4 two-sided **p = 2/70 = 0.029**, positive direction.

Search-time only, no store rebuild, and it *reduces* the returned text
(73,859 characters against base's 77,263) while returning the same 100 memories.

## The gain is where the mechanism said it would be

| gold evidence turns | n | base | arm | delta |
|---|---:|---:|---:|---:|
| 1 | 39 | 12.75 | 12.25 | **−0.50** |
| 2 | 74 | 41.25 | 45.50 | **+4.25** |
| >=3 | 20 | 4.50 | 6.50 | **+2.00** |

All of it on multi-evidence questions; single-evidence questions lose slightly.
That is the argument the arm was built on.

## The veto: fired

LoCoMo, `all10v2` — the original `all10` store had been overwritten by the
LongMemEval stores, so it was rebuilt and **both arms measured on the rebuild**.
Retrieval only; the veto is a coverage clause.

| complete@100 | base | `factev` | delta |
|---|---:|---:|---:|
| **category 1** | **0.596** | **0.543** | **−5.3pp** |
| category 2 | 0.941 | 0.931 | −1.0pp |
| category 3 | 0.533 | 0.500 | −3.3pp |
| category 4 | 0.952 | 0.936 | −1.6pp |
| needs 1 turn | 0.941 | 0.927 | −1.4pp |
| needs 2 turns | 0.748 | 0.699 | −4.9pp |
| needs >=3 turns | 0.497 | 0.448 | −4.9pp |

The pre-registration: *"LoCoMo cat1 complete@100 must not fall below base …
a gain end-to-end while completeness falls means the stated mechanism is not
what produced the gain, and the arm does not ship on that reading."*

It fell 5.3pp. **Per the rule written before the run, this does not ship.**

## What the two results together actually say

The arm **answers more** multi-evidence questions on LongMemEval (+4.25 on
two-turn, +2.00 on three-or-more) while **covering less** multi-evidence
evidence on LoCoMo (−4.9pp on both buckets). Not a contradiction in the data —
a contradiction in the assumption the veto was built on, that `complete@k`
tracks accuracy where `recall@k` does not.

That assumption is now falsified twice. `factonly` had the best coverage in the
project and the worst accuracy (`locomo_lost_arms.md`). This arm inverts
**bucket by bucket**: on LongMemEval its coverage gain was in single-evidence
(+5.1pp) and zero in three-or-more, while its *accuracy* gain was the exact
opposite. `complete@k` is not the honest metric this project took it for.

**That is a finding about how to write the next gate, not licence to override
this one.** Re-reading a pre-registration after seeing the numbers is the thing
pre-registration exists to prevent, and the veto's letter is unambiguous.

## What would resolve it

The gate and the veto live on different corpora, and `lme_chunk_memory.md` has
just shown that a result about what reaches the reader **does not transfer
between corpora with different session lengths** — LoCoMo chunks average ~2,600
characters, LongMemEval's ~10,900.

So the measurement that settles this is **LoCoMo end to end**, not LoCoMo
coverage. `all10v2` now exists, so it costs answering and judging only. If the
arm wins there too, the veto was measuring the wrong thing and a new gate can be
registered saying so. If it loses there, the veto caught a real cross-corpus
failure and the arm is correctly closed.

## Predictions, scored

The pre-registration predicted *"complete@100 up on cat1"* and *"a small
positive, under +4"* end to end.

Cat1 complete@100 went **down 5.3pp**. End to end was **+5.75**, above the
stated bound. **Both halves wrong, in opposite directions** — coverage fell
where I said it would rise, accuracy rose further than I allowed.

Fourth written prediction about a ranking or salience change in this project.
Fourth wrong one.

## Caveat on the effect's size

Run-level separation is complete, but the question-level test is not
significant: 26 movers, 17 up and 9 down, Wilcoxon **z = +1.59, p = 0.112**
(reported alongside, not gated on, per the pre-registration). Only 5 questions
went 0/4 to 4/4 and 2 went 4/4 to 0/4 — against `nowtrue`'s 13 and its
Wilcoxon p = 0.007 at a similar run-level separation.

The four replicates share one retrieval configuration and differ only in answer
sampling, so complete separation at run level overstates how settled +5.75 is.
**Trust the direction; do not quote the number.**
