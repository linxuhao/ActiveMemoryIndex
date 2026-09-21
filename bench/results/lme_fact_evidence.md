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

---

# 2026-09-22 — LoCoMo end to end: significantly worse. Closed.

The reading registered in the pre-registration's 2026-09-22 amendment.
`all10v2`, `base` and `factev`, two replicates each, retrieve → answer → judge
at prefix 100, n=1540.

| arm | replicates | mean | vs base |
|---|---|---:|---:|
| `base` | 1033 · 1028 | 1030.5 (.669) | — |
| `factev` | 1001 · 1006 | 1003.5 (.652) | **−27.0 = −1.75pp** |

Paired over questions: **195 discordant (12.7%, above the ~6% floor), 82 up,
113 down, sign test two-sided p = 0.031**, negative. 38 questions went 0/2 → 2/2,
61 went 2/2 → 0/2.

| bucket | n | base | arm | delta | up | down |
|---|---:|---:|---:|---:|---:|---:|
| category 1 | 282 | 140.0 | 131.0 | −9.0 | 20 | 30 |
| category 2 | 321 | 167.5 | 158.5 | −9.0 | 23 | 33 |
| category 3 | 96 | 47.0 | 43.5 | −3.5 | 3 | 9 |
| category 4 | 841 | 676.0 | 670.5 | −5.5 | 36 | 41 |
| needs 1 turn | 1127 | 819.5 | 807.0 | −12.5 | 59 | 72 |
| needs 2 turns | 225 | 130.0 | 123.0 | −7.0 | 10 | 19 |
| needs ≥3 turns | 184 | 78.0 | 70.5 | −7.5 | 13 | 22 |

Down in every category and every evidence bucket — including the three-or-more
bucket, which is where LongMemEval gained most. **The registered rule's second
branch applies: the veto caught a real cross-corpus failure. The arm is closed.
`AMI_FACT_EVIDENCE` stays 0.**

## What this actually is

One switch, two corpora, both significant, opposite signs:

| | LongMemEval temporal | LoCoMo |
|---|---:|---:|
| end to end | **+5.75 / 133**, p=0.029 | **−27 / 1540**, p=0.031 |
| complete@100 | +0.8pp (0 on ≥3-turn) | −5.3pp on cat1 |
| chars per chunk | ~10,900 | ~2,600 |

This is the second mechanism in two days whose sign is set by the corpus rather
than by the reader (`lme_chunk_memory.md` was the first). The candidate
explanation — **post hoc, from two points, not to be believed until it predicts
something** — is the same property both times: session length. In a short
LoCoMo chunk the neighbour window (±1 around any selected turn) already reaches
most of the chunk, so the two turns a fact pulls are largely redundant and only
displace breadth, which is the −5.3pp coverage. In a long LongMemEval session
the window reaches almost none of it, and a fact's two best turns are evidence
the reader would otherwise never see.

If that explanation is right it is *testable*, and testable by a rule that
gates on a **measurable property of the data** rather than on a guess about
salience: expand only when the fact's chunk is longer than some threshold. That
is not registered here. It would need its own pre-registration and, per the
lesson of this file, **end-to-end on both corpora** as the gate, no coverage
veto.

## Partial retraction of the section above

"What the two results together actually say" claims the veto's premise —
`complete@k` tracks accuracy — was falsified twice. That was too strong. Within
LoCoMo, coverage fell and accuracy fell: **the veto and the outcome agree**, and
the veto did its job. What is falsified is narrower and more useful:

1. a coverage reading on one corpus does not predict accuracy on another
   (this arm), and
2. within LongMemEval, coverage and accuracy inverted bucket by bucket
   (the section "The gain is where the mechanism said it would be" against
   read 1).

`complete@k` is not unreliable. It is **not portable across corpora**, and on
this one subset it is not portable across evidence buckets either.

## Consequence for cycle 2

The evaluation is 32 sources. A switch that is +4.3pp on one session-length
distribution and −1.75pp on another cannot be shipped as a global default on a
corpus whose distribution is unknown. Any future arm of this shape needs either
a data-gated rule or evidence on both instruments before it can be turned on.
