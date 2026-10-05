# ActiveMemoryIndex

An Add/Search memory system for the [Agent Memory Leaderboard](https://agentmemories.ai) (Agent
Memory Challenge 2026, Academic Methods track, Textual Memory).

**Release candidate `academic-v4-20261005-rc3`** (built on the `academic-v4-20261001` release):
`text-embedding-v4` (1024 dimensions, separate credentials and endpoint) for embeddings and
`gpt-4o-mini` as the only LLM, for fact extraction, recall questions and the explicit-update
mechanism below. BGE (`bge-small-en-v1.5`) is historical local research only and is not part
of the academic profile. See [RELEASE.md](RELEASE.md) for scope, validation and status.

rc3 adds, on top of the 20261001 release, three things that are switched on by configuration
and are all off in code by default: an opt-in diagnostic request log, the **explicit-update
mechanism** (when a user explicitly replaces or corrects a value, the earlier value can be
left out of what Search returns; see "Explicit updates" below, which is also the declaration
of generative-model use in evidence organisation that competition FAQ Q18 asks for), and an
**admission valve** that answers overload and transient upstream failures with 429/503 plus
`Retry-After` instead of a 500.

The research numbers below come from historical BGE embeddings and local answer/judge
runs. They are not official leaderboard scores and do not establish a v4 quality gain.
The v4 evidence establishes integration and contract behavior, and a small v4 check of the
explicit-update mechanism. No benchmark data or gold answers are bundled with, or consulted
by, the service. Platform Smokes have been run (three, on 2026-10-04 and 2026-10-05); the
official Full has **not** started.

**One sentence:** memories are stored twice — as verbatim timestamped turns and as atomic
first-person facts — and retrieval asks the log the question *the user themselves would ask*
("Did I tell you about …?"), because matching the log's own first-person register is worth more
at retrieval time than any amount of query rewriting in the question's register.

---

## Quick start (Docker, self-hosted)

```bash
git clone https://github.com/linxuhao/ActiveMemoryIndex.git
cd ActiveMemoryIndex
git checkout academic-v4-20261005-rc3   # the rc3 release tag
cp .env.academic.example .env.academic
# Edit .env.academic: OPENAI_API_KEY, AMI_EMBED_API_KEY, AMI_AUTH_TOKEN,
# and AMI_EMBED_BASE_URL for the embedding key's region/workspace.
AMI_ENV_FILE=.env.academic docker compose --env-file .env.academic -p ami-academic up -d --build
```

The academic profile uses a separate container, loopback port `8012`, named volume
`ami-academic-v4-data`, and database `/data/memory-v4.sqlite3`. Start with a new database:
BGE vectors cannot be reused for v4. The store records backend/model/dimensions/endpoint
and preprocessing identity and rejects incompatible or unlabelled populated remote stores.

Use the same environment selection for subsequent Compose commands:

```bash
AMI_ENV_FILE=.env.academic docker compose --env-file .env.academic -p ami-academic ps
AMI_ENV_FILE=.env.academic docker compose --env-file .env.academic -p ami-academic logs --tail 20
```

`OPENAI_API_KEY` supplies the `gpt-4o-mini` components; `AMI_EMBED_API_KEY` supplies the
separate embedding API. The template's Singapore URL is an example: set the endpoint
explicitly for your region and, where required, your workspace. The tested deployment
uses the user-confirmed Beijing workspace endpoint. Credentials are never committed.

The Docker image includes PyTorch and cached BGE weights for optional historical research
(the academic profile never loads them); a clean build downloads dependencies and is about
2.5 GB. The v4 pipeline needs outbound
network access to both providers at startup and during Add/Search, with paid API usage.
Embedding failures fail startup or the request explicitly; they cannot use the LLM's
raw-only fallback, silently change model, or commit missing vectors.

The service binds loopback by default. Configure bearer authentication and publish through
a HTTPS proxy/tunnel before platform evaluation. `/health` is unauthenticated; Add and
Search require `Authorization: Bearer <AMI_AUTH_TOKEN>`.

