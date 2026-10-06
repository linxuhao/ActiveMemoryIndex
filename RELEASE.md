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
