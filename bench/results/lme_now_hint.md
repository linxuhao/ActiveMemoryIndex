# Routing the current date: the largest effect measured on this axis, and it
# depends on a date we do not have

Run 2026-09-04. All four arms answer over **one** retrieval (`base`), so the
only difference between them is one line prepended to the memory list. Four
end-to-end replicates each, prefix 100, the platform's prompts, local judge.

## The decomposition

| arm | what changed | runs | mean | vs base |
|---|---|---|---:|---:|
| `base` | — | 57, 59, 60, 58 | 58.50 | — |
| `qdate-reader` | true date, **question frame**, ungated | 58 | 58.00 | −0.50 |
| routed splice | as above but **gated** on the question needing a present | 70, 72, 71, 70 | 70.75 | +12.25 |
| **`nowtrue`** | gated, true date, **memory channel** | 68, 70, 68, 72 | **69.50** | **+11.00** |
| `nowest` | gated, **estimated** date, memory channel | 55, 56, 59, 58 | 57.00 | −1.50 |

`nowtrue`: permutation 4v4 two-sided **p = 0.029, complete separation** (worst
run 68 against the best base 60); Wilcoxon over 30 movers **z = 2.69, p = 0.007**;
13 questions went from wrong in all four runs to right in all four.

That is the strongest result this project has measured. Three of its four parts
are now separated:

**Routing is the whole difference between +12.25 and −0.50.** Ungated, the two
halves cancel exactly as `lme_temporal_baseline.md` recorded. Gated, the loss
on the 81 questions that do not need a present is **−1.00**, so the pinned
regex leaks very little.

**The channel is nearly free.** The platform's answer template has five slots
and we fill only `speaker_1_memories`, so the question frame is not ours. Moving
the date out of the question and into the memory list as
`[today's date is YYYY-MM-DD]` costs 1.25 questions of the 12.25. Given this
project's four consecutive failures at making a time anchor salient, that was
the outcome to bet against, and it did not happen.

**The date's correctness is everything.**

| | now-anchored (52) | the rest (81) |
|---|---:|---:|
| true date | **+12.00** | −1.00 |
| estimated date | **+0.00** | −1.50 |

Not weak — zero. The estimated arm buys nothing at all on the subset it is
aimed at, and pays a small toll elsewhere.

## Why the estimator fails, and one caveat on that

"Now" was estimated as the newest dated memory in the returned set, the only
present a submission can compute. On the 52 router-positive questions it is
exact 4 times, within three days 8 times, within fifteen days 29 times; median
error +5 days, p75 +21, max +108. A "how many weeks ago" question does not
survive a five-day error.

**The caveat.** LongMemEval-S is adversarial for this estimator by
construction: its haystacks contain sessions that *postdate* the question, so
`question_date` precedes the newest returned memory in 56 of 133 instances. A
dataset where the question is asked after the last message — which is what a
deployed memory service sees — would give the estimator a far better anchor.
This result rules the estimator out **on this instrument**, not in general.

## What this makes the critical path

The mechanism works, is large, is specific, and survives the only channel we
have. It needs one input we are not given.

The platform's public pipelines send `/search` four fields, and the answer
template has no date slot. But those pipelines are the local reproduction path,
**we have never inspected a live platform request**, and pydantic drops unknown
fields in silence — which is exactly why `note_extra` was built, and it has
never been deployed.

So the question "does the platform send us a timestamp" is now worth about
eleven questions on this instrument, and there are two ways to answer it:
deploy `note_extra` and read one evaluation's logs, or ask the platform.

## What this is not

+11.00 is on 133 questions of one type of one dataset under a local judge, on an
instrument that reads about 2.5x the platform's axis C. It does not convert to a
leaderboard number. And the arm that produced it **cannot ship**: it needs a
date nobody gives us. What ships, if anything, is whatever survives once that
input exists.

## A contract question this raises before anything ships

Gating the injection on the question makes the *content* of what `/search`
returns depend on the query. The invariant this project has held is that the
query selects which stored text is returned and never changes the text. A
routed date line breaks that invariant; an ungated one keeps it and is worth
−0.50. That is a decision about what kind of system this is, and it is not
settled here.

## Cost

Eight answer-and-judge passes over 133 questions, no retrieval, no ingest.
About $2.
