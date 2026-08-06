# Local benchmark harness

The leaderboard does not publish a smoke test set, gold answers, or a dataset download, and the
code-submission route cannot trigger a smoke run itself. This harness reconstructs an equivalent
local loop from public parts so that the two retrieval knobs (`AMI_RETURN_LIMIT`,
`AMI_RECALL_WEIGHT`) are set from data rather than from taste — the formal evaluation runs once.

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
