# Submission notes — Agent Memory Challenge 2026

Release metadata and technical notes. Keep in sync with `README.md` and `RELEASE.md`.

On 2026-10-01 the user reported submitting the access application. Approval/Eval Key is
pending; no issued credential or approval receipt has been independently verified. Official
platform Smoke and Full have not run. The platform's concrete Answer/Eval models are not
confirmed; public materials do not establish a DeepSeek model switch.

Historical numerical results below use BGE and local answer/judge runs. They are not v4
benchmark results or official leaderboard scores. This release has functional integration
validation and makes no v4 quality-gain claim.

| field | value |
|---|---|
| System name | ActiveMemoryIndex |
| Version | `academic-v4-20261001`; public tag identifies the fixed release commit |
| Evaluation type | Textual Memory |
| Division / route | Academic Methods · API (self-hosted) |
| Repository | https://github.com/linxuhao/ActiveMemoryIndex |
| Endpoint URL | `https://amindex.linxuhao.app` (HTTPS, Cloudflare; see the GitHub release notes for deployment verification) |
| Contact | Xuhao Lin · linxuhao84@gmail.com · independent researcher |
| Models used by Add and Search | `gpt-4o-mini` for extraction/recall; remote `text-embedding-v4`, 1024 dimensions, for embeddings |

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
git checkout academic-v4-20261001
cp .env.academic.example .env.academic
# Set OPENAI_API_KEY, AMI_EMBED_API_KEY, AMI_AUTH_TOKEN and region/workspace endpoint.
AMI_ENV_FILE=.env.academic docker compose --env-file .env.academic -p ami-academic up -d --build
```

| variable | purpose |
|---|---|
| `OPENAI_API_KEY` | Participant-supplied `gpt-4o-mini` key |
| `AMI_EMBED_API_KEY` | Separate participant-supplied embedding key |
| `AMI_EMBED_BASE_URL` | Explicit endpoint matching embedding key region/workspace; tested with the user-confirmed Beijing workspace endpoint |
| `AMI_EMBED_BACKEND` / `AMI_EMBED_MODEL` / `AMI_EMBED_DIMENSIONS` | `openai` / `text-embedding-v4` / `1024` |
| `AMI_AUTH_SCHEME` / `AMI_AUTH_TOKEN` | `bearer` / Memory System Key shared privately with platform |
| `AMI_DB_PATH` / `AMI_VOLUME` | Fresh `/data/memory-v4.sqlite3` / `ami-academic-v4-data`; never reuse BGE vectors |

The release retains raw turns plus facts, extraction and recall enabled, recall weight `0.5`,
raw-first ordering, neighbor window radius `1`, at most `100` results within `top_k`, and a
`400000`-character response budget. Agentic, hop2, DCI, fact-evidence/selection, chunk-memory,
event-date, fact-key/supersession, chronology/newest and cross-encoder experiments remain off.

- Add: `POST https://amindex.linxuhao.app/add`
- Search: `POST https://amindex.linxuhao.app/search`
- Health: `GET https://amindex.linxuhao.app/health` (unauthenticated)
- Outbound access and paid API usage are required for both the embedding provider and LLM.
- Remote embedding failures fail startup or the request explicitly, without changing model
  or partially storing a successful Add. LLM-only fallback is not an embedding fallback.
- The service must remain available throughout an evaluation. Public routing and bounded
  concurrency checks are recorded in the GitHub release notes; sustained capacity is unmeasured.

## Validation and evaluation flow

The fixed release app source passed **105 checks**: 26 adapter/store unit tests, 41 baseline
checks and 38 Add/Search contract checks through the real SDK and a loopback fake embedding
API in a network-none container with temporary storage. The earlier candidate used identical
embed/store/main/LLM code; its small synthetic real-provider test observed 17 v4 HTTP requests
(all 200, 1024 dimensions) and 15 `gpt-4o-mini` requests (all 200), plus 38 contract checks and
42/37 controls before/after restart. The 19 persisted items across four synthetic users,
long Unicode source, vectors, request ledger and embedding identity survived restart exactly.
Release config removes unused DCI research additions, and release DCI uses the base version.
These are integration checks, not benchmark quality, production throughput or Full results.
See `RELEASE.md` for scope and evidence references.

