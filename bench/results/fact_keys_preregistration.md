# Pre-registration — supersession by extractor key (State DAG rung 2)

Written 2026-09-22 after `supersede_mark_calibration.md`, before any code.
Read this before any number.

## Why this arm

The delivery is built: `superseded()` renders an old fact with its latest
successor attached, from the store alone, keeping the old node. What closed
it was the *link*: fact-embedding cosine ranks the true successor top-3
among hundreds in 12 of 12 stale pairs but cannot threshold it (precision
≤ 0.20 at every τ). The pre-registration said the thing that turns rank into
a decision is a canonical key from the extractor. This is that arm.

## What changes

`AMI_FACT_KEYS=1` (Add side). The extraction prompt asks for
`{"facts": [{"text": "...", "key": "..." | null}]}` where `key` is
`<subject>.<attribute>` — `me.team_size`, `me.gym_time`, `rachel.location`,
`me.instagram_followers` — for a fact that states the **current value of a
property that can change**, and `null` for events, requests, opinions and
anything with no mutable value. Same attribute → same key, every time.
Keys are stored (`items.fact_key`, added by `ALTER TABLE` on old stores),
indexed per user (`UserIndex.by_key`), and otherwise inert.

`AMI_SUPERSEDE_MARK=1` (Search side) then links **by key equality**: for a
returned keyed fact, the successor is the latest strictly-later fact of the
same user with the same key. Unkeyed facts are never marked. The cosine path
stays closed. Rendering is unchanged from the calibration file.

The prompt is written once, before the smoke, and **frozen**. The only edits
allowed after the smoke are format fixes (JSON that fails to parse), declared
in an amendment. No rewording on the strength of what keys come back.

## Stores and the confound

A prompt change moves the base (+1.75 measured, `lme_event_dates_add.md`).
So the store is rebuilt with the new prompt and **both arms run on it**:

* `lme-ku-k` — 3,734 Add calls with `AMI_FACT_KEYS=1`.
* `kbase1–4`: `AMI_SUPERSEDE_MARK=0` on `lme-ku-k` — the matched base.
* `kmark1–4`: `AMI_SUPERSEDE_MARK=1` on `lme-ku-k` — the arm.

`kbase` against the old `kubase1–4` (57.00) is the prompt's own effect,
**reported, not gated**.

Guards need `lme-t-k` (6,392 Add calls) and `all10v2-k` (LoCoMo). They are
guards on *shipping*, not on the reading, so **they are built only if the
gate passes.** If the gate fails, the arm closes on `lme-ku-k` alone.

## Smoke, before the run

1. Unit tests: parser accepts both the old string form and the new object
   form; keys land in the store and index; key-linking marks the right
   successor, ignores different keys, never marks unkeyed or raw items.
2. Live extraction on the chunks holding the old and the new statement of
   each of the 13 stale pairs: does the extractor key both, and with the
   **same** key? Reported as agreement /13. **This is a firing read, not a
   tuning step** — the prompt does not change after it. If agreement is
   below 6/13 the arm still runs; that number is the ceiling.

## Decision rule

* **Primary gate:** `lme-ku-k`, `kmark1–4` vs `kbase1–4`, prefix 100,
  permutation 4v4 two-sided **p < 0.05, positive**.
* **Guard 1 (only if the gate passes):** LoCoMo `all10v2-k`, mark vs base
  ×2, paired sign test; ships only if not significantly worse.
* **Guard 2 (only if the gate passes):** `lme-t-k`, mark vs base ×4;
  permutation; ships only if not significantly worse.
* Coverage identical between mark and base by construction (same store,
  same selection). The prompt change *can* change coverage; reported.
* Never gated on recall@k.

## Reads

1. The 13 stale questions, per question: keyed on both sides? marked?
   answered with the current value?
2. Share of facts keyed; share of returned facts marked; characters added.
3. Precision of delivered markers on `lme-ku-k`, hand-judged sample of 20.
4. Collateral on the base's 4/4 set and the three "previous value"
   questions.
5. Prompt effect: `kbase` vs `kubase`.

## Prediction

Key agreement on the stale pairs **8–11 of 13**. Gate **+3 to +6**. Prompt
effect within ±2.

Seven written predictions about the reader, seven wrong on the gate. Scored,
not believed.

## If it passes

Ships as `AMI_FACT_KEYS=1` + `AMI_SUPERSEDE_MARK=1` after the guards. The
State DAG versioning half is then live: node = fact, key = attribute,
successor link at search time, nothing deleted.

## If it fails

Versioning at search time is closed in full: three orderings, cosine
marking, key marking. The remaining move is Add-time consolidation, which
rewrites stored text and is a different system.

## Amendment 2026-09-22 — smoke done; one format fix; ceiling 3/13

**Format fix, declared.** The first smoke lost 3 of 26 chunks to parse
failures: gpt-4o-mini closed the list with a stray brace (`}}]}`) twice, and
once mixed malformed `{"text":"x":"y"}` entries into the reply. The parser
now salvages each well-formed `{"text", "key"}` object on its own
(`95fda1f`). The prompt did not change. Second smoke: 0 of 26 parse failures.

**Smoke result (second run).** Keyed on both sides 4/13; **same key 3/13**
(`031748ae` me.team_size, `59524333` me.gym_time, `6a1eabeb`
me.5k_personal_best). One disagreement (`b6019101`: me.mcu_films_watched vs
me.movie_count). Nine pairs unkeyed on at least one side — nearly always the
**new** statement, the one phrased as an aside, which the extractor keys as
`null`. Below the 6/13 line: per the rule the arm still runs, and 3/13 is
the ceiling to read the gate against. Prediction of 8–11 agreement: wrong.
