# Pre-registration — withholding the old value: is its *presence* what the reader answers from? (2026-09-26)

Membership is the one rung of State DAG versioning not yet measured (order
×3, marking ×2 all flat or negative on the 13 stale knowledge-update
questions, `lme_knowledge_update_baseline.md`). The user's proposal: let the
memory agent choose which memories *not* to return. Withholding at search
time is not deletion — the store keeps every version.

## Stage 0 — what a key-linked fact drop could reach (measured before this file, `kmark1`)

For each of the 13 stale questions, where the old value sits in the returned
top-100 (`/tmp/stale_reach.py`):

| qid | old fact marked (key link found) | old value in unmarked facts | old value in **raw turns** |
|---|---:|---:|---:|
| 031748ae | 1 | 0 | 2 |
| 07741c45 | 0 | 1 | 2 |
| 0f05491a | 1 | 0 | 2 |
| 59524333 | 1 | 2 | 3 |
| 69fee5aa | 0 | 1 | 5 |
| 6a1eabeb | 1 | 0 | 1 |
| 7401057b | 0 | 0 | 2 |
| 830ce83f | 0 | 3 | 8 |
| 852ce960 | 0 | 2 | 4 |
| a2f3aa27 | 1 | 0 | 2 |
| b6019101 | 0 | 1 | 1 |
| ba61f0b9 | 1 | 1 | 3 |
| f685340e | 0 | 1 | 3 |

**In 13 of 13 the old value is also in returned verbatim turns**, which are
delivered first (`RAW_FIRST`). A key-linked drop of the old *fact* — the
mechanism that exists (`superseded()`) — removes the old value from the
fact block in 6 of 13 and from the list in 0 of 13. Its reach is zero before
it runs, so it is not run. The question this file registers is the one
underneath it.

## Stage 1 — oracle splice (this run)

**Question.** If every returned memory carrying the old value is withheld —
facts and raw turns, chosen with the gold old value, i.e. an oracle — does the
gpt-4o-mini reader answer the new value? This is a diagnostic of the reader,
not a mechanism, exactly like the routed-splice arm in `lme_now_hint.md`.

**Procedure.** `bench/splice_oracle_drop.py` reads `bench/out/kbase{1..4}/
retrieval.json`, keeps only the 13 stale questions, removes any ranked item
whose content matches that question's old-value pattern (fixed list in the
script; word-bounded), and writes `bench/out/kdrop_o{1..4}/retrieval.json`
with the same order otherwise. Nothing is backfilled. Then `run_lme.py
answer` + `judge` at prefix 100, four replicates, same model and prompts as
`kbase`. The comparison is per question against `kbase{1..4}` judgments.

**Populations.**
* **SINGLE (11)**: 07741c45, 0f05491a, 59524333, 69fee5aa, 6a1eabeb,
  7401057b, 830ce83f, 852ce960, a2f3aa27, b6019101, ba61f0b9 — the question
  asks for the current value only.
* **TWO-PART (2)**: 031748ae, f685340e — the question asks for the *previous
  and* the current value. Withholding the old value destroys what they need.
  They stay in the splice as the built-in collateral reading.

**Readings, fixed now.** On SINGLE, a question "rises" when its 4-replicate
mean under the splice exceeds its `kbase` mean; "flips" when it reaches ≥ 3/4.
* ≥ 8 of 11 flip → the old value's presence is the cause. The reader's stale
  answer is a membership problem, and the mechanism has to reach raw turns,
  not just facts. Stage 2 (a non-oracle mechanism) gets its own
  pre-registration; it is not designed here.
* ≤ 3 of 11 flip → presence is not the cause; the reader answers the old
  value from something else (the hedge in the new statement's wording, a
  prior, the question form). Withholding is closed as a lever and the finding
  changes: "a direct assertion outweighs a hedged update" becomes "the reader
  does not take the hedged update even alone."
* 4–7 → report both halves; no build.
* TWO-PART: expected to fall or stay. If they *rise*, something in the splice
  is wrong; inspect before reading anything else.

**Prediction (eleventh, written before the run):** 9 of 11 flip; the two
two-part questions fall to 0/4. Ten predictions about this reader have been
wrong; this is written so that an eleventh can be.

**What this cannot show.** Whether any non-oracle mechanism can identify the
old value's raw turns. That is stage 2's question and only exists if stage 1
says presence is the cause.

**Cost.** 13 × 4 answer calls + 13 × 4 judge calls. No server, no store.
