# ActiveMemoryIndex

An Add/Search memory system for the [Agent Memory Leaderboard](https://agentmemories.ai) (Agent
Memory Challenge 2026, Academic Methods track, Textual Memory).

**One sentence:** memories are stored twice — as verbatim timestamped turns and as atomic
first-person facts — and retrieval asks the log the question *the user themselves would ask*
("Did I tell you about …?"), because matching the log's own first-person register is worth more
at retrieval time than any amount of query rewriting in the question's register.

---

## Quick start (Docker, self-hosted)

```bash
# Clone and deploy with docker compose (recommended):
git clone https://github.com/linxuhao/ActiveMemoryIndex.git
cd ActiveMemoryIndex
cp .env.example .env
# Edit .env: set OPENAI_API_KEY and AMI_AUTH_TOKEN (everything else has sensible defaults)
docker compose up -d

# Or standalone docker run:
docker build -t activememoryindex .
docker run -d --name ami -p 8000:8000 -v ami-data:/data \
  -e OPENAI_API_KEY="$OPENAI_API_KEY" \
  -e AMI_AUTH_TOKEN="$AMI_AUTH_TOKEN" \
  activememoryindex
```

The service must be reachable at a public HTTPS URL for evaluation. Health is unauthenticated;
Add and Search require `Authorization: Bearer <AMI_AUTH_TOKEN>`.

That is the whole startup. The image bakes in the embedding weights, so the container needs no
model download at run time.

| entrypoint | method | purpose |
|---|---|---|
| `/add` | POST | synchronous write; returns 200 only after the memories are persisted and searchable |
| `/search` | POST | relevance-ordered memories for one question, scoped to `user_id` |
| `/health` | GET | unauthenticated liveness check, returns 2xx |

Verify a running instance against the contract:

```bash
python scripts/smoke_contract.py http://127.0.0.1:8000
```

The script checks synchronous persistence, exact `request_id`/`user_id`/`session_id` echo,
response shape, `top_k` bound, `user_id` isolation, idempotent re-adds, and 422 on malformed
input. It requires no dependencies beyond the standard library.

## Configuration

All configuration is environment variables; **no credential is stored in this repository**.

| variable | default | meaning |
|---|---|---|
| `OPENAI_API_KEY` | *(empty)* | key for the Add/Search model. Required for the full pipeline. |
| `AMI_LLM_MODEL` | `gpt-4o-mini` | the model used by Add and Search. The challenge requires `gpt-4o-mini`; leave it. |
| `OPENAI_BASE_URL` | *(unset)* | any OpenAI-compatible endpoint. Local development only. |
| `AMI_LLM_CONCURRENCY` | `16` | cap on simultaneous provider calls, so a 64-worker Add burst queues instead of hitting 429s |
| `AMI_LLM_TIMEOUT` | `60` | seconds per provider call |
| `AMI_LLM_MAX_TOKENS_EXTRACT` / `_QUERY` | `1200` / `200` | completion caps; raise only when developing against a reasoning model |
| `AMI_RECALL_WEIGHT` | `0.5` | weight of the user-voice recall-question channel in the fused score |
| `AMI_RETURN_LIMIT` | `100` | maximum memories returned (never more than `top_k`) |
| `AMI_RETURN_CHAR_BUDGET` | `400000` | character budget for one response; large enough never to truncate `AMI_RETURN_LIMIT` silently |
| `AMI_AGENTIC_SEARCH` | `1` | after retrieval, gpt-4o-mini reflects on gaps and may fire a second recall question. Adds ~1 LLM call per search; improves recall ~1.7 pp |
| `AMI_EMBED_MODEL` | `BAAI/bge-small-en-v1.5` | embedding model, runs locally on CPU |
| `AMI_DB_PATH` | `/data/memory.sqlite3` | SQLite file |
| `AMI_AUTH_SCHEME` | `bearer` | `none` \| `bearer` \| `token` \| `x-api-key`. Formal evals require auth; `none` is for local smoke only. |
| `AMI_AUTH_TOKEN` | *(empty)* | expected secret when a scheme is set. This is the Memory System Key shared with the platform. |

**Degraded mode.** With no `OPENAI_API_KEY` the service still starts and serves: it stores the raw
timestamped turns and ranks them by the original query alone. This is a deliberate availability
property — a missing or rate-limited key degrades retrieval quality instead of failing Add.

## Method

### Write path (`/add`)

1. Every message is stored **verbatim**, one memory per message, prefixed with its own UTC
   timestamp (`[2023-05-20 14:00] I: …`). Nothing is discarded at write time.
2. The chunk is additionally passed to `gpt-4o-mini`, which extracts **atomic, self-contained,
   first-person facts** with the same timestamp prefix. The extraction prompt forbids inference,
   pronouns without referents, and summarisation, and requires that names, numbers and dates
   survive verbatim.
3. Both kinds are embedded with `bge-small-en-v1.5` and committed to SQLite before the response is
   written, so the memories are searchable the moment Add returns. Re-sending a `request_id` is
   idempotent.

Storing both is the point: extraction gives clean retrieval keys, the verbatim copy keeps the
details extraction inevitably drops. Timestamps are carried inside `content` (not only in
`created_at`) because the platform's answering prompt is instructed to resolve relative time
expressions from the memory text itself.

