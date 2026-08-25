# LongMemEval-S temporal-reasoning — baseline, and the falsification of H1

Run 2026-08-19. Store `lme-t`: 133 temporal-reasoning instances, 6,392 `/add`
calls, 6,041 extraction calls, 0 failures. Shipped configuration
(`RAW_FIRST=1`, `WINDOW_RADIUS=1`, `AGENTIC_SEARCH=0`, `RETURN_LIMIT=100`).
Bench container, bench volume, bench port; production untouched.

Pre-registration and decision rule: `lme_temporal_preregistration.md`. Read it
first — it contains the hypothesis this file kills.

## H1 was wrong

The pre-registration predicted a *completeness* deficit: `turn@k` high,
`all-chunks` much lower, because 85% of these questions need evidence from two
or more sessions. What the instrument says:

| | base | base2 (identical config, second run) |
|---|---:|---:|
| `turn@k` — evidence turns retrieved | 0.947 | 0.947 |
| `chunk@k` — evidence chunks retrieved | **1.000** | **1.000** |
| `all-turns` — every evidence turn, every question | 0.924 | 0.924 |
| `all-chunks` — every evidence chunk, every question | **1.000** | **1.000** |
| `all-sess` — every evidence session | 1.000 | 1.000 |

**Retrieval is saturated.** All 133 questions get all of their evidence. There
is no multi-target retrieval deficit to fix, and no retrieval arm can improve a
number that is already 1.000.

The direction is also inverted from the prediction. Multi-evidence questions
are the *easiest* to retrieve, not the hardest:

| subset | n | `turn@k` |
|---|---:|---:|
| single-evidence | 39 | 0.846 |
| 2 evidence turns | 74 | **1.000** |
| >=3 evidence turns | 19 | 0.946 |

The structural argument for H1 — that LoCoMo is 73% single-evidence and
LongMemEval is 69% multi-evidence, so our knobs were tuned on the wrong task —
described the two datasets correctly. The inference from it, that the
difference would show up as missing evidence, did not survive contact with the
measurement. A lexical-overlap check run before the result (worst evidence turn
shares 0.222 of the question's content words against the best turn's 0.375, a
ratio of 0.667, with only 13% of questions having a near-invisible second
piece) already pointed this way and was recorded as weakening H1.

## Where the loss actually is

| | base | base2 |
|---|---:|---:|
| end-to-end accuracy, `gpt-4o-mini`, platform prompts | 0.429 (57/133) | 0.444 (59/133) |

**56% of questions are answered wrong while holding 100% of the evidence.** The
whole of this axis's loss is downstream of retrieval.

Two failures from the pilot, both with complete evidence:

| question | gold | generated |
|---|---|---|
| days between the Sunday mass and the Ash Wednesday service | 30 days (31 also accepted) | 29 days |
| which show did I start watching first | 'Game of Thrones' | 'The Crown' |

Arithmetic and ordering over ~77,000 characters of correctly retrieved context.

## The noise floor, measured before any arm is judged

base and base2 are the same configuration over the same store. Retrieval is
effectively deterministic — every metric above is identical to three decimals,
and the returned text differs by 6 characters out of 77,263. The end-to-end
layer is not:

* net difference: 2 questions (57 vs 59), 1.5 pp
* **discordant pairs: 8 of 133 (6.0%)** — same question, same retrieved set,
  opposite verdict

The net difference understates the noise by a factor of four. **An arm must
move substantially more than 8 questions in one direction to be readable at
this n; a difference under ~6 pp is not interpretable.** This supersedes the
looser wording in the pre-registration, which asked only that an arm beat "the
replicate noise" without fixing a number to it.

## The largest identifiable loss is not ours to fix

