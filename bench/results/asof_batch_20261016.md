# Batched as-of time reading — rc6 candidate result (2026-10-16)

Pre-registration `asof_batch_preregistration.md`; code `research/asof-batch-rc6-20261016`
(eb91553) = rc5 + `AMI_ASOF_BATCH` (50 lines per call, cap 1,200). State node
`research.asof-batch-rc6`, attempt `attempt-0e055b5d021e4809be3ebc473dc6b1fd`.
Production untouched. Fresh gpt-4o-mini ≈ 3.8M tokens (Part 2 3.67M, Part 1 replay 0.13M,
plus its answers).

## Verdict: all gates pass — rc6 candidate

| gate | rule | result |
|---|---|---|
| 1a big-list failures | `times_failures` = 0 on 26 | **0**; 64 batches, 0 batch failures, longest reply 293 tokens; Search p50 1.6 s, max 3.6 s |
| 1b big-list answers | C − R ≥ −1.0 | LoCoMo 24: R 18.5, C 18.0 (−0.5; only conv3-q183 moved, 1/2 → 0/2); LME 1: 0/4 = 0/4; BEAM 1: 0.5 = 0.5 |
| 2 TempReason L2 150 ×2 | C − R ≥ −1.0 | 150, 150 = 150, 150 |
| 2 TempReason L3 100 ×2 | C − R ≥ −1.0 | 81, 83 = 81, 83 (classifier: 100/100 not as-of in both) |
| 2 synthetic 288 ×2 (6 languages, incl. "now") | C − R ≥ −1.0 | 280, 278 = 280, 278 |
| 2 failures | C ≤ R | 0 = 0 |

* **On the 26 big lists C applies where rc5 silently failed** (21 applied vs 17; the
  4 recovered questions are conv3-q187, conv5-q78, conv6-q12, conv9-q75) and is
  faster than rc5's single call. On these questions the answers did not change:
  three of the four were already right without selection and one is wrong in both.
  So this is a **robustness fix, not a measured score gain**: it removes a silent
  failure mode (≈ 26 % of large as-of Searches) without changing behaviour where
  rc5 worked.
* On the small as-of sets (≤ 54 messages per user) C sends rc5's prompt in one or two
  batches; answers are identical replicate by replicate. Withheld counts: L2 1,946 vs
  1,938, synthetic 2,527 vs 2,526.

## Next

rc6 = rc5 + `AMI_ASOF_BATCH=50` (cap default 1,200). Release through State node
`submission.release-candidate` (six criteria, contract, suite, no-language-regex,
Q18 declaration update) and one platform Smoke before the Full. Deployment needs the
user's go-ahead.
