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
| `AMI_LLM_MAX_TOKENS_EXTRACT` / `AMI_LLM_MAX_TOKENS_QUERY` | `1200` / `200` | completion caps; raise only when developing against a reasoning model |
| `AMI_RECALL_WEIGHT` | `0.5` | weight of the user-voice recall-question channel in the fused score |
| `AMI_RETURN_LIMIT` | `100` | maximum memories returned (never more than `top_k`) |
| `AMI_RAW_FIRST` | `1` | order the returned set verbatim turns first, extracted facts second; changes order, never membership |
| `AMI_RETURN_CHAR_BUDGET` | `400000` | character budget for one response; large enough never to truncate `AMI_RETURN_LIMIT` silently |
| `AMI_AGENTIC_SEARCH` | `0` | after retrieval, gpt-4o-mini reflects on gaps and may fire a second recall question. Off by default — measured at zero end-to-end gain when the full `top_k` is returned, at the cost of one extra LLM call per search |
| `AMI_EMBED_MODEL` | `BAAI/bge-small-en-v1.5` | embedding model, runs locally on CPU |
| `AMI_DB_PATH` | `/data/memory.sqlite3` | SQLite file |
| `AMI_CACHE_MAX_ITEMS` | `1000000` | upper bound on rows in the per-user vector cache, across all users, evicted least-recently-used. The cache is a read-through of SQLite, so eviction costs a reload and never a result. A dataset carrying one `user_id` per question would otherwise grow the process until it is killed. One row is ~1.5 kB of vector plus ~0.5 kB of Python object, so the default is ~2 GB; raise it on a larger host, and note that where the host has zram this is close to free |
| `AMI_AUTH_SCHEME` | `bearer` | `none` \| `bearer` \| `token` \| `x-api-key`. Any of the three schemes carrying the right secret is accepted. The service **refuses to start** if a scheme is set and `AMI_AUTH_TOKEN` is empty or a placeholder — use `none` deliberately for local testing. |
| `AMI_AUTH_TOKEN` | *(empty)* | expected secret when a scheme is set. This is the Memory System Key shared with the platform. |
| `AMI_BIND` / `AMI_PORT` | `127.0.0.1` / `8000` | host interface and port (compose). Publish deliberately. |
| `AMI_CONTAINER` / `AMI_IMAGE` / `AMI_VOLUME` | `activememoryindex` / `activememoryindex:latest` / `ami-data` | names used by compose; override all three to run a second copy on one host |
| `AMI_EDGE_NETWORK` | `vip-gateway_default` | external Docker network for the optional tunnel override — site-specific |
| `AMI_LLM_RETRIES` | `1` | retries per provider call |
| `AMI_LLM_MAX_FACTS` | `24` | cap on extracted facts per Add chunk (a cap, not a target) |
| `AMI_EMBED_DEVICE` / `AMI_EMBED_BATCH` | `cpu` / `64` | embedding device and batch size |
| `AMI_EMBED_THREADS` | `1` | intra-op threads for the embedder. One is right when the server is already serving concurrently — 16 to 64 requests each opening an OpenMP team oversubscribes the machine and the workers wait in barriers. Measured on 8 cores: Add-shaped calls 3.61/s at 8 threads against 4.53/s at 1; Search-shaped 70.4/s against 101.8/s. `0` leaves torch's heuristic alone |
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
4. The selected memories are ordered **verbatim turns first, extracted facts second**, each block
   keeping its relevance order (`AMI_RAW_FIRST`, on by default). This changes the order of the
   returned set and never its membership. See "Why the order of the returned set is the largest
   lever we found" below.
5. Optionally (`AMI_AGENTIC_SEARCH=1`, **off by default**), `gpt-4o-mini` inspects the top results
   and may fire a second targeted recall question if evidence is missing; results from both rounds
   are merged and deduplicated. See "Why the agentic round is off" below.

Search returns memory evidence only. It never produces or disguises a final answer, and never
reads outside the requested `user_id`.

