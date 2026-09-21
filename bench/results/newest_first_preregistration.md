# Pre-registration — newest-first ordering (supersession, rung 1)

Written 2026-09-22 after `lme_knowledge_update_baseline.md` and before the
switch was implemented. Read this before any number.

## Why this arm, and why first

The knowledge-update baseline found 13 of 78 questions answered with a value
the user had since replaced, while **both** the old and the new value sat in
the returned set as extracted facts, 13 of 13 times. In 8 of the 13 the old
value appears earlier in the returned list than the new one; in 11 of 13 the
reader chose the old value in 4 of 4 replicates.

The user's State DAG proposal has two halves: link a fact to its evidence
(measured three ways, closed — `lme_fact_evidence.md`, `lme_chunk_memory.md`)
and **version** facts so that a later statement about the same attribute
supersedes an earlier one without deleting it. The cheapest thing that
versioning could do at search time is put the newer version in front of the
older. This arm does exactly that and nothing else, without a canonical key:

> Inside each block that `AMI_RAW_FIRST` already forms, order the returned
> memories **newest first** by their stored timestamp.

It is a one-line variant of `AMI_CHRONO_ORDER`, which orders oldest-first and
measured flat on temporal (`lme_temporal_baseline.md`, closed). It changes
order only, never membership, never text — the project invariant holds. No
prompt changes, no store rebuild, so **base parity is exact**: the base
replicates already on disk are the base.

If ordering alone cannot move the 8 questions it can reach, then the
demotion half of rung 2 (canonical-key versioning) has no mechanism either,
and rung 2 would need to be something other than an ordering — that is worth
knowing before paying for the extraction-prompt change and its matched base.

## What changes

`app/config.py`: `NEWEST_FIRST = _env("AMI_NEWEST_FIRST", "0") != "0"`.
`app/main.py` `order()`: when set, a stable sort by `created_at` descending
**before** the existing raw-first block sort, so the block structure is
untouched and each block is newest-first inside. Undated memories sort last.
`created_at` is the message's own timestamp (`stamp(message.timestamp)`), i.e.
event time, not Add time. If `AMI_CHRONO_ORDER` is also set it wins; the two
are not meant to be combined.

## Stores

None built. Three existing stores, search-time only:
`lme-ku` (knowledge-update, 78 q), `lme-t` (temporal-reasoning, 133 q),
`all10v2` (LoCoMo, 1,540 q). Bases already on disk: `kubase1–4`
(57/58/56/57), `base1–4` on `lme-t` (57/59/60/58), `lc2_base_r1–2`
(1033/1028). Same image lineage, same config, switch default off.

## Decision rule

Arm differs from base in `AMI_NEWEST_FIRST` only. Per the lesson of the last
two arms: **end to end on every instrument, no coverage veto.** Coverage cannot
change — the switch does not touch membership — and will be asserted equal, not
read.

* **Primary gate:** `lme-ku`, four replicates, prefix 100, local judge.
  Permutation 4v4 two-sided **p < 0.05**, positive, against `kubase1–4`.
* **Guard 1:** LoCoMo `all10v2`, two replicates, against `lc2_base_r1–2`.
  Paired sign test on discordant questions, two-sided. Ships only if **not
  significantly worse** (p ≥ 0.05, or positive). Discordance under the ~6%
  floor is "no difference".
* **Guard 2:** `lme-t`, four replicates, against `base1–4`. Permutation 4v4,
  ships only if not significantly worse. This is the instrument where the
  opposite ordering was flat; a global ordering change cannot ship without a
  reading here.
* Ships as `AMI_NEWEST_FIRST=1` only if the gate passes **and** both guards
  hold. Wilcoxon over movers reported alongside, not gated on.
* Never gated on recall@k.

## Reads before the gate

1. **Which of the 13 stale questions flip.** Split by the baseline's own
   labelling: the 8 where the old value was earlier in the list, and the 5
   where the new value was already first. The mechanism predicts movement in
   the 8 and none in the 5. Movement in the 5 means something other than
   "the reader takes the first statement" is at work, and the mechanism read
   is wrong even if the gate passes.
2. **Collateral on the 56 questions the baseline got right in 4/4.** An
   ordering change touches every returned set; the cost is what it breaks.
3. Position of the old and new value in the arm's returned lists, to confirm
   the switch actually inverted them (a check on the code, not on the reader).

## Prediction

`lme-ku` **+3 to +6** of 78 (some of the 8, none of the 5, minus collateral).
LoCoMo within the noise floor. `lme-t` flat, as its mirror image was.

Recorded with the standing caveat: this project has made **five** written
predictions about how the reader responds to a ranking or salience change and
**all five were wrong**, the last one on all three of its counts. The
prediction is here to be scored, not believed.

## If it passes

Ships as `AMI_NEWEST_FIRST=1`, and rung 2 (canonical-key versioning with the
older version demoted, never dropped) is pre-registered on top of it, with a
matched base for the extraction-prompt change.

## If it fails

Ordering is not how supersession reaches the reader. Rung 2 as "demote the
older version" is closed before it is built; anything that remains of the
versioning idea has to change what is returned or how it is marked, and each
of those is a separate pre-registration with its own confound accounting.
