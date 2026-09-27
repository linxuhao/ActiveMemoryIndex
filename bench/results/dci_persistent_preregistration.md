# Pre-registration — persistent DCI searcher (2026-09-28)

Written before the arm is built or run. Follows `dci_search.md`, whose gate
failed (KU −6.75 for `dci`, −0.25 for `dcifill`) with a searcher that used
**1.8 of 12** tool calls on the KU gate: one grep, then `finish`, returning
the first plausible statement ("Ford Mustang" when the later project is the
F-150; "four times" when the latest count is six). That arm's system prompt
said *"Stop as soon as you have the evidence."* — the harness told the model
to stop early, then the result was read as "the searcher is lazy". The DCI
paper's searcher does the opposite: chained searches, local peeks,
re-localisation, plans revised on what it finds. So the paper's central
behaviour has not yet been tested under our hand-off. This arm tests it.

> **Research question.** Is the `dci` loss on the KU gate the harness's early
> stop (recoverable by making the searcher persist), or the narrowness of an
> agent-chosen set for a fixed reader (not recoverable that way)?

This is a replication of the paper's described behaviour, not prompt tuning
against a benchmark: every change below maps to a behaviour the paper
describes, none maps to a question in any corpus.

## Mechanism (`AMI_DCI_MIN_CALLS=N`, default 0 = today's behaviour)

Everything in `dci_search_preregistration.md` stands (corpus view, three
tools, budget 12, `finish` with ids only, fallback). With `N > 0`:

1. **Instruction.** The line *"Stop as soon as you have the evidence"* is
   replaced by: do not stop at the first match; after every hit, grep again
   for the subject of that hit (its noun, name, number, or a synonym) with
   context, to find later restatements or updates of the same thing; read
   around a hit when a pronoun is unresolved; finish only once the value you
   found has been checked for later updates; the budget is stated.
2. **Minimum probes.** A `finish` issued before `N` tool calls is refused.
   The refusal is a tool result: *"Not yet: k of at least N searches done.
   Grep the subject of your best hit again, with context, to check for a
   later restatement or update; then finish."* The refused `finish` counts
   as one call toward the budget, so the loop still terminates: at the
   budget the model is offered `finish` only and forced to call it, and that
   call is accepted regardless of `N`.

The only value tried: **N = 4** (previous median 1–2; four = an opening
grep, a subject re-grep, a read, and one more). Budget stays 12. No other
prompt or tool change. If the model does exactly four calls and finishes,
that is reported as such: persistence imposed from outside, not supplied.

## Arms and runs

* `dcip` — agent's ids only, `AMI_DCI_MIN_CALLS=4`. Tags `kdcip1–4`,
  `lc-dcip`, `tdcip1–4`.
* `dcipfill` — agent's ids first, embedding fills to `top_k`,
  `AMI_DCI_MIN_CALLS=4`. Tags `kdcipfill1–4`, `lc-dcipfill`.

Instruments, in run order, identical to the previous arm:

1. **KU gate** `lme-ku-k`, 78 q, 4 replicates per arm, vs `kbase1–4`
   (59.50) and vs `kdci1–4` (52.75) / `kdcifill1–4` (59.25). Named
   subpopulations: the **8 settled questions** that collapsed 4/4 → 0/4
   under `dci` (`0977f2af 3ba21379 618f13b2 6a27ffc2 830ce83f 9ea5eabc
   db467c8c f9e8c073`), the **3 stale flips** (`69fee5aa b6019101 ba61f0b9`),
   the remaining stale (`07741c45 0f05491a 59524333 6a1eabeb 7401057b
   852ce960 a2f3aa27`), the two-part (`031748ae f685340e`).
2. **LoCoMo** conv 2–3, 351 q, store `lc-smoke`, one retrieval per arm,
   **two reader replicates per arm declared now** (`_r2`), vs base
   `lc-smoke` 220 / `lc-smoke_r2` 215 and vs `lc-dci` 188, `lc-dcifill`
   243 / 240. Same hop2-style decomposition and the 42 NEITHER.
3. **Temporal guard** `lme-t`, 133 q, 4 replicates, `dcip` only, vs `base1–4`
   (58.50) and `tdci1–4` (60.00). Now-anchored (49) and rest (84) apart.

Logged per run: tool calls per search (mean, and the distribution from the
counters), refused finishes (new counter `dci_refused`), fallbacks, empty
finishes, seconds.

## Statistics

As before: 4-vs-4 exact permutation two-sided; paired sign test on
discordant questions; LoCoMo majority-of-2 movers with sign test and the
replicate discordance stated.

## Decision rules, fixed now

* **Ship candidate** — unchanged from the previous arm: KU ≥ +4.0 over
  `kbase` at p ≤ 0.05, LoCoMo not below base beyond noise, temporal not
  below base at p ≤ 0.05, then cost.
* **Research readings, in this order:**
  * `dcip` within noise of `kbase` (≥ 57.5) **and** mean tool calls ≥ 4 →
    the previous −6.75 was the harness's early stop; an agent-chosen set is
    not itself a loss for this reader. The 8 settled questions are expected
    to carry this: ≥ 6 of 8 back to ≥ 3/4.
  * `dcip` still ≤ 55 **with** mean tool calls ≥ 4 → persistence does not
    recover it; the loss is the narrow set itself (the paper's gain lives in
    the coupling of searcher and answerer, as the earlier reading suspected).
  * Mean tool calls < 4 → the minimum did not bind (model refused/forced
    paths dominate); report the mechanism as failed before reading accuracy.
  * `dcipfill` on LoCoMo ≥ +15 over base (majority-of-2) → the ordering
    effect is robust to the searcher change; still corpus-specific unless KU
    also moves (≥ +2), and still does not ship on its own.
  * Temporal now-anchored moving by more than 0.05 → inspect for leakage
    before reading anything else.

## Prediction (thirteenth, written before the run)

KU `dcip` **60.0** (+0.5 over `kbase`, +7.25 over `dci`); 6 of the 8
settled questions return to ≥ 3/4; the 3 stale flips hold; the two-part
stay at `dci` levels. `dcipfill` 60.0. Mean tool calls **4.3**: the model
does the minimum and one more, then finishes. Refused finishes ≈ 1 per
search. LoCoMo `dcip` 200 (−20), `dcipfill` +20 (holds). Temporal `dcip`
+1.0, now-anchored unchanged. Fallbacks < 5%, empty finishes ≤ 6 per run.

## What this does not test

A searcher stronger than gpt-4o-mini; more than one value of N; any change
to grep/read caps; `dcipfill` on temporal.