### Read path (`/search`)

1. `gpt-4o-mini` rewrites the benchmark question as a **memory-check question in the user's own
   voice** — "Did I tell you about my sister's wedding?" — never addressing the user as *you*, and
   never answering the question.
2. Both the original query and that recall question are embedded, and every memory is scored by
   the fused similarity `(1-w)·sim(query) + w·sim(recall question)`.
3. The ranked list is deduplicated and truncated to at most `AMI_RETURN_LIMIT` memories, always
   within `top_k`, under a character budget.
4. When `AMI_AGENTIC_SEARCH=1` (the default), `gpt-4o-mini` inspects the top results and may fire
   a second targeted recall question if evidence is missing; results from both rounds are merged
   and deduplicated.

Search returns memory evidence only. It never produces or disguises a final answer, and never
reads outside the requested `user_id`.

**Why the user-voice question.** In our own per-fact audits, matching the *register* of the store
beat every trained retrieval front end we measured: embedding a first-person "Did I tell you …"
question retrieved the gold line in the top-6 at 0.384, versus 0.216 for a keyword elicited from a
fine-tuned adapter and 0.152 for a keyword from the frozen model, over the same 241-line store and
the same embedder. Genre match, not query cleverness, was the lever. This service is that finding
implemented with compliant parts.

**Why we fill `top_k`, having expected the opposite.** The prior from our own per-fact audits was
that long contexts dilute the reader: there, the probability that a reader applied a correctly
retrieved fact fell monotonically with context size (0.59 at one line, 0.28 at 16, 0.20 at 125).
That prediction is **false for this reader on this benchmark**. Sweeping the return limit over
1, 2, 3, 5, 10, 20, 40 and 100 on LoCoMo with the platform's own answer and judge prompts, accuracy
rises monotonically with the number of returned memories, and so does the *conditional* rate at
which the reader applies a retrieved gold memory:

| memories returned | 1 | 5 | 10 | 20 | 40 | 100 |
|---|---|---|---|---|---|---|
| accuracy (n=529) | .214 | .361 | .433 | .488 | .552 | **.597** |
| accuracy given gold retrieved | .447 | .510 | .556 | .580 | .605 | **.626** |

Returning 100 wins every pairwise comparison on both tuning subsets, and the choice was then
confirmed on a held-out subset never used for tuning (n=464, accuracy .584). The earlier audits
used a 9B reader; `gpt-4o-mini` evidently uses extra context rather than drowning in it. The knob
stays exposed because the right value is a property of the reader, not of the memory system —
`AMI_RETURN_CHAR_BUDGET` must be raised alongside it, or the character budget silently truncates
the list. Method in `bench/`.

## Repository layout

```
app/config.py    environment configuration
app/main.py      FastAPI service: /add, /search, /health
app/llm.py       the single LLM (gpt-4o-mini): fact extraction + recall-question rewriting
app/embed.py     bge-small-en-v1.5 embeddings
app/store.py     SQLite store with a per-user in-process vector cache
scripts/         contract smoke test
```

## Disclosure of original work and changes

* **The method comes from our own prior research**, not from a third-party memory system:
  *An Index, Not a Store: The Model Does Remember — It Just Needs Its Notebook* (Xuhao Lin,
  independent researcher, 2026), preprint and raw timelines at
  [doi:10.5281/zenodo.21405963](https://doi.org/10.5281/zenodo.21405963), research code at
  <https://github.com/linxuhao/index-not-store>. The register-matching retrieval result and the
  context-dilution curve quoted above are from that work; the numbers were measured on the InMind
  benchmark with a different backbone and **do not transfer as predictions** to this leaderboard's
  datasets.
* **What is new here** is the service: the Add/Search wrapper, the extraction and recall-question
  prompts, the dual store, the fused ranking, and the return policy. This code was written for this
  submission and is not a fork of another repository.
* **Third-party components used as-is:** `BAAI/bge-small-en-v1.5` (embeddings, MIT), FastAPI,
  uvicorn, sentence-transformers, SQLite, and the OpenAI Python SDK. No benchmark data, gold
  answer, or evaluation artefact is bundled or consulted.
* **Deliberately excluded:** the strongest configuration in the paper above writes each memory into
  a LoRA adapter on a local 9B model and elicits the recall statement from those weights. That
  variant is **not** submitted and **not** implemented here, because the challenge requires the
  model used during Add and Search to be `gpt-4o-mini`. Only the compliant, frozen pipeline is in
  this repository.
* **Integrity:** no hard-coded answers, no benchmark leakage, no prompt injection, no cross-`user_id`
  retrieval, no manual intervention during evaluation. Retrieval scope is `user_id` and only
  `user_id`; `session_id` is stored for provenance and never used to filter.

## AI assistance disclosure

This repository was written with AI assistance (Claude, Anthropic) under the author's direction:
the author set the design, the prompts' intent, the compliance constraints, and reviewed all code.
The underlying research results cited above were produced by the author's own experiments; the AI
assistant participated in analysis, drafting, and implementation.

## License

MIT — see [LICENSE](LICENSE).
