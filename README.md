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

# Or standalone docker run. This path does NOT read .env — pass the file
# explicitly, or export the variables first:
docker build -t activememoryindex .
docker run -d --name ami -p 127.0.0.1:8000:8000 -v ami-data:/data \
  --env-file .env \
  activememoryindex
```

Check that it actually came up — `docker compose up -d` exits 0 even when the
container then refuses to start:

```bash
docker compose ps
docker compose logs --tail 20
```

The first build downloads PyTorch and the embedding weights: about 1 minute on a
fast link, and a 2.5 GB image. Startup after that is ~4 seconds, with no network
needed for retrieval.

Both paths bind loopback only. Publish deliberately — set `AMI_BIND=0.0.0.0`
(compose) or change the port mapping — and only once `AMI_AUTH_TOKEN` is a real
secret.

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
python3 scripts/smoke_contract.py http://127.0.0.1:8000
```

It reads `.env` for the auth scheme and token, so it works against an
authenticated instance without extra flags. Run from elsewhere, or against a
remote deployment, pass the secret in the environment:

```bash
AMI_AUTH_TOKEN=<your token> python3 scripts/smoke_contract.py https://your-host
```

It needs **no** OpenAI key: the full suite passes in degraded mode, which is the
cheapest way to verify a checkout.

**Publishing.** Both startup paths bind loopback. To expose the service, either
set `AMI_BIND=0.0.0.0` and put HTTPS in front of it, or route it through an
existing tunnel/proxy on a shared Docker network with the optional override:

```bash
AMI_EDGE_NETWORK=<your proxy's network> \
  docker compose -f docker-compose.yml -f docker-compose.edge.yml up -d
```

**Cost.** Each Add chunk costs one `gpt-4o-mini` call (up to ~1200 completion
tokens), and each Search one more; `AMI_AGENTIC_SEARCH=1` adds a second Search
call. Retrieval itself — embedding and ranking — is local and free, and degraded
mode costs nothing at all.

**Unauthenticated surface:** `/health` (liveness only; store counts and LLM
counters require the same secret as Search) and FastAPI's generated `/docs`,
`/redoc` and `/openapi.json`, which describe the same contract this README does.

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
| `AMI_LLM_CONCURRENCY` | `40` | cap on simultaneous provider calls; matches the server threadpool, so the gate adds no queueing of its own |
| `AMI_LLM_TIMEOUT` | `25` | seconds per provider call. With `AMI_LLM_RETRIES` (`1`), one Add stays well under a typical 100 s CDN cut-off |
| `AMI_LLM_MAX_TOKENS_EXTRACT` / `_QUERY` | `1200` / `200` | completion caps; raise only when developing against a reasoning model |
| `AMI_RECALL_WEIGHT` | `0.5` | weight of the user-voice recall-question channel in the fused score |
| `AMI_RETURN_LIMIT` | `100` | maximum memories returned (never more than `top_k`) |
| `AMI_RETURN_CHAR_BUDGET` | `400000` | character budget for one response; large enough never to truncate `AMI_RETURN_LIMIT` silently |
| `AMI_AGENTIC_SEARCH` | `0` | after retrieval, gpt-4o-mini reflects on gaps and may fire a second recall question. Off by default — measured at zero end-to-end gain when the full `top_k` is returned, at the cost of one extra LLM call per search |
| `AMI_EMBED_MODEL` | `BAAI/bge-small-en-v1.5` | embedding model, runs locally on CPU |
| `AMI_DB_PATH` | `/data/memory.sqlite3` | SQLite file |
| `AMI_AUTH_SCHEME` | `bearer` | `none` \| `bearer` \| `token` \| `x-api-key`. Any of the three schemes carrying the right secret is accepted. The service **refuses to start** if a scheme is set and `AMI_AUTH_TOKEN` is empty or a placeholder — use `none` deliberately for local testing. |
| `AMI_AUTH_TOKEN` | *(empty)* | expected secret when a scheme is set. This is the Memory System Key shared with the platform. |
| `AMI_BIND` / `AMI_PORT` | `127.0.0.1` / `8000` | host interface and port (compose). Publish deliberately. |
| `AMI_CONTAINER` / `AMI_IMAGE` / `AMI_VOLUME` | `activememoryindex` / `activememoryindex:latest` / `ami-data` | names used by compose; override all three to run a second copy on one host |
| `AMI_EDGE_NETWORK` | `vip-gateway_default` | external Docker network for the optional tunnel override — site-specific |
| `AMI_LLM_RETRIES` | `1` | retries per provider call |
| `AMI_LLM_MAX_FACTS` | `24` | cap on extracted facts per Add chunk (a cap, not a target) |
| `AMI_EMBED_DEVICE` / `AMI_EMBED_BATCH` | `cpu` / `64` | embedding device and batch size |
| `AMI_EXTRACT` / `AMI_RECALL_QUERY` | `1` / `1` | set either to `0` to disable that LLM channel |
| `AMI_LLM_DISABLE_THINKING` | `0` | development only: suppress reasoning output from a local reasoning model |

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
4. Optionally (`AMI_AGENTIC_SEARCH=1`, **off by default**), `gpt-4o-mini` inspects the top results
   and may fire a second targeted recall question if evidence is missing; results from both rounds
   are merged and deduplicated. See "Why the agentic round is off" below.

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
| accuracy (n=529) | .219 | .353 | .427 | .482 | .554 | **.597** |
| accuracy given gold retrieved | .461 | .493 | .551 | .578 | .603 | **.626** |
| evidence actually retrieved | .410 | .641 | .741 | .815 | .885 | **.940** |

