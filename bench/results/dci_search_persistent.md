# Persistent DCI searcher — gate failed again; laziness was half the story (2026-09-28)

Pre-registration: `dci_persistent_preregistration.md` (with Amendment 1,
declared before any accuracy was read: the first build let refused finishes
count toward the minimum; 3 replicates set aside as `kdcip*_v0`). Code:
`AMI_DCI_MIN_CALLS=4` on top of `AMI_DCI_SEARCH` (`app/dci.py`), 23 tests.
Change against the previous arm, and only this: the instruction *"Stop as
soon as you have the evidence"* is replaced by persistence guidance (re-grep
the subject of every hit for later restatements), and a `finish` before 4
grep/read probes is refused. Budget 12, tools, caps, reader, corpora, tags
otherwise identical to `dci_search.md`.

## Results

| instrument | arm | replicates | mean | vs base | vs lazy `dci` arm | test |
|---|---|---|---:|---:|---:|---|
| **KU gate** `lme-ku-k` (78) | `dcip` — agent's ids only (2.5 items/q) | 55 · 59 · 55 · 54 | 55.75 | **−3.75** vs kbase 59.50 | **+3.00** vs `dci` 52.75 | perm p = 0.114 (base), 0.086 (`dci`); movers 11 up / 20 down vs base |
| | `dcipfill` — agent's ids first, embedding fills to 100 | 59 · 61 · 60 · 59 | 59.75 | +0.25 | +0.50 vs `dcifill` 59.25 | perm p = 1.0; 5 up / 5 down |
| **LoCoMo** conv 2–3 (351) | `dcip` (4.1 items/q) | reader ×2: 191 · 188 | 189.5 | **−28.0** vs 220 · 215 | +1.5 vs `dci` 188 | majority movers 33 up / 62 down, sign p = 0.004 |
| | `dcipfill` | reader ×2: 233 · 233 | 233.0 | **+15.5** | −8.5 vs `dcifill` 243 · 240 | movers 37 up / 18 down, sign p = 0.015; worst arm run beats best base run by 13; discordance 6 |
| **Temporal guard** `lme-t` (133) | `dcip` | 62 · 59 · 60 · 55 | 59.00 | +0.50 vs 58.50 | −1.00 vs `dci` 60.00 | perm p = 0.91 (base), 0.71 (`dci`); now-anchored 0.303 → 0.317, rest 0.528 → 0.525; 3.7 items/q; probes 6.0/search |

Operational, per search (`dcip_counters.log`): probes (grep/read) **4.2–4.4**
on KU, 4.8 on LoCoMo, 6.0 on temporal (previous arm 1.8 / 3.5 / 4.5);
refused finishes 1.7 (KU), 0.9–1.0 (LoCoMo), 0.6 (temporal); empty finishes
**0** on KU (was 3–6), 2–6 on LoCoMo, 1–3 on temporal; fallbacks 0; 5.0–5.5 s
per search (was 2–4 s); LLM calls per search ≈ 7.2–7.6. The minimum binds: the
model does the minimum plus a fraction, then finishes — persistence is
supplied from outside, not by the model.

## Decision, against the rules as written

Ship candidate required KU ≥ +4.0 at p ≤ 0.05. **KU is −3.75 (`dcip`) and
+0.25 (`dcipfill`). Not shipped; defaults unchanged.**

Research readings, in the pre-registered order:

* *"`dcip` within noise of kbase (≥ 57.5) with probes ≥ 4 → the loss was the
  early stop"* — **not reached**: 55.75. *"`dcip` ≤ 55 with probes ≥ 4 →
  the loss is the narrow set itself"* — **not reached either**: 55.75 sits
  in the 0.75-point gap between the two thresholds. The honest reading is
  the one the numbers give: persistence recovered **+3.0 of the −6.75**
  (p = 0.086 against the lazy arm), and the remaining −3.75 is what a
  4-probe gpt-4o-mini searcher still cannot find or the reader cannot use.
* Settled 8: **4 of 8** back to ≥ 3/4 under `dcip` (predicted 6). Under
  `dcipfill` 7 of 8.
* *"`dcipfill` on LoCoMo ≥ +15 → ordering effect robust to the searcher"* —
  +15.5, **just over the line** and 8.5 below the lazy arm's +24. Robust in
  sign, weaker in size; KU did not move (+0.25), so still corpus-specific
  and still not a ship case.
