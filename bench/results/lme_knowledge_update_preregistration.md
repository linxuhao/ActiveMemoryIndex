# Pre-registration — the knowledge-update baseline, before any supersession is built

Written 2026-09-22 before the store existed. Read this before any number.

## Why this subset, and why a baseline first

The idea on the table is fact **supersession**: the same fact extracted from two
sessions, keyed canonically, the newer version — by event time, not by Add
order — ranked above the older. `lme_fact_evidence.md` and `lme_chunk_memory.md`
tested the other half of the State-DAG proposal (fact → evidence links) and
closed it; **the versioning half has never been measured**, and neither has the
subset it is aimed at.

LongMemEval-S `knowledge-update`: 78 questions, 47.5 haystack sessions each,
~488 messages each. Every one of them is "X changed; what is X now?" — the
exact shape supersession exists for. `lme_temporal_baseline.md` mapped this
subset to **axis D, where we are already first (37.95)**. That mapping is ours,
not the platform's, and it is a reason to measure before building, not a reason
not to.

## The number this baseline exists to produce

Supersession can only help a question the reader got wrong **because it chose
the old value while the new one was in front of it**. It cannot help a question
whose new value was never returned, and it cannot help a question the reader
got wrong for some other reason. So the reachable headroom is not "1 − accuracy";
it is:

> **stale-with-evidence-returned** = wrong answers where (a) the returned set
> contains the turn carrying the current value and (b) the generated answer is a
> value the haystack held *earlier*.

That count, out of 78, is the ceiling of the whole mechanism on this instrument.
If it is small, no implementation quality reaches past it.

## Store and arm

`lme-ku`: LongMemEval-S `knowledge-update`, 78 questions, ~1,950 Add calls,
shipped configuration (`AMI_RAW_FIRST=1`, `AMI_WINDOW_RADIUS=1`, every
September switch off). One arm, `kubase`, **four end-to-end replicates**, prefix
100, `gpt-4o-mini` answer and judge as the platform does it.

## Reads, in order

1. **Accuracy, four replicates, and the spread** — the noise floor of this
   instrument before anything is judged against it. On temporal the floor was
   ~8 discordant of 133; here n=78, so expect worse resolution.
2. **Coverage**: `all-turns`, `all-chunks`, `all-sess` from `report`. If the
   current value's turn is usually *not* returned, the loss is upstream of the
   reader and supersession is the wrong tool — retrieval is.
3. **Failure-mode classification of every wrong answer** (mean over replicates;
   a question counts as wrong if wrong in ≥2 of 4), by reading the generated
   answer against the gold and the haystack:
   * **stale** — the answer is a value the haystack held earlier for the same
     attribute;
   * **missing** — the current value's turn is not in the returned set;
   * **other** — evidence returned, answer neither stale nor current.
   Each wrong question gets exactly one label and the label is recorded per
   question id in the results file so it can be checked.
4. **stale-with-evidence-returned** = stale ∩ (current turn in returned set).

## Decision rule for what happens next

* **stale-with-evidence-returned ≥ 8 of 78** (≈10pp, above what four replicates
  at n=78 can resolve): supersession has room. Its own pre-registration follows,
  with a matched base for any extraction-prompt change (the confound that moved
  the base +1.75 in `lme_event_dates_add.md`), and — per the lesson of the last
  two arms — **end to end on both corpora as the gate, no coverage veto.**
* **Below 8**: the mechanism is not worth building on this instrument. That is
  recorded as the result and the State-DAG line closes unless a different
  instrument shows a different failure mix.
* `missing` dominating the wrong answers is its own finding — it says the
  knowledge-update loss is retrieval-side, and points back at selection rather
  than at versioning.

## Prediction

Accuracy between 45% and 60% (35–47 of 78). Stale is a **minority** of wrong
answers — under 40% of them — because the reader, given both values in a
timestamped list, mostly picks the later one already; and stale-with-evidence-
returned lands **below 8**.

Recorded with the standing caveat that four written predictions about how the
reader responds to what it is shown have all been wrong. This one is about a
failure *mix* rather than a direction, which is a different kind of claim, and
it is here to be scored.
