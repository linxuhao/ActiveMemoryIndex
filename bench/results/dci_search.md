# Direct corpus interaction as the search step — gate failed, one corpus-specific positive (2026-09-27)

Pre-registration: `dci_search_preregistration.md`. Code: `app/dci.py`,
`AMI_DCI_SEARCH` / `AMI_DCI_FILL`, 18 tests (`tests/test_dci.py`). Agent =
gpt-4o-mini with grep / read / finish over the user's store, budget 12 tool
calls, ids only. Image rebuilt from `9eea90b`. Every number below is from the
runs the pre-registration named, plus one declared post-hoc reader replicate
on LoCoMo.

## Results

| instrument | arm | replicates | mean | vs base | test |
|---|---|---|---:|---:|---|
| **KU gate** `lme-ku-k` (78) | `dci` — only the agent's ids (2.9 items/q) | 50 · 53 · 54 · 54 | 52.75 | **−6.75** vs kbase 59.50 | perm p = 0.029, complete separation *negative*; movers 8 up / 17 down |
| | `dcifill` — agent's ids first, embedding fills to 100 | 60 · 59 · 59 · 59 | 59.25 | −0.25 | perm p = 1.0; 5 up / 8 down |
| **LoCoMo** conv 2–3 (351) | `dci` (4.3 items/q) | 1 | 188 | **−32** vs 220 | +29 / −61 |
| | `dcifill` | reader ×2: 243 · 240 | 241.5 | **+24** vs 220 · 215 | majority-of-2 movers **45 up / 17 down, sign p = 0.0005**; worst arm run beats best base run by 20; replicate discordance 7 and 11 |
| **Temporal guard** `lme-t` (133) | `dci` (3.6 items/q) | 61 · 60 · 61 · 58 | 60.00 | +1.50 vs 58.50 | perm p = 0.26; now-anchored 0.303 → 0.250, rest 0.528 → 0.580 |

Operational: 0 fallbacks anywhere; empty `finish` 3–6 per run; tool calls
per search **1.8** (KU), 3.5 (LoCoMo), 4.5 (temporal) of a budget of 12;
2–4 s per search; LLM calls per search ≈ 3.7–5.3 including the recall
question.

## Decision, against the rules as written

Ship candidate required KU ≥ +4.0 at p ≤ 0.05. **KU is −6.75 (`dci`) and
−0.25 (`dcifill`). Not shipped; nothing changes in the defaults.**

Research readings, in the pre-registered order:

* *"`dci` ≥ +4 on KU and the stale questions flip"* — no. Three stale
  questions flipped up (69fee5aa, b6019101, ba61f0b9), eight settled ones
  collapsed 4/4 → 0/4.
* *"Evidence-complete rises on NEITHER but conversion stays ≈ 1 in 5"* —
  the opposite on LoCoMo `dcifill`: 18 questions gained complete evidence
  and **14 are right (base 5)**; hop2's 16 gained converted 3. NEITHER
  complete: 12 of 42 (`dci`: 5).
* *"`dci` < `dcifill` everywhere"* — yes on KU and LoCoMo; on temporal the
  3.6-item `dci` list matched the 100-item baseline (+1.5, n.s.).
* Temporal now-anchored did not move (0.303 → 0.250): no leakage of a
  present.

## What the anatomy says

**The narrow arm fails because the searcher is lazy, not because the reader
needs a hundred items.** gpt-4o-mini used 1.8 of 12 tool calls on KU: one
grep, then `finish`. It returned the first plausible statement and missed the
later one — "Ford Mustang" (2023-05-20) when the current project is the F-150,
"four times" when the latest count is six. On three questions it returned
nothing and the reader hallucinated ("3 months"). When it did return two
versions, the reader summed them (three sessions + five sessions → "eight").
Every one of these is the 4o-mini searcher stopping early; the paper's
searcher refines hypotheses over many calls.

**The positive is an ordering effect, on one corpus.** In `dcifill` the
agent's lines go first and the ordinary list follows. On LoCoMo the median
rank of the first evidence-bearing item moves **7 → 0**; the 38 questions
that flip up are dominated by category 2 temporal (15) and single-hop (14):
"When did Maria go to the beach?" — the agent's top line is the exact turn
with the timestamp, and the reader reads the date off it. On the 292
questions whose evidence was already complete in base, accuracy still rises
207 → 219: same membership, agent-chosen head. On LongMemEval KU the same
mechanism is flat (59.50 → 59.25): the agent's head is the same kind of line
the list already led with, and the stale questions need membership, not a
head.

This is the eleventh time in this project that a ranking/salience change has
had a sign the written prediction did not anticipate, and the third time in a
week that a search-time mechanism's sign was set by the corpus (`parent`,
`FACT_EVIDENCE`, now `dcifill`). Under the 2026-09-22 rule that is "artifact
of the corpus", not "gate it by corpus".

## Prediction (twelfth) scored

KU `dci` +5 → **−6.75**. `dcifill` +2 → −0.25. NEITHER ≥ 10 gain evidence →
12 (`dcifill`), 5 (`dci`). LoCoMo end-to-end +4 inside noise → **+24, far
outside it**. Temporal −2 → +1.5. Fallback < 5% → 0. Median 6 tool calls →
**1–2**. Right on the fallback and the NEITHER count, wrong on every
accuracy.

## What the DCI question got answered

*Does DCI's gain survive handing evidence to a fixed reader?* Partly, and
only in one form: when the agent's chosen lines **lead** a list the reader
was already getting, LoCoMo gains 24 with a reader that converts 14 of 18
newly complete questions. Handing the reader **only** the agent's lines loses
on both corpora, because the permitted searcher stops after one grep. The
paper's gain therefore lives in two places we can now separate: the
searcher's persistence (which gpt-4o-mini does not supply under this budget)
and the head of the list (which it does supply, and which the LongMemEval
reader ignores).

## Not done, deliberately

* `dcifill` was not run on temporal (pre-registration named `dci` only) and
  has no KU gain, so there is no ship case to build guards for.
* No prompt tuning of the searcher after seeing it stop early. A "persistent
  searcher" variant (minimum number of probes, mandatory check for later
  restatements) is a new arm with its own pre-registration, not an edit to
  this one.
* Cost at scale, if it ever matters: ~4 LLM calls per search × 6,000+
  instances, plus 2–4 s latency, within the 30-minute allowance.
