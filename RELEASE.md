# Academic release academic-v4-20261001

The public tag `academic-v4-20261001` identifies the fixed release commit. This document
records the release scope and completed source checks. The GitHub release notes record
the deployed image/commit, public routing checks and bounded concurrency probe.
The deployed image reuses the pinned, previously deployed dependency image and replaces
all app/scripts source; it is not evidence of a fresh dependency download/build. The
repository Dockerfile remains the clean-build recipe.

## Scope

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

## Completed validation

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

## Platform status

On 2026-10-01 the user reported submitting the access application. Eval Key/approval is
pending and no issued credential or approval receipt has been independently verified.
Official platform Smoke and Full have not run. The platform's concrete Answer/Eval models
are unconfirmed; participant `gpt-4o-mini` settings do not determine those models.
