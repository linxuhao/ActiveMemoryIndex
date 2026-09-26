# Oracle withholding — the old value's presence is what the reader answers from (2026-09-26)

Pre-registration: `supersede_drop_preregistration.md` (stage 1). Script:
`bench/splice_oracle_drop.py`. Base: `kbase1–4` (keyed-prompt store
`lme-ku-k`, `lme_fact_keys.md`). Splice: `kdrop_o1–4` — the 13 stale
knowledge-update questions with every returned memory carrying the gold old
value removed (facts and raw turns; 2–11 items of 100, identical across
replicates because retrieval is deterministic), nothing backfilled, the new
value verified present in every spliced list. Answer + judge at prefix 100,
four replicates, same model and prompts.

## Result

| qid | kbase | splice | |
|---|---:|---:|---|
| 07741c45 under my bed → shoe rack | 0/4 | **4/4** | |
| 59524333 gym 7:00 → 6:00 pm | 0/4 | **4/4** | |
| 6a1eabeb 5K 27:12 → 25:50 | 0/4 | **4/4** | |
| 7401057b one free night → two | 1/4 | **4/4** | |
| 852ce960 pre-approved $350k → $400k | 0/4 | **4/4** | |
| b6019101 4 MCU films → 5 | 0/4 | **4/4** | |
| ba61f0b9 5 women → 6 | 0/4 | **4/4** | |
| 69fee5aa 37 coins → 38 | 0/4 | 0/4 | new value never stated: store says "I added a new coin"; 38 = 37 + 1, and 37 was withheld |
| 0f05491a 125 stars → 120 | 4/4 | 4/4 | already fixed by the keyed prompt |
| 830ce83f Chicago → suburbs | 4/4 | 4/4 | already fixed by the keyed prompt |
| a2f3aa27 1250 → ~1300 followers | 4/4 | 4/4 | already fixed by the keyed prompt |
| 031748ae *then 4 → now 5* engineers | 4/4 | **0/4** | two-part: asks for the old value too |
| f685340e *weekly → every other week* | 3/4 | **0/4** | two-part: asks for the old value too |
| **13 questions, per replicate** | 4 · 6 · 5 · 5 | **10 · 10 · 10 · 10** | |

**Seven of the eight questions that were still stale under `kbase` flip to
4/4 with complete separation.** The eighth cannot flip by withholding: its
new value is an increment on the old one, so removing the old value removes
the arithmetic's input. The two two-part questions fall to 0/4 exactly as
registered — withholding the old value destroys what a history question
needs.

## Against the pre-registered readings

The readings were written over SINGLE = 11. Three of the eleven were
already 4/4 under the keyed prompt (`lme_fact_keys.md`'s +2.5 moved exactly
these) and could not flip; the pre-registration fixed its populations from
the old-prompt baseline table without re-checking `kbase`. By the letter,
**7 of 11 flipped → the "4–7, report, no build" band.** By the measure the
rule was written to capture — of the questions that *could* flip, how many
did — it is **7 of 8, and 7 of 7 whose new value is stated in the store.**
Both are reported; the denominator error is mine and is recorded here rather
than repaired after the fact. The eleventh prediction ("9 of 11 flip; the
two-part fall to 0/4") was wrong on the count for the same denominator
reason and right on the collateral.

## What it settles

**The reader's stale answer is a membership problem.** With the old value's
sentences absent — and only then — gpt-4o-mini answers the hedged update it
had been ignoring under three orderings and two markings. This closes the
2026-09-22 finding's open half: "a direct assertion outweighs a hedged
update" is about the assertion being *present*, not about the update being
unreadable. It also says why every search-time versioning arm was flat:
each left the old sentence in the list.

Where the old value lives matters: in 13 of 13 stale questions it is in
returned **raw turns**, delivered first. A fact-only drop (`superseded()`
turned into a filter) reaches zero of them (stage 0 in the
pre-registration). Any real mechanism has to withhold verbatim turns, and
that is where the cost sits: a raw turn carries more than the one value.

## What it does not settle, and what a stage 2 would have to carry

This was an oracle: the old value was chosen with the gold answer. The three
things a non-oracle mechanism needs are each visible in this table:

1. **Identify the old value's sentences without the gold.** The key link
   finds the old *fact* in 6 of 13; reaching its raw turns needs a value
   string — the extractor would have to emit `(text, key, value)` — and then
   a lexical match inside the old fact's own chunk. Reach ≤ 6 of 8 by the
   current link rate.
2. **Do not withhold when the question asks for history.** Two of 13 here,
   and the temporal subset is full of them. A question-form router (the same
   kind of regex that gates the +11 date hint) is the cheapest gate; its
   leak rate is the collateral.
3. **Do not withhold when the new value is defined relative to the old.**
   "I added one" needs 37 on the page. Detectable at extraction (value is
   relative) — or not detectable, in which case it is the floor on the loss.

None of that is built. This file's job was the causal question, and the
answer is yes: presence is the cause.