42 of these questions are anchored to "now" ("how many weeks ago…", "how many
months since…"). No published pipeline in the platform's evaluation repository
conveys the question date to the answer model, and the answer prompt has no
slot for one.

| subset | n | base | base2 |
|---|---:|---:|---:|
| now-anchored | 49 | 0.286 | 0.286 |
| not now-anchored | 84 | 0.512 | 0.536 |

Not zero — the model sometimes reaches the answer through relations between
memories rather than through the calendar — but 22 pp below the rest. Bringing
this subset up to the rest of the set is worth about +8.6 pp; solving it
outright is worth about +26 pp.

Inferring "now" from the store does not work. `question_date` minus the newest
haystack date has a median of 3.5 days, p75 of 17 days and a maximum of 188
days; only 60 of 133 fall within a day. A system that guessed "now" from its
most recent memory would miscount most of these questions.

## Returned-set size against its budget

Scored on the same retrieval, truncated to a prefix:

| returned | `turn@k` | `chunk@k` | `all-chunks` | characters |
|---:|---:|---:|---:|---:|
| 10 | 0.627 | 0.838 | 0.750 | 12,909 |
| 20 | 0.797 | 0.901 | 0.856 | 25,176 |
| 40 | 0.902 | 0.959 | 0.932 | 48,527 |
| 60 | 0.928 | 0.974 | 0.962 | 69,261 |
| 100 | 0.947 | 1.000 | 1.000 | 77,263 |

`RETURN_LIMIT=100` was chosen by sweeping LoCoMo. On this unrelated instrument
100 is exactly where coverage saturates, which is an independent check on that
decision rather than a restatement of it.

Shortening the context is a narrower option than it looks. The last 40 items
cost 11% more characters and buy the final 3.8 points of coverage, because
raw-first puts the long verbatim turns at the head and the short extracted
facts at the tail — items 61-100 average about 200 characters each.

## Consequences

* Every arm aimed at retrieval coverage — the agentic second round, query
  decomposition, multi-vector retrieval — has nothing to gain here. They were
  the plan; the plan was wrong.
* The arms worth running on this axis are reader-side: ordering (`chrono`),
  and whether the reader knowing the date recovers the now-anchored subset.
* The neighbour window and `RETURN_LIMIT` are both vindicated on an instrument
  they were not tuned on.

---

# Arms

All arms read the same store. `qdate-reader` reuses `base`'s retrieval file
byte for byte and changes only what the answer model is told, so it isolates
the reader from any retrieval difference.

| arm | accuracy | vs base | discordant vs base |
|---|---:|---:|---:|
| base | 0.429 (57/133) | — | — |
| base2 — identical config | 0.444 (59/133) | +2 | 8 |
| qdate-reader — reader told the current date | 0.436 (58/133) | +1 | 31 |
| chrono — each block oldest-first | 0.444 (59/133) | +2 | 28 |

Every arm lands inside the noise floor. Neither is worth shipping on this
evidence. **But the net figure hides the largest effect measured in this
cycle**, and reporting these three numbers alone would have been wrong.

## The question date: +26.5 pp where it is needed, -14.3 pp where it is not

| subset | n | base | base2 | qdate-reader |
|---|---:|---:|---:|---:|
| now-anchored | 49 | 0.286 | 0.286 | **0.551** |
| the rest | 84 | 0.512 | 0.536 | **0.369** |

15 discordant pairs on the 49-question subset, against a same-config floor of
2 on that same subset. This is an effect, not jitter, and the two halves cancel
to nothing.

### What the damage is not

It was first attributed here to the judge's rule against converting relative
expressions into absolute ones. **That explanation was checked and is wrong.**
Of the 15 questions that went CORRECT to WRONG, only 1 gained an absolute date
it did not have before, and only 5 have a gold answer that is a bare relative
expression.

### What the damage is

The arithmetic itself degrades:

| question | gold | base | qdate-reader |
|---|---|---|---|
| days between finishing the book and the book club | 18 days | **18 days** | 14 days |
| months before the anniversary that Rachel got engaged | 2 | **2 months** | 1 month |
| days before buying the iPhone that the Holiday Market was attended | 7 days | **a week** | 15 days |
| which happened first, meeting Rachel or the pride parade | meeting Rachel | **meeting Rachel (Apr 10 before May 1)** | the pride parade |

These are memory-to-memory questions with no bearing on the present. Supplying
a current date adds a third anchor to a two-anchor computation and the model
tries to use it. The last row loses an ordering it had right.

This generalises past this arm. The reader already sees 100 timestamped
memories across 77,000 characters. If one additional date can derail a
subtraction between two others, the number of competing anchors in the returned
set is itself a variable worth measuring — which makes the shorter prefixes,
dismissed above as a poor character-for-coverage trade, worth an end-to-end
test they had no motivation for before.

### What the gain depends on

The dataset's `question_date` precedes the newest memory we return in 56 of 133
instances, because the haystack carries sessions that postdate the question.
The gain is concentrated where it does not:

| subset | n | base | qdate-reader |
|---|---:|---:|---:|
| now-anchored, stated date at or after the newest returned memory | 37 | 0.297 | **0.622** |
| now-anchored, stated date precedes a returned memory | 12 | 0.250 | 0.333 |
| not now-anchored, date consistent | 40 | 0.525 | 0.375 |
| not now-anchored, date inconsistent | 44 | 0.500 | 0.364 |

The damage is flat across both date conditions (-0.150 and -0.136), so it is
not caused by an inconsistent date. The gain is not: +0.324 when the date is
consistent against +0.083 when it is not.

So the date is worth roughly +26 pp on a third of this axis and cannot be
applied indiscriminately. It is also not ours to supply: no pipeline in the
platform's public evaluation repository conveys the question date, the answer
prompt has no slot for one, and inferring it from the newest stored memory is
wrong by a median of 3.5 days and a p75 of 17. **This is a contract question,
not an engineering one.**

## Chronological ordering does nothing, including where it should

| subset | n | base | base2 | chrono |
|---|---:|---:|---:|---:|
| questions containing an ordering word (first, before, after, order, earlier, later) | 64 | 0.516 | 0.500 | **0.516** |
| the rest | 69 | 0.348 | 0.391 | 0.377 |

Flat to three decimals on the subset built to favour it, while flipping 28
verdicts across the set against a floor of 8 — churn without direction. The
arm was added after seeing two pilot failures, was declared as post-hoc in the
pre-registration, and is now closed.

Note which subset is hard. Ordering questions are the *easier* half (0.516
against 0.348). What fails is duration arithmetic anchored to the present.

## Where this leaves the axis

Of 133 questions with complete evidence, 76 are answered wrong. About 35 of
those are now-anchored, and roughly 13 of them are recoverable by a date the
contract does not carry. The rest is `gpt-4o-mini` doing calendar arithmetic
over 77,000 characters, which no retrieval change reaches.

That the entire open leaderboard sits at 18-24.6 on this axis while one
commercial entry reports 60.0 is consistent with the date being conveyed on
some integration path we cannot see from the public repository. That is a
hypothesis this instrument cannot test, not a finding.

---

# Context volume is not a variable

The qdate result suggested a generalisation: if one spurious date can derail a
subtraction between two others, perhaps the hundred timestamped memories we
already return are themselves interference. **Tested, and false.**

Scored on the same retrieval, truncated before the answer stage:

| returned | complete evidence | accuracy | **accuracy given complete evidence** | characters |
|---:|---:|---:|---:|---:|
| 40 | 0.932 | 0.402 | **0.431** | 48,527 |
| 60 | 0.962 | 0.417 | **0.433** | 69,261 |
| 100 | 1.000 | 0.432 | **0.432** | 77,263 |

The context nearly doubles and the conditional accuracy does not move in the
third decimal. Returned-set size decides only whether the evidence is present;
once it is, the reader succeeds at 43.2% regardless of how much text surrounds
it. The qdate damage came from putting a false anchor in the question's frame,
not from the volume of anchors in the memories, and the generalisation drawn
from it here was wrong.

# The axis, closed

1. At `top_k=100` every one of the 133 questions receives all of its evidence.
2. Given that evidence, `gpt-4o-mini` answers 43.2% correctly.
3. That rate is invariant to how much context is returned.
4. The only intervention measured to move it is the question date: +32.4 pp on
   the 37 questions where the date is consistent with the memories, at a cost
   of -14 pp everywhere else, and the contract does not carry it.

Nothing on the memory system's side of the interface changes this number. The
arms that were planned for September — a second retrieval round, query
decomposition, multi-vector retrieval, write-time relative-date normalisation,
fact versioning — all address a bottleneck that this instrument says does not
exist on this axis.

## What does not transfer

This instrument reads 0.432 where the platform's axis C reads 18.35, and the
LoCoMo harness reads ~0.5 on its own temporal category. **Both local
instruments sit roughly 2.5x above the platform.** Axis C aggregates three
leaves across an undisclosed mix of datasets under an undisclosed judge, so
what generalises from this file is the *ordering* of arms and the *location* of
the bottleneck, not the number. Whether axis C as a whole is retrieval-saturated
the way LongMemEval temporal-reasoning is remains untested.

## What to measure next

The same harness, the same store-building cost (~6,400 Add calls, about two
hours), pointed at a different `question_type`. The question for each axis is
the one this file answered for C: is the loss upstream of the interface, where
we can reach it, or downstream, where we cannot?

| subset | n | axis it feeds | our score |
|---|---:|---|---:|
| `multi-session` | 133 | B, relational and multi-hop | 45.04 |
| `knowledge-update` | 78 | D, memory governance | 37.95 (first on the board) |

`multi-session` first: B is the second-weakest axis, all 133 of its questions
need two or more sessions, and if *its* loss is retrieval-side then that is
where September belongs.
