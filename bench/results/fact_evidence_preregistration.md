# Pre-registration — a fact brings its own evidence

Written 2026-09-21 before the switch was implemented. Read this before any number.

## The question this arm exists to answer

The cross-encoder arm failed in a specific, diagnosed way. It scored *does this
passage answer the question*, and on a multi-evidence question **no passage
answers it alone**, so it demoted all of them: LoCoMo cat1 complete@100 fell
0.559 → 0.456, and 0.647 → 0.441 with the neighbour window off, while recall@1
doubled (`locomo_rerank.md`). We checked and killed both easy explanations — not
a slot tax (distinct source chunks 22.2 → 22.2), not a bias against facts.

An extracted fact does not have that problem. It is a standalone claim, so it
scores *well* under exactly the kind of relevance model that demotes the turns it
was extracted from. The claim under test is that this asymmetry is usable:

> Rank the facts. Let a selected fact pull its evidence turns in behind it.

If that works, a multi-evidence retrieval problem becomes single-target retrieval
plus a deterministic expansion, and the mechanism is structural rather than a
nudge to how salient something looks. That matters because the five interventions
before this one all moved salience, and none of their outcomes was predictable
from any measurable property of the change.

## What actually changes

`select()` already does this for verbatim turns: a taken raw pulls the turns
either side of it within its Add chunk (`neighbours`, WINDOW_RADIUS=1). A taken
fact pulls nothing. This arm makes the symmetric move.

A fact's id is `{digest}-f{n}`; its chunk's turns are `{digest}-r{0..m}`. The
expansion takes the **`AMI_FACT_EVIDENCE` highest-scoring raws of that digest**,
by the embedding scores already computed for the query — so "of my chunk's turns,
the most relevant ones", at no extra cost. Pulled turns inherit the fact's score,
exactly as neighbours inherit theirs, so they land adjacent in relevance order.
`take()` is unchanged, so dedup, the return limit and the char budget all still
apply, and the expansion can only spend slots that the limit already allows.

**This is chunk-level, not claim-level.** It pulls the turns of the Add call the
fact came from, not the specific turns that support it — that would need the
extractor to emit turn indices, which lengthens the extraction prompt, which we
have measured moves the *base* by +1.75 (`lme_event_dates_add.md`). Arm 0 is
deliberately the version that costs no prompt change and therefore carries no
confound. If expansion does nothing here, the precise version is not worth buying.

## Store

**None is built.** This is a search-time change over stores that already exist:
`lme-t` (LongMemEval-S temporal-reasoning, 133 questions, 6,392 Add calls) and
the LoCoMo stores. No Add calls, no `gpt-4o-mini` spend, no ingest time. The
arm is a re-run of retrieval and answering only.

## Read before the arm

1. **Does it fire, and what does it cost?** Share of returned sets where a fact
   pulled at least one turn, and mean turns pulled. An arm that never fires is
   not a negative result about the mechanism.
2. **The slot tax, measured the way `locomo_rerank.md` measured it.** Distinct
   source chunks per returned set, and the raw/fact mix. The neighbour window
   trades breadth of sources for local context; this trades it again, on top.
   Base is 22.2 distinct chunks and 54.4 raw turns.
3. **Base parity is free here** — the store is the same store, so any difference
   is the switch and nothing else. This is the first arm in the project where
   that is true.

## Decision rule

Arms differ only in `AMI_FACT_EVIDENCE`: base 0, arm 2. Everything else as
shipped, including `AMI_RAW_FIRST=1` and `AMI_WINDOW_RADIUS=1`.

* **Primary gate, end to end:** LongMemEval-S temporal-reasoning, four replicates
  each, prefix 100, local judge, permutation 4v4 two-sided **p < 0.05** in the
  positive direction against the base's 57/58/59/60 (mean 58.50).
* **Secondary, and a veto:** LoCoMo cat1 **complete@100** must not fall below
  base. This is the metric the cross-encoder destroyed, and it is the one the
  mechanism claims to fix; a gain end-to-end while completeness falls means the
  stated mechanism is not what produced the gain, and the arm does not ship on
  that reading.
* Wilcoxon over the movers is reported alongside, not gated on.
* **Never gated on recall@k** (`bench/README.md`).

## Prediction

Completeness rises and breadth falls: complete@100 up on cat1, distinct source
chunks down from 22.2, because pulled turns spend slots that would otherwise
have gone to other chunks. End to end I expect a small positive, under +4.

Recorded with the standing caveat that this project has made two written
predictions about ranking changes and **both were wrong**. The prediction is here
to be scored, not to be believed.

## If it passes

It ships as `AMI_FACT_EVIDENCE=2`, a search-time switch with no Add-side cost and
no store migration — so it can be turned on and off against a built store, which
none of the event-date arms could. It preserves the project invariant: the
expansion changes *which* stored turns are returned and in what order, never the
text of any of them.

## If it fails

It closes arm 1 (claim-level evidence links) before that arm is built, since arm
1 buys precision on an expansion that did not help when it was free. It does not
close arm 2 (supersession ordering on a canonical fact key), which is a different
mechanism — ordering versions of one claim, not attaching evidence to a claim.
