# Submission notes — Agent Memory Challenge 2026

Paste-ready materials for the evaluation access request. Keep in sync with `README.md`.

| field | value |
|---|---|
| System name | ActiveMemoryIndex |
| Version | 1.0.0 (commit `e97b483` pinned at submission) |
| Evaluation type | Textual Memory |
| Division / route | Academic Methods · API (self-hosted) |
| Repository | https://github.com/linxuhao/ActiveMemoryIndex |
| Endpoint URL | `https://amindex.linxuhao.app` (HTTPS, Cloudflare, stable ≥30 days) |
| Contact | Xuhao Lin · linxuhao84@gmail.com · independent researcher |
| Model used by Add and Search | `gpt-4o-mini` (only model in the system; the embedder is a local `bge-small-en-v1.5`) |

## Key flow

Two keys, one in each direction:

| Key | Provided by | Used for |
|---|---|---|
| **Eval Key** | Platform (issued after approval) | We use it to initiate smoke tests and full evaluations from the platform side |
| **Memory System Key** | Us (generated secret) | The platform includes it in `Authorization: Bearer <key>` when calling our Add/Search endpoints |

Neither key appears in the repository. The Memory System Key is set as `AMI_AUTH_TOKEN` at
deployment and shared with the platform through the access-request flow (stored encrypted).

## Authentication

`AMI_AUTH_SCHEME=bearer` — the platform authenticates with `Authorization: Bearer <token>`.
`/health` is unauthenticated (any 2xx → healthy).

`none` is supported for local smoke testing only; formal evaluations require an auth scheme.

## Run instructions (self-hosted)

```bash
git clone https://github.com/linxuhao/ActiveMemoryIndex.git
cd ActiveMemoryIndex
cp .env.example .env
# Edit .env: set OPENAI_API_KEY and AMI_AUTH_TOKEN (all other defaults match production)
docker compose up -d
```

| variable | purpose |
|---|---|
| `OPENAI_API_KEY` | Our `gpt-4o-mini` API key — participant-supplied, injected at deployment |
| `AMI_AUTH_SCHEME` | `bearer` (also supports `token`, `x-api-key`) |
| `AMI_AUTH_TOKEN` | The Memory System Key shared with the platform |

- Add: `POST https://amindex.linxuhao.app/add`
- Search: `POST https://amindex.linxuhao.app/search`
- Health: `GET https://amindex.linxuhao.app/health` (unauthenticated)
- The image bakes in `bge-small-en-v1.5` weights; no model download at runtime.
- Outbound: the container needs access to `https://api.openai.com` (or `OPENAI_BASE_URL`).
- The endpoint is served behind Cloudflare with HTTPS and will remain stable ≥30 days after submission.
- The container runs without a key in degraded raw-text-only mode (missing key lowers scores
  instead of failing the run).

## Evaluation flow

1. **Submit access request** — provide this metadata, endpoint URL, auth scheme, and Memory
   System Key through the platform's request form.
2. **Receive Eval Key** — issued after approval; used to initiate evaluations.
3. **Run smoke test** — use the Eval Key on the platform's evaluation page to verify the
   synchronous Add → Search → Answer → Evaluate flow (1/hour, private).
4. **Submit full evaluation** — after smoke passes; 1 every 3 months, private first, public
   after review and eligibility gate.

---

## 原始作者 · Original Author

**Xuhao Lin**, independent researcher (linxuhao84@gmail.com).

The method comes from the author's own prior research:

