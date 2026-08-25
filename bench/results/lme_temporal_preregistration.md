# Pre-registration — LongMemEval-S temporal-reasoning, September cycle

Written 2026-08-19, before any arm was run. Ledger rule: the hypothesis and the
decision rule go on disk before the first call, not after the first number.

## Why a second instrument

Every retrieval knob in this project was chosen on LoCoMo. Measured on the
public data, the two benchmarks are different tasks:

| instrument | questions needing >=2 pieces of evidence | median evidence |
|---|---:|---:|
| LoCoMo, all (n=1540, cat5 excluded) | 26.8% | 1 turn |
| LoCoMo cat2, its temporal category (n=321) | 12.5% | 1 turn |
| LoCoMo cat4 (n=841, 55% of the set) | 5.5% | 1 turn |
| LongMemEval-S, all (n=500) | 69% | 2 turns |
| LongMemEval-S temporal-reasoning (n=133) | 85% (113/133) | 2 turns |

On a set where three quarters of questions want one thing, filling the returned
100 with near-duplicates of that one thing is optimal. That is the regime our
diversity-cap arm lost in (.5799, rejected) and the regime `AMI_AGENTIC_SEARCH`
was switched off in. Neither result transfers to a multi-target task by itself.

## Instrument

* `longmemeval_s_cleaned.json` (the original is deprecated upstream; the two
  differ by ~180 turns out of 246,930, so the choice is not load-bearing).
* `question_type = temporal-reasoning`, n=133 after excluding abstention items,
  which have no supporting memory the way LoCoMo category 5 has none.
* One `user_id` per question: each instance carries its own ~48-session haystack.
* Store tag `lme-t`, ingested once at shipped write-time settings and reused by
  every retrieval-only arm. An arm that changes write behaviour needs its own store.
* Bench service is a separate container, separate volume, separate port.
  Production is not touched.

## Primary metric

**`all-chunks`** — the share of questions where *every* evidence turn's chunk is
represented in the returned set. Per-turn recall cannot distinguish "found one
of the two events" from "found both", and on this subset that is the whole
question.

Secondary: end-to-end accuracy under the platform's own LongMemEval answer and
judge prompts, `gpt-4o-mini`, temperature 0.

## H1

Our shipped configuration has a *completeness* deficit, not a recall deficit:
`turn@k` will be substantially higher than `all-chunks`. If instead the two are
close and both low, the bottleneck is ordinary retrieval quality and the
multi-target framing is wrong.

## Arms (retrieval-only, one shared store)

| arm | change | why |
|---|---|---|
| `base` | shipped defaults | reference |
| `agentic` | `AMI_AGENTIC_SEARCH=1` | second targeted recall when evidence looks incomplete — a multi-target mechanism switched off on a single-target instrument. Confounded until its merge path is fixed: it bypasses `select()`, so it also drops raw-first and the window. Report as confounded or fix first. |
| `nowindow` | `AMI_WINDOW_RADIUS=0` | the window was chosen on LoCoMo; neighbours spend slots that multi-target questions may need for the second event |
| `qdate` | question date prepended to the query | ceiling probe, not a shippable arm: 42/133 questions are anchored to "now" and the platform's answer prompt has no slot for it |

## Decision rule, fixed in advance

1. An arm ships only if it improves **both** `all-chunks` and end-to-end
   accuracy. Retrieval coverage alone does not select: on LoCoMo the arms are
   *inverted* between the two layers, and a pre-registered coverage gate would
   have selected the worst configuration. That mistake is not repeated here.
2. `qdate` is a measurement of headroom. Whatever it is worth, it is not
   shipped unless the contract is shown to carry the question date.
3. Any arm that costs an extra LLM call per search must beat `base` by more
   than the replicate noise of this instrument, which is measured before any
   arm is judged, not assumed.
4. A judge failure is a missing measurement, never a WRONG verdict.

## Known confound, stated up front

Extraction returns no facts for ~16% of LongMemEval chunks (the model replies
`{"facts": []}`; zero timeouts). Sessions here are often the user asking for
information and the assistant explaining at length, which carries no personal
fact. The facts channel is therefore thinner on this instrument than on LoCoMo,
and per-kind numbers must be read with that in mind.


---

## Amendment, 2026-08-19, after the pilot — declared, not folded in

Two questions were run end-to-end on a 2-instance pilot before the full store
finished. Both retrieved **all** their evidence (`all-chunks` = 1.000) and both
were judged WRONG:

| question | gold | generated |
|---|---|---|
| days between the Sunday mass and the Ash Wednesday service | 30 days (31 also accepted) | 29 days |
| which show did I start watching first | 'Game of Thrones' | 'The Crown' |

Both failures are arithmetic and ordering over evidence that was present, in a
~64,000-character context — not retrieval misses. n=2 settles nothing, and the
full run may not reproduce it.

**New arm, added after seeing data — recorded here so it is never mistaken for
part of the original hypothesis:**

| arm | change | why |
|---|---|---|
| `chrono` | order the returned set by `created_at` instead of relevance, within the raw-first block | "which came first" is nearly readable off the page when the memories arrive in time order. Ordering was the largest single win on LoCoMo (raw-first, +4.5pt), costs no LLM call, and changes order only, never membership. |

If H1 fails — `turn@k` and `all-chunks` close together and both low — then the
bottleneck is the reader, `chrono` is the arm that addresses it, and the
multi-target framing in this document is wrong. That outcome gets reported as
plainly as the other one.

### Instrument artifact, measured not assumed

Spacing turns one minute apart inside a session pushes 280 of 65,519 turns
(0.43%) past midnight into the following date. **0 of 259 evidence turns** are
affected, so it did not cause the off-by-one above and does not justify
re-ingesting. Recorded as a known deviation.
