# Release candidate academic-v4-20261006-rc5

rc5 is the release candidate for the official Full: rc4 (`academic-v4-20261006-rc4`, commit
`a0b3e99`) with one rule applied everywhere and one cap removed. The tag
`academic-v4-20261006-rc5` identifies the fixed commit once the release step creates it; the
image is `activememoryindex:academic-v4-20261006-rc5`, built from the repository Dockerfile
with OCI labels (revision = the tagged commit).

| step | commit | what |
|---|---|---|
| rc4 | `a0b3e99` | token budget, deadlines, as-of selection (deployed at the time of writing) |
| rc5 code | `0d43865`, `6616634` | no language-dependent regex or word list; time reader; adaptive chunk without its own cap |
| rc5 pre-registrations | `8965c49` (amendment 1 in `6616634`, before any validation search) | `bench/results/rc5_language_neutral_preregistration.md`, `adaptive_chunk_rc5_addendum.md` |
| rc5 | this branch | results and docs |

## The rule: no language-dependent heuristics

No regex or word list that depends on a natural language takes part in any decision — month
names, relative-time words, range words, history words, pronoun sets, relative-change words,
stopword or script tests — not even as a pre-filter that can only add protection. Real users
write in any language. `gpt-4o-mini` reads language, only when needed and cached; code handles
only our own id and stamp formats, ISO dates the model returns, JSON and digits.
`tests/test_language_neutral.py` fails on any regex or word list in `app/` that is not on its
reviewed allowlist (on rc4's `app/` it flags 13 literal regexes, 10 run-time-built ones and 10
word lists).

### Audit of every regex and word list in rc4's `app/`

| where | pattern / list | purpose | language-dependent | rc5 |
|---|---|---|---|---|
| `asof.py` | `_MONTHS` / `MON` (month names, 7 languages), `PATTERNS` (mdy, dmy, my, CJK/Korean y-m-d, dotted, ISO, bare year) | parse the question's date and item ranges | yes | removed: question classifier + time reader |
| `asof.py` | `ANY_YEAR` / `YEAR` gate (year in digits) | open the as-of path; exempt items naming a year | yes (二〇二四, words) | removed: classify every question; stated times from the time reader |
| `asof.py` | `RANGE_JOIN`, `RANGE_OPEN` (to/until/到/hasta/bis…, from/between/从/desde…) | find date ranges | yes | removed: the model flags spans |
| `asof.py` | `RELATIVE` (yesterday/ayer/hier/gestern/上周/先週/어제…) | keep relative-time items | yes | removed: the model resolves relative times against the stamp |
| `asof.py` | `STAMP`, `_DELIVERED`, `parse_iso` | our stamp, our chunk/span ids, ISO from the model | no | kept |
| `updates.py` | `HISTORY_QUESTION`, `DATED_QUESTION`, `DATED_CJK` | protection pre-filter | yes | removed: router (`QUESTION_SCOPE2_SYSTEM`) only |
| `updates.py` | `RELATIVE_WORDS` | mark relative updates | yes | removed: stage 2 `relative` |
| `updates.py` | `SELF` = {me, i, my, myself, mine, user, the user} | the user's own subject | yes | replaced by protocol tokens {"me" (stage 2 is told to write it in every language), "i" (our own speaker label)} |
| `updates.py` | `_SCRIPTS` + `_STOPWORDS` + `[a-zà-ÿ']+` | render-language check | yes | removed: stage-2 language tags must be equal |
| `updates.py` | `STAMP`, `RELATIVE_SIGN` (`^[+-]\d`), `_phrase` (escaped quoted value) | our stamp; a signed number; verbatim containment | no | kept |
| `main.py` | `_TIME_HINT` | request-log field only | yes | removed with the field |
| `main.py` | `STAMPED`, `RAW_ID` | our stamp, our raw id | no | kept |
| `llm.py` | `_KEY_JUNK` (`[^a-z0-9._]+`), `[a-z]`, {null, none, n_a, na} | fact-key normalisation (`AMI_FACT_KEYS`) | Latin-only keys | dead on the release path (flag off); left, reported |
| `llm.py` | `_KEYED_OBJECT` | JSON salvage (`AMI_FACT_KEYS`) | no | left (flag off) |
| `llm.py` | `_REASONING`, `\{.*\}`, list-line markers, `_ISO_DAY` / ISO fullmatch | `<think>` markup, JSON, bullets/numbers, ISO | no | kept |
| `dci.py` | `_ITEM_ID`; the agent's own grep pattern | our ids; DCI research (off) | no | kept |

