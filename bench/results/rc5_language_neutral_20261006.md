# rc5: no language-dependent regex or word list — validation result, 2026-10-06

Pre-registration: `rc5_language_neutral_preregistration.md` (commit `8965c49`,
amendment 1 in `6616634`, both before any validation search). Code: `app/` at
`6616634`, compared with rc4 (`a0b3e99`). One replicate unless stated,
platform answer and judge prompts, gpt-4o-mini; every model and embedding
call through `bench/llm_proxy.py`. Benchmark text and outputs stay in the run
directory (not committed).

## Verdict: every pre-registered gate PASSED

| gate | set | n | rc4 (R) | rc5 (N) | N − R | W / L | sign p | rule | pass |
|---|---|---:|---:|---:|---:|---|---:|---|---|
| A1 | en/zh as-of pooled (TempReason L2 fresh + synthetic en + zh dated) | 230 | 224 | 230 | **+6** | 6 / 0 | 0.031 | ≥ 0, no part < −1 | yes |
| A2 | new languages pooled (synthetic fr + de + es + ja dated) | 160 | 136 | 154 | **+18** | 19 / 1 | 4e-5 | > 0, p < 0.05, none < 0 | yes |
| A3 | LoCoMo dated (rc4's 194) | 194 | 142 | 141 | −1 | 0 / 1 | 1 | ≥ −1 | yes (at the bound) |
| A3 | LongMemEval knowledge-update (BGE guard store) | 78 | 55 | 55 | 0 | identical lists | — | ≥ −1 | yes |
| A3 | TempReason L3 fresh (relation questions) | 100 | — | — | 0 | identical lists | — | ≥ −1 | yes |
| A3 | synthetic "now" questions | 48 | 47 | 47 | 0 | identical lists | — | ≥ −1 | yes |
| B1 | updates router, LLM only, every language of every set | 400 | — | — | — | — | — | recall ≥ 0.95, false protection ≤ 0.15 | yes |
| B2 | MQuAKE, RW5 − B | 400 × 2 | 258.5 | 328.5 | **+70.0** | 81 / 7 | < 1e-4 | > 0, p < 0.05 | yes |
| B2 | MQuAKE, RW5 − RW4 (rc4) | 400 × 2 | 323.5 | 328.5 | +5.0 | 9 / 2 | 0.11 (sign-flip) | not significantly negative | yes |

## A. As-of selection, rc4 regex (R) vs rc5 (N)

Store reproduction first: the LoCoMo v4 store re-ingested with rc4 code from the
proxy cache reproduces rc4's lists exactly (rc4 P on the 194: 194/194; rc4 B and
L4 on the 770: 770/770 each); the KU guard store reproduces rc4's B 78/78.

| set | n | lists changed | R | N | N − R | W / L |
|---|---:|---:|---:|---:|---:|---|
| TempReason L2 fresh (en) | 150 | 14 | 150 | 150 | 0 | 0 / 0 |
| synthetic en dated | 40 | 25 | 35 | 40 | +5 | 5 / 0 |
| synthetic zh dated | 40 | 30 | 39 | 40 | +1 | 1 / 0 |
| synthetic fr dated | 40 | 25 | 37 | 40 | +3 | 3 / 0 |
| synthetic de dated | 40 | 20 | 36 | 40 | +4 | 4 / 0 |
| synthetic es dated | 40 | 25 | 29 | 35 | +6 | 7 / 1 |
| synthetic ja dated | 40 | 29 | 34 | 39 | +5 | 5 / 0 |
| synthetic "now" (6 languages) | 48 | 0 | 47 | 47 | 0 | — |
| TempReason L3 fresh | 100 | 0 | — | — | 0 | — |
| LoCoMo dated | 194 | 15 | 142 | 141 | −1 | 0 / 1 |
| LoCoMo 770 held-out (reported) | 770 | 13 | 497 | 496 | −1 | 0 / 1 (the same question) |
| LongMemEval KU | 78 | 0 | 55 | 55 | 0 | — |

* **Question classifier.** Synthetic dated questions: 236 / 240 `as_of_state`
  (en, fr, de, es, zh 40/40 each; ja 36/40 — the four misses are all
  "…日に、…のパーソナルトレーナーは誰でしたか？", called `event_on_date`, which withholds
  nothing). Periods: 240 / 240 equal to the generator's dates, including dates
  entirely in words, 二〇二三年 / 二零…号 numerals and Japanese era dates (令和).
  "Now" questions 48 / 48 `other`; TempReason L2 150 / 150 `as_of_state`; L3
  100 / 100 `other`; KU 78 / 78 `other`; LoCoMo 770: 16 state, 69 event, 683
  other (2 cached).
