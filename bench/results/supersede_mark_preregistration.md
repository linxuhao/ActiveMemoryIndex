# Pre-registration — mark a superseded fact with its successor

Written 2026-09-22 after `lme_chrono_ku.md`, before anything was implemented.
Read this before any number.

## Why this arm

Three orderings have now been measured on knowledge-update. Eight of the 13
stale questions did not move under any of them — with the current value at
position 1, at position ~50, and last, dated every time. The finding recorded
in `lme_chrono_ku.md`: *where the old value is stated as a direct assertion
and the new one as an aside, order does not reach the reader.*

The user's State DAG has one half left untested: a fact is a node, a later
fact on the same attribute supersedes it, **and the superseded node is kept,
not deleted**. Rendered at search time, that is:

> When a returned fact has a later fact of the same user that says the same
> kind of thing, show the old fact *with its successor attached*:
> `[superseded on 2023-10-15 by: <successor text>] <old fact text>`

The update is delivered at the exact place the old assertion is read, in the
old assertion's own register. Nothing is dropped: `e66b632c` asks for the
previous value and still gets it, marked. The newest version is never marked.

## What changes, and the invariant

Search-time only. `AMI_SUPERSEDE_MARK=1`, `AMI_SUPERSEDE_TAU=<cosine>`.

For each **fact** in the returned set, over the user's whole in-memory index
(not the returned set): candidates are the user's facts with a strictly later
`created_at`; cosine from the already-normalised embedding matrix; if the best
candidate is ≥ τ, the successor is the **latest-dated** candidate at or above
τ (so a chain 37 → 38 → 39 marks 37 with 39, not 38). Raw turns are never
marked. Facts of the same chunk share a `created_at` and so cannot mark each
other.

Rendering goes through the same out-render path as `redated`: **stored text
is never rewritten**, and the marker for a fact is a function of the user's
store alone — the query decides which facts are shown, never what they say.
This is the first arm in the project that changes the *text* the reader sees
(an annotation, derived from stored text, no LLM), so the invariant is
narrowed rather than broken, and it is declared here. Cycle-2 Q18 permits
organisation of stored memories; this attaches one stored memory to another.

No prompt change, no store rebuild. Base parity is exact: `kubase1–4`,
`base/base2/base3/base4`, `lc2_base_r1–2` are the bases.

## Threshold — chosen without knowledge-update gold

τ is the one free parameter and it must not be tuned on the 78 questions the
gate is scored on. Procedure, in this order:

1. On the `lme-t` and `all10v2` stores, for every fact, the best
   later-neighbour cosine. Report the distribution.
2. At τ ∈ {0.85, 0.90, 0.95}: the share of facts marked, and a sample of
   **15 marked pairs per τ per store, hand-judged** as same-attribute-update
   / same-topic-not-an-update / unrelated. Recorded in the amendment.
3. τ = the loosest value whose hand-judged precision is ≥ 0.80 on both
   stores. If none reaches 0.80, the arm is closed *before* the KU run, on
   the reading that fact embeddings cannot identify "same attribute".
4. Only then, the **firing read on `lme-ku`**: for the 13 stale questions,
   is the old fact marked, and by what. Reported; **not used to change τ**.
   If it fires on fewer than 6 of 13 the arm still runs, and that number is
   the ceiling to read the result against.

The chosen τ is written into an amendment to this file before the arm runs.

## Decision rule

* **Primary gate:** `lme-ku`, four replicates, prefix 100, permutation 4v4
  two-sided **p < 0.05, positive**, against `kubase1–4` (57.00).
* **Guard 1:** LoCoMo `all10v2` ×2 against `lc2_base_r1–2`; paired sign test;
  ships only if not significantly worse.
* **Guard 2:** `lme-t` ×4 against `base/base2/base3/base4` (58.50);
  permutation; ships only if not significantly worse.
* Coverage is unchanged by construction. Never gated on recall@k.
* Ships as `AMI_SUPERSEDE_MARK=1` with the amended τ only if the gate passes
  and both guards hold.

## Reads

1. The 13 stale questions, per question: marked? answered with the new value?
2. Firing rate: share of returned facts marked, per instrument; characters
   added per query (each marker duplicates a successor's text).
3. Precision of the markers actually delivered on `lme-ku`, hand-judged on a
   sample of 20 — the false-positive cost the reader paid.
4. Collateral on the 56 base-4/4 questions, and the three "previous value"
   questions separately.

## Prediction

`lme-ku` **+3 to +6**, from the marked subset of the 13; guards flat.

Seven written predictions about the reader's response to a change in what it
sees, seven wrong on the gate. This is recorded to be scored.

## If it passes

Ships. Rung 2 proper — a canonical key from the extractor instead of a cosine
threshold — becomes worth its matched base, because the delivery has been
shown to work and only the link's precision is left to buy.

## If it fails

The State DAG's versioning half is closed at search time: ordering (three
ways) and marking have both been measured. What would remain is Add-time
consolidation — rewriting the old fact when the new one arrives — which
changes stored text and is a different kind of system; not registered here.

## Amendment 2026-09-22 — closed at step 3

Calibration ran on `lme-t` and `all10v2` (`supersede_mark_calibration.md`).
Hand-judged precision of the marks is ≤ 0.20 in every band on both stores;
the 0.80 bar is not reached at any τ. Per step 3 the arm is closed before
the knowledge-update run. No τ is chosen; step 4 was not performed as a
firing read — the 13-pair cosine table in the calibration file was computed
after closure and used for nothing.