### Replacements

* **As-of selection** (`app/asof.py`). *Question side*: one `gpt-4o-mini` classification per
  distinct (question, options) on every Search, run in parallel with the recall-question
  rewrite (no added latency) and cached: `as_of_state | event_on_date | other` and the ISO start
  and end. *Item side*: for an `as_of_state` question, one call over the candidates not read
  before (what the Search would return, then the next ranked items, ≤ `AMI_ASOF_ITEMS`=200,
  ≤ 400 characters each), sent with their stamp dates; it returns every time each text states
  (ISO at the text's precision, relative times resolved, span or not), cached per item. Code
  applies rc4's two rules on ISO dates (an item whose spans all miss the period is withheld when
  a returned item's span covers it; an item said after the period that states no time starting
  by its end is withheld when a returned item was said by its end). Refill, evidence-only and
  "a failure withholds nothing" are unchanged; event questions withhold nothing. The registered
  direct judgement ("which items are not valid / about the period") was replaced on development
  data before validation because gpt-4o-mini listed only the answering memory (amendment 1).
* **Updates router and exceptions** (`app/updates.py`). The regex pre-filters are gone; the
  router (`needs_past_value` / `time_scoped`) decides protection for every version, and stage
  2's `relative` and `subject_is_user` decide the rest.
* **Render-language check.** Stage 2 returns `statement_language` and `current_language`
  (ISO 639-1) and renders in the statement's language; a render needs both tags and equal
  primary subtags. Chosen over a second LLM check: zero extra calls (≈ 10 completion tokens per
  record) against one call per rendered record; the model that wrote the sentence names its
  language in the same reply.

### Validation (pre-registered; `bench/results/rc5_language_neutral_20261006.md`)

| gate | result | pass |
|---|---|---|
| as-of, English/Chinese vs rc4 (TempReason L2 fresh 150 + synthetic en/zh dated 80) | 224 → 230, +6 (6 W / 0 L) | yes |
| as-of, new languages (synthetic fr/de/es/ja dated, digits / words / native numerals) | 136 → 154, +18 (19 W / 1 L, p = 4e-5); fr +3, de +4, es +6, ja +5 | yes |
| guards: LoCoMo dated 194 / KU 78 / TempReason L3 100 / "now" 48 | −1 / 0 / 0 / 0 | yes |
| updates router alone, every language of round-5, round-5b and new fr/de sets | recall 0.95–1.00, false protection 0.00 everywhere | yes |
| MQuAKE 400 × 2 replicates | rc5 +70.0 over no withholding (81 W / 7 L); rc4 +65.0; rc5 − rc4 +5.0 (9 / 2) | yes |
| render probe (24 updates, 6 languages) | 24 / 24 rendered, all in the statement's language | (reported) |

Classifier: 236 / 240 synthetic dated questions `as_of_state` with 240 / 240 correct periods
(dates in words, 二〇二三年, 令和); the 4 misses are Japanese and withhold nothing.

**Added cost.** Search: the classifier ≈ 680 prompt + 16 completion tokens per distinct
question, beside the recall call (no added wall time); the time reader on as-of state questions
only, ≈ 1,000 + 155 tokens per call (long LoCoMo-sized candidate lists ≈ 6.7k + 1.4k), one
sequential call more on those questions. Add: ≈ 10 completion tokens per accepted update
statement (the two tags); no new call.

## Adaptive chunk delivery without its own cap (`bench/results/adaptive_chunk_rc5_20261006.md`)

`AMI_ADAPTIVE_CHUNK_TOTAL` is removed; adaptive delivery is bounded by `top_k`, the character
budget and the token budget like every mode (every BEAM, LoCoMo and LongMemEval list stayed
inside the token budget). BEAM-100K conversations 1–5 (100 questions): mean rubric B 0.466,
L4 0.447 (13 up, 13 down; L4 now delivers 169k vs 139k characters). LoCoMo 770: L4 lists
byte-identical to rc4's (+5.58 points, unchanged). LongMemEval temporal 57 → 57, knowledge-update
55 → 58. **Not recommended** (BEAM point estimate below B): `AMI_ADAPTIVE_CHUNK=0` stays.

