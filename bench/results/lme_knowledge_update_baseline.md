# Knowledge-update baseline — supersession has room, and the room is not where I said

Read `lme_knowledge_update_preregistration.md` first. Written before the store
existed; every number here came after.

## Accuracy and coverage

`lme-ku`: 78 questions, 3,734 Add calls, shipped configuration, four end-to-end
replicates at prefix 100.

| replicate | correct / 78 | all-turns complete | chars/q |
|---|---:|---:|---:|
| `kubase1` | 57 | 1.000 | 80,048 |
| `kubase2` | 58 | 1.000 | 80,052 |
| `kubase3` | 56 | 1.000 | 80,390 |
| `kubase4` | 57 | 1.000 | 79,994 |
| **mean** | **57.0 = 73.1%** | | |

Coverage is saturated: every gold turn is inside the returned set in every
replicate, for every question. **`missing` = 0.** Whatever is lost on this subset
is lost after retrieval — the same shape `lme_temporal_baseline.md` found for
temporal, and it holds here without exception.

## Every wrong answer, labelled

Wrong in ≥2 of 4 replicates: **22 of 78**. One label each, per the rule.

| qid | label | old value → current | answered (×/4) |
|---|---|---|---|
| `031748ae` | **stale** | 4 engineers → five | 4 (4/4) |
| `07741c45` | **stale** | under my bed → shoe rack in closet | under bed (4/4) |
| `0f05491a` | **stale** | 125 stars → 120 | 125 (4/4) |
| `59524333` | **stale** | gym 7:00 pm → 6:00 pm | 7:00 (4/4) |
| `69fee5aa` | **stale** | 37 coins → +1 = 38 | 37 (4/4) |
| `6a1eabeb` | **stale** | 5K PB 27:12 → 25:50 | 27:12 (4/4) |
| `7401057b` | **stale** | one free night → two | one (4/4) |
| `830ce83f` | **stale** | Rachel: Chicago → the suburbs | Chicago (4/4) |
| `852ce960` | **stale** | pre-approved $350k → $400k | $350k (3/4) |
| `a2f3aa27` | **stale** | 1250 followers → ~1300 | 1250 (2/4) |
| `b6019101` | **stale** | 4 MCU films → 5 | 4 (4/4) |
| `ba61f0b9` | **stale** | 5 women (half of 10) → 6 | 5 (4/4) |
| `f685340e` | **stale** | weekly tennis → every other week | weekly (3/4) |
| `4b24c848` | other | 3 tops → 5; answered **eight** (summed both) | 4/4 |
| `e66b632c` | other | asks for the *previous* PB; answered a later statement | 4/4 |
| `22d2cb42` | other | "music shop on Main St" vs "Rhythm Central on Main St" — same shop, judged wrong | 4/4 |
| `ed4ddc30` | other | **judge false negative**: answered "20 dozen", gold "20" | 4/4 |
| `031748ae_abs` | abstain | should refuse (role never mentioned); answered anyway | 4/4 |
| `0ddfec37_abs` | abstain | football vs baseball | 4/4 |
| `2133c1b5_abs` | abstain | Shinjuku vs Harajuku | 4/4 |
| `2698e78f_abs` | abstain | Dr. Johnson vs Dr. Smith | 4/4 |
| `f685340e_abs` | abstain | table tennis vs tennis | 4/4 |

| label | n | supersession can reach it? |
|---|---:|---|
| **stale** | **13** | **yes — this is the whole target** |
| abstain | 5 | no (a refusal problem, not a versioning one) |
| other | 4 | no |
| missing | 0 | — |

**stale-with-evidence-returned = 13 of 78.** The rule said ≥ 8 means the
mechanism has room. It has room: a ceiling of **16.7pp on this subset**, and
11 of the 13 are wrong in **4 of 4** replicates — a deterministic bias, not
sampling noise.

## Where the two values live

For the 13 stale questions, the returned set was searched for the old and the
current value, as verbatim turns and as extracted facts, over all four replicates.

| | old value | current value |
|---|---:|---:|
| present as an extracted **fact** | **13 / 13** | **13 / 13** |
| present as a verbatim turn | 13 / 13 | 13 / 13 |
| appears **earlier** in the returned list | 8 / 13 | 5 / 13 |

Two things follow.

**The extractor is not the problem.** It captured the update in every single
case; both versions sit in the store as clean first-person facts. The store
holds two competing claims about one attribute and nothing marks which is
current. That is exactly the object supersession would act on, and it exists.

**Order is only part of the problem.** In 8 of 13 the old value comes first in
the list and "the reader took the first value it saw" is a live explanation.
In the other 5 the current value comes first — at **position 1** in
`07741c45`, `59524333`, `6a1eabeb`, `b6019101` (old value at 5.5–6), and at 5
against 11 in `f685340e` — and the reader still answers the old one, 4/4 in
four of them. A pure ordering change cannot reach those five.

Looking at the evidence text, the old value tends to be a direct assertion
("I lead a team of 4 engineers", "I need 125 stars") and the update tends to be
a "by the way" aside inside an unrelated request. That is an observation about
the corpus, recorded as such; per this project's standing constraint it is not
a prediction about what the reader will do if the aside is made more salient.

## Prediction, scored

I predicted accuracy 45–60%, stale a minority of wrong answers (< 40%), and
stale-with-evidence-returned below 8.

Actual: **73.1%**, stale **13 of 22 = 59%**, stale-with-evidence-returned
**13**. Wrong on all three. Fifth written prediction in this project, fifth
wrong — this one about a failure *mix*, so the miss is not only about reader
salience; I underestimated the reader overall and underestimated how
systematically it prefers the earlier statement.

## What this licenses

Per the pre-registration: a supersession pre-registration follows. Two rungs,
because the second read above splits the target:

1. **Ordering only** — within the returned set, the newer of two same-attribute
   facts ahead of the older. No canonical key needed if done by global
   newest-first ordering of the fact block; a search-time switch, no prompt
   change, no confound. Ceiling: the 8 order-explained questions.
2. **Versioning** — a canonical attribute key from the extractor, the older
   version demoted (never dropped: the user's rule, and `e66b632c` asks for the
   *previous* value and needs it). Needs a matched base, because it lengthens
   the extraction prompt and that moved the base +1.75 last time.

Gate for either: **end to end on both corpora, no coverage veto**, per
`lme_fact_evidence.md`. LoCoMo has no knowledge-update label, so on LoCoMo the
gate is "not significantly worse", and the gain has to come from here.

Axis note, unchanged: this subset maps to D, where we are already first. The
16.7pp ceiling is real but it is a ceiling on our strongest axis.
