# Pre-registration — direct corpus interaction as the search step (2026-09-27)

Written before the arm is built or run. Motivated by *Beyond Semantic
Similarity: Rethinking Retrieval for Agentic Search via Direct Corpus
Interaction* (arXiv 2605.05242, NeurIPS 2026 spotlight): an agent with grep /
read over the raw corpus, no index, beats dense + rerank retrieval by +11 on
BrowseComp-Plus and +30.7 on multi-hop QA, and a small agent (GPT-5.4-nano)
gains +16–18 over the same model with a vector retriever. Their searcher is
their answerer; ours cannot be. The research question this arm asks:

> **Does DCI's gain survive handing the found evidence to a separate, fixed
> reader?** Or does it live in the coupling of search and answer?

Two of our own results point opposite ways: `AMI_HOP2_SLOTS` delivered
complete evidence to 16 more LoCoMo questions and the reader converted 3
(`locomo_completeness_smoke.md`); the oracle splice showed the reader answers
correctly the moment the returned *set* is right (`supersede_drop_oracle.md`).
The difference is membership: a 100-item relevance list versus a few lines an
agent chose.

## Mechanism (`AMI_DCI_SEARCH=1`)

* **Corpus.** The user's store, unchanged. Verbatim turns grouped by Add
  chunk ("file" = chunk digest), each line `id · timestamp · text`; extracted
  facts in one more file. Nothing is rewritten.
* **Agent.** `gpt-4o-mini` (the permitted model) with three tools:
  `grep(pattern, context)` (case-insensitive regex over all lines, capped at
  20 hits, ±context lines from the same chunk), `read(file, start, end)`
  (capped at 40 lines), `finish(ids)`. The file list with date ranges is
  shown up front. Budget: **12 tool calls**; when exhausted, one final call
  restricted to `finish`.
* **Instruction.** Find the lines a reader would need; do not answer; if a
  value was updated later, return the latest statement and leave out the
  superseded one unless the question asks about the past; include the
  neighbouring turns needed to resolve a pronoun.
* **Output.** Stored items by id, in the agent's order. The agent never
  emits content; `/search` returns stored text only. Q18 compliance:
  evidence organisation by a declared generation model, disclosed.
* **Two arms.**
  * `dci` — return exactly the agent's ids (≤ `top_k`), nothing else.
  * `dcifill` — the agent's ids first, then the ordinary embedding selection
    fills the remaining slots (existing `select()` with `exclude`).
* If the agent fails (no `finish`, API error), the search falls back to
  today's behaviour and logs it. Fallback count is reported per arm.

## Instruments, in run order

1. **Knowledge-update gate** — `lme-ku-k`, 78 questions, 4 replicates per
   arm, against `kbase1–4` (59.50). Per-question table on the 8 still-stale
   and the 2 two-part questions from `supersede_drop_oracle.md`.
2. **LoCoMo completeness + end-to-end** — conversations 2–3, 351 questions,
   store `lc-smoke`, one replicate per arm, against `lc-smoke` base (evidence
   complete 293/351, accuracy 220/351) and `lc-h30` (306, 223). Report the
   hop2-style decomposition: gained / lost complete evidence × converted.
   The 42 NEITHER questions from `key_target_check.md` are the named
   subpopulation.
3. **Temporal guard** — `lme-t`, 133 questions, 4 replicates, `dci` only,
   against `base, base2, base3, base4` (58.50). Report now-anchored (49) and
   the rest (84) separately.

Also logged per search: tool calls, wall seconds, fallback, returned count.

## Statistics

4-vs-4: exact permutation, two-sided (complete separation p = 0.029). Paired
sign test on discordant questions. LoCoMo single replicate: paired
discordance count, with the ~6.6% between-replicate noise floor of that
instrument stated next to it.

## Decision rules, fixed now

* **Ship candidate** only if all three hold: KU `dci` or `dcifill` ≥ +4.0
  over `kbase` with p ≤ 0.05; LoCoMo end-to-end not below base by more than
  the noise floor; temporal not below base with p ≤ 0.05. Even then it ships
  only after a cost/latency reading (tool calls × 6,000 instances).
* **Research reading, independent of shipping:**
  * `dci` ≥ +4 on KU and the 8 stale questions flip → membership by a
    reading agent works for this reader; DCI's gain survives the hand-off.
  * LoCoMo: evidence-complete rises on NEITHER but conversion stays ≈ 1 in 5
    → the gain does *not* survive the hand-off; it lives in the coupling.
  * `dci` < `dcifill` everywhere → the reader still wants the long list;
    the agent's set is too narrow for it.
* Temporal now-anchored questions are expected not to move (no "now"); if
  they do, inspect for leakage of the question date through the agent
  before reading anything else.

## Prediction (twelfth, written before the run)

KU: `dci` **+5** over `kbase` (≈ 64.5), with 6 of the 8 stale questions
flipping and the 2 two-part questions holding (the agent reads both values).
`dcifill` +2. LoCoMo: ≥ 10 of the 42 NEITHER gain complete evidence under
`dci`; end-to-end +4 on 351, inside the noise floor. Temporal: `dci` −2,
n.s.; now-anchored unchanged. Fallback rate < 5%. Median 6 tool calls.

## What this does not test

A stronger searcher (Sonnet-class) — not permitted. Streaming. Whether the
agent's choices leak the question into returned text — it cannot, by
construction (ids only), but the returned set is a function of the question,
which today's invariant already allows (the query selects).