## Recommended production environment (relative to `academic-rc4-20261006.env`)

```
AMI_IMAGE=activememoryindex:academic-v4-20261006-rc5
```

Nothing else changes: `AMI_ASOF_SELECT=1`, `AMI_UPDATE_DETECT/RENDER/WITHHOLD=1`,
`AMI_UPDATE_VERSION=7`, `AMI_ADAPTIVE_CHUNK=0` and every other line stay as in rc4. The new
knobs keep their defaults (`AMI_ASOF_ITEMS=200`, `AMI_ASOF_ITEM_CHARS=400`,
`AMI_LLM_MAX_TOKENS_ASOF=80`, `AMI_LLM_MAX_TOKENS_ASOF_ITEMS=3000`); `AMI_ASOF_POOL`,
`AMI_ASOF_GRACE_DAYS` and `AMI_ADAPTIVE_CHUNK_TOTAL` no longer exist (ignored if set). The
store is compatible (no schema change; the embedding identity is unchanged).

## Studies' spend

≈ 19.1M fresh gpt-4o-mini tokens (cap 35M) and 0.64M text-embedding-v4 tokens (cap 3M), through
the caching, metering proxy (`bench/llm_proxy.py`), real-API concurrency 8.

## Validation of the code

* Whole suite in the rc4 image with the rc5 tree, network-free, fake providers: **31 test files,
  0 failed, 371 checks** (rc4's suite plus `test_language_neutral.py`; `test_asof.py`
  rewritten for the classifier and time reader).
* Built-image checks on a separate container (contract smoke, overload, huge-query budget, a
  French as-of query end to end): see the GitHub release notes.

No official Full has started; rc5 has not been deployed. No benchmark data or gold answers are
bundled with or consulted by the service.

---

# Release candidate academic-v4-20261006-rc4

rc4 is the release candidate for the official Full: rc3 (`academic-v4-20261005-rc3`, commit
`203314d`) plus four changes. The tag `academic-v4-20261006-rc4` identifies the fixed commit
once the release step creates it; the image is `activememoryindex:academic-v4-20261006-rc4`,
built from the repository Dockerfile with OCI labels (revision = the tagged commit).

| step | commit | what |
|---|---|---|
| rc3 | `203314d` | admission valve, 429/503 mapping, update-call tolerance (deployed) |
| rc4 code | `99cba0e`, `4356107` | token budget, request deadlines, embedding settings, adaptive chunk (off), as-of selection |
| rc4 studies | `93b21d3`, `15d0ce8` (pre-registrations), `4209cc0` (results) | see "Studies" |
| rc4 | this branch | zero-fact fallback removed (failed), docs |

## What rc4 changes

* **Token-aware return budget** (`app/tokens.py`, always on, every delivery mode). The
  platform's Answer window is 117,760 input tokens shared by instructions, question, options
  and the returned memories, and Answer keeps a token-counted prefix of what does not fit. Per
  Search the memories get `(AMI_ANSWER_INPUT_TOKENS − AMI_ANSWER_PROMPT_TOKENS) /
  AMI_TOKEN_SAFETY − tokens(query) − tokens(options)` = (117,760 − 1,024) / 1.15 − question;
  each memory costs its tokens + `AMI_ANSWER_ITEM_TOKENS` (20). Counted with tiktoken
  `o200k_base` (baked into the image); a conservative estimate otherwise. `select()` never
  exceeds it (a memory that does not fit is skipped, never cut, no first-memory exception);
  the rendered response is cut to it as a final guard (DCI picks, re-rendering); a query that
  leaves no room returns `[]` without any model call. The 400,000-character budget remains.
  Why 1,024 / 20 / 1.15: `bench/results/token_budget_20261006.md`.
* **Request deadlines and the rc4 embedding settings** (`app/deadline.py`, `app/embed.py`,
  `app/llm.py`). User decision: `AMI_EMBED_CONCURRENCY=16`, `AMI_EMBED_TIMEOUT=40` (shipped
  defaults now). An Add embeds 2–5 batches; at 40 s with one retry, sequential batches could
  take 320 s against the ~100 s edge cut. Now every Add and Search has a deadline
  (`AMI_ADD_DEADLINE` / `AMI_SEARCH_DEADLINE`, 85 s from arrival including admission wait):
  batches run side by side inside the shared gate, every LLM and embedding attempt is clipped
  to the time left, a retry is made only if it can still fit, and a call that cannot is
  answered **503 + Retry-After before persistence**. The SDK clients make no retries of their
  own (`max_retries=0`); `AMI_LLM_RETRIES` / `AMI_EMBED_RETRIES` count them in
  `deadline.call`. Worst case Add/Search ≈ 85 s + persistence.
