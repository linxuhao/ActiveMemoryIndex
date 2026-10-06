# Adaptive chunk delivery without its own cap (rc5) — result, 2026-10-06

Addendum: `adaptive_chunk_rc5_addendum.md` (commit `8965c49`, before any run).
Code: `6616634` (`AMI_ADAPTIVE_CHUNK_TOTAL` removed). One replicate,
gpt-4o-mini, all calls through `bench/llm_proxy.py`.

## Decision: L4 is NOT recommended — `AMI_ADAPTIVE_CHUNK` stays 0

Rule 1 (BEAM L4 − B ≥ 0) fails; rules 2 and 3 hold.

| rule | comparison | n | B | L4 | L4 − B | up / down | p | holds |
|---|---|---:|---:|---:|---:|---|---:|---|
| 1 | BEAM-100K conv. 1–5, mean rubric | 100 | 0.466 | 0.447 | **−0.019** | 13 / 13 | sign 1.0, sign-flip 0.40 | **no** |
| 2 | LoCoMo 770 (lists identical to rc4's: rc4 verdicts) | 770 | 497 | 540 | +43 (+5.58 pt) | 82 / 39 | 0.0001 | yes |
| 3a | LongMemEval temporal | 133 | 57 | 57 | 0 | 8 / 8 | 1.0 | yes (≥ −2) |
| 3b | LongMemEval knowledge-update | 78 | 55 | 58 | +3 | 5 / 2 | 0.45 | yes (≥ −1) |

## Delivered text (read first)

| set | arm | chars/q (max) | counted tokens/q (max) | within the token budget |
|---|---|---:|---:|---|
| BEAM | B | 139,497 (260,866) | 36,797 (60,749) | all |
| BEAM | L4 | 168,668 (306,808) | 44,877 (76,619) | all |
| LoCoMo | B / L4 | 13,642 / 77,366 (L4 max 110,952) | 5,757 / 23,206 | all |
| LME temporal | B / L4 | 77,063 / 124,919 (L4 max 197,320) | 18,946 / 29,604 | all |
| LME KU | B / L4 | 79,704 / 139,630 (L4 max 192,118) | 19,588 / 32,990 | all |

Without the 120,000-character cap L4 now delivers more than B on BEAM (rc4 pilot:
less), and every list stays inside the Answer-window token budget. On LoCoMo
no L4 list ever reached the old cap: rc5's L4 lists are byte-identical to rc4's
on all 770 questions (and rc5 B to rc4 B), so rc4's +5.58 points stand unchanged.
On LongMemEval the cap bound (rc4: 113–118k characters): 75 of 133 temporal and
60 of 78 knowledge-update L4 lists changed and were answered again.

## BEAM by category (n = 10 each)

| category | B | L4 |
|---|---:|---:|
| abstention | 0.200 | 0.200 |
| contradiction resolution | 0.050 | 0.075 |
| event ordering (rubric only) | 0.231 | 0.297 |
| information extraction | 0.725 | 0.733 |
| instruction following | 0.600 | 0.525 |
| knowledge update | 0.775 | 0.750 |
| multi-session reasoning | 0.475 | 0.375 |
| preference following | 0.750 | 0.750 |
| summarization | 0.503 | 0.460 |
| temporal reasoning | 0.350 | 0.300 |

The rc4 pilot's summarisation drop (0.577 → 0.390, n = 4, with L4 delivering
less text) is not what removing the cap fixes: with L4 now delivering 21 % more
text than B, summarisation is still lower (0.503 → 0.460) and the overall point
estimate is negative, though not significant (13 up, 13 down).

## Cost

≈ 10.7M fresh gpt-4o-mini tokens for readers and judges (BEAM both arms,
LongMemEval L4 for the 135 changed lists); ≈ 1.3M for the BEAM ingest
(conversations 1–2 largely from the cache); text-embedding-v4 ≈ 0.4M.

## Caveats

* BEAM: one replicate, 100 questions, gpt-4o-mini reader and rubric judge (the
  leaderboard pipeline's default model is not available); event ordering's
  extra LLM alignment not run.
* The guards are BGE research stores (as in rc4).
