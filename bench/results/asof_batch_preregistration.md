# Pre-registration — batched as-of time reading as an rc6 candidate (2026-10-16)

> **FROZEN before any model call.** User request 2026-10-15/16 ("1，2，3继续做",
> "我们继续测试"). Branch `research/asof-batch-rc6-20261016` = rc5 (90bb326) + the
> batching change only. Diagnosis: `asof_times_truncation_20261015.md`.

## Change

`AMI_ASOF_BATCH=50`: the as-of item-side time reader runs as parallel calls of at
most 50 lines, each capped at `AMI_LLM_MAX_TOKENS_ASOF_BATCH=1200` (raised from the
diagnosis's 800 so a 50-line said-date enumeration finishes). A failed batch leaves
only its own items unjudged and never withheld; all batches failing withholds
nothing, as rc5. Default 0 keeps rc5's single call byte-identical. Arms: **R** = rc5
(single call, cap 3,000), **C** = batches.

## Part 1 — the 26 big-list as-of Searches (where C changes behaviour)

The keyed-prompt study's B store (copy in volume `ami-asofb`) and its 26
as-of-state Searches (LoCoMo 24, LongMemEval temporal 1, BEAM-100K 1), replayed
with C at cap 1,200 (harness of the diagnosis session). R's lists, answers and
verdicts are the archived B arm (LoCoMo ×2, LME ×4, BEAM ×1). C is answered with
the same prompts and salts.

* **Gate 1a:** `times_failures` = 0 on all 26 C Searches.
* **Gate 1b:** C − R ≥ −1.0 correct answers (mean over replicates) on the 26.
* Reported: the 4 questions R left unselected (conv3-q187, conv5-q78, conv6-q12,
  conv9-q75), per replicate.

## Part 2 — regression on rc5's as-of validation sets (small lists)

Fresh build of `bench/rc5_asof_data.py` streams (TempReason L2 150, L3 100, synthetic
en/fr/de/es/zh/ja 48 streams / 288 questions incl. 48 "now"), ingested by the rc6
image with production settings into a new store; Search in-process under R and C;
leaderboard LongMemEval answer and judge prompts, gpt-4o-mini, ×2 replicates. Most of
these lists are under 50 lines, where C sends the same prompt as R apart from the cap,
so this is an equivalence check.

* **Gate 2:** on each of L2, synthetic dated, L3 and "now": C − R ≥ −1.0 (mean of
  replicates), and C's `times_failures` ≤ R's.

## Decision

All gates pass → rc6 candidate = rc5 + `AMI_ASOF_BATCH=50` (cap 1,200), to go through
the State release flow (six criteria, contract, suite) and one platform Smoke before
the Full. Any gate fails → rc5 stays. Budget: 30M fresh gpt-4o-mini tokens.