* **As-of evidence selection** (`app/asof.py`, `AMI_ASOF_SELECT`, default 0; recommended 1).
  Passed its pre-registered gate. Declared under FAQ Q18 in `SUBMISSION.md`.
* **Adaptive chunk delivery** (`AMI_ADAPTIVE_CHUNK`, default 0; recommended 0). Built and
  tested; failed its gate (the gain equals an equal-text control). Stays off.
* Not included: the zero-fact extraction fallback (lead L5) failed its gate and was removed.

## Recommended production environment (relative to `academic-rc3-20261005.env`)

```
AMI_IMAGE=activememoryindex:academic-v4-20261006-rc4
AMI_EMBED_TIMEOUT=40          # was 20
AMI_EMBED_CONCURRENCY=16      # was 4
AMI_ASOF_SELECT=1             # new; passed its gate
# new, at their defaults (written out so the profile is explicit):
AMI_ADD_DEADLINE=85
AMI_SEARCH_DEADLINE=85
AMI_ANSWER_INPUT_TOKENS=117760
AMI_ANSWER_PROMPT_TOKENS=1024
AMI_ANSWER_ITEM_TOKENS=20
AMI_TOKEN_SAFETY=1.15
AMI_ADAPTIVE_CHUNK=0          # failed its gate
```

Everything else as in rc3 (update mechanism on, v7; Add valve 16, wait 45, Search valve off;
platform job Add 16 / Search 16). Start a new store only if the embedding identity changes; it
does not between rc3 and rc4.

## Studies (pre-registered, one replicate, platform prompts, gpt-4o-mini)

| study | report | gate | numbers |
|---|---|---|---|
| as-of selection | `bench/results/asof_selection_20261006.md` | **passed** | as-of sets +30 of 300 (31 W / 1 L, p = 1.5e-8); LoCoMo dated 0 of 194; KU 0 of 78 |
| adaptive chunk | `bench/results/adaptive_chunk_20261006.md` | **failed** | LoCoMo 770: L4 − B +5.6 pt (p = 0.0001) but L4 − equal-text control 0 (43 / 43); guards +2 / +1; BEAM pilot 0.496 → 0.484 |
| zero-fact fallback | `bench/results/zero_fact_fallback_20261006.md` | **failed** | ScriptMem +1 of 94 (needed +2); LoCoMo firing 1 of 399 |
| embedding c16 / 40 s | `bench/results/embed_c16_20261006.md` | (no gate) | attempt timeouts 2.5 %, calls ok 53 / 55, max call 85.04 s, 0.45 Adds/s embedding-bound |

Spend: 51.05M fresh gpt-4o-mini tokens (cap 60M), 1.27M text-embedding-v4 tokens (cap 15M),
through a caching, metering proxy (`bench/llm_proxy.py`); real-API concurrency 8 except the
step test (16, as specified).

## Validation

* Whole suite in the rc4 image, network-free, fake providers: **30 test files, 376 checks,
  0 failed** (rc3's 330 plus `test_token_budget` 9, `test_deadline` 11, `test_adaptive_chunk`
  8, `test_asof` 18).
* Built-image checks on a separate container with a fresh store and the recommended
  environment (contract smoke, overload, a huge-query Search): see the GitHub release notes.

No official Full has started; rc4 has not been deployed. No benchmark data or gold answers are
bundled with or consulted by the service.

---

# Release candidate academic-v4-20261005-rc3

rc3 is the release candidate for the official Full. It is the `academic-v4-20261001`
release (tag; commit `0e2e224`, deployed) plus three additions, each switched by
configuration. The tag `academic-v4-20261005-rc3` identifies the fixed commit once the
release step creates it; the GitHub release notes record the deployed image id, commit and
the public checks, as for the earlier release. The image reuses the pinned dependency image
and replaces `app/` and `scripts/`; the repository Dockerfile remains the clean-build recipe.

Lineage (each step a commit on top of the previous):

