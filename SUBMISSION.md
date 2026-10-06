# Submission notes — Agent Memory Challenge 2026

Release metadata and technical notes. Keep in sync with `README.md` and `RELEASE.md`.

**Status (2026-10-06).** On 2026-10-01 the user reported submitting the access application.
Platform Smokes have since been run (three, on 2026-10-04 and 2026-10-05); the results are
the platform's and are not reproduced here. The **official Full has not started**. At the time
of writing the deployed container runs rc4 (the 20261001 release plus the explicit-update
mechanism, the admission valve, a token-aware return budget, request deadlines, the rc4
embedding settings and as-of evidence selection). rc5 removes every language-dependent
regex and word list from the decision paths (gpt-4o-mini reads the language instead) and
removes adaptive chunk delivery's separate cap; it is the candidate for the Full (see
`RELEASE.md`) and has not been deployed or bound to a Full. The
platform's concrete Answer/Eval models are not confirmed; the
[official public configuration](https://github.com/AML-memory/agent-memory-leaderboard/blob/main/api_config.py)
leaves them unset and public materials do not establish a model switch. The participant
Add/Search requirement (`gpt-4o-mini`, `text-embedding-v4`, per the
[competition FAQ](https://agentmemories.ai/competition/)) does not identify the platform's
answerer or judge.

Historical numerical results below use BGE and local answer/judge runs. They are not v4
benchmark results or official leaderboard scores. This release has functional integration
validation and a small v4 check of the explicit-update mechanism; it makes no v4
quality-gain claim. No benchmark data or gold answers are bundled with or consulted by the
service.

| field | value |
|---|---|
| System name | ActiveMemoryIndex |
| Version | `academic-v4-20261006-rc5` (release candidate; the tag identifies the fixed commit), built on `academic-v4-20261001` |
| Evaluation type | Textual Memory |
| Division / route | Academic Methods · API (self-hosted) |
| Repository | https://github.com/linxuhao/ActiveMemoryIndex |
| Endpoint URL | `https://amindex.linxuhao.app` (HTTPS, Cloudflare; see the GitHub release notes for deployment verification) |
| Contact | Xuhao Lin · linxuhao84@gmail.com · independent researcher |
| Models used by Add and Search | `gpt-4o-mini` only, for extraction, recall questions, the explicit-update prompts and the as-of question classifier and time reader; remote `text-embedding-v4`, 1024 dimensions, for embeddings. BGE is historical local research only |

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
git checkout academic-v4-20261006-rc5   # the rc5 release tag
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
| `AMI_UPDATE_DETECT` / `AMI_UPDATE_RENDER` / `AMI_UPDATE_WITHHOLD` / `AMI_UPDATE_VERSION` | `1` / `1` / `1` / `7` in the rc3 profile (all three flags default `0` in code): the explicit-update mechanism, declared below |
| `AMI_ADD_MAX_INFLIGHT` / `AMI_SEARCH_MAX_INFLIGHT` / `AMI_ADMISSION_WAIT` / `AMI_RETRY_AFTER` | `16` / `0` / `45` / `10`: admission valve for the Full (Add valve 16, Search valve off); start the platform job with Add 16 and Search 16 |
| `AMI_EMBED_TIMEOUT` / `AMI_EMBED_RETRIES` / `AMI_EMBED_CONCURRENCY` | `40` / `1` / `16` (rc4 defaults and profile): per-attempt timeout, retries, provider requests in flight; every attempt is clipped to the request deadline |
| `AMI_ADD_DEADLINE` / `AMI_SEARCH_DEADLINE` | `85` / `85` s from arrival (admission wait included): an upstream call the deadline leaves no time for is not made; 503 + `Retry-After`, nothing persisted |
| `AMI_ANSWER_INPUT_TOKENS` / `AMI_ANSWER_PROMPT_TOKENS` / `AMI_ANSWER_ITEM_TOKENS` / `AMI_TOKEN_SAFETY` | `117760` / `1024` / `20` / `1.15`: token-aware return budget against the platform's Answer window (always on) |
| `AMI_ASOF_SELECT` | `1` in the rc4 and rc5 profiles (default `0` in code): as-of evidence selection, declared below; passed its pre-registered gates (rc4, and rc5's language-neutral version) |
| `AMI_ADAPTIVE_CHUNK` | `0`: adaptive chunk delivery; not recommended (rc4 gate failed; rc5 without its cap: BEAM below the baseline), not used |

The release retains raw turns plus facts, extraction and recall enabled, recall weight `0.5`,
raw-first ordering, neighbor window radius `1`, at most `100` results within `top_k`, a
`400000`-character response budget and, from rc4, a token budget sized to the platform's Answer
window. Agentic, hop2, DCI, fact-evidence/selection, chunk-memory, adaptive-chunk, event-date,
fact-key/supersession-mark, chronology/newest and cross-encoder experiments remain off; the
explicit-update mechanism and as-of evidence selection (below) are the deliberate additions.

- Add: `POST https://amindex.linxuhao.app/add`
- Search: `POST https://amindex.linxuhao.app/search`
- Health: `GET https://amindex.linxuhao.app/health` (unauthenticated)
- Outbound access and paid API usage are required for both the embedding provider and LLM.
- Remote embedding failures fail startup or the request explicitly, without changing model
  or partially storing a successful Add. LLM-only fallback is not an embedding fallback.
- The service must remain available throughout an evaluation. Public routing and bounded
  concurrency checks for the 20261001 release are recorded in its GitHub release notes;
  sustained Full capacity is unmeasured (the load tests on a fake and a real upstream are in
  `bench/results/beam_capacity_20261004.md`, branch `codex/beam-capacity-20261004`).
- Under overload or a transient upstream failure the service answers 429/503 with
  `Retry-After` (admission valve, below) rather than 500, before anything is persisted.

## Validation and evaluation flow

**No language-dependent heuristics (rc5).** No regex or word list that depends on a natural
language decides anything in the service — not month names, relative-time, range or history
words, pronoun sets, stopword or script tests, and not as a protection-only pre-filter. Where
language must be read, `gpt-4o-mini` reads it (only when needed, cached); code handles only our
own formats, ISO dates the model returns, JSON and digits. `tests/test_language_neutral.py`
fails on any regex or word list in `app/` that is not on its reviewed allowlist. Pre-registered
validation against rc4's regex version (`bench/results/rc5_language_neutral_20261006.md`):
English/Chinese as-of +6 of 230 (6 / 0), new French, German, Spanish and Japanese streams with
dates in digits, words and native numerals +18 of 160 (19 / 1), LoCoMo dated −1 of 194, other
guards unchanged; the update router alone recall ≥ 0.95 and 0 false protections in five
languages; MQuAKE +70.0 of 400 over no withholding (rc4 +65.0).

**rc5 source tests.** The whole suite, network-free in the image with fake LLM and embedder:
**31 test files, 0 failed** (counts in `RELEASE.md`), including `test_language_neutral.py`.

**rc4 source tests.** The whole suite, run network-free in the rc4 image with fake LLM and
embedder: **30 test files, 376 checks, 0 failed**, including the rc4 cases for the token budget
(9), request deadlines against a fake slow upstream (11), adaptive chunks (8) and as-of
selection (18). rc3's suite (26 files, 330 checks) is part of it. The 20261001 release's own validation (105 checks; 17 real v4 and 15 real
`gpt-4o-mini` requests, all 200; 38 contract checks; 42/37 controls before/after restart;
19 persisted items across four synthetic users surviving a restart exactly) is recorded in
`RELEASE.md`. Contract and overload checks of the rc3 image are listed there too. These are
integration checks, not benchmark quality, production throughput or Full results.

**rc4 studies** (pre-registered, one replicate, platform answer/judge prompts with
`gpt-4o-mini`; `bench/results/*_20261006.md`): as-of selection passed (TempReason L2 fresh +24
of 200, new synthetic profiles +6 of 100, pooled 31 wins / 1 loss; LoCoMo dated 0 of 194 and
LongMemEval knowledge-update 0 of 78). Adaptive chunk delivery failed: +5.6 points over the
shipped selection on 770 held-out LoCoMo questions, but exactly equal (540 = 540) to an
equal-text control, so the gain is volume, not the unit. A zero-fact extraction fallback
failed (+1 of 94 on ScriptMem against +2 required) and is not in rc4.

**Explicit-update results** (public MQuAKE-Remastered, LongMemEval and LoCoMo data; research
branch `research/explicit-update-20261004`, reports `bench/results/explicit_update_*.md`):
render+withhold **+65 to +70 correct of 400** MQuAKE edit/multi-hop questions on BGE research
stores (shipped version 7: +65.00), **+13.5 of 75** (15 wins, 0 losses, p = 0.0001) on the
real v4 stack, guards non-negative (LongMemEval knowledge-update +0.25 of 78; LoCoMo 1540
unchanged). Details in the explicit-update section below.

**Evaluation flow.**

1. Access application submitted on 2026-10-01 (user report). Platform Smokes have been run
   (three, 2026-10-04/05).
2. Use the fixed rc5 tag and verify the authenticated public endpoint before the Full.
3. Run the platform's official Smoke against the bound version and inspect it (at most 30
   per key/track this cycle, at most one per hour; private).
4. Start the official Full only after readiness and Smoke pass: at most two per key/track,
   the second only 30 days after the first completes. A Full usually takes 0.5 to 2 days,
   results are private before review, and once accepted the version cannot be replaced or
   withdrawn because of unfavourable results; the latest valid Full replaces the prior one.
   After a Full is accepted, models, algorithm, prompts and result-changing implementation
   cannot change (FAQ Q29). Use the platform limits documented at
   [the competition page](https://agentmemories.ai/competition/). **The official Full has not
   started.**

The platform's Answer/Eval model configuration is distinct from participant extraction and
recall; its exact models are unconfirmed.

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
  │        + explicit-update detection beside extraction (stage 1 / stage 2; optional,
  │          a failed call skips it) and a rendered current-value memory
  │        + text-embedding-v4 embeddings (1024 dimensions)
  │        + SQLite commit
  └──→  200 (only after persistence is searchable); 429/503 + Retry-After
        (before any write) when overloaded or the embedding/extraction upstream fails

Search ──→  recall-question rewrite ("Did I tell you about …?")
         │  + fused embedding retrieval (original query + recall question)
         │  + earlier values an explicit update replaced are left out (verifier,
         │    router; a failed call withholds nothing)
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

6. **Token budget (rc4):** the platform's Answer window is 117,760 input tokens shared with
   the instructions, the question and its options, and Answer keeps a token-counted prefix of
   what does not fit. Each Search's memories get `(117,760 − 1,024) / 1.15` tokens minus the
   question and options (o200k_base via tiktoken; 20 tokens per memory for its formatting); a
   memory that does not fit is skipped, never cut, and the response never exceeds the budget.
   The 400,000-character budget stays as an extra cap. Measurements:
   `bench/results/token_budget_20261006.md`.
7. **As-of evidence selection (rc4, on in the profile; rc5 language-neutral):** for a question
   asking for a state at a stated date, returned items not valid at that date are withheld and
   their slots refilled from the ranking (declared below).

Search returns memory evidence only. It never produces or disguises a final answer, and never
reads outside the requested `user_id`.

### Explicit updates: declaration of generative-model use in evidence organisation (FAQ Q18)

FAQ Q18 allows summarising, structuring or organising legitimately written memories within
the declared method, provided the content comes only from the same `user_id`'s allowed
history, no future information, external answers or gold labels are introduced, and the
current question is never read to generate a final answer that is then disguised as a
historical memory. The explicit-update mechanism stays inside those boundaries:

* **Model:** `gpt-4o-mini` only. Its output never becomes an answer.
* **Purpose:** when a user explicitly replaces or corrects a value, record that fact and keep
  the earlier, replaced value out of the returned set, so the reader is not shown two
  conflicting values.
* **Prompts, all in `app/llm.py`:**
  1. *Stage 1, intent classification* (Add): labels the user's value-bearing statements and
     quotes them; code keeps only explicit replacements and corrections whose quote is found
     verbatim (whitespace-normalised) in a user turn.
  2. *Stage 2, update extraction* (Add, only for accepted statements): subject, attribute,
     new value (must appear in the user turn), old value (only if stated), whether the subject
     is the user, whether the change is relative, one present-tense sentence stating the
     current value in the turn's language, and (rc5) the ISO 639-1 language of the statement
     and of that sentence.
  3. *Render* (Add): that sentence is stored as one extra memory beside the extracted facts,
     only for absolute updates and only if stage 2's two language tags are equal (rc5; no
     script or stopword heuristic, no extra call). It is
     derived from the user's own update turn when the chunk is written, before any question
     exists.
  4. *Search-time verifier*: shown the update and candidate earlier memories of the same
     user (earlier Adds only), quotes the replaced value in each and says whether it differs
     from the new one; code requires the quote to be in the memory. It never sees the
     question; verdicts are stored.
  5. *Search-time router*: reads the question and returns two booleans (needs the past value;
     time-scoped). If either is true, nothing is withheld. It is called only when withholding
     would change the returned list, and cached per query. rc5: it is the only decider, in
     every language; the English/CJK pattern pre-filter and the English relative-change and
     pronoun word lists are removed (stage 2's `relative` and `subject_is_user` decide).
* **Switches:** `AMI_UPDATE_DETECT`, `AMI_UPDATE_RENDER`, `AMI_UPDATE_WITHHOLD`,
  `AMI_UPDATE_VERSION=7`; the three flags are off in code and on in the rc3, rc4 and rc5
  profiles.
* **The query only selects or withholds evidence.** No returned text is generated from the
  question: Search returns verbatim turns, extracted facts and the Add-time rendered
  sentence, minus the withheld items. Relative updates, history/date questions and the update's
  own Add chunk are never withheld. Any failed model call degrades to "no update" at Add and
  "withhold nothing" at Search.
* **Results:** MQuAKE-Remastered (public) +65 to +70 of 400 on BGE research stores, +13.5 of 75
  on v4, guards non-negative; reports on `research/explicit-update-20261004`
  (`explicit_update_r5_20261005.md` and rounds 1 to 4). See `README.md` for the full summary.

### As-of evidence selection: declaration of generative-model use (FAQ Q18)

Within the same Q18 boundaries as the explicit-update mechanism:

* **Model:** `gpt-4o-mini` only, at Search, two prompts in `app/llm.py`. Their output never
  becomes an answer and is never returned.
* **Purpose:** a question such as "What was Maya's job title as of 5 September 2025?" is
  answered with the latest value when later values are also returned. For such a question,
  items not valid at the stated date are left out of the returned set.
* **Question classifier** (`ASOF_SCOPE_SYSTEM`): on every Search, one call per distinct
  (question, options), run beside the recall-question rewrite and cached. It returns
  `{"kind": "as_of_state" | "event_on_date" | "other", "start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}`
  for a question in any language, with the date written in any way. Only `as_of_state` with a
  period goes further.
* **Time reader** (`ASOF_ITEMS_SYSTEM`): for an `as_of_state` question only, one call over the
  candidate memories of the same user not read before (what the Search would return, then the
  next ranked ones, at most 200), each with its own stamp date. It returns the times each
  memory's text states (ISO dates at the text's precision; relative times resolved against the
  stamp) and whether each is a span. It never sees the question. Cached per memory.
* **Rules, in code on ISO dates:** (a) a memory whose spans all miss the period is withheld when
  a returned memory has a span covering it; (b) a memory said after the period that states no
  time starting by its end is withheld when a returned memory was said by its end. Event
  questions, unread memories and any failed call withhold nothing.
* **The query only selects evidence.** Nothing is rewritten or generated; the freed slots are
  refilled with stored memories from the ranking. Switch: `AMI_ASOF_SELECT` (off in code, on in
  the rc4 and rc5 profiles). Results: `bench/results/asof_selection_20261006.md` (rc4) and
  `bench/results/rc5_language_neutral_20261006.md` (rc5).
* **Added cost:** ≈ 700 gpt-4o-mini tokens per distinct Search question (classifier; no added
  wall time), and ≈ 1,150 tokens and one sequential call more on as-of state questions (time
  reader; more for long candidate lists).

### Request deadlines

Every Add and Search carries a deadline (`AMI_ADD_DEADLINE` / `AMI_SEARCH_DEADLINE`, 85 s from
arrival, admission wait included) under the ~100 s edge cut. Every `gpt-4o-mini` and embedding
attempt is clipped to it, retries are made only while time is left, an Add's embedding batches
run side by side, and a call the deadline leaves no time for is answered 503 + `Retry-After`
before anything is persisted. Real-provider step test at concurrency 16 / timeout 40 s:
`bench/results/embed_c16_20261006.md`.

### Admission valve and upstream-error mapping

`AMI_ADD_MAX_INFLIGHT` / `AMI_SEARCH_MAX_INFLIGHT` (0 = off) bound concurrent work in
a pure-ASGI middleware; a request without a slot within `AMI_ADMISSION_WAIT` s is answered
429 + `Retry-After: AMI_RETRY_AFTER` before authentication, any model call or any write.
Embedding rate limit → 429 with the provider's `Retry-After`; timeout/connection/5xx → 503 +
`Retry-After`, raised before persistence, instead of a 500. `AMI_EXTRACT_REQUIRED=1` (default 0)
applies the same mapping to a failed extraction call. Explicit-update calls are tolerated, never
mapped. Counters in authenticated `/health`. Recommended for the Full: Add 16, wait 45, Search
valve off, platform concurrency 16/16. See `README.md`.

### Key design decisions

| Decision | Rationale |
|---|---|
| Dual store (verbatim + facts) | Facts are clean retrieval keys; verbatim preserves details extraction drops |
| Register-matching recall | First-person "Did I tell you…" queries match the store's genre; empirically beats keyword-based retrieval |
| Agentic reflection, off by default | Measured at zero end-to-end gain once the full `top_k` is returned; kept in the code behind `AMI_AGENTIC_SEARCH` |
| Fill `top_k` (100) | Swept 1→100 against the platform's own answer/judge prompts: accuracy is monotone increasing for `gpt-4o-mini`, reversing the paper's 9B dilution prior; confirmed on a held-out subset |
| Timestamps in content text | The platform answer model resolves relative time from content, not `created_at` |
| Explicit-update withholding (opt-in, on in rc3) | An explicit "replace/correct" by the user makes the earlier value stale; leaving it out of the returned set measured +65 to +70 of 400 on public MQuAKE-Remastered and was non-negative on the guards; the query only selects evidence |
| Admission valve, Add only | 429 + Retry-After before any write is a retry the platform sanctions; Search valve stays off because Search's retry budget is unpublished |
| Token-aware return budget (rc4) | The Answer window is token-counted and shared with the question; a character cap alone ignores tens-of-KB task prompts and CJK text |
| Request deadline 85 s (rc4) | Per-call timeouts summed past the ~100 s edge cut; a deadline bounds the whole request and fails it cleanly (503) before persistence |
| As-of evidence selection (rc4, on) | Passed its pre-registered gate: +30 of 300 on as-of questions (31 W / 1 L), 0 on LoCoMo dated and knowledge-update guards |
| No language-dependent heuristics (rc5) | Real users write in any language; a pattern sees only the languages it was written for. gpt-4o-mini reads language; code compares ISO dates. +18 of 160 on new-language as-of questions, no loss on English/Chinese |
| Adaptive chunk delivery (off) | rc4: +5.6 points on LoCoMo but identical to an equal-text control. rc5 without its own cap: BEAM 0.466 → 0.447; not recommended |

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
   tunnel, user-scoped idempotent re-add, persistent embedding identity and vector validation,
   admission valve and 429/503 mapping. LLM fallback does not replace the required remote
   embedding service. None of this infrastructure exists in the research codebase.
7. **Explicit-update withholding** — described above (FAQ Q18 declaration). New in this
   submission; not in the paper.
8. **Token-aware return budget and request deadlines** (rc4) — service engineering against
   the platform's published Answer window and the edge's request cut; not in the paper.
9. **As-of evidence selection** (rc4; language-neutral in rc5) — described above (FAQ Q18
   declaration). New in this submission; not in the paper.
10. **Contract compliance** — Synchronous persistence (200 only after SQLite commit),
   `user_id` isolation, `request_id` echo, 422 on malformed input, `/health` liveness.
   These are competition requirements, not research concerns.

What was **excluded** from the paper:

- LoRA-based weight writing (incompatible with `gpt-4o-mini` requirement)
- EWC regularization and Benna-Fusi cascade (weight-level mechanisms, no API-model equivalent)
- The 9B local backbone and its recall elicitation pipeline
- Per-user weight partitions

## Third-party components

Runtime components: DashScope `text-embedding-v4` service, `gpt-4o-mini`, FastAPI, uvicorn,
SQLite, OpenAI Python SDK and tiktoken (MIT; its `o200k_base` encoding file is baked into the
image) for token counting. The image also includes sentence-transformers and
`BAAI/bge-small-en-v1.5` (MIT) for optional historical research; the academic profile does not
use BGE. No benchmark data, gold answer or manual relation annotation enters runtime retrieval.

## Integrity

No hard-coded answers, no benchmark leakage, no prompt injection, no manual intervention, no
cross-`user_id` retrieval. Retrieval scope is `user_id` only; `session_id` is stored for
provenance and never used as a filter. Evaluation data is used solely to serve the run and is
not retained for training or analysis.
