# Facts select, the chunk is delivered whole — measured, failed, family closed

Read `chunk_memory_preregistration.md` first, including its 2026-09-22
amendment. Both were written before the numbers below existed.

## What was asked

Nineteen recovered cycle-1 LoCoMo arms (`locomo_lost_arms.md`) left one diagonal
unoccupied. `factonly` selected with facts and delivered facts: the best
retrieval coverage in the project, complete@100 .904 against .850, and the worst
accuracy of any non-degenerate arm, .5127 against .6802. `parent` delivered
whole chunks chosen by an ordinary embedding ranker and scored .7114, the
highest number in the set. Nobody had run `factonly`'s selection with `parent`'s
delivery.

## Read one: the budget veto, before any accuracy number

| arm | memories/q | chars/q | all-turns complete |
|---|---:|---:|---:|
| `base` (shipped) | 100.0 | 77,263 | 0.924 |
| `chunkmem` (delivery only) | 36.5 | **398,840** | 1.000 |
| `factsel` (the arm) | 35.3 | **397,782** | 1.000 |

Both sat on `AMI_RETURN_CHAR_BUDGET`'s ceiling of 400,000 — clipped by it, which
the pre-registration named as disqualifying — or ~99,700 tokens of the
platform's 117,760-token Answer budget. Neither was answered. The +7.6pp of
strict turn completeness they bought cost 5.2x the text.

## Read two: at matched text, it loses by seven questions

`capsel` = `AMI_FACT_SELECT=1` + `AMI_CHUNK_MEMORY=1` + `AMI_RETURN_CHAR_BUDGET`
set to `base`'s own 77,263, so the volume confound is gone. LongMemEval-S
temporal-reasoning, 133 questions, prefix 100, four replicates each.

| arm | replicates | mean | vs base |
|---|---|---:|---:|
| `base` | 57 · 59 · 60 · 58 | 58.50 | — |
| `capsel` | 54 · 50 · 51 · 51 | **51.50** | **−7.00** |

Complete separation: the best `capsel` run (54) is below the worst `base` run
(57). Permutation 4v4 two-sided **p = 2/70 = 0.029**, in the negative direction.
The gate required a positive direction. **Failed.**

Per the amendment, written before the run, the delivery-only control is
therefore not run: with nothing gained there is nothing to attribute.

## Why it lost, which is the part worth keeping

| | memories/q | chars/q | all-turns complete |
|---|---:|---:|---:|
| `base` | 100.0 | 77,263 | **0.924** |
| `capsel` | 7.2 | 76,557 | **0.924** |

**Identical evidence completeness. Identical text volume. Seven fewer questions.**

It is not coverage — that is equal to three decimal places, and fact selection
reached exactly the evidence the shipped mixed selection reaches. It is not
volume — that was matched by construction. What is left is **granularity**: with
evidence and text held constant, the reader does worse given seven large blocks
than given a hundred small targeted ones.

That is the same direction as every other result in this project that touched
the unit of delivery — `AMI_RAW_FIRST` (+4.5pt), the raw-share gradient across
five LoCoMo arms, `parentcap`'s .5718 against .6802 — and it is now measured
with the two obvious confounds removed rather than inferred across arms that
varied several things at once.

## The structural ceiling this family has

The platform grants two budgets at once: **100 slots and ~117,760 tokens.**
Delivering turns spends both efficiently — 100 memories inside 77k characters.
Delivering whole chunks exhausts the token budget at **7.2 memories and leaves
93 slots unused**. No ranking improvement recovers those slots, because the
constraint is the size of the delivery unit, not the quality of the selection.

`parent` won on LoCoMo because LoCoMo chunks average ~2,600 characters, so 23.9
of them fit. LongMemEval chunks average ~10,900, so 7 of them fill the budget.
The arm that won there cannot exist here. **A result about the unit of delivery
does not transfer between corpora with different session lengths** — which is
the first time this project has had a mechanism whose sign is set by a property
of the data rather than of the reader.

## Status of the switches

`AMI_FACT_SELECT` and `AMI_CHUNK_MEMORY` stay in the tree, both default off,
like every other failed arm's switch. Fact-only selection has now been measured
with both deliveries — lossy (`factonly`, −16.8pp on LoCoMo) and verbatim
(`capsel`, −7.00 here). The family is closed.

What is *not* closed: `AMI_FACT_EVIDENCE` (`fact_evidence_preregistration.md`),
which expands a fact by two turns rather than by its whole chunk and so does not
pay the slot cost measured above. Its own note already records that it fires
only when a fact outranks turns, and read 1 of that arm is still unrun.
