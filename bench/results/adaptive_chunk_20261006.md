# Adaptive chunk delivery (AMI_ADAPTIVE_CHUNK) — confirmation result, 2026-10-06

Pre-registration: `adaptive_chunk_preregistration.md` (commit `93b21d3`, before
any run). Code: `app.main.select_adaptive` at `99cba0e`. Harness
`bench/rc4_study.py`. One replicate, platform answer and judge prompts,
gpt-4o-mini, all calls through `bench/llm_proxy.py`.

## Verdict: gate FAILED — ships off

| gate | comparison | n | result | W / L | sign p | rule | pass |
|---|---|---:|---|---|---:|---|---|
| 1 | LoCoMo L4 − B | 770 | 497 → 540, **+5.58 pt** | 82 / 39 | 0.0001 | ≥ +2 pt, p < 0.05 | yes |
| 2 | LoCoMo L4 − C (equal text) | 770 | 540 → 540, **0** | 43 / 43 | 1.0 | > 0 | **no** |
| 3a | LongMemEval temporal L4 − B | 133 | 57 → 59, +2 | 11 / 9 | 0.82 | ≥ −2 | yes |
| 3b | LongMemEval knowledge-update L4 − B | 78 | 55 → 56, +1 | 3 / 2 | 1.0 | ≥ −1 | yes |

`AMI_ADAPTIVE_CHUNK` stays 0 in code and is **not recommended** for production.

## What the control says

C is B's own unit — the same ranking, turn ±1 neighbours, facts, raw-first
order — allowed to run past 100 memories until it has spent, per question,
exactly the characters L4 spent (mean difference −11 characters, max −39).

| arm | chars/q | memories/q | counted tokens/q (max) | LoCoMo correct |
|---|---:|---:|---:|---:|
| B | 13,642 | 100 | 5,757 (6,798) | 497 |
| L4 | 77,366 | 100 (28.0 chunks, 1.4 spans, 70.6 facts) | 23,206 (31,534) | 540 |
| C | 77,355 | 569.5 | 32,803 (45,361) | 540 |

C − B is +43 (75 W / 32 L, p < 0.0001) and L4 − C is 0 (43 W / 43 L). At equal
text the unit adds nothing: the whole gain over B is the extra verbatim text,
which on this reader and this corpus is worth ≈ 5.6 points from 13.6k to 77k
characters — the same direction as the project's earlier finding that accuracy
rises with returned text for gpt-4o-mini (`AMI_RETURN_LIMIT` sweep). By
category, L4 − C is +7 on multi-hop (cat 1, 12 / 5), −6 on temporal (cat 2,
9 / 15), −2 on open-domain, +1 on single-hop; none significant.

What the pre-registered gate does not weigh, and the coordinator may: C is not
deployable (it returns ~570 memories against `top_k` 100), so L4 is the only one
of the two ways to deliver that volume inside the contract. The gate was
written to ship L4 only if the unit itself helped; it does not. A decision to
ship L4 *as a volume mechanism* would be a different question and needs its own
registration (and its own guards: L4 spends 4× B's Answer tokens on LoCoMo).

## Guards and BEAM

LongMemEval (BGE guard store, mostly chunks > 4,000 characters, so L4 is merged
spans under the 120,000-character cap): temporal 113,820 vs 77,063 characters
per question, +2 of 133; knowledge-update 117,744 vs 79,704, +1 of 78. No harm,
no signal.

BEAM-100K pilot (descriptive, conversations 1 and 2, 57 Adds, 40 probing
questions, fresh v4 store, leaderboard BEAM answer prompt and batched rubric
judge with gpt-4o-mini, event-ordering alignment not run): B 148,892 characters
and 36,006 counted tokens per question, L4 104,194 / 25,490 (the 120,000-character
cap binds: BEAM chunks are ≈ 15k characters, so L4 is spans). Mean rubric
score B 0.496, L4 0.484 (4 up, 5 down). Summarisation fell (0.577 → 0.390, n = 4)
with the smaller text; nothing else moved by more than one question.

## Cost

gpt-4o-mini ≈ 41M fresh tokens for this study (LoCoMo readers and judges
B 3.6M, L4 ≈ 18M, C ≈ 17.7M; guards L4 6.0M and B 2.3M; BEAM pilot 2.4M incl.
ingest), text-embedding-v4 ≈ 0.95M (LoCoMo store 0.7M, BEAM store 0.25M). The
LoCoMo extraction at ingest was almost entirely served from the proxy cache of
earlier runs (identical prompts).

## Caveats

* n = 770, not the 1,540 the brief asked for: the full design projected ≈ 73M
  reader tokens against a 60M cap for all rc4 studies (pre-registered
  reduction, held-out positions 150–919 of the smoke's shuffle).
* One replicate; platform gpt-4o-mini judge, not the calibrated internal
  judge.
* Guards on BGE stores (stated in the pre-registration).
