# As-of evidence selection (AMI_ASOF_SELECT) — confirmation result, 2026-10-06

Pre-registration: `asof_selection_preregistration.md` (commit `93b21d3`,
amendment 1 in `4356107`, both before any validation search). Code: `app/asof.py`
at `4356107`. Harness `bench/rc4_study.py`; data `bench/rc4_asof_data.py`.
One replicate, platform answer and judge prompts, gpt-4o-mini, every model and
embedding call through `bench/llm_proxy.py`. Benchmark text and outputs stay in
the run directory (not committed).

## Verdict: gate PASSED

| gate | set | n | B | P | diff | W / L | sign p | rule | pass |
|---|---|---:|---:|---:|---:|---|---:|---|---|
| 1 | as-of pooled (TempReason L2 fresh + synthetic dated) | 300 | 269 | 299 | **+30** | 31 / 1 | 1.5e-8 | > 0, p < 0.05 | yes |
| 2 | LoCoMo dated (cat 1–4, v4 store) | 194 | 142 | 142 | **0** | 0 / 0 | 1 | ≥ −1 | yes |
| 3 | LongMemEval knowledge-update (BGE guard store) | 78 | 55 | 55 | **0** | — | — | ≥ −1 | yes |

Recommendation: `AMI_ASOF_SELECT=1` in the production environment. The shipped
code default stays 0.

## Per set

| set | n | lists changed | B | P | diff | W / L |
|---|---:|---:|---:|---:|---:|---|
| TempReason L2, fresh (v4) | 200 | 200 | 175 | 199 | +24 | 25 / 1 |
| synthetic NEW templates, en dated | 50 | 48 | 46 | 50 | +4 | 4 / 0 |
| synthetic NEW templates, zh dated | 50 | 33 | 48 | 50 | +2 | 2 / 0 |
| synthetic, "now" | 20 | 0 | 20 | 20 | 0 | identical |
| TempReason L3, fresh (relation questions, no dates) | 100 | 0 | — | — | 0 | identical, not answered |
| LoCoMo dated | 194 | 9 | 142 | 142 | 0 | 0 / 0 |
| LongMemEval KU | 78 | 0 | 55 | 55 | 0 | identical (no question names a year) |

* **TempReason L2.** Rule (a) does the work (every fact is a dated range, all
  stamped 2024-06-01): memories per question 15.3 → 2.6, 2,543 items withheld
  over 200 questions; the router was called on all 200 and called every one an
  as-of state question. The one loss: "Which political party did Kōichirō
  Genba belong to in Nov, 2018?" — P returned the right range and an undated
  extracted fact ("… is a member of the Democratic Party of Japan."), and the
  reader took the fact.
* **Synthetic (new templates).** The new templates were easier for B than the
  smoke's (94/100 against the smoke's 56/80), so the room was small; P took
  every dated question. The router called 48/50 English and 33/50 Chinese dated
  questions as-of state; the other 19 (17 Chinese: "2023年2月14日那天，我用的是哪家运营商？",
  "2023年9月，我开的是什么车？"; 2 English: "What car was I driving in
  September 2023?") were called **event** — rule (b) was then not applied and
  the list stayed as B's. B answered all 19 correctly, so this cost nothing
  here, but it is the router's measured recall on state questions: 96 %
  English, 66 % Chinese. It errs toward withholding nothing.
* **LoCoMo dated.** At the parser's period, rule (b) would have changed 161 of
  the 194 lists; the router called 173 event, 13 as-of state and 8 other, so
  only 9 lists changed — all nine as-of wording ("How many pets did Andrew have,
  as of September 2023?", "What project was Jolene working on as of 1 February,
  2023?", …). 8 of 9 correct in both arms. The smoke's loss mechanism
  ("yesterday I came back from …" withheld for an event question) did not
  recur: event questions no longer get rule (b), and relative wording within
  31 days is kept.
* **KU.** No knowledge-update question carries a year in digits, so the gate
  never opens; identical by construction.

## Cost

Router: one call per distinct dated question whose list the rules would change
(TempReason 200, synthetic 94, LoCoMo 161 in this study; ~250 prompt tokens
each). gpt-4o-mini spend of this study ≈ 2.4M fresh tokens (ingest of 420
TempReason/synthetic Adds with update detection ≈ 1.0M, answers and judges of
changed lists ≈ 1.2M, router ≈ 0.12M, development check 0.2M);
text-embedding-v4 ≈ 0.15M.

## Caveats

* One replicate; gpt-4o-mini reader and judge are the platform's prompts, not
  the calibrated internal judge of `docs/research_evaluation_protocol.md`.
* TempReason's fact sentences carry clean "from X to Y" ranges; the synthetic
  streams state values without years by design. Both test the mechanism; the
  LoCoMo and KU guards test that it stays out of the way.
* KU used the BGE research store (stated in the pre-registration); the update
  records in that store never withhold (all 273 stored verdicts are "not
  replaced"), so B there is the rc3 selection.
* Chinese state questions are under-detected by the router (66 %): the
  mechanism is safe there but delivers less of its gain.
