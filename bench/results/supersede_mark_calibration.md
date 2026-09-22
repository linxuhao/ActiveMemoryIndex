# Supersession marking — closed at calibration, before the knowledge-update run

Read `supersede_mark_preregistration.md` first. Its step 3 said: τ is the
loosest value whose hand-judged precision is ≥ 0.80 on both the `lme-t` and
`all10v2` stores; *if none reaches 0.80, the arm is closed before the KU run,
on the reading that fact embeddings cannot identify "same attribute".* None
does. **The arm is closed. `AMI_SUPERSEDE_MARK` stays 0 and no KU replicate
was run.**

## Step 1 — best later-neighbour cosine, every fact

| store | facts | with a later fact | p50 | p90 | p95 | p99 |
|---|---:|---:|---:|---:|---:|---:|
| `lme-t` (133 users) | 62,743 | 61,195 | 0.719 | 0.801 | 0.824 | 0.879 |
| `all10v2` (10 users) | 4,691 | 4,562 | 0.822 | 0.889 | 0.908 | 0.944 |

LoCoMo facts sit ~0.1 higher across the board: ten users, two speakers,
months of the same topics — every fact has a near neighbour.

## Step 2 — share marked, and what the marks are

| τ | `lme-t` marked | `all10v2` marked |
|---|---:|---:|
| 0.85 | 1,407 / 61,195 = 2.3% | 1,399 / 4,562 = **30.7%** |
| 0.90 | 387 = 0.6% | 309 = 6.8% |
| 0.95 | 108 = 0.2% | 38 = 0.8% |

Fifteen pairs sampled per band per store (`random.seed(7)`), hand-judged as
**update** (same attribute, changed value), **topic** (same subject, not an
update), or **dup** (restatement of the same fact):

| band | store | update | topic | dup | precision |
|---|---|---:|---:|---:|---:|
| [0.85, 0.90) | `lme-t` | 2 (pasta → fettuccine; city centre → San Francisco) | 13 | 0 | 0.13 |
| [0.90, 0.95) | `lme-t` | 3 (started → finished *The Nightingale*; two sculpture-material changes) | 10 | 2 | 0.20 |
| [0.95, 1.00] | `lme-t` | 1 (asked a 4th-grade question → 1st-grader-can't) | 2 | 12 | 0.07 |
| [0.85, 0.90) | `all10v2` | 0 | 15 | 0 | 0.00 |
| [0.90, 0.95) | `all10v2` | 0 | 13 | 2 | 0.00 |
| [0.95, 1.00] | `all10v2` | 1 (first → fourth tournament) | 4 | 10 | 0.07 |

Nowhere near 0.80. Above 0.95 the marks are overwhelmingly the same fact
extracted twice (`I thanked Dave.` → `I thanked Dave.`, cosine 0.997); in
[0.85, 0.95) they are the same topic continuing (`I am looking for advice on
hiking boots` → `I am wondering about the insulation of these boots`). The
date prefix inside every fact's text makes same-day facts look alike and
different-month facts look different, which is the wrong axis for this job.

## Informational, after closure — the 13 stale pairs on `lme-ku`

Not used for anything; the decision above was taken first. For each stale
question, the earliest fact carrying the old value and the latest carrying
the new value (regex, `ku_stale.py`'s patterns), cosine between them, and
the new fact's **rank among all later facts** of that user:

| qid | cos(old, new) | rank of new among later | later facts |
|---|---:|---:|---:|
| `852ce960` | 0.970 | **1** | 386 |
| `b6019101` | 0.957 | 2 | 95 |
| `031748ae` | 0.938 | 2 | 476 |
| `ba61f0b9` | 0.929 | **1** | 324 |
| `f685340e` | 0.918 | **1** | 375 |
| `7401057b` | 0.906 | 2 | 349 |
| `a2f3aa27` | 0.899 | 2 | 294 |
| `0f05491a` | 0.854 | 3 | 451 |
| `59524333` | 0.847 | 3 | 364 |
| `07741c45` | 0.823 | **1** | 387 |
| `6a1eabeb` | 0.816 | 3 | 210 |
| `830ce83f` | 0.780 | **1** | 141 |
| `69fee5aa` | 0.486 | 215 | 292 |

(`69fee5aa`'s regex caught the wrong "37"; disregard.) **Twelve of twelve
true successors are in the old fact's top three later neighbours**, six at
rank 1, among hundreds. The embedding *ranks* the successor almost
perfectly. What it cannot do is *threshold* it: the true pairs span
0.78–0.97, the same band where the sampled marks are topic chatter and
duplicates. A τ that catches ten of the twelve (≥ 0.82) marks ~4% of `lme-t`
facts and ~40% of LoCoMo facts, nearly all wrongly. "Mark the top-1 later
neighbour regardless of τ" marks every fact, and the samples show what the
top-1 neighbour usually is.

So the link is not the problem; the *decision* is. A successor is
identifiable by rank, not by similarity level — which is a statement about
what a canonical key would buy: it is the thing that turns "nearest later
fact" into "same attribute or not". That is rung 2 proper, an extraction-
prompt change with a matched base, and it is not registered here.

## Standing

- The delivery mechanism (`superseded()` in `app/main.py`) is built, tested
  (`tests/test_supersede.py`, 8/8), and unmeasured end to end — no link of
  acceptable precision exists to feed it.
- Prediction: not scored; the arm never reached the gate.
- The State DAG versioning half at search time is now: ordering ×3 closed by
  measurement, cosine-linked marking closed at calibration. What survives is
  the extractor-keyed link, whose delivery is ready and whose cost is known.
