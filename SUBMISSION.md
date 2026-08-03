# Submission notes — Agent Memory Challenge 2026

Paste-ready材料 for the evaluation access request. Keep in sync with `README.md`.

| field | value |
|---|---|
| System name | ActiveMemoryIndex |
| Version | 1.0.0 (commit pinned at submission) |
| Evaluation type | Textual Memory |
| Division / route | Academic Methods · code submission (platform-deployed Docker) |
| Repository | https://github.com/linxuhao/ActiveMemoryIndex |
| Contact | Xuhao Lin · linxuhao84@gmail.com · independent researcher |
| Model used by Add and Search | `gpt-4o-mini` (only model in the system; the embedder is a local `bge-small-en-v1.5`) |

## Run instructions

```bash
docker build -t activememoryindex .
docker run -d -p 8000:8000 -v ami-data:/data \
  -e OPENAI_API_KEY=<key> -e AMI_LLM_MODEL=gpt-4o-mini \
  activememoryindex
```

* Add: `POST http://<host>:8000/add`
* Search: `POST http://<host>:8000/search`
* Health: `GET http://<host>:8000/health` (no authentication)
* Authentication: none by default; `AMI_AUTH_SCHEME` supports `bearer` / `token` / `x-api-key`.
* No credential is stored in the repository. `OPENAI_API_KEY` must be injected as an environment
  variable at deployment. **Open question for the organizers:** for the platform-deployed code
  route, does the platform provide the `gpt-4o-mini` access, or should the participant supply a key
  through a private channel? The container also runs without a key, in a degraded raw-text-only
  mode, so a missing key lowers scores instead of failing the run.
* The image bakes in the embedding weights; the container needs no model download at run time.
  It does need outbound access to the OpenAI-compatible endpoint.

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
2026), [doi:10.5281/zenodo.21405875](https://doi.org/10.5281/zenodo.21405875), research code at
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
