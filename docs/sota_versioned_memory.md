# Versioned / graph memory vs. the knowledge-update reader — what the field has measured (2026-09-23)

Written after the 2026-09-22 series closed every search-time form of State DAG
versioning (`bench/results/lme_newest_first.md`, `lme_chrono_ku.md`,
`supersede_mark_calibration.md`, `lme_fact_keys.md`). Question asked: a State
DAG should be able to weave a user's "git history" — did we build it wrong?

## 1. The structure we built already exists in the field, and it measured the same

| system | how supersession is represented | what the reader sees | knowledge-update effect |
|---|---|---|---|
| **Zep / Graphiti** (arXiv 2501.13956) | bitemporal edges: a contradicting fact sets the old edge's `t_invalid` = new edge's `t_valid`; **old edge kept, not deleted** | each fact with its `t_valid, t_invalid` | LongMemEval KU, **gpt-4o-mini: full-context 76.9% → Zep 74.4%** (down); gpt-4o: 78.2% → 83.3% |
| **ROAM** (arXiv 2609.09778) | atomic memories + LLM-written relations at write time (`supersedes`, `elaborates`, `contradicts`) | current + history via relations | claims KU/temporal gains; per-category numbers not extracted |
| **TOKI** (arXiv 2606.06240) | bitemporal operator algebra (valid time × transaction time), full provenance kept | only currently-valid facts, with markers | synthetic contradictions only |
| **Mem0** (2504.19413) | LLM decides ADD / UPDATE / DELETE / NOOP at write time — **overwrites** | the surviving memory | LoCoMo-strong; on MemConflict *dynamic* conflicts **0.12** (worst of six) |
| **A-Mem** (NeurIPS 2025) | Zettelkasten links + "memory evolution" rewrites older notes | evolved notes | MemConflict dynamic 0.36 |
| **ours, `AMI_FACT_KEYS` + `AMI_SUPERSEDE_MARK`** | extractor key; old fact rendered with its latest same-key successor; **nothing deleted** | `[superseded on <date> by: <new>] <old>` | LongMemEval KU, gpt-4o-mini: **+0.25 / 78, p = 1.0** |

Zep's Graphiti is, to the letter, the State DAG proposal: node = fact, versions
kept, validity interval shown to the reader. On the reader the competition
fixes, it moved knowledge-update **down 2.5pp**; ours moved it +0.3 (n.s.). We
did not build it wrong. We built what the leading versioned-graph system
built, with a matched base, and got the number it got.

## 2. The bottleneck the field has now named: the reader, not the store

* **Supersede** (arXiv 2606.27472, "the memory-update gap"): on the same
  LongMemEval knowledge-update subset, **full-context** accuracy is 82%
  (gpt-4.1-mini), 91% (gpt-4.1), 92% (gpt-5.4) — "roughly 13% of questions are
  wrong even in full context." With a bounded self-managed memory it falls to
  63–77% and **a bigger model does not close the gap, a 24× larger memory
  budget does not either** (28% → 28%). No presentation-side intervention
  (ordering, marking, deleting, instructing) was tested; the only thing that
  moved it was **training the model** (GRPO with a supersession-aware reward,
  Qwen2.5-3B 9.0% → 16.7%). Their conclusion: supersession "is a behavior that
  must be optimized for," not one the next model absorbs.
* **MemConflict** (arXiv 2605.20926): six memory systems on dynamic conflicts
  ("earlier and later states coexist"): best **0.50** (LangMem), MemOS 0.38,
  Letta 0.40, A-Mem 0.36, Mem0 0.12. Conflict *recognition* ≤ 0.25 for every
  system. They name an **Evidence Utilization Gap**: the valid memory is
  retrieved and the answer is still wrong — "answer-generation rather than
  retrieval failures dominate."
* **Mastra Observational Memory** (dated observations, three date fields per
  entry, same store for every actor): knowledge-update **85.9% with gpt-4o,
  94.9% gemini-3-pro, 96.2% gpt-5-mini**. The store is constant; the reader
  is the variable, and it is worth 10 points.
* **Knowledge-conflicts survey** (EMNLP 2024, arXiv 2403.08319): for
  inter-context conflict the documented reader preferences are order
  sensitivity, popularity / number of corroborating documents, relevance, and
  agreement with parametric memory. **Whether a newer statement supersedes an
  older one is listed as a gap** — no paper in the survey measures it.

Our 2026-09-22 numbers sit exactly where this literature puts them: coverage
1.000, three orderings flat or negative, correct markers ignored, 73% for
gpt-4o-mini against Zep's 76.9% full-context for the same reader.

## 3. What this settles, and what it leaves

**Settled.** Under the competition's constraints — reader fixed at gpt-4o-mini,
`/search` returns evidence and never an answer — the versioned DAG cannot
express its value at search time. Every system that reports a knowledge-update
gain gets it from (a) a stronger reader (Zep on gpt-4o, Mastra on gpt-5-mini),
(b) overwriting at write time (Mem0 — which MemConflict shows destroys facts
that should have been kept, static conflicts 0.19), or (c) training the reader
(Supersede). None of the three is a search-time change.

**Answered from the literature, not from our run.** The research question
left open on 2026-09-22 — is "a direct assertion outweighs a hedged update"
a gpt-4o-mini property or a reader-general one — has an answer in the
Supersede and Mastra tables: it shrinks with reader strength (82 → 92, 86 →
96) and does not vanish (13% residual at full context on gpt-5.4). Replicating
that on `lme-ku` with another reader would confirm, not discover.

**Left.** Two things the DAG still is:
1. **A record.** Versions kept with keys are the auditable "git history" the
   user described; that it does not move a 4o-mini reader is a fact about the
   reader. If cycle 2's Q18 is ever read as permitting the memory system to
   *organise* (not answer), rendering "current value per key" is the one
   organisation the DAG makes trivial — and it is the same object Mem0's
   UPDATE produces, without Mem0's deletions.
2. **Training data.** Supersede's reward is programmatic over exactly the
   (old value, new value, key) triples a keyed store holds. That is the one
   route the field has shown to move a small reader, and it is a research
   direction, not a competition move.

## Sources

- Zep: A Temporal Knowledge Graph Architecture for Agent Memory — https://arxiv.org/abs/2501.13956
- Supersede: Diagnosing and Training the Memory-Update Gap in LLM Agents — https://arxiv.org/abs/2606.27472
- MemConflict: Evaluating Long-Term Memory Systems Under Memory Conflicts — https://arxiv.org/abs/2605.20926
- TOKI: A Bitemporal Operator Algebra for Contradiction Resolution — https://arxiv.org/abs/2606.06240
- ROAM: Robust Organization of Atomic Memories through Semantic Relations — https://arxiv.org/abs/2609.09778
- Rethinking How to Remember: Beyond Atomic Facts (TriMem) — https://arxiv.org/abs/2605.19952
- A-Mem: Agentic Memory for LLM Agents (NeurIPS 2025) — https://arxiv.org/abs/2502.12110
- Mem0 — https://github.com/mem0ai/mem0 ; State of AI Agent Memory 2026 — https://mem0.ai/blog/state-of-ai-agent-memory-2026
- Mastra, Observational Memory: 95% on LongMemEval — https://mastra.ai/research/observational-memory
- Knowledge Conflicts for LLMs: A Survey (EMNLP 2024) — https://arxiv.org/abs/2403.08319
- LongMemEval (ICLR 2025) — https://arxiv.org/abs/2410.10813