1. Access application submitted on 2026-10-01 (user report); approval/Eval Key pending.
2. Use the fixed source tag and verify the authenticated public endpoint before evaluation.
3. Once the platform issues the Eval Key, run its official Smoke and inspect the result.
4. Start official Full only after readiness and Smoke pass, using current platform limits
   documented at [the competition page](https://agentmemories.ai/competition/).

The platform's Answer/Eval model configuration is distinct from participant extraction and
recall. Its exact models are unconfirmed; refer to the official
[API configuration](https://github.com/AML-memory/agent-memory-leaderboard/blob/main/api_config.py).

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
  │        + text-embedding-v4 embeddings (1024 dimensions)
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
3. Both kinds are embedded with `text-embedding-v4` (1024 dimensions) and committed to SQLite before the
   response is written. Re-sending a `request_id` is idempotent within the user. Long source
   text is retained whole while embedding uses lossless UTF8 segmentation and normalized
   byte-weighted pooling; identity checks prevent vector-space mixing.

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
4. **Verbatim-first ordering:** The selected memories are returned verbatim turns first,
   extracted facts second, each block keeping its relevance order (`AMI_RAW_FIRST=1`). This
   changes the order of the returned set, never its membership, and it is the single largest
   lever we measured — larger than every retrieval change we tried, combined (see below).
5. **Return policy:** The ranked list is deduplicated and returned up to `AMI_RETURN_LIMIT`
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
for the LLM components during Add and Search, with `text-embedding-v4` for embeddings.

What was **adapted** from the paper for this submission:

| Paper finding | How it's used here |
|---|---|
| Register-matching beats query rewriting | The recall-question channel: ask "Did I tell you about X?" in first person, fuse with original query. **This is HyDE** (Gao et al., 2022, arXiv:2212.10496) with a first-person recall question as the hypothesis; the 50/50 fusion is HyDE's own N=1 case, since blending the two similarities is algebraically identical to averaging the two embeddings. Only the prompt — a recall *question* rather than a hypothetical *answer*, for a first-person corpus — is specific to this work. |
| Context-dilution curve (0.59 → 0.20) | **Tested and not reproduced on `gpt-4o-mini`.** The paper's 9B reader loses accuracy as context grows; this reader gains it. We therefore return the full `top_k` (100) rather than the short set the paper's curve implies — the reversal is reported here rather than hidden because it is a property of the reader, not of the memory system |
| Verbose storage is safe with good retrieval | The dual-store: keep everything (verbatim) + index clean keys (facts) |

What is **new** in this submission (not in the paper):

0. **Verbatim-first ordering of the returned set — the largest single lever, and the one we
   did not expect.** Having fixed *what* to return, we looked for further gains in *retrieval*
   and found almost none there. Ordering the same returned memories verbatim-turns-first is
   worth more than every retrieval change we tried. Over all ten LoCoMo conversations
   (n=1540), three independent answer+judge runs per arm:

   | ordering / ranking of the returned 100 | accuracy | vs relevance order, paired |
   |---|---|---|
   | diversity cap (≤2 memories per source chunk) | .5799 | net −5, p = 0.77 |
   | extracted facts first | .5828 | net −7, p = 0.64 |
   | relevance order (dense ranking) | .5887 | — |
   | hybrid BM25 + dense (reciprocal rank fusion) | .6067 | net +27, p = 0.094 |
   | **verbatim turns first** | **.6333** | **net +70, p = 4×10⁻⁶** |

   A verbatim turn is the primary source; an extracted fact is a lossy paraphrase of it. Three
   competing explanations were tested and ruled out: it is not the grouping (facts-first groups
   identically and gains nothing), not head-and-tail attention (splitting the verbatim turns
   across head and tail is indistinguishable, net +1, p = 1.000), and not context volume (the
   winning arm returns exactly as many characters as the baseline). A **lexical BM25 channel
   (SQLite FTS5 + reciprocal rank fusion) was built, measured and removed** — worth +1.8pt
   alone, but dominated by the ordering change, which needs no index and no extra call.

   We also record that our own pre-registered gate for this decision was the wrong instrument.
   Retrieval coverage is inverted against accuracy across these arms: the arm with the best
   coverage at k=100 had the *worst* accuracy. Every arm returns the same evidence, so a metric
   that scores whether the evidence was returned cannot see ordering at all.

1. **Dual-store architecture** — The paper stores only extracted facts. This submission stores
   both verbatim turns and extracted facts in parallel, embedded with the same model, so the
   verbatim channel catches details extraction misses. **This is not novel and we do not claim it
   is**: Zep/Graphiti (episode subgraph plus entity subgraph) and MemGPT/Letta (recall plus
   archival memory) ship the same dual store, and *Fidelity Before Structure* (arXiv:2601.00821)
   reports that on LoCoMo the union of chunks and extracted artifacts is statistically
   indistinguishable from verbatim chunks alone (42.5 vs 43.9, McNemar p=0.39). Our contribution
   here is only the ordering of that union (item 0), which recovers value their ablation could not
   see because their reader prompt has a single undifferentiated context slot.
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
   tunnel, user-scoped idempotent re-add, persistent embedding identity and vector validation.
   LLM fallback does not replace the required remote embedding service. None of this infrastructure
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

Runtime components: DashScope `text-embedding-v4` service, `gpt-4o-mini`, FastAPI, uvicorn,
SQLite and OpenAI Python SDK. The image also includes sentence-transformers and
`BAAI/bge-small-en-v1.5` (MIT) for optional historical research; the academic profile does not
use BGE. No benchmark data, gold answer or manual relation annotation enters runtime retrieval.

## Integrity

No hard-coded answers, no benchmark leakage, no prompt injection, no manual intervention, no
cross-`user_id` retrieval. Retrieval scope is `user_id` only; `session_id` is stored for
provenance and never used as a filter. Evaluation data is used solely to serve the run and is
not retained for training or analysis.
