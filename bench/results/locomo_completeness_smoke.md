# LoCoMo completeness smoke — the multi-target deficit is on multi-hop, not temporal

Run 2026-08-19, conversations 2-3, 90 Add calls, 351 questions with evidence.
Shipped configuration. A smoke, not a full run: two conversations, no
end-to-end layer, no replicate. Read the direction, not the third decimal.

## Why this exists

`bench/results/lme_temporal_baseline.md` found LongMemEval temporal-reasoning
retrieval saturated and concluded the whole multi-target family had nothing to
do. That conclusion was drawn from one subset of one dataset. The platform's
own leaderboard contradicts it: the answer model and judge are held fixed
across submissions, so an open system scoring 24.6 on axis C against our 18.35
differs only in which memories it returned. Six points exist somewhere we had
not looked.

## The metric this smoke added

`run_bench.py report` counted a question as retrieved when **any** one of its
evidence turns was inside the top k. That cannot distinguish "found one of the
three" from "found all three", and 26.8% of LoCoMo questions need two or more
evidence turns — 97.9% of category 1. A completeness metric was added
alongside; the two come apart exactly where it matters.

| | recall@100 (any) | complete@100 (all) |
|---|---:|---:|
| all questions, n=351 | 0.923 | **0.835** |

## Where the deficit is

| complete@100 | n | base | agentic on |
|---|---:|---:|---:|
| category 1 — multi-hop | 68 | **0.559** | **0.559** |
| category 2 — temporal | 67 | 0.910 | 0.940 |
| category 3 | 19 | 0.579 | 0.632 |
| category 4 — single-hop | 197 | 0.929 | 0.944 |
| needs 1 evidence turn | 264 | 0.920 | 0.936 |
| needs 2 evidence turns | 54 | 0.741 | 0.741 |
| needs >=3 evidence turns | 33 | **0.303** | 0.364 |
| all | 351 | 0.835 | 0.852 |

**44% of multi-hop questions never receive all of their evidence, and 70% of
questions needing three or more turns do not.** This is the deficit predicted
in the LongMemEval pre-registration and not found there. It is real; it lives
on the category that feeds axis B (relational and multi-hop, our 45.04), not
the one that feeds axis C.

It was also partly visible in the LongMemEval run and was missed there, because
`all-chunks` (1.000) is the generous measure — a fact's provenance is its whole
chunk — while the strict `all-turns` measure read 0.924 overall and **0.789 for
questions needing three or more turns**. The saturation claim in that file
leaned on the generous number. Checked against the end-to-end labels, the ten
questions that were chunk-complete but not turn-complete score 0.200 against
0.451 for the strictly complete ones — a real gap worth about two questions in
132, inside that instrument's noise floor, so the conclusion there survives on
the strict metric even though the wording did not.

## The agentic second round does not address it

`AMI_AGENTIC_SEARCH=1` — reflect on the first round, fire one more targeted
recall when the evidence looks incomplete — was the mechanism this project
already had for exactly this failure. On the category it was aimed at it moves
**nothing**: 38 of 68, before and after.

Its +1.7 pp overall is six questions spread across categories that had little
deficit to begin with, including three in category 4 which was already at
0.929. It costs one extra LLM call on every search. **Not shipped.**

This is a clean negative on a pre-registered target, and it leaves the cycle in
an honest place: the deficit is located and the tool for it is not found.

## Caveats

Two conversations, one seed, retrieval layer only. Category 3 is n=19 and
category 1 is n=68, so the per-category figures carry real sampling error; the
>=3-turn row is n=33 and its +2 questions under agentic mean nothing on their
own. What this smoke establishes is a location, not a magnitude.

---

# Where the missing evidence sits

Same store, our own `RETURN_LIMIT` raised to 600 for the measurement only — the
contract caps `top_k` at 100 and nothing here proposes returning more.

`AMI_RAW_FIRST` had to be turned off for this probe. It reorders the whole
selected list *after* selection, so under a 600 cap it floats every verbatim
turn above every fact and the first 100 of a 600-list are not the 100 a 100-cap
would return. The first attempt at this measurement left it on and reported
38.2% complete-within-100 against the smoke's 55.9%; with relevance order
restored the two agree exactly at 38/68. **Any diagnostic that widens the
return and truncates is measuring a different list unless raw-first is off.**

| category 1, n=68 — depth needed for ALL evidence | n | share |
|---|---:|---:|
| complete within 100 | 38 | 55.9% |
| needs 101-200 | 12 | 17.6% |
| needs 201-400 | 11 | 16.2% |
| needs 401-600 | 5 | 7.4% |
| not found within 600 | 2 | 2.9% |

Median depth of the evidence that falls outside the cut: **213**. Only 2 of 68
questions have evidence the ranker never surfaces at all.

**This is not a recall failure. It is a slot-allocation failure.** The retriever
finds the evidence and ranks it just past the cut.

# The neighbour window is the slot tax

At radius 1 each verbatim hit consumes three slots — itself and the turns
either side — so 100 slots buy 33 sources. Sweeping the radius on the same
store, retrieval only:

| complete@100 | r=0 | r=1 (shipped) | r=2 |
|---|---:|---:|---:|
| category 1 — multi-hop (68) | **0.662** | 0.559 | 0.529 |
| needs >=3 evidence turns (33) | **0.424** | 0.303 | 0.273 |
| needs 2 evidence turns (54) | **0.796** | 0.741 | 0.685 |
| needs 1 evidence turn (264) | 0.898 | 0.920 | **0.936** |
| category 4 — single-hop (197) | 0.904 | 0.929 | **0.934** |
| category 2 — temporal (67) | 0.910 | 0.910 | **0.940** |

Monotone in both directions across three points: every multi-evidence row falls
as the radius grows, every single-evidence row rises. The window buys local
context with breadth, and which side of that trade wins depends entirely on how
many distinct sources the question needs.

## What this does not license

The window's +4.5/+4.7 points were measured **end-to-end**. Everything in this
file is **coverage**. On this project's own LoCoMo record the two are *inverted*
across arms, which is why `bench/README.md` says never to gate a decision on
recall@k. Seven more complete category-1 questions at r=0 may be worth nothing,
or less than nothing, once the answer model sees a context stripped of the
turns that give a message its antecedent.

**No change to `AMI_WINDOW_RADIUS` is proposed on this evidence.**

## What it does suggest

One global radius cannot serve both populations: it helps 264 single-evidence
questions and harms 87 multi-evidence ones, in the same sweep, monotonically.
The problem is not which value to pick; it is that there is only one value.

The shape a fix would take is a **breadth floor** — allocate slots to distinct
sources by relevance first, guarantee some number of them, and spend only the
remainder on neighbours. Single-evidence questions never exhaust a hundred
sources, so they would keep their context; multi-evidence questions would stop
paying for context they did not ask for. That is a two-pass change to
`select()`, and it needs an end-to-end measurement before it is worth anything.