| entrypoint | method | purpose |
|---|---|---|
| `/add` | POST | synchronous write; returns 200 only after the memories are persisted and searchable |
| `/search` | POST | relevance-ordered memories for one question, scoped to `user_id` |
| `/health` | GET | unauthenticated liveness check, returns 2xx |

Verify a running instance against the contract after securely exporting its
`AMI_AUTH_TOKEN` (and `AMI_AUTH_SCHEME=bearer`) into the shell environment:

```bash
python3 scripts/smoke_contract.py http://127.0.0.1:8012
```

This script loads `.env`, not `.env.academic`; supply the academic instance's auth values
through the environment. It writes synthetic memories and exercises the configured
service. Against v4 it incurs embedding calls, and with the full profile it also incurs
LLM calls. Local contract checks are separate from the official platform Smoke.

**Publishing.** Route the configured candidate through a HTTPS proxy or existing tunnel.
For a proxy on a shared Docker network, select the actual network and retain both
academic environment selections:

```bash
AMI_EDGE_NETWORK=<your-proxy-network> AMI_ENV_FILE=.env.academic \
  docker compose --env-file .env.academic -p ami-academic up -d
```

Check the network exists and that the proxy targets the academic container's port `8000`.
A network name with no proxy attached can leave the service unreachable even when healthy.

