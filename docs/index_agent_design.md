# Per-user index agent — design note and application draft (2026-09-26)

Written for two readers: the Agent Memory Challenge 2026 cycle-2 admission form
(Q8 requires self-trained components to be declared before the first Full), and
ourselves in a month when the context is gone. Every design choice below is
tied to a measurement we already have; nothing here is a hope.

## 0. One sentence

A small per-`user_id` LoRA adapter, trained online from that user's own Add
stream, that contributes **retrieval keys** to `/search` and nothing else. The
reader stays the platform's `gpt-4o-mini`; the returned text stays stored text.
Weights are an index, not a store.

## 1. Rules this has to satisfy (cycle-2 official Q&A, `docs/cycle2_official_qa_zh.md`)

| rule | consequence for this design |
|---|---|
| Q7 — generation model in Add/Search must be `gpt-4o-mini` | the adapter never generates returned text; it emits key strings that are used to *look up* stored text. Declare it alongside embedding/reranker as a non-generation component and get written confirmation before Full. |
| Q8 — self-trained models and **"任务内在线参数更新"** are not approved by default; list base, training procedure, training data, weight release, actual use; obtain a written conclusion before Full | this is exactly that case. §7 is the draft. |
| Q9 — no training on LoCoMo-Refined, BEAM or any public eval subset; eval data only for the current evaluation; derived copies deleted | training data = the user's own Add stream during the evaluation, nothing else. Adapters are derived copies: deleted with the data inside 30 days, logged in the deletion record. Our bench corpora (LoCoMo, LongMemEval-S) are measurement only. |
| Q18 — content only from that user's history; no future info, no external answer; no answer disguised as memory | keys are strings, matched lexically against the user's own store; only matched stored text is returned. The adapter's own generations never reach the reader. |
| Q24 — strict isolation across runs and `user_id` | one adapter file per `user_id`, keyed by the same digest as the store; loaded only for that user's Search. |
| Q20 — 30 min per Add / Search; 429 + Retry-After sanctioned | online write per Add chunk fits; concurrency during Full is the real limit, shed with 429. |

## 2. What we measured that this rests on (`dual-brain-memory/CLAIMS.md`, index paper)

| finding | number | design consequence |
|---|---|---|
| top-k first tokens at the answer slot retrieve the gold log line even when recall has failed | gold_in_Ri **47/48** on a healthy substrate, incl. 4/5 recognition-only and 1/1 "gone" (grep-rescue v3) | keys are the adapter's product |
| key window outlives recall | HL_recall 2 < HL_key10 **7** < HL_2AFC 16 fact-writes (naked); miss-gated replay holds key10 at 0.94–1.0 with no window closing | maintenance = ewcreplay with miss-gated replay, self-test drawn from the store |
| in-context reading *through* the adapter regresses recalled facts | 42 → 11/12 with adversarial same-attribute distractors | **read the store with the index OFF** — the reader is the frozen model; here the platform enforces it |
| familiarity (Δlp) authenticates presented content but cannot select | AUC 0.93+ presented; self-generated candidates → frankensteins, net recall 42 → 31, three times | no adapter-based reranking, no self-generated candidates as evidence |
| familiarity is indifferent to time | stale dissociation 14 → 14 while the base follows the timestamp rule 31 → 19 | the adapter does **not** address knowledge-update / supersession |
| "do I have an impression" gates are dead at agent level; scanning presented candidates works | presence AUC 0.63 / 0.39 on three instruments; SCAN recovers 48% of misses | no gate: run KEY on every search |
| rank is not the forgetting lever | rank-vs-forgetting de-noised weak | choose r for disk, not for retention |

And from this repo (`bench/results/locomo_completeness_smoke.md`): the evidence
that multi-hop questions miss sits at a median embedding rank of **213**; a
second embedding round with fused scores moves nothing (38/68 → 38/68);
reserving slots for it moves complete@100 0.559 → 0.647 but end-to-end
220 → 223 (16 questions gained evidence, 3 converted). Retrieval-side gains
convert at roughly one in five with this reader. That is the prior for any
number this design produces.

## 3. Architecture

```
Add(user, chunk) ──> store (raw turns + facts, unchanged)
                └──> adapter[user] ← online write of the chunk's facts/turns
                                      (ewcreplay; miss-gated replay; self-test = store)

Search(user, query, options)
   1. embedding round (unchanged)                       → E
   2. KEY: adapter[user] on prompt(query, options):
        top-30 first tokens at the answer slot + short greedy continuations
        ∪ content terms of the query                     → key strings K
   3. lexical search of the user's raw turns + facts with K (FTS)   → L
   4. MERGE: reserved slots (HOP2_SLOTS style), L fills what E did not take;
      no score fusion
   5. return stored text, ordered as today; reader = gpt-4o-mini, index OFF
```

* **WRITE.** Base: a ≤2B instruct model (probes used Qwen3.5-2B). Rank: r8–r16
  all-linear (r64 was the probe setting; rank is not the retention lever, and
  disk is per-user). Mechanism: summed-Fisher EWC + error-gated micro-replay;
  the self-test clozes the adapter on lines drawn from the store, misses first.
