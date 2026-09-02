# Pre-registration — cross-encoder rerank on LoCoMo multi-hop

Written 2026-09-02 before the arm was run. Read this before any number from it.

## What is being tested

`AMI_RERANK_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2`, `AMI_RERANK_CANDIDATES=200`,
`AMI_RERANK_MAX_LENGTH=256`. The top 200 by the fused bi-encoder score are
re-scored by the cross-encoder and `select()` draws from that pool in its order;
everything else is unchanged from the shipped configuration (raw-first on,
window radius 1, agentic off, hop2 off, event dates off).

Store: `lc-smoke` (LoCoMo conversations 2-3, 90 Add calls, 351 questions with
evidence), the same store every arm in `locomo_completeness_smoke.md` read.
Nothing is re-ingested. `base` is re-run in the same session so the two arms
share one day's recall-question generation; the earlier base figures
(cat1 38/68 = 0.559) are context, not the comparator.

## Why this arm, and how strong the case for it actually is

The deficit it targets is located: 44% of multi-hop questions do not receive
all their evidence, and the missing evidence sits at a median rank of 213 of
600 — selection, not recall. Reranking the top 200 is a change to selection.

Two peers were cited for it. Stated honestly:

* GraphMemix (arXiv 2608.26983) — its node verifier is the largest term in its
  own ablation, +5.2 of +12.35. Measured on four **multimodal** benchmarks at a
  budget of **K=10**, where a verifier's value is mostly in what it removes.
  We return 100, so its number is not an expectation here.
* InvMem (`vanilla-rag-memory`, open text board #1) — has a `CrossEncoderReranker`
  class and a `MEMORY_RERANK_CANDIDATES=200` setting, **but ships with
  `MEMORY_RERANKER_MODEL=` empty and no documentation of ever setting it.**
  Code that exists is not code that ran. This was over-stated earlier in the
  project log; it is one source of support, not two.

Model choice is latency, measured on the server inside the bench image at 256
tokens, 200 pairs: MiniLM-L-6-v2 26 ms/pair (5.2 s single-threaded, 2.1 s at
four threads); bge-reranker-base 176 ms/pair (35 s). Only the first is
serveable on CPU under the platform's concurrency.

## Prediction

Axis B rises (category 1, >=3-evidence). Axis C does not move: on LongMemEval
temporal every question already receives all of its evidence and accuracy is
invariant to context size, so reordering has nothing to act on there.

## Decision rule

**Gate 1 — coverage, free.** Same-session `base` vs `rerank`, `complete@100`:

* category 1 (n=68): rerank >= base + 5 pp (at least 4 more questions), AND
* category 4 (n=197): rerank >= base − 3 pp.

The >=3-evidence row (n=33) is reported, not gated. Failing gate 1 ends the arm.

**Gate 2 — end to end, paid, only if gate 1 passes.** All 351 questions, prefix
100, local judge, both arms. Pass = accuracy higher AND a one-sided sign test on
the discordant pairs at p < 0.05. This instrument has shown ~6-7% discordant
pairs between identical arms; a difference must clear that, not merely exist.

**Nothing ships on gate 1 alone.** Coverage and end-to-end have been inverted
across arms on this project's own record (`bench/README.md`).

Production is a separate question from either gate: a per-search latency budget
under the platform's 16-64 concurrent calls, behind Cloudflare's ~100 s cut.
The smoke runs 200 candidates at 8 workers; that is not a serving configuration.