**Cost.** A new Add chunk uses a `gpt-4o-mini` extraction call and embeds its raw turns
and facts with `text-embedding-v4`. With `AMI_UPDATE_DETECT=1` it also makes one stage-1
call (stage 2 only when stage 1 accepted an explicit replacement or correction), run beside
the extraction call. Search uses a recall-question call and embeds the query and recall
question; with `AMI_UPDATE_WITHHOLD=1` a Search whose result would lose a withheld item adds
one router call (cached per query), and the first Search after an update may add verifier
calls (their verdicts are stored, so each pair is judged once). Embedding batching,
long-text segmentation and retries affect API request counts and charges. Ranking over
stored vectors remains local. Experimental agentic/DCI calls are disabled in the academic
release. No cost or throughput projection for an official Full has been established by the
small synthetic checks; the capacity measurements that exist (fake and real upstream, BEAM
shapes) are in `bench/results/beam_capacity_20261004.md` on branch
`codex/beam-capacity-20261004`, and the real-provider throughput of one Add is dominated by
the embedding gate.

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
| `AMI_WINDOW_RADIUS` | `1` | return each selected verbatim turn with the turns either side of it from the same Add chunk. A single message often is not self-contained — the antecedent, the reply, and the session date are in the neighbours. Neighbours take slots from the same `top_k`, so this trades breadth of sources for local context rather than returning more text. `.6333` → `.6802` on LoCoMo (n=1540, paired p<0.0001); radius 1, 2 and 3 were indistinguishable, so 1 is shipped for keeping the most breadth per slot. `0` disables it |
| `AMI_RAW_FIRST` | `1` | order the returned set verbatim turns first, extracted facts second; changes order, never membership |
| `AMI_RETURN_CHAR_BUDGET` | `400000` | character budget for one response; large enough never to truncate `AMI_RETURN_LIMIT` silently |
| `AMI_AGENTIC_SEARCH` | `0` | after retrieval, gpt-4o-mini reflects on gaps and may fire a second recall question. Off by default — measured at zero end-to-end gain when the full `top_k` is returned, at the cost of one extra LLM call per search |
| `AMI_EMBED_BACKEND` | `bge` | `openai` selects the remote academic adapter; the academic profile explicitly sets it |
| `AMI_EMBED_MODEL` | backend-dependent | academic profile: `text-embedding-v4`; optional local research: `BAAI/bge-small-en-v1.5` |
| `AMI_EMBED_API_KEY` | *(empty)* | separate embedding credential; `DASHSCOPE_API_KEY` is an alternative. Never inherited from the LLM key |
| `AMI_EMBED_BASE_URL` | *(empty)* | explicit OpenAI-compatible embedding endpoint for the credential's region/workspace |
| `AMI_EMBED_DIMENSIONS` | `1024` | vector dimensions for the remote model; fixed to 1024 in the academic profile |
| `AMI_EMBED_TIMEOUT` / `AMI_EMBED_RETRIES` / `AMI_EMBED_CONCURRENCY` | `25` / `1` / `8` | adapter defaults; academic template sets timeout 20 s, retries 1, concurrency 4 |
| `AMI_DB_PATH` | `/data/memory.sqlite3` | SQLite file |
| `AMI_CACHE_MAX_ITEMS` | `1000000` | upper bound on cached rows across users, evicted least-recently-used and reloaded from SQLite. A v4 float32 vector alone uses 4096 bytes per row, before text, objects and temporary arrays; size this cap for the host. Full capacity has not been established by the small integration checks |
| `AMI_AUTH_SCHEME` | `bearer` | `none` \| `bearer` \| `token` \| `x-api-key`. Any of the three schemes carrying the right secret is accepted. The service **refuses to start** if a scheme is set and `AMI_AUTH_TOKEN` is empty or a placeholder — use `none` deliberately for local testing. |
| `AMI_AUTH_TOKEN` | *(empty)* | expected secret when a scheme is set. This is the Memory System Key shared with the platform. |
| `AMI_BIND` / `AMI_PORT` | `127.0.0.1` / `8000` | host interface and port (compose). Publish deliberately. |
| `AMI_CONTAINER` / `AMI_IMAGE` / `AMI_VOLUME` | `activememoryindex` / `activememoryindex:latest` / `ami-data` | names used by compose; override all three to run a second copy on one host |
| `AMI_EDGE_NETWORK` | `ami_edge_unused` | the Docker network your tunnel/proxy connector is on, read by the base compose file (there is no override file). Site-specific. Unset → compose creates the throwaway default; a name matching nothing is created empty, not refused |
| `AMI_LLM_RETRIES` | `1` | retries per provider call |
| `AMI_UPDATE_DETECT` | `0` | Add: detect explicit updates (stage 1 intent labelling, stage 2 extraction) and store them as records. See "Explicit updates" |
| `AMI_UPDATE_RENDER` | `0` | Add, needs `AMI_UPDATE_DETECT`: also store each absolute update's current-value sentence as an extra memory (language-checked) |
| `AMI_UPDATE_WITHHOLD` | `0` | Search: leave out earlier memories that state a value an explicit update replaced; membership only, nothing is rewritten |
| `AMI_UPDATE_VERSION` | `7` | explicit-update design version; `7` is the release. Versions 1-6 exist only to reproduce research results |
| `AMI_UPDATE_CANDIDATES` | `20` | earlier memories handed to the verifier per update |
| `AMI_ADD_MAX_INFLIGHT` / `AMI_SEARCH_MAX_INFLIGHT` | `0` / `0` | admission valve: at most this many `/add` (`/search`) run at once; `0` = off. See "Admission valve" |
| `AMI_ADMISSION_WAIT` | `30` | seconds a request may wait for a slot before it is answered 429 |
| `AMI_RETRY_AFTER` | `10` | `Retry-After` seconds on a valve 429 and on an upstream 503 |
| `AMI_EXTRACT_REQUIRED` | `0` | `1`: an extraction call that failed upstream (rate limit, timeout, connection, 5xx) fails the Add with 429/503 before anything is stored, instead of storing the turns without facts |
| `AMI_REQUEST_LOG` | *(empty)* | path of a JSON-lines diagnostic log: every Search's query, options, undocumented fields and returned ids; every Add's message metadata (no content). Off when empty; it is evaluation data, keep it beside the database |
| `AMI_LLM_MAX_FACTS` | `24` | cap on extracted facts per Add chunk (a cap, not a target) |
| `AMI_EMBED_DEVICE` / `AMI_EMBED_BATCH` | `cpu` / backend-dependent | device applies to local BGE; batch defaults to 64 for BGE and 10 for remote v4 (academic profile: 10) |
| `AMI_EMBED_THREADS` | `1` | intra-op threads for the embedder. One is right when the server is already serving concurrently — 16 to 64 requests each opening an OpenMP team oversubscribes the machine and the workers wait in barriers. Measured on 8 cores: Add-shaped calls 3.61/s at 8 threads against 4.53/s at 1; Search-shaped 70.4/s against 101.8/s. `0` leaves torch's heuristic alone |
| `AMI_EXTRACT` / `AMI_RECALL_QUERY` | `1` / `1` | set either to `0` to disable that LLM channel |
| `AMI_LLM_DISABLE_THINKING` | `0` | development only: suppress reasoning output from a local reasoning model |