* **KEY.** Question form: `Q: <query>\nA:`; options appended when present.
  Take the top-30 first tokens at `A:`, greedily continue each ≤6 tokens,
  detokenise, drop stopwords and fragments <3 chars. Keys are never returned.
* **MERGE.** Same reservation logic as `AMI_HOP2_SLOTS`; the lexical channel
  gets the reserved places. Fused scoring is already measured not to work here.
* **READ.** No change. No gate.
* **AUTH.** Off. Δlp becomes relevant only if we ever render organised text
  under Q18; and even then it does not catch recombination errors.

## 4. What it does not do

* **Knowledge-update / supersession.** Familiarity has no clock. This stays
  where 2026-09-22 left it: closed at search time for this reader.
* **Reranking.** lpA +1 safe, Δlp −11: not a selector.
* **Anything for the coding track** without a public instrument. Separate note.

## 5. Gate before building anything: does the key channel have a target?

Pre-registered in `bench/results/key_target_check_preregistration.md`. On the
existing `bench/out/lc-smoke` and `lc-h30` retrievals, for the questions whose
evidence neither arm completed: is the missing turn reachable by a lexical
search at all, with question terms alone, or only with answer terms? If
question terms alone reach it, the adapter is unnecessary for this corpus and
plain FTS is the arm to run. If nothing lexical reaches it, this channel has no
target here and the design stops. Only "answer terms reach it, question terms
do not" gives the adapter a role.

**Outcome (2026-09-26, `bench/results/key_target_check.md`):** an oracle
answer key reaches 12 of the 42 never-completed questions (10 beyond question
terms), 8 under the union rule this section's design implies — 2.8% of 351 on
completeness, before the adapter's own emission rate and the reader's ~1/5
conversion. Expected end-to-end ≈ 1–2 questions against ~23 of replicate
noise. Of the 34 out of reach, 17 fail on precision (answer terms are common
words) and 17 on reach (the turn's content is anaphoric — "I've had them for 3
years"). **Search-time key arm: not built. Application: not submitted on this
evidence; §7 stays a draft.** Re-run the script on an entity-heavy corpus
before reopening.

## 6. Cost and operations

* Users: LongMemEval-S is one haystack per question (~500 `user_id`s per 500
  questions); cycle 2 is 6,000+ instances across 32 sources, `user_id` count
  unknown. Assume thousands.
* Disk: r8 all-linear on a 2B model ≈ 10–20 MB per user → tens of GB. Store on
  the data volume next to the SQLite store; delete with the data.
* Add: one online write per chunk + ~4 replay steps, on the CUDA card. Fits
  30 min per request by a wide margin for one user; Full concurrency is the
  bottleneck → 429 + Retry-After, and adapters written asynchronously after
  the store write returns 200 (Q11: 200 means durably stored — the store is,
  the adapter is a derived index and may lag).
* Search: load adapter (cold, seconds), one forward for keys, FTS query.
* Reconstructibility: the adapter is a function of the store; if it is lost or
  lags, Search degrades to today's behaviour, never to a wrong answer.

## 7. Application draft (Q8 items)

**基座.** Qwen3.5-2B-Instruct（开源，Apache-2.0），冻结；仅训练 LoRA adapter。
**训练流程.** 每个 `user_id` 一个 adapter。在该用户每次 Add 之后，对该 chunk 的
原文轮次与抽取事实做在线 LoRA 写入（summed-Fisher EWC + 错误门控微回放，回放
自测题从该用户自己的 store 中生成）。无离线预训练、无跨用户共享参数。
**训练数据.** 仅该 `user_id` 在本次评测中通过 Add 收到的内容。不使用任何本期
公开评测子集（LoCoMo-Refined、BEAM、LongMemEval 等）或外部语料训练。评测数据及
adapter（其派生副本）在评测结束后 30 天内一并删除，删除记录可审计。
**权重开放方式.** 训练代码与配置随固定 commit 公开；评测期间产生的 per-user
adapter 属评测数据派生副本，不发布、按期删除。
**实际用途.** Search 时 adapter 只产生**检索键**（答案槽 top-k token 及其短续写），
用于对该用户自己的 store 做词法检索；命中的**原文**进入返回列表。adapter 不生成
任何返回文本，不参与排序打分，不参与作答。生成模型仍为 `gpt-4o-mini`
（Add 端事实抽取与 Search 端 recall question），与现有申报一致。

## 8. Notes to self (the things that get forgotten)

* Pre-register every arm; never gate a decision on recall@k or complete@k —
  end-to-end on both `lme-*` and LoCoMo, one prediction written down first.
  Nine written predictions about this reader; nine wrong. Measure.
* The adapter is an *index over the store*; if a design step needs the adapter
  to hold a fact the store does not, the step is wrong.
* Keys valid t≲7 writes un-maintained — maintenance is not optional.
* No gate. Always scan.
* This does not touch KU. Do not let it drift into "the adapter knows which
  version is current" — measured, it does not.
* Read the store with the index OFF. The competition makes this free.
