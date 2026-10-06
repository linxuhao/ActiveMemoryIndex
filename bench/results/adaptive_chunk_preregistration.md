# Pre-registration — adaptive chunk delivery (AMI_ADAPTIVE_CHUNK), confirmation

Written 2026-10-06 before any run. Code under test: commit `99cba0e`
(`app.main.select_adaptive`), branch `release/rc4-20261006`. Harness:
`bench/rc4_study.py`. Read this before any number.

## Where this comes from

Lead smoke L4 (`lead_smoke_delivery_20261005.md`, branch
`research/lead-smoke-delivery-20261005`): on the frozen BGE store, delivering a
selected turn's whole Add chunk when it is ≤ 4,000 characters, else a merged
turn ±1 span ≤ 4,000, with delivered text ≤ 120,000 characters, scored LoCoMo
106 → 116 of 150 (+6.7 pt, 15 W / 5 L, p = 0.041) at 5.8× the text, and 11 → 11
of 27 on LongMemEval temporal. Cycle 1's `parent` arm (whole chunks) was +3.1 pt
on n = 1,540. The open question the smoke could not answer: is the gain the
**unit** (a chunk costs one slot; context arrives contiguous and in order) or
just **more text**?

## Mechanism (as built)

`AMI_ADAPTIVE_CHUNK=S` (characters; 0 = off, the shipped default),
`AMI_ADAPTIVE_CHUNK_TOTAL=T` (characters, default 120,000):

* a selected verbatim turn is delivered as its whole Add chunk — the chunk's
  stored turns, verbatim, in order, joined by newlines, id `<digest>-c0` — when
  that text is ≤ S; otherwise as the turn plus neighbours within
  `AMI_WINDOW_RADIUS` (1), contiguous, each added only while the span stays
  ≤ S (the hit itself always), id `<digest>-s<lo>-<hi>`;
* a span overlapping or touching an already chosen span of the same chunk is
  merged into it, in its place (a merged span may exceed S, as in the smoke);
* facts are delivered as they are; raw-first order (chunks and spans, then
  facts, each in relevance order); one memory = one slot of `top_k`;
* total text ≤ min(T, `AMI_RETURN_CHAR_BUDGET`), and always the token budget
  of `app/tokens.py`;
* **withheld turns** (explicit-update withholding, as-of selection) are left
  out of the chunk or span text; the rest of the chunk is still delivered.
  Chosen over skipping the chunk because a LoCoMo chunk is a whole session
  (~18 turns): skipping it would drop every other turn of that session —
  usually the context the update itself sits in — to keep out one sentence,
  and the remaining text is still the stored turns concatenated in order, the
  same kind of object as a span. A withheld hit starts nothing.

No text is rewritten; the query only selects (Q18 evidence organisation).

## Budget projection and the deviation it forces

The brief asks for LoCoMo 1,540 × three arms. Reader prompt tokens measured in
the smoke: B ≈ 4.5k, L4 ≈ 21.4k per LoCoMo question; the equal-text control
costs what L4 costs. Full specification ≈ 1,540 × (4.5 + 21.4 + 21.4)k ≈ 73M
reader tokens plus judges, against a 60M cap for **all** rc4 studies, which
the brief orders 1 → 4 → 3 → 2 → 5. **Reduced, fixed now:** LoCoMo
categories 1–4 in the smoke's own order (`random.Random(20261005)` shuffle of
the 1,540), positions **150–919 (n = 770)** — the first 150 were the smoke's
answered sample and are excluded, so this is held-out. Est. ≈ 37M tokens for
the three arms. If the proxy cap would be reached before all three arms finish,
the run stops, nothing is extrapolated, and the gate is reported as not
evaluated.

## Store

Fresh text-embedding-v4 store: LoCoMo all 10 conversations, 20-message session
chunks (`bench/run_bench.py ingest`, 399 Adds), ingested through the rc4
service in a separate container with production-like settings (update
detect/render/withhold on, v7), model and embedding calls through
`bench/llm_proxy.py`. The same store serves the as-of study's LoCoMo guard.

## Arms (one replicate)

| arm | definition | role |
|---|---|---|
| **B** | rc4 shipped selection (turn ±1, raw-first, limit 100, token budget) | baseline |
| **L4** | B + `AMI_ADAPTIVE_CHUNK=4000`, `AMI_ADAPTIVE_CHUNK_TOTAL=120000` | the switch |
| **C** | equal-text control: B's unit and order, with the 100-item limit lifted and the character budget set, **per question**, to the characters L4 delivered on that question | separates unit from volume |

**Why C is built this way.** L4 differs from B in two things at once: the unit
(a chunk or span is one slot and arrives contiguous and ordered) and the
volume (~5.8× the characters). A control at `top_k` 100 cannot separate them:
100 single turns are ≈ 13k characters on LoCoMo, so B's unit can only reach
L4's ≈ 75k characters by returning more items. C therefore keeps everything
about B — same ranking, same ±1 neighbour unit, same facts, same raw-first order
— and only lets the same selection run on until it has spent exactly the text
L4 spent on that question. L4 − C is then the unit at equal text; C − B is the
volume at B's unit. C returns more than 100 memories, which the contract does
not allow: it is a research control, never a deployable configuration.

## Guards (B vs L4 only)

LongMemEval-S temporal (133) and knowledge-update (78) on the BGE guard store
(rc2 guard store copy with v7 update records). Deviation, stated: BGE, not
text-embedding-v4 (re-ingesting LongMemEval is not budgeted). On these corpora
most chunks exceed 4,000 characters, so L4 is mostly merged spans under the
120,000-character cap: the long-chunk regime.

## BEAM (descriptive only, not gating)

If at least 5M tokens remain after everything above and the as-of study: a
BEAM-100K pilot (first two conversations, their probing questions), B vs L4,
on a fresh v4 store, rubric scores reported per question. BEAM chunks are
~15k characters, so L4 is the span branch there.

## Metric

Platform answer and judge prompts (LoCoMo-refined pipeline for LoCoMo,
LongMemEval-S pipeline for the guards), gpt-4o-mini, temperature 0, one
replicate, every memory rendered (no 100-item cut in the harness). Per-question
paired comparison, exact two-sided sign test on discordant questions. Read
first, before accuracy: characters, memories and counted tokens per question
for each arm, and that C's characters match L4's.

## Gate (written first; all must hold)

1. LoCoMo (n = 770): L4 − B ≥ **+2.0 points** with sign-test **p < 0.05**.
2. LoCoMo: L4 − C **> 0** (net questions).
3. Guards: LongMemEval temporal L4 − B ≥ **−2** of 133; knowledge-update
   L4 − B ≥ **−1** of 78.

Pass → recommend `AMI_ADAPTIVE_CHUNK=4000` (with `AMI_ADAPTIVE_CHUNK_TOTAL=120000`)
for production; the shipped default stays 0. Fail → the flag ships off and the
result is reported as such.
