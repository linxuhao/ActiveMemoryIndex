# ActiveMemoryIndex

Agent Memory Challenge 2026 submission — Academic Methods track, Textual Memory, code-submission
route (platform-deployed Docker).

- **Deadline:** 2026-08-07 23:59 UTC+8
- **Rules:** https://agentmemories.ai/rules
- **Repo:** https://github.com/linxuhao/ActiveMemoryIndex.git
- **Contact:** Xuhao Lin · linxuhao84@gmail.com · independent researcher

## Method (one paragraph)

Messages are stored twice — verbatim timestamped turns + atomic first-person facts extracted by
`gpt-4o-mini`. Both are embedded with `bge-small-en-v1.5` and committed to SQLite before Add
returns 200. At Search time the question is rewritten as a memory-check question in the user's own
voice ("Did I tell you about …?"); original query and recall question are fused over the embedding
space. Search returns evidence only, never an answer.

The method comes from the author's prior research — *An Index, Not a Store: The Model Does
Remember — It Just Needs Its Notebook* (Xuhao Lin, independent researcher, 2026).
- **Paper (Zenodo):** [doi:10.5281/zenodo.21405963](https://doi.org/10.5281/zenodo.21405963)
- **Research code:** https://github.com/linxuhao/index-not-store

The register-matching retrieval finding and the context-dilution curve motivating the return policy
are from that work. A stronger LoRA-based configuration in that paper is deliberately excluded
(challenge requires `gpt-4o-mini`).

## Competition constraints (non-negotiable)

- **Model:** `gpt-4o-mini` is the only model used by Add and Search. This is a competition rule.
- **Search returns evidence only** — never generates or disguises a final answer.
- **`user_id` isolation** — no cross-user retrieval. `session_id` is stored for provenance only.
- **No hard-coded answers, no benchmark leakage, no prompt injection, no manual intervention.**
- **Add must be synchronous** — 200 only after persistence is searchable.
- **API contract:** `/add`, `/search`, `/health`. Full contract in `README.md` and `scripts/smoke_contract.py`.
- **Auth:** `none` by default; supports `bearer`/`token`/`x-api-key` via `AMI_AUTH_SCHEME`.
- **Evaluation `top_k` is 100.** `AMI_RETURN_LIMIT` (default 40) may return fewer — this is intentional
  (context dilution curve from the underlying paper), not a truncation bug.
- **No benchmark data or gold answers are bundled or consulted** in this repository.
- **Data retention:** eval data is used only to serve the run; not retained for training or analysis.

## Repository layout

```
app/config.py     environment configuration (all env vars)
app/main.py       FastAPI service: /add, /search, /health
app/llm.py        gpt-4o-mini: fact extraction + recall-question rewriting
app/embed.py      bge-small-en-v1.5 embeddings (local, CPU)
app/store.py      SQLite + per-user in-process vector cache
scripts/          smoke_contract.py (contract verification), inspect_prompts.py (prompt calibration)
tests/            test_parse_facts.py (guards against silent store poisoning)
bench/            local benchmark harness (LoCoMo-based, for knob tuning)
```

## Related research

### An Index, Not a Store (the retrieval finding)

- **Paper (Zenodo):** [doi:10.5281/zenodo.21405963](https://doi.org/10.5281/zenodo.21405963)
- **Research code:** https://github.com/linxuhao/index-not-store

The ActiveMemoryIndex submission uses the *retrieval* finding from this line of work
(register-matching beats query rewriting); the weight-resident LoRA configuration described in the
paper is explicitly not part of this submission (challenge requires `gpt-4o-mini`).

### Dual-Brain Live Memory (the broader research project)

Located at `~/papers/dual-brain-memory/`. This is a separate, larger project — a running
weak-Galápagos instrument testing whether LLMs can learn online through a two-brain architecture.

**Thesis:** LLMs can learn online if no component is required to live forever. Two pillars:
1. **Firewall** (separation in space) — frozen capability brain reads a plastic memory brain
   through a narrow prefix-token interface; capability should stay flat while memory degrades.
2. **Succession** (separation in time) — memory brains degrade and retire on schedule; user
   identity flows across generations via founding checkpoint W₀ + continuous hybrid education
   (implicit distillation + idle-cycle teaching QA), never raw-log replay.

**Named adversary:** model collapse (iterated model-to-model transfer degrades). Either outcome —
firewall holds or leaks, succession sustains or collapses — is a publishable adjudication.

**Hardware:** Dual AMD GPU (7900XTX 24GB + 7800XT 16GB), ROCm 6.2, RDNA3. Memory brain = 2B FP32
base + LoRA adapters on the big card; capability brain = 7B bf16 inference-only on the smaller card.

**Stage plan:**
| Phase | Status | What |
|---|---|---|
| E0 | Design | Calibration pilot — fix lr, steps/turn, eval cadence per substrate |
| Phase 1 | Ratified (lean POC) | Memory brain in isolation, ρ=0 survival curve, substrate comparison (0.6B full-FT vs 2B LoRA) |
| Phase 2 | Design | Add prefix-token interface + frozen capability brain: firewall test + reset test |
| Phase 3 | Design | Succession: staggered duo, scheduled rotation, per-generation ε measurement |
| Phase 4 | Sketch | K-generation capstone, identity half-life vs single-brain lifetime |

**Key established claims** (from `CLAIMS.md`, 🟢 = robust):
- Firewall: writing memory to LoRA cartridge on frozen base = **+0.00** permanent capability damage
- Per-turn online weight writes catastrophically forget (HL-2 single-digits, naked FIFO)
- EWC is the half-life lever; LoRA ≫ full-FT; online-EWC = negative (ratchet effect)
- d/r law inverts at fact granularity: r32 holds ≥384 facts, r256 worse
- Benna-Fusi cascade extends founded-cohort retention ~7× at N=8, keeps climbing past N=32
- Separation (not locality) is the protective primitive — parameter masking falsified
- Self-generated content confabulates; on-manifold content self-recites faithfully
- In-weight identity is a weak, regime-dependent layer — file is both carrier and defender

**Key corrected claims** (🔵, do not revert):
- BF "n_half" is HL-1 (founded-cohort survival), not HL-2 (online fact half-life)
- Online accumulation IS real with EWC (~5.6× naked), but BF does NOT accumulate (cohort-protector only)
- Identity is hollow — same information as any fact; what matters is on-manifold-ness + ground-truth-in-loop
- "0.76 succession fixed point" was off-manifold nonsense settling by survivors-survive, not identity

**Discipline rule:** ROCm is nondeterministic even at fixed seed. Trust directions and mechanisms;
never trust a single-seed number. Headline numbers must be multi-seed.

**Key files:**
- `README.md` — thesis and stage plan (read first)
- `CLAIMS.md` — canonical claims ledger (**read first every session**)
- `PHASE_1.md` — Phase 1 design (memory brain isolation, substrate comparison)
- `PHASE_3.md` — succession design
- `EXPERIMENT_0.md` — calibration pilot design
- `phase5/` — Benna-Fusi cascade, accumulation experiments, cleonic core

## Development

```bash
# Install
pip install -r requirements.txt

# Run tests (standalone script — not pytest-compatible)
python3 tests/test_parse_facts.py

# Run the service (needs OPENAI_API_KEY for full pipeline)
OPENAI_API_KEY=sk-... uvicorn app.main:app --host 0.0.0.0 --port 8000

# Verify against the contract
python3 scripts/smoke_contract.py http://127.0.0.1:8000

# Calibrate prompts across models
OPENAI_API_KEY=sk-... AMI_LLM_MODEL=gpt-4o-mini python3 scripts/inspect_prompts.py

# Local benchmark with Qwen reasoning model (via gateway, thinking disabled)
OPENAI_API_KEY=x \
OPENAI_BASE_URL=http://<gateway-host>/v1 \
AMI_LLM_MODEL=Qwen/Qwen3.5-27B \
AMI_LLM_DISABLE_THINKING=1 \
python bench/run_bench.py ingest --server http://127.0.0.1:8000 --tag local --conv 0 1
```

## Docker

```bash
docker build -t activememoryindex .
docker run -d --name ami -p 8000:8000 -v ami-data:/data \
  -e OPENAI_API_KEY="$OPENAI_API_KEY" \
  -e AMI_LLM_MODEL=gpt-4o-mini \
  activememoryindex
```

The image bakes in `bge-small-en-v1.5` weights; the container needs no model download at runtime.
It does need outbound access to the OpenAI API.

## Configuration

All via environment variables. No credentials in the repository. See `.env.example` and
`app/config.py` for the full list. Key ones:

| variable | default | meaning |
|---|---|---|
| `OPENAI_API_KEY` | *(empty)* | required for full pipeline; service starts without it (degraded raw-text mode) |
| `AMI_LLM_MODEL` | `gpt-4o-mini` | competition-required model |
| `AMI_LLM_DISABLE_THINKING` | `0` | set to `1` for local Qwen reasoning models via gateway; injects `<<DISABLE_THINKING>>` into system prompt |
| `AMI_RECALL_WEIGHT` | `0.5` | weight of user-voice recall channel in fused score |
| `AMI_RETURN_LIMIT` | `40` | max memories returned (≤ top_k) |
| `AMI_EMBED_MODEL` | `BAAI/bge-small-en-v1.5` | local embedding model |

## Notes

- `tests/test_parse_facts.py` uses `sys.exit(0)` — run it directly, not via pytest
  (pytest crashes on the SystemExit during collection).
- The local benchmark harness (`bench/`) uses public LoCoMo data for offline knob tuning.
  It does not access the platform's private evaluation suite.
- Degraded mode (no API key): service starts and serves raw-text-only retrieval. Deliberate
  availability property — missing key degrades quality instead of failing Add.
