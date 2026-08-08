# Local benchmark harness

The leaderboard does not publish a smoke test set, gold answers, or a dataset download, and the
code-submission route cannot trigger a smoke run itself. This harness reconstructs an equivalent
local loop from public parts so that every retrieval decision (`AMI_RETURN_LIMIT`,
`AMI_RECALL_WEIGHT`, `AMI_RAW_FIRST`) is set from data rather than from taste — the formal
evaluation runs once.

Nothing from the platform or the datasets is vendored here. `fetch.sh` downloads them.

```bash
bash bench/fetch.sh                      # LoCoMo + the platform's public evaluation code
python bench/run_bench.py ingest   --server http://127.0.0.1:8000 --tag base --conv 0 1
python bench/run_bench.py retrieve --server http://127.0.0.1:8000 --tag base --conv 0 1
python bench/run_bench.py report   --tag base
```

* **`ingest`** replays LoCoMo conversations through `/add` the way the platform does: one call per
  source session, split at 20 messages, `role` `user`/`assistant`, Unix-millisecond timestamps,
  one `user_id` per conversation.
* **`retrieve`** calls `/search` once per question with `top_k=100` and records the ranked ids.
* **`report`** scores the retrieval layer against LoCoMo's `evidence` field (which memory a
  question's answer actually needs) and prints recall@k. No answer model is involved, so the
  ranking knobs can be swept cheaply and without judge noise.
* **`answer` / `judge`** run the end-to-end layer with the platform's own answer and judge prompts,
  imported from the cloned `agent-memory-leaderboard` repository — never copied into this one.

## What is in `results/`

| file | what it settles |
|---|---|
| `tuning_conv2-4_sweep.json`, `holdout_conv5-7_sweep.json` | the return-limit sweep and its held-out confirmation |
| `baseline_all10_coverage.txt` | retrieval coverage over all ten conversations, n=1536 |
| `ordering_ab_all10.txt` | the ordering of the returned set: relevance vs random vs verbatim-first vs facts-first vs diversity-capped |
| `hybrid_ab_all10.txt`, `hybrid_e2e_all10.txt`, `hybrid_replicates_all10.txt` | the BM25 hybrid channel that was built, measured and removed |
| `granularity_audit.txt` | why the higher-scoring coarse-granularity option was not shipped |

Two habits these files exist to enforce. **Read a retrieval number and an end-to-end number as
different things** — across the arms in `ordering_ab_all10.txt` they are *inverted*, and a
pre-registered gate on coverage would have selected the worst configuration. **Read any accuracy
figure next to its token budget** — `granularity_audit.txt` shows accuracy rising monotonically with
returned characters, so an accuracy quoted without tokens-per-query is not interpretable.

## Results

The two subsets are LoCoMo conversations 2-4 (tuning, n=529 questions with evidence) and 5-7
(held out, never used for tuning, n=464). Regenerate either table with:

```bash
bash bench/fetch.sh
python bench/run_bench.py ingest   --server <url> --tag tuning --conv 2 3 4
python bench/run_bench.py retrieve --server <url> --tag tuning --conv 2 3 4 --top-k 100
for p in 1 5 10 20 40 100; do
  python bench/run_bench.py answer --tag tuning --prefix $p
  python bench/run_bench.py judge  --tag tuning --prefix $p
done
python bench/run_bench.py sweep --tag tuning
```

`sweep` joins the judged answers back to the retrieval record, so every column below comes from
committed artifacts rather than an ad-hoc script. Aggregates live in `bench/results/`; the raw
per-question files stay out of git because they contain LoCoMo questions and gold answers.

**Return-limit sweep, tuning subset (conv 2-4, n=529).** `gpt-4o-mini` answering, the platform's
verbatim answer and judge prompts:

| memories returned | 1 | 5 | 10 | 20 | 40 | 100 |
|---|---|---|---|---|---|---|
| accuracy | .219 | .353 | .427 | .482 | .554 | **.597** |
| evidence retrieved | .410 | .641 | .741 | .815 | .885 | **.940** |
| accuracy given evidence retrieved | .461 | .493 | .551 | .578 | .603 | **.626** |

Both rows rise with the return size: the reader finds more, *and* applies what it finds more often.
That is the opposite of the dilution prior this harness was built to test. Paired against p100,
every smaller prefix loses — p40 by 34:11 flipped questions, p20 by 73:12, p1 by 213:13.

**Held-out confirmation (conv 5-7, n=464), at the chosen p100:** accuracy .584, evidence retrieved
.981, accuracy given evidence retrieved .591. Consistent with the tuning subset, so the choice is
not an artifact of the subset it was chosen on.

**How much of this is noise.** Two independent answer+judge runs of the identical configuration
(p100, n=529) differed by one question, ~0.2 pp. Differences of a few points are real; the third
decimal is not. All of it is one local harness with one local judge — the platform's judge is a
different instrument, so treat the ordering as the finding and the absolute values as indicative.

## Deviations from the official evaluation, stated up front

* The platform evaluates `locomo_refined`; this harness uses the public `locomo10.json`.
* The platform's answer model is `gpt-4o-mini` at temperature 0. Use the same when a key is
  available; any local substitute must be reported as such.
* The platform's judge model is not disclosed. A local judge is a different instrument, so only
  large differences between configurations should be trusted — the ordering of configurations,
  not their absolute scores.
* LoCoMo category 5 (adversarial, no supporting memory) is excluded from both layers.
* **Credit is asymmetric between the two stored kinds, in favour of extracted facts.** A verbatim
  turn counts as a hit only when it *is* the evidence turn; an extracted fact counts when the
  evidence turn is anywhere in the chunk it was extracted from (a fact's provenance is its whole
  chunk, up to 20 messages). So the facts channel is scored more generously than the verbatim
  channel, and the per-kind breakdown in `report` must be read with that in mind — treat the facts
  row as an upper bound. The end-to-end layer has no such asymmetry: the judge sees the answer.
* How the platform conveys speaker identity for two-speaker conversations is not documented; this
  harness maps speaker A to `user` and speaker B to `assistant` under one `user_id`, which is the
  literal reading of the contract.