| step | commit | what |
|---|---|---|
| academic-v4-20261001 | `0e2e224` | `text-embedding-v4` adapter, store identity protection (below) |
| request log | `47510eb` | opt-in diagnostic request log, `AMI_REQUEST_LOG`, default off |
| rc1 | `ed6e3bd` | explicit-update detection, render and withholding (`AMI_UPDATE_*`, default off) |
| rc2 | `394a0bf` | language-independent update routing; `AMI_UPDATE_VERSION=7` (deployed at the time of writing) |
| rc3 | this branch | admission valve, 429/503 mapping, update-call timeout tolerance, docs |

## What rc3 changes

* **Admission valve and upstream-error mapping** (`app/main.py`, `app/llm.py`,
  `app/config.py`; ported from commit `cd56f55` of the research branch
  `codex/beam-capacity-20261004`, with none of its other research code). It fixes an Add that
  returned 500 on an upstream `httpx.ReadTimeout` (State issue `iss-f1251324d2434864`):
  `AMI_ADD_MAX_INFLIGHT` / `AMI_SEARCH_MAX_INFLIGHT` (0 = off), `AMI_ADMISSION_WAIT` (30),
  `AMI_RETRY_AFTER` (10), `AMI_EXTRACT_REQUIRED` (0). A request without a slot in time is
  answered 429 + `Retry-After` before authentication, model calls or any write; an embedding
  rate limit becomes 429 with the provider's `Retry-After`, a timeout/connection/5xx becomes
  503 + `Retry-After`, both before persistence; counters in authenticated `/health`. All
  defaults keep rc2 behaviour except that a transient embedding failure is now 429/503
  instead of 500.
* **Update-call tolerance** (tests added in `tests/test_admission.py`): the explicit-update
  calls (stage 1, stage 2, verifier, router) are optional. A timeout or 5xx there skips
  update detection for the chunk and the Add still returns 200 (the calls are not strict, and
  `updates.detect()` additionally swallows any exception); a failed router or verifier call at
  Search withholds nothing and never produces a 500.
* **Documentation**: `README.md`, `SUBMISSION.md`, this file and `.env.academic.example`
  describe the academic v4 profile (`text-embedding-v4`, 1024 dimensions, separate
  credentials and endpoint, store identity protection; `gpt-4o-mini` only; BGE is historical
  research only), the explicit-update mechanism with the FAQ Q18 declaration, and the valve.

The rc2 explicit-update mechanism (opt-in, `AMI_UPDATE_DETECT` / `AMI_UPDATE_RENDER` /
`AMI_UPDATE_WITHHOLD`, `AMI_UPDATE_VERSION=7`) and the request log are unchanged by rc3.
Research mechanisms other than explicit updates remain disabled in the academic profile.

## Recommended configuration for the Full

See `.env.academic.example`. Relative to rc2's environment: `AMI_IMAGE` set to the rc3 image
and the valve added: `AMI_ADD_MAX_INFLIGHT=16`, `AMI_SEARCH_MAX_INFLIGHT=0`,
`AMI_ADMISSION_WAIT=45`, `AMI_RETRY_AFTER=10`. Start the platform job with Add concurrency 16
and Search concurrency 16. After the Full is accepted nothing here can change (FAQ Q29), so
the rc3 configuration is to be fixed before the Full is requested.

## Validation

* Whole test suite, network-free, fake LLM and embedder, in the rc2 image: **26 test files,
  330 checks (291 plain-script checks, 39 unittest cases), 0 failed.** The valve commit alone
  reported 59 files and 882 passed on the research branch, whose suite includes research
  modules that are not in rc3.
* `tests/test_admission.py`, 13 cases: valve pass-through when off, reject-before-work and
  clean retry, FIFO admission, independent Search limit, 429/503 mapping with no partial
  persistence, idempotent replay, non-transient errors stay 500, extraction degrade vs
  required, update-call timeouts (stage 1 and stage 2, with and without
  `AMI_EXTRACT_REQUIRED`) tolerated, an extraction failure still mapped when the update calls
  work, router and verifier failures withhold nothing and never 500.
* Contract and overload checks of the built rc3 image (`scripts/smoke_contract.py` on a
  separate container; a concurrent-Add overload check) are recorded in the GitHub release
  notes.
* Load tests of the valve against a fake and a real upstream: `bench/results/beam_capacity_20261004.md`
  on `codex/beam-capacity-20261004` (throughput unchanged, attempts kept under the edge cut,
  no partial persistence in any run).

