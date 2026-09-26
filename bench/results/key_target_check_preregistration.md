# Pre-registration — does the lexical key channel have a target on LoCoMo? (2026-09-26)

Gate for `docs/index_agent_design.md` §5. Offline, on retrievals that already
exist; no model, no training, no new arm. Written before the script ran.

## Data

* `bench/out/lc-smoke/retrieval.json` — base, conversations 2–3, 351 questions
  with evidence, `top_k=100` (the run behind `locomo_completeness_smoke.md`).
* `bench/out/lc-h30/retrieval.json` — same store, `AMI_HOP2_SLOTS=30`.
* `bench/out/lc-smoke/chunks.json` — item id → dialogue ids, as `report` uses.
* `bench/third_party/locomo10.json` — turn text by `dia_id`.

## Populations

* **NEITHER** — questions whose evidence is complete in neither arm at k=100
  (the "neither did" cell, 42 in the end-to-end decomposition; recomputed here
  on the retrieval files, which may differ by a question or two).
* **GAINED** — complete in `lc-h30` but not in `lc-smoke` (16), reported for
  contrast only.
* For each question the **missing turns** are its evidence `dia_id`s not
  covered by the arm's top 100 (`item_dias` semantics: a raw turn covers its
  own id; a fact covers its whole chunk).

## Tokenisation (fixed)

Lowercase, split on non-alphanumerics, drop tokens < 3 chars and a fixed
English stopword list (the ~120 most common function words, listed in the
script). Numbers kept. Turn text = the LoCoMo `text` field of the turn only —
the same text the store holds for `r` items (captions are not stored).

## Tests, per missing turn

* **T1 question-term reach**: the turn shares ≥1 token with the question.
* **T1r rare question-term reach**: shares ≥1 token whose document frequency
  across all turns of that conversation is ≤ 5% of turns.
* **T2 answer reach**: the turn contains the gold answer string verbatim
  (case-insensitive), or shares ≥1 token with the gold answer after the same
  tokenisation.
* **Hit-set size**: for T1r and T2, the number of turns in the conversation
  matching the same rule — the precision side. A key is usable only if its
  hit set fits in the reserved slots (≤30).

## Question-level outcome (the number that decides)

A question is **reachable** under a rule when *every* one of its missing turns
is reached and the union hit set is ≤ 30 turns. Report, on NEITHER:

| rule | reachable questions / NEITHER |
|---|---|
| T1r alone (question terms, no adapter needed) | |
| T2 alone (answer terms — what the adapter is supposed to supply) | |
| T1r ∪ T2 | |
| neither | |

## Decision rule, fixed now

* If **T1r alone** reaches ≥ half of NEITHER: the next arm is plain FTS on
  question terms with reserved slots — no adapter, no application. The
  adapter idea is not falsified, it is unnecessary on this corpus.
* If **T2 adds ≥ 10 questions** beyond T1r (≈ a quarter of NEITHER): the
  adapter has a distinct target; proceed to the application and to a design
  for the *key* arm (which will need its own pre-registration, end-to-end).
* If **T1r ∪ T2** reaches < 10 of NEITHER: the lexical channel has no target
  on this corpus; stop the design here and say so.
* Everything else: report, no build.

Prediction, written down (tenth): T1r reaches roughly a third of NEITHER;
T2 adds few, because multi-hop answers are mostly inferred (counts, "both",
dates) and not verbatim in a turn. Expected outcome: "report, no build" or
"plain FTS arm". If T2 adds many, I was wrong again and the adapter is live.

## What this cannot show

Whether a real adapter would emit those answer tokens — that is the key-window
measurement (47/48 in a synthetic testbed, "partially holds" at 2B under
question form). This check only asks whether there is anything for a correct
key to hit.
