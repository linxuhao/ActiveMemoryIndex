# Submission notes — Agent Memory Challenge 2026

Paste-ready materials for the evaluation access request. Keep in sync with `README.md`.

| field | value |
|---|---|
| System name | ActiveMemoryIndex |
| Version | 1.0.0 (commit pinned at submission) |
| Evaluation type | Textual Memory |
| Division / route | Academic Methods · API (self-hosted) |
| Repository | https://github.com/linxuhao/ActiveMemoryIndex |
| Endpoint URL | `https://<host>:8000` (HTTPS, public, stable ≥30 days) |
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
docker build -t activememoryindex .
docker run -d --name ami -p 8000:8000 -v ami-data:/data \
  -e OPENAI_API_KEY=<gpt-4o-mini-key> \
  -e AMI_LLM_MODEL=gpt-4o-mini \
  -e AMI_AUTH_SCHEME=bearer \
  -e AMI_AUTH_TOKEN=<memory-system-key> \
  activememoryindex
```

| variable | purpose |
|---|---|
| `OPENAI_API_KEY` | Our `gpt-4o-mini` API key — participant-supplied, injected at deployment |
| `AMI_AUTH_SCHEME` | `bearer` (also supports `token`, `x-api-key`) |
| `AMI_AUTH_TOKEN` | The Memory System Key shared with the platform |

- Add: `POST https://<host>:8000/add`
- Search: `POST https://<host>:8000/search`
- Health: `GET https://<host>:8000/health` (unauthenticated)
- The image bakes in `bge-small-en-v1.5` weights; no model download at runtime.
- Outbound: the container needs access to `https://api.openai.com` (or `OPENAI_BASE_URL`).
- The endpoint must remain reachable and stable for at least 30 days after submission.
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

## Method summary

Every message is stored verbatim with its timestamp; the same chunk is also passed to
`gpt-4o-mini`, which extracts atomic first-person facts carrying the same timestamp. Both are
embedded locally with `bge-small-en-v1.5` and committed to SQLite before Add returns 200, so
memories are searchable immediately. At Search time `gpt-4o-mini` rewrites the question as a
memory-check question in the user's own voice ("Did I tell you about …?"); the original query and
that recall question are fused over the embedding space, and the ranked, deduplicated list is
returned within `top_k`. Search returns evidence only and never generates an answer.

## Disclosure

The method comes from the submitter's own prior research — *An Index, Not a Store* (Xuhao Lin,
2026), [doi:10.5281/zenodo.21405963](https://doi.org/10.5281/zenodo.21405963), research code at
<https://github.com/linxuhao/index-not-store>. The register-matching retrieval finding and the
context-dilution measurement motivating the return policy are from that work; those numbers were
measured on a different benchmark and backbone and are not claimed to transfer. The service code
in this repository was written for this submission and is not a fork. Third-party components used
unmodified: `BAAI/bge-small-en-v1.5`, FastAPI, uvicorn, sentence-transformers, SQLite, the OpenAI
Python SDK. No benchmark data or gold answer is bundled or consulted.

A stronger configuration in that paper writes each memory into a LoRA adapter on a local 9B model
and elicits the retrieval query from those weights. It is **not** part of this submission and not
implemented in this repository, because the challenge requires `gpt-4o-mini` as the model used
during Add and Search.

## Integrity

No hard-coded answers, no benchmark leakage, no prompt injection, no manual intervention, no
cross-`user_id` retrieval. Retrieval scope is `user_id` only; `session_id` is stored for provenance
and never used as a filter. Evaluation data is used solely to serve the run and is not retained for
training or analysis.
