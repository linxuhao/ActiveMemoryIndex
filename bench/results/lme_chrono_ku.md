# Raw-first + oldest-first on knowledge-update — +1.0, not significant; ordering is exhausted

Read `chrono_ku_preregistration.md` first. Written before any number below.

## The gate: not passed

`lme-ku`, 78 questions, store unchanged, prefix 100, four replicates.
`AMI_CHRONO_ORDER=1` on top of the shipped configuration.

| arm | replicates | mean | vs base |
|---|---|---:|---:|
| `base` (`kubase1–4`) | 57 · 58 · 56 · 57 | 57.00 | — |
| `chrono` (`kuchrono1–4`) | 58 · 58 · 58 · 58 | **58.00** | **+1.00** |

No separation (base has a 58). Permutation 4v4 **p = 0.143**. Movers 4 up,
4 down. **Not significant; does not ship. `AMI_CHRONO_ORDER` stays 0.**

Coverage identical by construction. The switch did what it says: the old
value now precedes the new in 12 of 13 stale lists (base 8, newest-first 0).

## Guards, for the record

| instrument | base | chrono | delta | test |
|---|---:|---:|---:|---|
| `lme-t` 133 ×4 | 57·59·60·58 = 58.50 | 58·53·58·56 = 56.25 | −2.25 | perm p = 0.200; 18 up, 19 down |
| LoCoMo 1,540 ×2 | 1033·1028 = 1030.5 | 1037·1038 = 1037.5 | +7.0 | 220 discordant, 111 up, 109 down, p = 0.95 |

Both flat. Both guards would have held; the gate did not.

## The reads

**Read 1 — the 13 stale questions.** 3 up (`7401057b`, `b6019101`,
`f685340e`: 0→4/4, 0→4/4, 1→4/4), 2 down (`852ce960` 1→0, `a2f3aa27` 2→0),
8 unchanged at 0/4. With the current value now the *last* mention in 12 of
13 lists, the reader still answers the old value 4/4 in eight of them.

**Read 2 — the 10 questions newest-first broke.** All ten stay 4/4. This is
the one prediction in the file that held.

**Read 3 — the "previous value" questions.** `e66b632c` 0→0, `50635ada` 1→1,
`10e09553` 1→1. No price paid; the predicted loss of 1–2 did not happen.

**Read 4 — collateral on the 56.** Two fell 4/4 → 0/4: `618f13b2` (times worn
the Converse; a count) and `9ea5eabc` (most recent family trip: answers
Hawaii, gold Paris — an *older* trip, under the ordering built to put the
newest last).

## What three orderings say together

| order within each raw-first block | `lme-ku` | stale still wrong 4/4 |
|---|---:|---:|
| relevance (shipped) | 57.00 | 11 / 13 |
| newest first | 47.75 | 11 / 13 |
| oldest first | 58.00 | 8 / 13 |

The "last mention wins" reading from `lme_newest_first.md` survives one test
and fails the other. It predicted the ten collateral questions would come
back under oldest-first, and they did — so it does describe *something* the
reader does. But it also predicted the stale set would flip, and eight of
thirteen did not move under any of the three orderings, with the current
value at position 1, at position ~50, and last. **Where the old value is
stated as a direct assertion and the new one as an aside, order does not
reach the reader.** That was the observation recorded in the baseline; it is
now the finding.

Ordering as a lever on stale answers is measured out: three orderings,
one significant result, and it was negative.

## Prediction, scored

Predicted `lme-ku` +4 to +8 (actual **+1.0, n.s.**); the ten stay right
(**held**); "previous" questions lose 1–2 (actual **0**); temporal flat
(held); LoCoMo noise (held). The gate prediction was wrong. **Seventh written
prediction; the first with any component right, and the component that
mattered was not.**

## What remains of the State DAG versioning idea

Not an ordering. If the reader ignores position and printed date when the
old value is asserted more directly, the remaining levers change what is
returned or how it is marked:

* **Mark the superseded version at Add time** — a version link written when
  a later fact on the same attribute arrives, rendered as a prefix on the
  older fact. Query-independent, so the project invariant (the query never
  changes stored text) survives; but it changes returned text, and needs a
  canonical key from the extractor, i.e. a prompt change and a matched base.
* **Return only the current version** — drops text the user has said must
  not be dropped (`e66b632c` asks for the previous value). Closed by the
  user's rule before measurement.

Neither is registered here. Either would be its own pre-registration, with
end-to-end on all three instruments as the gate, and with the standing
caveat that its effect on the reader is not predictable from its design.