**LLM fallback and research mode.** Missing or failed LLM calls can fall back to raw
turns/original-query retrieval, but this is not a complete academic profile validation.
Remote embedding credentials and successful embeddings remain required; embedding failures
fail the operation. For historical local research, `.env.example` selects the default BGE
backend with a separate database; cached BGE retrieval can operate without provider access.
All other experimental mechanisms stay off in `.env.academic.example`; only the explicit-update flags and the valve are set.

## Method

### Write path (`/add`)

1. Every message is stored **verbatim**, one memory per message, prefixed with its own UTC
   timestamp (`[2023-05-20 14:00] I: …`). Nothing is discarded at write time.
2. The chunk is additionally passed to `gpt-4o-mini`, which extracts **atomic, self-contained,
   first-person facts** with the same timestamp prefix. The extraction prompt forbids inference,
   pronouns without referents, and summarisation, and requires that names, numbers and dates
   survive verbatim.
3. Both kinds are embedded with `text-embedding-v4` (1024 dimensions) and committed to SQLite before the response is
   written, so the memories are searchable the moment Add returns. Re-sending a `request_id` is
   idempotent and scoped to the user. Long input is split losslessly into at most 2048 UTF8-byte
   segments for embedding; normalized vectors are pooled by byte weight. The stored source
   text stays whole. This segmentation is not a formal guarantee of provider token limits.

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

## Explicit updates (opt-in; on in the rc3 release profile)

**What it does.** When a user *explicitly* says that an earlier value is replaced or was
wrong ("Update: my gym time is now 6 pm", "correction: the dog's name is Biscuit"), the service
records the update at Add time and, at Search time, leaves the earlier, replaced items out of
the returned set, so the reader is not shown two conflicting values. It also stores one extra
memory stating the current value. Nothing else changes: no memory text is edited, relative
changes ("one more coin") and history or date questions are left untouched, and only the same
`user_id`'s own history is ever used.

**Model.** `gpt-4o-mini`, the same and only LLM as the rest of the service. Its output is
never returned as an answer. Five prompts (all in `app/llm.py`):

| prompt | when | what it is for |
|---|---|---|
| stage 1, intent classification (`UPDATE_INTENT_SYSTEM`) | Add, beside extraction, only if the chunk has a user turn | labels the user's value-bearing statements (explicit replacement, correction, restatement, new info, relative change, plan, history) and copies a quote. Code accepts only replacement/correction labels whose quote appears verbatim, after whitespace normalisation, in a user turn |
| stage 2, update extraction (`UPDATE_EXTRACT5_SYSTEM`) | Add, only for statements stage 1 accepted | extracts subject, attribute, new value, old value (only if the turn states it), `subject_is_user`, `relative`, and one present-tense sentence stating the current value in the language of the turn. Code drops an entry whose new value is not in the user turn |
| render | Add, `AMI_UPDATE_RENDER=1` | the stage-2 current-value sentence is stored as an extra memory beside the extracted facts, only for absolute (not relative) updates and only if it is in the same language as the user's turn. It is derived from the user's own update turn at write time and cannot depend on any later question |
| search-time verifier (`UPDATE_VERIFY3_SYSTEM`) | Search, first time an (update, earlier memory) pair is needed | given the update and candidate earlier memories (earlier Adds only, mentioning the subject, not mentioning the new value), quotes the value each states and says whether it is DIFFERENT from the new one. Code accepts a verdict only if the quote is in the memory. Verdicts are stored, so each pair is judged once; the verifier never sees the question |
| search-time router (`QUESTION_SCOPE2_SYSTEM`) | Search, only when a withheld item is in the list the search would return | reads the question and returns two booleans: does it need the past value (history, change, first/initial value), is it time-scoped. If either is true, nothing is withheld. Cached per (query, options). English and CJK date patterns remain as a pre-filter that can only add protection |