- **Paper:** *An Index, Not a Store: The Model Does Remember — It Just Needs Its Notebook*
  (Xuhao Lin, 2026), [doi:10.5281/zenodo.21405963](https://doi.org/10.5281/zenodo.21405963)
- **Research code:** https://github.com/linxuhao/index-not-store

The paper's primary subject is **online weight-level learning** — writing new knowledge directly
into a model's weights (LoRA adapters on a local 9B backbone) so that the model itself becomes
the memory store. The memory harness (Add/Search API, dual-store architecture, register-matching
retrieval) was developed to evaluate that weight-level system on the **InMind benchmark**
(https://github.com/imlrz/InMind), an indirect AI memory benchmark that measures whether a
reader model can answer questions after the memory system ingests a conversation.

The paper is still in active research; the memory harness portion may not yet reflect the latest
experiment results at the time of this submission.

## 技术报告 · Technical Report

### Architecture

```
Add  ──→  verbatim store (timestamped turns)
  │        + fact store (gpt-4o-mini extraction)
  │        + bge-small-en-v1.5 embeddings
  │        + SQLite commit
  └──→  200 (only after persistence is searchable)

Search ──→  recall-question rewrite ("Did I tell you about …?")
         │  + fused embedding retrieval (original query + recall question)
         │  + optional agentic gap-check (off by default; see method changes)
         │  + deduplicate, trim under character budget
         └──→  evidence only, never an answer
```

### Write path (`/add`)

1. Every message is stored **verbatim**, one memory per message, prefixed with its UTC
   timestamp (`[2023-05-20 14:00] I: …`). Nothing is discarded at write time.
2. The same chunk is passed to `gpt-4o-mini`, which extracts **atomic, self-contained,
   first-person facts** (e.g., "[2023-05-20] I adopted a beagle named Ollie from the shelter
   in Malmo."). The extraction prompt forbids inference, pronouns without referents, and
   summarisation; it requires names, numbers, and dates to survive verbatim.
3. Both kinds are embedded with `bge-small-en-v1.5` and committed to SQLite before the
   response is written. Re-sending a `request_id` is idempotent.

Storing both is the point: extraction gives clean retrieval keys; the verbatim copy keeps the
details extraction inevitably drops. Timestamps are carried inside `content` (not only in
`created_at`) because the platform's answering prompt resolves relative time expressions from
the memory text itself.

### Read path (`/search`)

1. **Register-matching recall question:** `gpt-4o-mini` rewrites the benchmark question as a
   memory-check question in the user's own first-person voice — "Did I tell you about my
   sister's wedding in Kyoto?" — never addressing the user as *you*, never answering the
   question. This is the core retrieval finding from the underlying paper: matching the
   register of the store (first-person chat log) beats any amount of query rewriting in the
   question's register.
2. **Fused retrieval:** Both the original query and the recall question are embedded. Every
   memory is scored by `(1-w)·sim(query) + w·sim(recall question)` where `w=0.5`.
3. **Agentic gap-check (available, off by default):** `gpt-4o-mini` can inspect the first
   retrieval and, if evidence looks incomplete, generate a second targeted recall question,
   merging and re-ranking both rounds. Disabled (`AMI_AGENTIC_SEARCH=0`) because it measured
   zero end-to-end gain at the deployed return size while costing an extra call per search.
4. **Return policy:** The ranked list is deduplicated and returned up to `AMI_RETURN_LIMIT`
   (100) memories, never exceeding `top_k`, under a character budget (400,000) set large enough
   never to truncate that list silently. This value is **measured, not assumed**. The underlying
   paper reported a monotonic context-dilution curve on a 9B reader (accuracy 0.59 at 1 line →
   0.20 at 125), which predicts a short return set; we swept the limit over 1/2/3/5/10/20/40/100
   on LoCoMo using the platform's own answer and judge prompts and found the **opposite** for
   `gpt-4o-mini` — accuracy rises monotonically (0.219 at 1 → 0.597 at 100, n=529), as does the
   conditional rate at which the reader applies a retrieved gold memory (0.461 → 0.626).
   Returning 100 won every pairwise comparison on both tuning subsets and was then confirmed on a
   held-out subset never used for tuning (n=464, accuracy 0.584). Details and method in `bench/`.

Search returns memory evidence only. It never produces or disguises a final answer, and never
reads outside the requested `user_id`.

### Key design decisions

| Decision | Rationale |
|---|---|
| Dual store (verbatim + facts) | Facts are clean retrieval keys; verbatim preserves details extraction drops |
| Register-matching recall | First-person "Did I tell you…" queries match the store's genre; empirically beats keyword-based retrieval |
| Agentic reflection, off by default | Measured at zero end-to-end gain once the full `top_k` is returned; kept in the code behind `AMI_AGENTIC_SEARCH` |
| Fill `top_k` (100) | Swept 1→100 against the platform's own answer/judge prompts: accuracy is monotone increasing for `gpt-4o-mini`, reversing the paper's 9B dilution prior; confirmed on a held-out subset |
| Timestamps in content text | The platform answer model resolves relative time from content, not `created_at` |

## 全部方法改动 · All Method Changes from the Original Paper

The original paper (*An Index, Not a Store*) investigates **weight-level memory** — writing
memories directly into a model's LoRA weights and retrieving by eliciting recall from those
weights. The strongest configuration in that paper (LoRA r=32 on a 9B backbone) is
**deliberately excluded** from this submission because the competition requires `gpt-4o-mini`
as the only model used during Add and Search.

What was **adapted** from the paper for this submission:

| Paper finding | How it's used here |
|---|---|
| Register-matching beats query rewriting | The recall-question channel: ask "Did I tell you about X?" in first person, fuse with original query |
| Context-dilution curve (0.59 → 0.20) | **Tested and not reproduced on `gpt-4o-mini`.** The paper's 9B reader loses accuracy as context grows; this reader gains it. We therefore return the full `top_k` (100) rather than the short set the paper's curve implies — the reversal is reported here rather than hidden because it is a property of the reader, not of the memory system |
| Verbose storage is safe with good retrieval | The dual-store: keep everything (verbatim) + index clean keys (facts) |

What is **new** in this submission (not in the paper):

1. **Dual-store architecture** — The paper stores only extracted facts. This submission stores
   both verbatim turns and extracted facts in parallel, embedded with the same model, so the
   verbatim channel catches details extraction misses.
2. **Fact extraction prompt** — The extraction pipeline (24 atomic first-person facts per
   chunk, timestamp prefixing, no-inference constraint) was written specifically for this
   submission to work with `gpt-4o-mini` on the LoCoMo dataset.
3. **Agentic search (gap-check + second retrieval), implemented but DISABLED by default** —
   `gpt-4o-mini` can inspect the first retrieval and fire a second targeted recall question.
   We measured it and turned it off: on the one clean A/B (same store, same weight, conv 2-4,
   n=529) it moved retrieval recall@10 from 0.711 to 0.741 but left end-to-end accuracy
   unchanged at 0.599 — the gain lives at small return sizes, and we return the full `top_k`.
   It costs one extra LLM call per search, so it is off (`AMI_AGENTIC_SEARCH=0`). An earlier
   draft of this document claimed "+1.7 percentage points"; that figure came from an ablation
   whose two arms were later found to be byte-identical, and it is retracted.
4. **Fused embedding scoring** — Weighted combination of original query and recall-question
   similarity, with tunable weight `AMI_RECALL_WEIGHT`, calibrated on LoCoMo.
5. **Return policy — the paper's context-dilution finding tested and NOT reproduced.**
   The ranked list is deduplicated and returned up to `AMI_RETURN_LIMIT` (100, i.e. the full
   `top_k`) under a 400,000-character budget sized never to truncate it. The paper predicted a
   short return set; on `gpt-4o-mini` accuracy rises monotonically with the returned count
   (see the read-path section above).
6. **Production service wrapper** — FastAPI, bearer auth, Docker deployment, Cloudflare
   tunnel, idempotent re-add, degraded mode without API key. None of this infrastructure
   exists in the research codebase.
7. **Contract compliance** — Synchronous persistence (200 only after SQLite commit),
   `user_id` isolation, `request_id` echo, 422 on malformed input, `/health` liveness.
   These are competition requirements, not research concerns.

What was **excluded** from the paper:

- LoRA-based weight writing (incompatible with `gpt-4o-mini` requirement)
- EWC regularization and Benna-Fusi cascade (weight-level mechanisms, no API-model equivalent)
- The 9B local backbone and its recall elicitation pipeline
- Per-user weight partitions

## Third-party components

Used unmodified: `BAAI/bge-small-en-v1.5` (MIT), FastAPI, uvicorn, sentence-transformers,
SQLite, OpenAI Python SDK. No benchmark data or gold answer is bundled or consulted.

## Integrity

No hard-coded answers, no benchmark leakage, no prompt injection, no manual intervention, no
cross-`user_id` retrieval. Retrieval scope is `user_id` only; `session_id` is stored for
provenance and never used as a filter. Evaluation data is used solely to serve the run and is
not retained for training or analysis.