Returning 100 wins every pairwise comparison — against p40 by 34:11 flipped questions, against p1
by 213:13 — and the choice was then confirmed on a held-out subset never used for tuning (n=464,
accuracy .584). The earlier audits used a 9B reader; `gpt-4o-mini` evidently uses extra context
rather than drowning in it. The knob stays exposed because the right value is a property of the
reader, not of the memory system — `AMI_RETURN_CHAR_BUDGET` must be raised alongside it, or the
character budget silently truncates the list.

These are single-run numbers from a local harness with a local judge, not the platform's. Two
independent re-runs of the same configuration differed by one question in 529 (~0.2 pp), so the
monotone ordering is what to rely on, not the third decimal. Aggregates are committed in
`bench/results/`; `bench/README.md` has the commands that regenerate them.

## Tests

```bash
python3 tests/test_parse_facts.py     # write-path guards; standard library only
docker run --rm -v "$PWD/tests:/srv/tests:ro" -w /srv activememoryindex \
  python3 tests/test_concurrency.py   # needs numpy + app deps, so run it in the image
```

`test_parse_facts.py` pins the two ways a bad LLM reply could poison the store.
`test_concurrency.py` pins the write path against the platform's retry policy:
overlapping retries of one `request_id`, and a `request_id` reused by a second
user. Both are plain scripts with exit codes, not pytest.

## Repository layout

```
app/config.py    environment configuration
app/main.py      FastAPI service: /add, /search, /health
app/llm.py       the single LLM (gpt-4o-mini): fact extraction + recall-question rewriting
app/embed.py     bge-small-en-v1.5 embeddings
app/store.py     SQLite store with a per-user in-process vector cache
scripts/         contract smoke test, prompt calibration
tests/           write-path guards and write-path concurrency (plain scripts, not pytest)
bench/           offline LoCoMo harness used to set the retrieval knobs; not in the image
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
  uvicorn, sentence-transformers, SQLite, and the OpenAI Python SDK. The offline harness in
  `bench/` additionally downloads two public repositories at run time — LoCoMo
  (<https://github.com/snap-research/locomo>, `locomo10.json`) for conversations and gold
  answers, and the platform's own public evaluation code
  (<https://github.com/AML-memory/agent-memory-leaderboard>) whose answer and judge prompts it
  imports verbatim. Neither is vendored into this repository or into the image.
* **The service never sees benchmark data.** No dataset, gold answer, or evaluation artefact is
  bundled in the image or consulted by `/add` or `/search`. `bench/` does read gold answers, but
  it runs offline, on the author's machine, against public data, and is not part of the
  deployed service (the Dockerfile copies only `app/` and `scripts/`).
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