**Why the user-voice question.** This is [HyDE](https://arxiv.org/abs/2212.10496) (Gao, Ma, Lin
and Callan, 2022) with a first-person recall question as the hypothesis. The fusion is HyDE's own:
because `(1-w)·(q·d) + w·(r·d) = ((1-w)·q + w·r)·d`, scoring against a weighted blend of the two
similarities *is* averaging the two embeddings, which at `w=0.5` is HyDE's N=1 case and the default
in mainstream RAG libraries. Only the prompt is ours — HyDE generates a hypothetical *answer*, we
generate a first-person *recall question*, because the corpus is a first-person chat log. The
sibling for sparse retrieval is [query2doc](https://arxiv.org/abs/2303.07678). In our own per-fact
audits, matching the *register* of the store
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

**Why the order of the returned set is the largest lever we found.** Having fixed *what* to
return, we asked what else could matter, expecting the answer to be better retrieval. It was not.
Ordering the same returned memories verbatim-turns-first is worth more than every retrieval change
we tried, combined. Measured over all ten LoCoMo conversations (n=1540), three independent
answer+judge runs per arm so that the spread within a row is reader and judge noise alone:

| ordering / ranking of the returned 100 | accuracy | vs dense, paired |
|---|---|---|
| diversity cap (≤2 memories per source chunk) | .5799 | net −5, p = 0.77 |
| extracted facts first | .5828 | net −7, p = 0.64 |
| relevance order (what a dense ranker gives) | .5887 | — |
| hybrid BM25 + dense, reciprocal rank fusion | .6067 | net +27, p = 0.094 |
| **verbatim turns first** | **.6333** | **net +70, p = 4×10⁻⁶** |

A verbatim turn is the primary source; an extracted fact is a lossy paraphrase of it, and the
reader attends to the head of the context. Three competing explanations were tested and ruled out:

* It is **not** that grouping by kind spares the reader from switching register — putting *facts*
  first groups just as tidily and gains nothing (net −7).
* It is **not** head-and-tail attention — splitting the verbatim turns across head *and* tail is
  indistinguishable from putting them all at the head (net +1, p = 1.000). At ~3k tokens there is
  no lost-in-the-middle headroom to exploit.
* It is **not** context volume — the winning arm returns exactly as many characters as the
  baseline (12,366), and an arm returning 18% more gained nothing for it.

A lexical BM25 channel (SQLite FTS5, fused by reciprocal rank) was built, measured and **removed**.
It was worth +1.8pt on its own but is dominated: confining it to verbatim turns reached .6390,
inside the run-to-run spread of the ordering change alone (.6273–.6396), so the index, the query
language and the fusion rule bought nothing an `ORDER BY` does not. The negative result is kept in
`bench/results/ordering_ab_all10.txt`.

**Where this sits in the literature.** We are not claiming the ordering axis is untouched.
[COMBO](https://arxiv.org/abs/2310.14393) (Zhang et al., EMNLP 2023) fixes the arrangement of
generated and retrieved passages as a deliberate, ablated design choice — and puts the *generated*
passage first, the opposite of what we measure, for a fine-tuned reader resolving conflicts.
[Tan et al.](https://arxiv.org/abs/2401.11911) (ACL 2024, appendix B.3) vary generated-first
against retrieved-first on a frozen reader. [Fidelity Before
Structure](https://arxiv.org/abs/2601.00821) already establishes, on LoCoMo, that verbatim chunks
beat extracted artifacts and that indexing both is *accuracy-neutral* against verbatim alone
(42.5 vs 43.9, McNemar p=0.39) — with a single undifferentiated context slot, so ordering was never
a variable. Our result qualifies that: the artifacts are accuracy-neutral **at their ordering**, and
worth +4.5pt at ours. What we have not found stated anywhere is that a membership-identical,
character-identical reorder by *provenance* moves accuracy at all; deployed systems pick an order
silently and disagree with each other about which one.

**Why we do not return coarser memories, although it scores much better.** The contract caps the
*count* of returned memories, not their size. Answering with the 20-message source chunks behind the
top-100 ranked memories — the standard small-to-big pattern — scores **.711** against the .6333 we
ship. We did not take it. Holding characters constant at the baseline's budget, the coarse unit
*loses* 6.1pt (.572), because 4.9 whole chunks span 4.9 source chunks where 100 fragments span 26.2;
every point it gains comes from the 5.4x more context it is allowed to carry, not from the unit. On
accuracy per thousand tokens it is five times worse than the shipped arm and barely better than
sending the entire conversation. And the limit is degenerate: one LoCoMo conversation is ~40 chunks,
so "return every parent" is the whole transcript as 40 ≤ 100 memories. The full audit, including the
control that could not be built and why, is in `bench/results/granularity_audit.txt`. We suggest the
organisers cap returned tokens as well as returned items — TREC QA tightened answer strings from 250
to 50 bytes for the same reason.

**A warning about the retrieval metric.** Across these arms, retrieval coverage is not a weak proxy
for accuracy — it is inverted. That retrieval metrics can go negatively correlated with end-to-end
quality is itself reported by [Song et al.](https://arxiv.org/abs/2601.17532) (2026), and
[Samuel et al.](https://arxiv.org/abs/2603.08819) (ICTIR 2026) report the opposite for coverage at
the system level; we record what we measured on these arms rather than adjudicating that. The arm with the best coverage at k=100 (.961) had the worst accuracy
(.5625); the winning arm has the worst coverage at k=20 (.609) of anything we ran. Every arm returns
the same evidence, so a metric that scores *whether the evidence was returned* is structurally blind
to all of this. We had pre-registered a coverage threshold as the gate for changing the service, and
it would have selected the wrong configuration.

These are numbers from a local harness with a local judge, not the platform's. Re-running an
identical configuration moves accuracy by ~0.2pp and flips ~4% of questions, so the ordering of
configurations is what to rely on, not the third decimal. Aggregates are committed in
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
tests/           write-path guards, write-path concurrency, returned-set ordering
                 (plain scripts, not pytest)
bench/           offline LoCoMo harness used to set the retrieval knobs; not in the image
bench/results/   committed aggregates behind every number quoted in this file
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
