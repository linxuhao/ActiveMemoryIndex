# Newest-first ordering — significantly worse, and it breaks the questions the base had right

Read `newest_first_preregistration.md` first. Written before any number below.

## The gate: failed

`lme-ku`, 78 knowledge-update questions, store unchanged, prefix 100, four
replicates. `AMI_NEWEST_FIRST=1` against the shipped configuration.

| arm | replicates | mean | vs base |
|---|---|---:|---:|
| `base` (`kubase1–4`) | 57 · 58 · 56 · 57 | 57.00 | — |
| `newest` (`kunew1–4`) | 47 · 48 · 48 · 48 | **47.75** | **−9.25 = −11.9pp** |

Complete separation in the wrong direction: the best arm run is 8 below the
worst base run. Permutation 4v4 two-sided **p = 0.029, negative**. Paired over
questions: **3 up, 15 down, sign test two-sided p = 0.0075.** Coverage is
identical by construction (order only) and was asserted so.

**Per the rule written before the run, the arm does not ship. `AMI_NEWEST_FIRST`
stays 0.**

## Read 3 first: the switch did what it says

Every returned list was checked: **0 of 156 blocks** (78 questions × raw/fact)
violate newest-first. For the 13 stale questions the new value now precedes
the old in **13 of 13** lists (base: 5 of 13) — typically new at position
~10, old at ~50. And every memory carries its date in its text, so the reader
sees `[2023-10-15]` above `[2023-02-22]`.

## Read 1: the 13 stale questions did not move

| group | n | flipped up | flipped down | unchanged |
|---|---:|---:|---:|---:|
| old value was earlier in the base list (the mechanism's target) | 8 | 1 (`852ce960`) | 1 (`a2f3aa27`) | 6 |
| new value was already first | 5 | 1 (`b6019101`) | 1 (`f685340e`) | 3 |

Net **zero** on the 13 the arm existed for. In 11 of 13 the new value is now
well ahead of the old, and the reader still answers the old value 4/4.

## Read 2: the collateral is the whole result

Of the 56 questions the base answered 4/4, the arm dropped **13**, and **10 of
them went 4/4 → 0/4**:

| qid | question | gold | arm answers |
|---|---|---|---|
| `06db6396` | projects since starting painting classes | 5 | 4 — the earlier count |
| `6aeb4375` | Korean restaurants tried | four | three — the earlier count |
| `89941a93` | bikes currently owned | 4 | three — the earlier count |
| `8fb83627` | National Geographic issues finished | five | three — the earlier count |
| `affe2881` | bird species seen | 32 | 27 — the earlier count |
| `41698283` | camera lens bought most recently | 70-200mm zoom | 50mm prime — the earlier purchase |
| `e493bb7c` | where 'Ethereal Dreams' hangs | bedroom | living room — the earlier location |
| `b01defab` | did I finish 'The Nightingale' | yes | "no, you put it down" — the earlier state |
| `10e09553` | bass caught on the *earlier* trip | 7 | 9 — the later trip |
| `50635ada` | *previous* frequent-flyer status | Premier Silver | refuses |

**Eight of ten answered with an older value than the base did.** The base,
with the list in relevance order, reported the current count; the arm, with
the current statement at the *top* of the list and dated, reported the earlier
one. The two remaining are the two questions on this subset that ask for a
*previous* state, and they broke too.

## What this says about the reader

The pre-registration's mechanism was *"the reader takes the first statement
it meets."* That is falsified: putting the newer statement first, dated, moved
nothing on the stale set and pushed ten settled questions to an **older**
value. The reading that fits both the base and this arm is the opposite —
**the reader treats position in the list as position in time and takes the
last mention as current, ignoring the printed dates**. Under relevance order
the last mention is arbitrary and the base is 73%; under newest-first the last
mention is systematically the oldest, and accuracy falls 12pp.

That reading predicts something specific and cheap: **`AMI_CHRONO_ORDER=1`
(oldest-first, already built) should raise `lme-ku`**, because it makes the
last mention the newest. It was measured flat on temporal
(`lme_temporal_baseline.md`) and never on knowledge-update. It is recorded here
as a *candidate*, with the standing caveat below, not as a plan.

## Prediction, scored

Predicted `lme-ku` **+3 to +6**; actual **−9.25**, significant, opposite sign.
Predicted movement on the 8 and none on the 5; actual: net zero on both, and
the effect was entirely in the 56 the arm was not aimed at.

**Sixth written prediction about how the reader responds to an ordering or
salience change. Sixth wrong — this one wrong in sign, in location, and in
mechanism.** The project's constraint stands and has just been paid for again:
do not reason from "this makes the right thing more visible"; measure.

## Consequence for rung 2

The pre-registration said: if ordering cannot move the 8 it can reach, the
demotion half of canonical-key versioning has no mechanism. It cannot, so
**rung 2 as "demote the older version" is closed before it is built.** What
survives of the State DAG versioning idea is not an ordering. The one ordering
that this result *does* point at is the existing oldest-first switch, which
needs its own pre-registration on this subset before it is believed.

## Guards (temporal and LoCoMo) — 2026-09-22, after the gate

The gate had already failed; these are readings, not decisions.

**Guard 2, `lme-t` (133 temporal, four replicates against `base1–4`):**

| arm | replicates | mean | vs base |
|---|---|---:|---:|
| `base` | 57 · 59 · 60 · 58 | 58.50 | — |
| `newest` (`tnew1–4`) | 54 · 51 · 51 · 49 | **51.25** | **−7.25 = −5.5pp** |

Complete separation, negative, permutation p = 0.029. Same sign and similar
size as knowledge-update. Its mirror image, oldest-first, was flat here
(59 vs 57/59, one replicate). So on this instrument the reader is not
indifferent to order — it is indifferent to *oldest-first* and hurt by
newest-first, which is what "last mention wins" would produce on questions
that ask about the most recent of several dated events.

**Guard 1, LoCoMo `all10v2` (1,540, two replicates against `lc2_base_r1–2`):**

| arm | replicates | mean | vs base |
|---|---|---:|---:|
| `base` | 1033 · 1028 | 1030.5 (.669) | — |
| `newest` | 1025 · 1016 | 1020.5 (.663) | −10.0 = −0.65pp |

Paired: 214 discordant (13.9%, above the ~6% floor), **104 up, 110 down, sign
test p = 0.73**. Churn without direction — the same shape oldest-first
produced on temporal. Category 2 (multi-hop) −15.0 is the only bucket with a
lean (30 up, 44 down); category 4 (single-hop) +5.5 leans the other way.

**Together:** newest-first is significantly worse on both LongMemEval subsets
(−11.9pp knowledge-update, −5.5pp temporal) and noise on LoCoMo. That is the
third search-time mechanism whose LongMemEval and LoCoMo readings disagree,
and again the LoCoMo reading is the flatter one — consistent with the
session-length account in `lme_fact_evidence.md` (a ~2,600-character chunk
leaves little for an ordering to reorder), and still not a prediction.
