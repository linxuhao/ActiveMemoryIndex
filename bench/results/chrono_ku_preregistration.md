# Pre-registration — raw-first + oldest-first on knowledge-update

Written 2026-09-22 after `lme_newest_first.md`, before the arm ran. Proposed by
the user as "two orderings: raw first; newest latest." Read this before any number.

## Why this arm

Newest-first ordering lost 9.25 of 78 on knowledge-update, and the loss was
ten settled questions answered with an *older* value while the newest, dated
statement sat at the top of the list. The reading that fits both the base and
that arm: **the reader treats position in the list as position in time and
takes the last mention as current, ignoring printed dates.**

If that is what the reader does, the ordering that serves it is the mirror:
within each block, **oldest first, newest last**, so the last mention of any
attribute is its current value. That ordering already exists —
`AMI_CHRONO_ORDER=1` sorts each `AMI_RAW_FIRST` block by `created_at`
ascending, undated last — and was measured once on temporal: 59/133 against
base 57/59, flat (`lme_temporal_baseline.md`). It has never been measured on
knowledge-update or on LoCoMo.

Nothing is built for this arm. No prompt change, no store rebuild; base
parity is exact.

## Decision rule

Arm = shipped configuration + `AMI_CHRONO_ORDER=1`. End to end on every
instrument, no coverage veto (coverage cannot change; asserted equal).

* **Primary gate:** `lme-ku`, four replicates, prefix 100, local judge.
  Permutation 4v4 two-sided **p < 0.05, positive**, against `kubase1–4`
  (57/58/56/57).
* **Guard 1:** LoCoMo `all10v2`, two replicates, against `lc2_base_r1–2`.
  Paired sign test over discordant questions; ships only if not
  significantly worse (p ≥ 0.05 or positive; discordance under ~6% is "no
  difference").
* **Guard 2:** `lme-t`, four replicates, against `base1–4` (57/59/60/58).
  Permutation 4v4; ships only if not significantly worse. The single earlier
  reading is not reused as a replicate.
* Ships as `AMI_CHRONO_ORDER=1` only if the gate passes and both guards hold.
  Wilcoxon over movers reported, not gated on. Never gated on recall@k.

## Reads before the gate

1. **The 13 stale questions** of `lme_knowledge_update_baseline.md`. This is
   the first arm where a mechanism predicts they move *toward* the current
   value. Reported per question.
2. **The 10 questions newest-first broke** (`06db6396 10e09553 41698283
   50635ada 6aeb4375 89941a93 8fb83627 affe2881 b01defab e493bb7c`). If the
   "last mention" reading is right they stay 4/4 here; if they fall, the
   reading is wrong regardless of the gate.
3. **The "previous value" questions** — `e66b632c`, `50635ada`, `10e09553`
   ask for the state *before* the current one. Under oldest-first the last
   mention is the current value, which is not what they want. Reported
   separately; a loss there is the arm's expected price, not a surprise.
4. Collateral on the 56 the base has 4/4.

## Prediction

`lme-ku` **positive**, +4 to +8, from the stale set; the 10 stay right; the
"previous" questions lose 1–2. `lme-t` flat as before. LoCoMo within noise.

**Standing caveat: six written predictions about the reader's response to an
ordering or salience change, six wrong.** This one differs only in that it was
derived from a measured failure rather than from a plausibility argument.
That is a reason to run it, not a reason to believe it.

## If it passes

Ships as `AMI_CHRONO_ORDER=1` alongside `AMI_RAW_FIRST=1` — the two orderings
the user named, order only, never membership or text. Shipping requires the
LoCoMo guard, since cycle 2's sources are unknown and LoCoMo is the shorter-
session instrument where the last two search-time mechanisms flipped sign.

## If it fails

Then "last mention wins" does not explain the reader either, and this project
has no ordering left to try on knowledge-update: relevance, newest-first and
oldest-first will all have been measured. The stale set would then need a
change in *what* is returned or how it is marked, each a separate
pre-registration.
