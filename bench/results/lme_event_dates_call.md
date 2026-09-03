# A dedicated dating call at Add — the gate failed negatively, and the family closes

Run 2026-09-03 against `lme_event_dates_call_preregistration.md`. Store
`lme-t3`: LongMemEval-S temporal-reasoning, 6,392 Add calls,
`AMI_EVENT_DATES_ADD_CALL=1`, extraction prompt untouched, 124 minutes, 15,378
LLM calls, 0 failures. Four end-to-end replicates per arm.

## Verdict

**Fails, and in the wrong direction.** Per the pre-registration, this ends the
event-date family.

| | runs | mean |
|---|---|---:|
| `t3base` (dates stored, not rendered) | 59, 59, 58, 59 | 58.75 |
| `t3call` (rendered) | 58, 55, 55, 58 | **56.50** |

**−2.25**, permutation p = 0.086, overlapping. Wilcoxon over the 23 movers
z = −0.96; 8 up, 15 down.

## The base parity check passed, which makes this the cleanest of the three

Extraction kept its original prompt, and the store reproduces `lme-t`:

| | facts | zero-fact chunks | base mean |
|---|---:|---:|---:|
| `lme-t` | 62,743 | 910 (14.2%) | 58.50 |
| `lme-t2` (merged, confounded) | 67,886 | 474 (7.4%) | 60.25 |
| **`lme-t3`** | **63,133** | **904 (14.1%)** | **58.75** |

`lme-t2`'s +1.75 floor shift is gone. This arm's −2.25 is the arm.

## I have to withdraw the explanation in the previous file

`lme_event_dates_add.md` concluded that the merged arm underperformed because
the dates were worse — 38.6% non-trivial against the search-time reading's
68.3% — and predicted a dedicated call would recover the effect. The dedicated
call produced **better**-looking dates and did **worse**:

| reading | non-trivial dates | end to end |
|---|---:|---:|
| merged into extraction, at Add | 38.6% | +2.00 |
| dedicated call, at search | 68.3% | **+5.75** |
| dedicated call, at Add | **75.8%** | **−2.25** |

Non-monotone. **The non-trivial rate does not predict the outcome, so it was
never a quality measure** — a date that differs from the said-date can be an
extraction or a fabrication, and that audit cannot tell them apart. The
prediction written into the pre-registration ("if load was the cause, this
recovers most of +5.75") was wrong, and it was wrong in a way the audit could
not have caught.

## The three readings produce broadly the same dates

Measured on the returned sets, so this is what the answer model actually saw:

| | dated | non-trivial | dated *after* the said-date | turns / facts |
|---|---:|---:|---:|---|
| search-time (`evdate`) | 10.13% | 68.3% | 13.0% | **700 / 647** |
| Add, dedicated (`t3call`) | 9.02% | 75.8% | 15.0% | **469 / 731** |
| Add, merged (`t2evadd`) | 10.14% | 38.6% | 5.6% | 696 / 653 |

Where the search-time and Add-dedicated readings dated the same memory — 770
cases — they **agree on 87.7%** of the dates. Comparable coverage, comparable
error smell (13–15% of dates fall after the date the memory was uttered, which
the prompt forbids), largely the same answers. And the results are +5.75,
+2.00, −2.25.

The one structural difference left standing: the search-time reading dates
**150% as many verbatim turns as the Add readings do**, and correspondingly
fewer facts. Whether that is what matters is untested.

## What actually closes the family

The arm that worked is the one that read the **returned set** — the memories
this question was about, seen together, after selection. Both arms that read at
write time, with and without competition from extraction, failed. That property
is exactly the one that cannot ship: it costs about five calls per search and
roughly 24,000 per formal evaluation, dating a memory once for every question
that returns it.

So the event-date family is closed: the version that helps cannot be afforded,
and both affordable versions were measured and do not help. The switches stay
in the code, all off.

## The pattern this is the fourth instance of

| arm | what it made salient | result |
|---|---|---|
| `qdate-reader` | a current date in the question frame | +26.5 pp where needed, −14.3 pp elsewhere |
| `dayidx` | a numeric day beside every timestamp | fixed subtractions, broke ordering |
| `rerank` | one best passage at the head | recall@1 doubled, multi-hop completeness −10.3 pp |
| `t3call` | better event dates, written once | −2.25 |

Four interventions whose effect on the reader was not predictable from any
measurable property of what they changed. Two of them were predicted by this
project in writing beforehand, and both predictions were wrong. That is the
finding worth carrying into September, and it is a constraint on the whole
strategy of formatting the returned set, not a fact about dates.

## Cost

`lme-t3`: 124 minutes, 15,378 extraction and dating calls. Plus 8 × 133 answer
and judge calls. About $7. Cumulative on the event-date family across three
stores: about $18. Nothing shipped.
