# Addendum (rc5) to the adaptive-chunk pre-registration — L4 without its own cap

Written 2026-10-06 before any rc5 run. Code under test: commit `0d43865`
(`AMI_ADAPTIVE_CHUNK_TOTAL` removed). Parent: `adaptive_chunk_preregistration.md`
and its result `adaptive_chunk_20261006.md`.

## Why

In the rc4 BEAM pilot L4 delivered less than B (104k vs 149k characters, 25k
vs 36k counted tokens per question) because of the extra 120,000-character cap,
and summarisation fell 0.577 → 0.390 (n = 4). The user's requirement is only
that delivery stays inside the challenge's Answer window (117,760 input
tokens), which rc4's token budget (`app/tokens.py`) already enforces for every
mode. rc5 removes the separate cap: L4 is bounded by `top_k`, the general
character budget (`AMI_RETURN_CHAR_BUDGET`, 400,000) and the token budget. The
question asked now is the user's: ship L4 as a delivery mechanism (volume
included) if BEAM is not worse and LoCoMo keeps its gain. The rc4 gate's
"unit vs equal-text control" criterion is not re-asked.

## Runs

* **BEAM-100K, conversations 1–5** (100 probing questions, 10 per category;
  139 Adds; conversations 1–2 are the rc4 pilot's, 3–5 new), fresh
  text-embedding-v4 store ingested by rc5 with production settings. Arms on rc5
  code, both with `AMI_ASOF_SELECT=1` (production): **B** (`AMI_ADAPTIVE_CHUNK=0`)
  and **L4** (`4000`). Leaderboard BEAM answer prompt and batched rubric judge,
  gpt-4o-mini (event-ordering's extra alignment not run, as in rc4). Per
  question rubric mean; paired difference.
* **LoCoMo**: the rc4 770-question set on the LoCoMo v4 store re-ingested with
  rc4 code (must reproduce rc4's B lists). rc5 L4 (as-of off, as in rc4's
  study) is compared list by list with rc4's `l4_L4.json`; rc5 B with rc4's
  `l4_B.json`. Questions whose list changed are answered again (both arms if
  needed); the others keep rc4's verdicts.
* **Guards**: LongMemEval-S temporal (133) and knowledge-update (78) on the BGE
  guard store, rc5 B vs rc5 L4. If the projected fresh reader tokens of the L4
  guard lists (counted tokens + prompt, both sets) exceed 10M when they are
  searched, the guards run on a subset fixed now: the first 60 temporal and
  the first 40 knowledge-update questions by sorted question id.

## Decision rule (all must hold to recommend `AMI_ADAPTIVE_CHUNK=4000` ON)

1. BEAM: mean rubric L4 − B ≥ 0 (point estimate); reported with up/down
   counts, sign test and a paired sign-flip permutation p.
2. LoCoMo: L4 − B ≥ +2.0 points with sign-test p < 0.05 on the 770 (identical
   lists keep rc4's verdicts: 540 vs 497).
3. Guards: temporal L4 − B ≥ −2 of 133 and knowledge-update ≥ −1 of 78
   (subset: ≥ −1 of 60 and ≥ −1 of 40).

Otherwise the flag stays 0 in production. The shipped code default stays 0
either way. Read first, before accuracy: characters, memories and counted
tokens per question per arm, and that no list exceeds the token budget.

## Budget

≈ 1M BEAM ingest (conversations 1–2 mostly cached), ≈ 10M BEAM readers and
judges, LoCoMo only for changed lists, guards as above. Runs after the
language-neutral study's gates are evaluated, inside the 35M total.
