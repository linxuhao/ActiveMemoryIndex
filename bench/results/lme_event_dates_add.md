# Event dates read at Add — gate failed, and the reason is not the timing

Run 2026-09-02 against the decision rule in
`lme_event_dates_add_preregistration.md`, written before the store was built.
Store `lme-t2`: LongMemEval-S temporal-reasoning, 133 questions, 6,392 Add
calls ingested with `AMI_EVENT_DATES_AT_ADD=1`, 166 minutes, 0 LLM failures.
Four end-to-end replicates per arm, prefix 100, the platform's prompts, local
judge. `lme-t` was not touched.

## Verdict

**Fails both clauses of the gate. Not shipped.**

| clause | required | measured |
|---|---|---|
| permutation 4v4, two-sided | p < 0.05 | **p = 0.086**, overlapping |
| now-anchored subset | moves ≤ 1 question | **+1.50** |

| | runs | mean |
|---|---|---:|
| `t2base` (dates stored, not rendered) | 59, 61, 61, 60 | 60.25 |
| `t2evadd` (rendered) | 62, 64, 62, 61 | **62.25** |

+2.00, against +5.75 for the same rendering fed by the search-time reading.

## The confound check, read first

The pre-registration required the new base be compared to the old before
anything else. The longer prompt moved the floor:

| | zero-fact chunks | facts stored | base mean |
|---|---:|---:|---:|
| `lme-t` (original prompt) | 910 / 6,392 (14.2%) | 62,743 | 58.50 |
| `lme-t2` (dated prompt) | **474 / 6,392 (7.4%)** | 67,886 | **60.25** |

+1.75 on the base from the prompt change alone, under the pre-registered
threshold of two questions, so the arm was read — but it means the +2.00 is
measured from a floor that already moved, and the two stores' absolute numbers
are not interchangeable.

## Under one rule, the two arms have opposite shapes

The subset rule in the original write-up was not saved; both arms are re-scored
here under the rule pinned in the pre-registration amendment (52 of 133
questions are now-anchored).

| | now-anchored (52) | not now-anchored (81) | p |
|---|---:|---:|---:|
| search-time reading (`lme-t`) | +0.75 | **+5.00** | 0.029, complete separation |
| write-time reading (`lme-t2`) | **+1.50** | +0.50 | 0.086, overlapping |

The search-time arm moved only the subset its mechanism addresses. This arm
moves mostly the subset the mechanism *cannot* address — the questions that
need a present the system is never given. That is the signature of a small
diffuse lift, not of a working date channel, and the pre-registration named it
in advance as grounds for a different write-up.

## It is not the number of dates

The obvious explanation is that a write-time reading dates fewer memories. It
does not:

| share of returned memories carrying an event date | |
|---|---:|
| search-time (`evdate`) | 10.14% |
| write-time (`t2evadd`) | **10.17%** |

Identical, and the kinds are the same too (search-time 700 turns / 648 facts,
write-time 697 / 655).

## It is the quality of the dates

| | happened ≠ said |
|---|---:|
| search-time reading | **68.3%** (920 / 1,347) |
| write-time reading | **38.6%** (521 / 1,349) |

The write-time reading answers "it happened the day it was said" nearly twice
as often. A date equal to the utterance date is the answer the memory already
carried; it renders a longer prefix and adds nothing.

Joining the two on question and memory text, 389 memories were dated by both,
and they agree on only **74.0%**. The disagreements run one way:

    said 2023-05-26   search-time -> 2023-01-10   write-time -> 2023-05-26
      "I'm looking for some book recommendations. I recently attended a book reading..."
    said 2023-11-29   search-time -> 2023-09-25   write-time -> 2023-11-29
      "I'm looking for some information on local charity events happening..."

The write-time reading falls back to the envelope; the search-time reading digs
the event out of the prose. That is the whole difference between the arms.

## What this licenses, and what it does not

It does **not** show that dating at Add is wrong. It shows that **asking for
the dates as a side-task of the extraction call gets a worse answer than asking
for them alone.** Same model, same memories, same coverage, half the
non-trivial rate. The extraction call is reading a whole chunk and producing up
to 24 facts; the dating is a second job done under that load, and it satisfices.

The cheap thing that separates those two explanations is a **dedicated dating
call at Add** — one extra call per chunk, the same prompt the search-time arm
used, still priced once per memory instead of once per retrieval. That is 6,392
calls to build a store against roughly 24,000 per formal evaluation at search
time, so the economics that ruled out the search-time arm still favour Add.
It has not been run.

## Cost

166 minutes and 6,392 extraction calls to build `lme-t2`, plus 8 × 133 answer
and judge calls. About $6. Nothing shipped.
