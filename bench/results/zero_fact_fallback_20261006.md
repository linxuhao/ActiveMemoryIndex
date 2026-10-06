# Zero-fact extraction fallback — end-to-end result, 2026-10-06

Pre-registration: `zero_fact_fallback_preregistration.md` (commit `15d0ce8`,
before any run). Code tested: `AMI_EXTRACT_FALLBACK` at `99cba0e`. Harness
`bench/rc4_l5.py`. One replicate, gpt-4o-mini, text-embedding-v4, update
detection off in both arms.

## Verdict: gate FAILED — not included in rc4

| gate | result | rule | pass |
|---|---|---|---|
| ScriptMem *Enemy of the People*, 94 questions | B 43.00, F 44.00, **net +1.00** (2 up, 1 down) | ≥ +2 | **no** |
| LoCoMo firing | 1 of 399 chunks without a stored fact (0.25 %); the fallback returned no fact for it | ≤ 1 % | yes |

The switch and its prompt were removed from the rc4 branch after this result
(the harness and this report stay).

## What the fallback did

130 Adds on the official bounds with narration split from dialogue (37
narration-only, 93 dialogue):

| arm | narration-only Adds with zero facts | facts from them | dialogue Adds with zero facts | facts from them |
|---|---:|---:|---:|---:|
| B | 33 / 37 | 10 | 4 / 93 | 1,652 |
| F | 0 / 37 | 134 | 0 / 93 | 1,701 |

The mechanism works as the smoke said — narration stops being dropped — but on
this script the extra facts move one net question of 94. ScriptMem's questions
are mostly about characters' motives and exchanges, which the dialogue Adds
already cover; the stage directions' content (who enters, the setting) is
rarely what is asked. The CL-bench extraction-level probe of the
pre-registration was not re-run: it could not change the gate, which had
already failed on ScriptMem.

Cost ≈ 1.0M gpt-4o-mini tokens (ingest 130 Adds × 2 arms with shared
extraction cache, 37 fallback calls (33 narration + 4 dialogue Adds), 188 answers), ≈ 0.1M embedding tokens.
