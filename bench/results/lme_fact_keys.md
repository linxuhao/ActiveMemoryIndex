# Supersession by extractor key — +0.25, p = 1.0; closed. The prompt moved the base instead.

Read `fact_keys_preregistration.md` and its two amendments first. Every
number here came after.

## The gate: failed

`lme-ku-k` (3,734 Add calls with `AMI_FACT_KEYS=1`), 78 knowledge-update
questions, prefix 100, four replicates per arm, both arms on the same store.

| arm | replicates | mean | vs matched base |
|---|---|---:|---:|
| `kbase` (`AMI_SUPERSEDE_MARK=0`) | 59 · 61 · 59 · 59 | 59.50 | — |
| `kmark` (`AMI_SUPERSEDE_MARK=1`) | 59 · 59 · 63 · 58 | 59.75 | **+0.25** |

Permutation 4v4 **p = 1.000**. Movers 5 up, 4 down. **Not significant; does
not ship. `AMI_SUPERSEDE_MARK` stays 0. The guards were not built**, per the
rule that they are guards on shipping only. Coverage 1.000 on every measure
for both arms, as expected.

## Reads

**Firing.** 1,751 of 25,203 facts got a key (6.9%). Of 2,241 returned facts
across the 78 questions, **19 were marked** (0.8%), on 18 questions. The
marks added nothing measurable to the text (86,511 vs 86,553 chars/q).

**Precision of what fired.** All 19 delivered markers were read. About 15
attach a genuine later value of the same attribute — 5K PB 25:50 over 27:12,
1300 followers over 1250, gym 6:00 over 7:00, 6 women over 5, 120 stars over
125, 600 followers over 500. The link, once a key exists on both sides, is
**right**. The cosine link could not do this; the key can.

**The 13 stale questions** (old base → keyed base → keyed base + marks):

| qid | old base | `kbase` | `kmark` | marked |
|---|---:|---:|---:|---|
| `031748ae` | 0.00 | 1.00 | 1.00 | yes |
| `0f05491a` | 0.00 | 1.00 | 0.75 | yes |
| `830ce83f` | 0.00 | 1.00 | 1.00 | — |
| `a2f3aa27` | 0.50 | 1.00 | **0.25** | yes — correct marker, 1300 over 1250 |
| `f685340e` | 0.25 | 0.75 | 1.00 | — |
| `6a1eabeb` | 0.00 | 0.00 | **1.00** | yes — correct marker, 25:50 over 27:12 |
| `59524333` | 0.00 | 0.00 | 0.25 | yes — correct marker, 6:00 over 7:00 |
| `ba61f0b9` | 0.00 | 0.00 | 0.00 | yes — correct marker, 6 women over 5 |
| `7401057b` | 0.00 | 0.25 | 0.00 | — |
| `852ce960` | 0.25 | 0.00 | 0.25 | — |
| `69fee5aa`, `07741c45`, `b6019101` | 0.00 | 0.00 | 0.00 | — |

Six stale questions carried a marker, and in five of them the marker was
the exact right update, placed on the old assertion itself, in the old
assertion's register. Result on those five: +1.00, +0.25, +0.00, −0.25,
**−0.75**. Net ≈ 0. The reader, handed `[superseded on 2023-05-25 by:
… close to 1300 followers] … I have 1250 followers`, answered 1250 three
times out of four.

**Previous-value questions** all unchanged at 1.00. **Collateral:** three
questions fell below 4/4, two of them stale ones with correct markers.

## What moved: the prompt, not the marks

| | `kubase` (old prompt) | `kbase` (keyed prompt) | delta |
|---|---:|---:|---:|
| accuracy /78 | 57 · 58 · 56 · 57 = 57.00 | 59 · 61 · 59 · 59 = 59.50 | **+2.50**, perm p = 0.029 |
| facts extracted | 38,859 | 25,203 | **−35%** |
| mean fact length | 120 chars | 114 chars | |
| chars returned /q | 80,048 | 86,925 | +8.6% (more raw turns fill the slots) |

Asking for a key changed what the extractor writes: a third fewer facts,
and four of the thirteen stale questions fixed before any marker existed
(`031748ae`, `0f05491a`, `830ce83f`, `a2f3aa27`). **This was not a registered
arm.** It is an Add-side prompt change measured on one subset with no guard
on either other instrument, and the mechanism is unknown — fewer facts means
more verbatim turns in the hundred, which is a different delivery, not a
better extraction. It is recorded as a lead: if it is ever to ship it needs
its own pre-registration with `lme-t` and LoCoMo stores rebuilt under it.

## Prediction, scored

Key agreement 8–11 of 13: **3**. Gate +3 to +6: **+0.25**. Prompt effect
within ±2: **+2.5, significant**. Wrong on all three. **Eighth written
prediction about the reader; eighth wrong on the gate** — and this one had
the link *right* and the delivery *exact*, and the reader still did not
take it.

## What is closed

The State DAG's versioning half, at search time, in full:

| lever | result |
|---|---|
| ordering: relevance / newest-first / oldest-first | 57.0 / 47.75 (p=0.029 −) / 58.0 (n.s.) |
| mark old fact with cosine-linked successor | closed at calibration, precision ≤ 0.20 |
| mark old fact with key-linked successor | **+0.25, p = 1.0**; markers correct, reader unmoved |

The stale failures are not a retrieval problem (coverage 1.000), not an
ordering problem (three orderings), not a linking problem (the key link is
right), and not a delivery problem (the update was attached to the very
sentence the reader was misreading). What is left is the reader's own
weighting of a direct assertion over a qualified one, and that is not
something this system's `/search` can change without changing what it says
it does. Add-time consolidation — rewriting the old fact — is the one move
left, and it is a different system.