* **Where rc4 lost.** rc4's gate needs a year in digits and its parser knows
  digit and month-name formats: dates in words, CJK numerals and era dates get no
  as-of treatment at all, and a few numeric forms (US/EU slashes) are not parsed.
* **The one loss** is LoCoMo "How many pets did Andrew have, as of September
  2023?" (also the 770 set's only change in score): rc5 withheld items said after
  September 2023 that state no time, and the reader then answered with an older
  count.
* **Time extraction failures.** 9 of the item-side calls (all LoCoMo state
  questions with ~160 candidates) hit the 3,000-token completion cap and
  failed; they withheld nothing, as designed.

## B. Updates

**B1 — router, gpt-4o-mini only, no pre-filter** (`QUESTION_SCOPE2_SYSTEM`, unchanged):

| set | language | recall (TP/FN) | false protection (FP/TN) |
|---|---|---|---|
| round-5 frozen | en | 1.000 (33/0) | 0.000 (0/34) |
| round-5 frozen | zh | 0.971 (34/1) | 0.000 (0/34) |
| round-5 frozen | es | 1.000 (33/0) | 0.000 (0/34) |
| round-5b held-out | en | 0.950 (19/1) | 0.000 (0/20) |
| round-5b held-out | zh | 1.000 (20/0) | 0.000 (0/20) |
| round-5b held-out | es | 1.000 (20/0) | 0.000 (0/20) |
| rc5 NEW | fr | 0.950 (19/1) | 0.000 (0/20) |
| rc5 NEW | de | 1.000 (20/0) | 0.000 (0/20) |

Misses: zh "我的团队人数有什么变化？现在我带几个工程师？", en "Which train did I use to
take to work?", fr "Je t'avais dit que mon rendez-vous chez le dentiste était à
10 h ; c'est à quelle heure maintenant ?". Without the regex pre-filter the
round-4/5 false protection of "截止日期从5月1日推迟到了5月15日…" is gone (0 false
protections anywhere).

**B2 — MQuAKE re-check** (200 round-3 cases, 400 edit + multi questions, 2
replicates; streams reconstructed from the round-3 store and verified message by
message): B (withholding off, rc5) 258.5; RW4 (rc4 code on the RC2 store) 323.5 —
+65.0 over B, exactly the round-5 result; RW5 (rc5 code, store re-ingested with
the new stage-2 prompt) 328.5 — +70.0 over B (81 W / 7 L), +5.0 over RW4
(9 W / 2 L, sign-flip p = 0.11; edit +0.5, multi +4.5). RW5 store: 190 records
(RW4: 187), renders 237 (231).

**B3 — render language probe** (24 new explicit updates, en/fr/de/es/zh/ja, 4
each): 24 / 24 records; 24 / 24 rendered; stage-2 tags equal on all 24; a
separate gpt-4o-mini check (bench only) says every rendered sentence is in the
language of the user's turn (24 / 24).

## Cost and latency (fresh gpt-4o-mini tokens, from the proxy ledger)

* **Question classifier**: one call per distinct (question, options) on every
  Search, ≈ 680 prompt + 16 completion tokens; started beside the recall rewrite
  (≈ 200 + 18 tokens), so no added wall time (it is never on the critical path
  unless it is slower than the recall call; test `test_classifier_runs_beside_the_recall_rewrite`).
* **Time extraction**: only for `as_of_state` questions, only over candidates
  not read before (cached per item): mean ≈ 1,000 prompt + 155 completion tokens
  per call (p90 1.2k prompt; LoCoMo-sized candidate lists ≈ 6.7k + 1.4k). It is
  sequential after the first selection: one extra gpt-4o-mini round trip on
  state questions only.
* Add: stage 2 writes two language tags (≈ +10 completion tokens per accepted
  update statement); no new Add call.
* rc4's equivalent: one router call (≈ 250 tokens) only on dated questions whose
  list the rules would change.

## Caveats

* One replicate (MQuAKE two); platform gpt-4o-mini reader and judge, not the
  calibrated internal judge.
* TempReason L2 is at ceiling for both arms (150 / 150), so it shows no loss
  rather than a gain.
* The item side was redesigned on development data (amendment 1): the
  registered direct judgement did not enumerate (gpt-4o-mini listed only the
  answering memory).
* Spend for this study ≈ 8.3M fresh tokens including ≈ 3.5M development.