**Switches.** `AMI_UPDATE_DETECT` (stage 1 and 2 at Add), `AMI_UPDATE_RENDER` (store the
current-value sentence), `AMI_UPDATE_WITHHOLD` (verifier, router and withholding at Search),
`AMI_UPDATE_VERSION=7`. All three flags default to 0 in code; the rc3 release profile
(`.env.academic.example`) turns them on. With them off the service behaves as the 20261001
release. A store created without them is compatible: the update tables are added on start.

**Evidence organisation only.** The question selects and withholds evidence; it never
generates text that is returned. The only model outputs that reach a Search response are
stored memories: the user's verbatim turns, extracted facts, and the rendered current-value
sentence that was written at Add time from the user's own words. The router sees the question
but returns two booleans; the verifier sees no question. Any failure of a model call (timeout,
rate limit, invalid JSON) at either stage degrades to "no update detected" at Add, and to
"withhold nothing" at Search; an update call never fails an Add or a Search.

**Evidence** (research branch `research/explicit-update-20261004`, all numbers measured on
public data; reports not copied here):

* MQuAKE-Remastered CF-3k, 200 cases, 400 edit/multi-hop questions, BGE research stores,
  `gpt-4o-mini` reader and judge, 2 to 4 replicates: render+withhold beats the baseline by
  **+65 to +70 correct of 400** (rounds 3 and 4 +70.00; the shipped version 7 +65.00). `bench/results/explicit_update_20261004.md`, `explicit_update_r2_20261004.md`,
  `explicit_update_r3_20261005.md`, `explicit_update_r4_20261005.md`,
  `explicit_update_r5_20261005.md`.
* Check on the real v4 stack (25 fresh MQuAKE cases, 75 questions): **+13.5 of 75**
  (15 wins, 0 losses, p = 0.0001). `explicit_update_r5_20261005.md`, section RC2.
* Guards, version 7 (all non-negative): LongMemEval knowledge-update, 78 questions, +0.25
  (1 win, 0 losses); LoCoMo, 1540 questions, 0 update records and no change to any list;
  0 conversational items withheld. English history probes: 0 of 24 broken; router held-out
  sets, recall 0.95 to 1.00 and false protection 0.00 to 0.05 in English, Chinese and Spanish.
* Earlier rounds, which failed their registered gates on false withholding (round 1: 131 of
  166 withheld guard items false) and were revised, are kept in the same reports.

These gains come from synthetic update streams in which updates are explicit. In the first
round the single-hop gain was small (the reader already preferred the explicit update on
74.5% of edit questions), the multi-hop gain carried the result, and transfer to the
platform's datasets is unknown. No official score is claimed.

## Admission valve and upstream-error mapping

The platform drives Add at 16 to 64 concurrent requests and Search at 16 to 256, while the
upstream gates (`AMI_LLM_CONCURRENCY`, `AMI_EMBED_CONCURRENCY`) admit far fewer. Without a
bound, the excess queues inside the process and, past the ~100 s edge cut, the caller sees a
524 for an Add that is still running.

* `AMI_ADD_MAX_INFLIGHT` / `AMI_SEARCH_MAX_INFLIGHT` (0 = off) bound concurrent `/add` and
  `/search` in a pure-ASGI middleware. A request that cannot get a slot within
  `AMI_ADMISSION_WAIT` seconds (first come, first served) is answered **429 with
  `Retry-After: AMI_RETRY_AFTER`** *before* authentication, LLM calls, embedding or any write,
  so a rejected Add persisted nothing and its retry is an ordinary first attempt. Waiting
  holds no worker thread.
* A transient embedding failure is no longer an unhandled 500: a provider rate limit becomes
  429 carrying the provider's `Retry-After` (capped at 60 s); a timeout, connection error or
  5xx becomes 503 + `Retry-After`. This is raised before `store.add`, so nothing is persisted
  (this fixed an Add that returned 500 on an upstream `httpx.ReadTimeout`). Non-transient errors
  stay 500.
* Extraction is best-effort by default: a failed `gpt-4o-mini` call stores the verbatim turns
  without facts and Add returns 200. `AMI_EXTRACT_REQUIRED=1` maps it as above instead; the
  trade is that a long provider outage then exhausts the platform's retry budget rather than
  degrading. Off by default.
