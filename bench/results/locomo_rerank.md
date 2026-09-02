# Cross-encoder rerank on LoCoMo multi-hop — gate 1 failed

Run 2026-09-02 against the decision rule in `locomo_rerank_preregistration.md`,
written before the arm. Store `lc-smoke` (LoCoMo conversations 2-3, 351
questions with evidence), retrieval layer only, `base` re-run in the same
session as the comparator. `cross-encoder/ms-marco-MiniLM-L-6-v2`, top 200 by
the fused bi-encoder score re-scored, 256 tokens.

## Verdict

**Gate 1 fails on its first clause and the arm ends. Not shipped.** Gate 2 (end
to end) was not run. The switch stays in the code, off by default, because the
negative is specific to a pointwise answer-relevance model and the hook is
where any other rescorer would go; nothing about it is a finding.

## Shipped configuration (window radius 1), paired

| complete@100 | n | base | rerank | diff | gained | lost |
|---|---:|---:|---:|---:|---:|---:|
| category 1 — multi-hop | 68 | 0.559 | **0.456** | −0.103 | 3 | 10 |
| category 2 — temporal | 67 | 0.910 | 0.866 | −0.045 | 1 | 4 |
| category 3 | 19 | 0.579 | 0.316 | −0.263 | 0 | 5 |
| category 4 — single-hop | 197 | 0.929 | 0.934 | +0.005 | 6 | 5 |
| needs 1 evidence turn | 264 | 0.920 | 0.902 | −0.019 | 7 | 12 |
| needs 2 evidence turns | 54 | 0.741 | 0.630 | −0.111 | 1 | 7 |
| needs >=3 evidence turns | 33 | 0.303 | 0.212 | −0.091 | 2 | 5 |
| all | 351 | 0.835 | 0.795 | −0.040 | 10 | 24 |

The gate asked for category 1 at +5 pp; it came in at −10.3 pp. Category 4, the
clause meant to catch collateral damage, is flat.

What rose is the head. `recall@1` (any evidence) 0.120 → 0.259, `recall@20`
0.607 → 0.692, category 4 `recall@20` 0.624 → 0.746. The cross-encoder is
better than the bi-encoder at putting *one* right passage first, and worse at
keeping *all* of them inside a hundred.

## With the window off (diagnostic), paired

| complete@100 | n | base w=0 | rerank w=0 | diff | gained | lost |
|---|---:|---:|---:|---:|---:|---:|
| category 1 — multi-hop | 68 | 0.647 | **0.441** | −0.206 | 1 | 15 |
| category 4 — single-hop | 197 | 0.904 | 0.888 | −0.015 | 5 | 8 |
| needs 2 evidence turns | 54 | 0.778 | 0.611 | −0.167 | 1 | 10 |
| needs >=3 evidence turns | 33 | 0.424 | 0.182 | −0.242 | 0 | 8 |
| all | 351 | 0.835 | 0.749 | −0.085 | 6 | 36 |

`base w=0` replicates the earlier radius-0 measurement (44/68 vs 45/68 on
category 1). Removing the window **doubles** the reranker's loss on category 1.
The window was masking part of the damage — neighbours re-admit evidence the
cross-encoder demoted — not causing it. Category 3 `recall@20` reads 0.000 in
this arm.

## Two explanations that were checked and are wrong

**A slot tax.** If the cross-encoder favoured verbatim turns, each hit would
drag two neighbours in and breadth would fall. Measured on the returned sets:
verbatim turns 54.4 → 47.8 per question, distinct source chunks 22.2 → 22.2,
characters 12,762 → 12,057. Breadth did not move; the reranker returns *fewer*
verbatim turns.

**A bias against extracted facts.** The 30 evidence turns the reranker dropped
were covered in `base` by 21 verbatim turns and 9 facts — 70/30 — against
315/123 (72/28) for all evidence `base` covers. Proportional; no kind is
singled out. And the dropped evidence sat at positions 3 to 99 of the `base`
list, spread across it, not clustered at the cut.

## What survives

A model trained to score "does this passage answer this question" is asked,
on a multi-evidence question, to score passages none of which answers it on
its own. It scores them low, and they fall out of the hundred. The bi-encoder
fused with the user-voice recall question is a blunter instrument and keeps
them. The two effects are the same effect: head precision doubles on exactly
the questions where one passage *is* the answer, and completeness falls on
exactly the questions where none is.

This is the third arm on this store to show the same shape — window radius,
fused-vs-reserved second hop, now rerank: **whatever sharpens the head pays
for it in breadth, and this benchmark's multi-hop category is priced in
breadth.**

## What this says about the peers that motivated it

GraphMemix's node verifier is an LLM scoring "support for answering the
query" 0-5 — a support judgment, not an answer-relevance one — under a budget
of ten where removing wrong passages is most of the value. Whether that
distinction survives a hundred-slot budget is untested; this arm says only
that an MS MARCO cross-encoder does not. InvMem ships its `CrossEncoderReranker`
with no model configured, which is consistent with having measured this.

## Cost and latency

Four arms, ~1,400 recall questions, about $0.20. No end-to-end calls.
Reranking 200 candidates took 364 s for 351 searches at 8 workers — roughly
8 s per search single-threaded — so this configuration was not serveable under
the platform's concurrency regardless of the result.