* Temporal now-anchored: moved +0.014 (0.303 → 0.317), under the 0.05 inspection line; no leakage reading. (The split the script uses is 52 now-anchored / 81 rest, the same split as `dci_search.md`; the 49/84 in the pre-registration was a transcription error.).

## What the anatomy says

**Three of the four settled questions still lost under `dcip` are still a
missed later statement or a second hop, at 4+ probes.** "Where did I go on
my most recent family trip?" → the agent returns the Waikiki trip
(2023-05-26) and never the "recent family trip to Paris" line (05-28).
"Where did Rachel move to after her recent relocation?" → three facts
saying Chicago, never the later "moved back to the suburbs". "What kitchen
gadget did I buy before the Air Fryer?" → six lines about the Air Fryer,
never the Instant Pot. The instruction to re-grep the subject for later
restatements was followed in form (4 probes, 1.7 refusals) and not in
substance: the probes went to the same subject in the same place. The
fourth, "how many bereavement sessions", is the reader: the agent returned
**both** versions (three, 05-11; five, 10-30) and the reader summed them to
"eight" — with the same two lines inside a 100-item list the reader says
five. A two-line set invites arithmetic that a long list does not.

**On LoCoMo the persistent narrow set is no better than the lazy one**
(189.5 vs 188): 89 questions whose evidence the 100-list had complete lose
it under `dcip` (56 right → 27), against 14 that gain it (2 → 9). Evidence
complete 218/351 vs 293. The agent's 4-item set is simply too small for a
corpus where the answer is spread over turns.

**`dcipfill` keeps the ordering gain and loses a third of it.** Evidence
complete 308/351 (hop2 306, base 293); newly complete 17 → 11 right (base
3), the same ≈ 2-in-3 conversion the lazy arm showed (14/18); already
complete 291: 208 → 214. Category 2 (temporal) 26 → 35 as before. The 8.5
lost against the lazy `dcifill` is inside two replicate discordances (6 and
7–11) plus the arm's own stochasticity; not a real difference on this
instrument, and not one the pre-registration asked about.

## Prediction (thirteenth) scored

KU `dcip` 60.0 → **55.75**; settled 6/8 → 4/8; `dcipfill` 60.0 → 59.75 ✓;
probes 4.3 → 4.2–4.4 ✓; refusals ≈ 1 → 1.7; LoCoMo `dcip` 200 → 189.5;
`dcipfill` +20 → +15.5; temporal +1.0 → +0.5 ✓ (n.s. either way); fallbacks < 5% → 0 ✓;
empty ≤ 6 → 0–6 ✓. Right on everything operational and on `dcipfill`
KU, wrong on `dcip` KU again (fourth arm in a row where the narrow-set
prediction was too high), direction right on LoCoMo.

## What the DCI question got answered, now

The paper's gain, under our hand-off, has three parts and we have now
measured each:

1. **Early stop** (our harness): worth ≈ 3 points on KU. Removed.
2. **Searcher competence** (the permitted model): the remaining ≈ 4 points
   on KU and all of the LoCoMo loss. A 4o-mini searcher told to look for
   later restatements re-greps the same subject in the same place; it does
   not revise its hypothesis, which is the behaviour the paper attributes to
   its searcher. This is not tunable without changing the model or the tool
   surface, and the model is fixed by the rules.
3. **Head of the list** (survives): agent-chosen lines leading the full
   list, +15.5 to +24 on LoCoMo across two searcher variants, flat on
   LongMemEval. Corpus-specific; does not ship under the 2026-09-22 rule.

The paper is not "useless"; its mechanism has one component that transfers
to a fixed reader (choosing the head) and one that does not with this
searcher (finding the evidence at all). The coding track, where the
platform agent greps and there is no hand-off, is where the paper applies
as written.

## Not done, deliberately

* No second value of N, no prompt edits after seeing the anatomy, no
  transcript logging (the agent's probes are not saved; the anatomy above
  is read from what it returned, not from what it searched). Transcript
  logging would be the first change in any further DCI arm.
* `dcipfill` on temporal — not pre-registered, no ship case.
* Cost at scale, for the record: ≈ 7.5 LLM calls and 5 s per search.