* Explicit-update calls are optional and are never mapped: a timeout there skips update
  detection for that chunk (Add still returns 200), and a failed router or verifier call at
  Search withholds nothing.
* Valve and mapping counters (`valve_*`) are in the authenticated `/health`.

**Recommended settings for the Full:** `AMI_ADD_MAX_INFLIGHT=16`, `AMI_ADMISSION_WAIT=45`,
`AMI_RETRY_AFTER=10`, `AMI_SEARCH_MAX_INFLIGHT=0` (Search valve off), and start the platform
job with Add concurrency 16 and Search concurrency 16. At platform concurrency 16 the valve
never rejects (a safety net that bounds attempts if the provider slows or concurrency rises).
The Search valve is left off because Search's platform retry budget is not published and a
valve at Search concurrency 256 turned a 106 s worst case into a 220 s p95 in the load tests.
Measurements (fake and real upstream) are in `bench/results/beam_capacity_20261004.md` on
branch `codex/beam-capacity-20261004`; the valve and update-call tolerance cases (13) are in
`tests/test_admission.py`.

## Tests

```bash
# Every test file is a plain script with an exit code (not pytest), network-free,
# with fake LLM and embedder. Run them in the image, which has the dependencies:
docker run --rm --network none --entrypoint sh -v "$PWD":/w -w /w -e PYTHONPATH=/w \
  -e HF_HUB_OFFLINE=1 <image> -c 'for t in tests/test_*.py; do python3 $t || echo FAIL $t; done'
```

`test_parse_facts.py` pins the two ways a bad LLM reply could poison the store.
`test_concurrency.py` pins the write path against the platform's retry policy.
`test_admission.py` pins the valve, the 429/503 mapping with no partial persistence, and that
explicit-update calls can time out without failing an Add or a Search. `test_updates*.py`
cover the update mechanism, version by version. rc3: 26 test files, 330 checks, 0 failed.

## Repository layout

```
app/config.py    environment configuration
app/main.py      FastAPI service: /add, /search, /health
app/llm.py       the single LLM (gpt-4o-mini): extraction, recall question, update prompts
app/updates.py   explicit-update detection, candidate selection, verification, withholding
app/embed.py     text-embedding-v4 adapter; optional historical BGE backend
app/store.py     SQLite identity/vector guards, update records, per-user in-process cache
scripts/         contract smoke test, embedding preflight, prompt calibration
tests/           unit, contract, update-mechanism and admission-valve tests
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
* **Third-party components:** DashScope `text-embedding-v4` and `gpt-4o-mini` APIs, FastAPI,
  uvicorn, SQLite and OpenAI Python SDK. Sentence-transformers and
  `BAAI/bge-small-en-v1.5` (MIT) remain available for historical research. The offline harness in
  `bench/` additionally downloads two public repositories at run time — LoCoMo
  (<https://github.com/snap-research/locomo>, `locomo10.json`) for conversations and gold
  answers, and the platform's own public evaluation code
  (<https://github.com/AML-memory/agent-memory-leaderboard>) whose answer and judge prompts it
  imports verbatim. Neither is vendored into this repository or into the image.
* **The service never sees benchmark data.** No dataset, gold answer, or evaluation artefact is
  bundled in the image or consulted by `/add` or `/search`. `bench/` does read gold answers
  (LoCoMo, and the public MQuAKE-Remastered, LongMemEval and BEAM data on research branches),
  but it runs offline, on the author's machine, against public data, and is not part of the
  deployed service (the Dockerfile copies only `app/` and `scripts/`).
* **Deliberately excluded:** the strongest configuration in the paper above writes each memory into
  a LoRA adapter on a local 9B model and elicits the recall statement from those weights. That
  variant is **not** submitted and **not** implemented here, because the challenge requires the
  LLM components used during Add and Search to be `gpt-4o-mini`, with `text-embedding-v4`
  for embeddings. The other research mechanisms (agentic search, DCI, fact selection, chunk
  memory, event dates, fact keys, supersession marks, reranking) are disabled in the
  academic release profile; the explicit-update mechanism above is the one deliberate
  exception, declared there.
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