Explicit-update evidence, on branch `research/explicit-update-20261004` (reports are not
copied into this branch): `bench/results/explicit_update_20261004.md`,
`explicit_update_r2_20261004.md`, `explicit_update_r3_20261005.md`,
`explicit_update_r4_20261005.md`, `explicit_update_r5_20261005.md` and their
pre-registrations. MQuAKE-Remastered public data, +65 to +70 correct of 400 on BGE research
stores (shipped version 7: +65.00); +13.5 of 75 on the v4 stack (15 wins, 0 losses);
guards non-negative (LongMemEval knowledge-update +0.25 of 78, LoCoMo 1540 unchanged). Local
research stores used BGE and local answer/judge calls; these are not official scores.

No v4 benchmark gain, production capacity, official platform Full result or Full cost is
claimed. No benchmark data or gold answers are bundled with or consulted by the service.

## Platform status

Platform Smokes have been run (three, on 2026-10-04 and 2026-10-05). The official Full has
**not** started. rc2 is deployed; rc3 has not been deployed. The platform's concrete
Answer/Eval models are unconfirmed; participant `gpt-4o-mini` settings do not determine them.

---

## Scope of `academic-v4-20261001` (the base of rc3)

This release adds the explicit `text-embedding-v4` adapter and embedding configuration,
and persistent store identity/vector-integrity checks. The academic profile uses 1024
float32 dimensions, independent embedding and LLM credentials, an explicit region/workspace
endpoint and a fresh database. It retains `gpt-4o-mini` extraction/recall, recall weight 0.5,
raw turns plus facts, raw-first ordering, neighbor window 1, return limit 100 and a 400000
character budget. See `.env.academic.example` and the README quick start.

The runtime diff against `9bb0497c4a507256ab7c23a22d5c774ad19e77fe` is limited to
`app/embed.py`, `app/store.py` and the embedding additions in `app/config.py`.
`app/dci.py`, `app/main.py` and `app/llm.py` retain that base version. New DCI tool/trace
research code, manual semantic ordering annotations and benchmark artifacts are excluded.
All existing research mechanisms remain disabled in the academic profile. BGE remains
available for historical local research with its own database.

## Completed validation of `academic-v4-20261001`

- Release app source: 26 adapter/store unit tests, 41 existing concurrency/cache/order/parser
  checks and 38 Add/Search contract checks, **105 total**, passed independently. The real
  OpenAI SDK contacted a loopback fake embedding API inside a network-none container;
  source mounts were read-only and the database was temporary. Eleven mock HTTP requests,
  no real provider calls. Long Unicode source and failed-Add/no-partial-write/retry controls
  also passed. Source hashes remained unchanged.
- Earlier real-provider candidate: 17 embedding and 15 LLM HTTP attempts, all 200; v4
  response model and 1024 dimensions observed. Provider reported 1968 embedding tokens and
  5153 LLM input / 327 output tokens. The 38 contract checks and 42/37 pre/post-restart
  controls passed with 19 items across four synthetic users and full source/vector/ledger/
  identity persistence. Embed/store/main/LLM code matches the release; only inactive
  config/DCI research code differs. The stopped audit container was removed.
- Fake 429 controls established bounded SDK retries, no partial failed Add and successful
  explicit same-request retry. They did not produce actual provider rate limits.

Independent evidence retained by the maintainer:
`bench/out/academic-release-20261001-r1/release-source-validation.json` (SHA256
`13541dd48c930ec762f859dcdc777af966986e061535aef686c6172f4cafb4e7`) and
`bench/out/academic-live-20261001-r1/independent-live-review.json` (SHA256
`f1527a81c88afdd7801430a8508d4020ef16cfc40bfcd6f40a7801f2bb23f813`).
These local audit artifacts are excluded from the public runtime/build context.

No v4 benchmark gain, production capacity, official platform Smoke or official Full is
claimed. Historical README/SUBMISSION metrics used BGE and local answer/judge calls.

## Platform status at 20261001

On 2026-10-01 the user reported submitting the access application. Eval Key/approval is
pending and no issued credential or approval receipt has been independently verified.
Official platform Smoke and Full have not run. The platform's concrete Answer/Eval models
are unconfirmed; participant `gpt-4o-mini` settings do not determine those models.
