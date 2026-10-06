# Pre-registration — rc5: no language-dependent regex or word list (as-of, updates, render)

Written 2026-10-06 before any rc5 validation call. Code under test: commit
`0d43865` (branch `release/rc5-20261006`), compared with rc4 = `a0b3e99`
(tag `academic-v4-20261006-rc4`). Read this before any number.

## The rule and what changed

User rule (absolute): no regex or word list that depends on a natural language
may take part in any decision — month names, relative-time words, range words,
history words, pronoun sets, relative-change words, stopword or script tests —
not even as an "add-protection only" pre-filter. gpt-4o-mini decides instead,
called only when needed and cached. Language-neutral mechanics stay (our own id
and stamp formats, ISO dates the model returns, JSON parsing, digits as data).

* **As-of selection** (`app/asof.py`). rc4: a year-in-digits gate, a
  multilingual date parser and range-word / relative-time lists, with the
  model asked only when the rules would change the set. rc5: (1) one
  gpt-4o-mini classification of every Search question
  (`as_of_state | event_on_date | other`, ISO start and end), started beside
  the recall rewrite, cached per (query, options); (2) for an `as_of_state`
  question, one gpt-4o-mini call over the candidates (the returned set, then
  the next ranked items, at most `AMI_ASOF_ITEMS`=200, each ≤ 300 characters,
  with its stamp date) listing `valid`, `not_valid` and `about_period` items;
  (3) withhold `not_valid` items when some judged item is `valid`; withhold
  items said after the period that are neither `valid` nor `about_period` when
  a returned item was said by the period's end; refill from the ranking.
  Event questions withhold nothing (rc4's interval rule changed no event
  question's list in any rc4 set); unjudged items and failures withhold nothing.
* **Updates** (`app/updates.py`). Removed: `HISTORY_QUESTION`, `DATED_QUESTION`,
  `DATED_CJK` pre-filters, `RELATIVE_WORDS`, the `SELF` pronoun set. The router
  (`QUESTION_SCOPE2_SYSTEM`, unchanged) decides protection for every version;
  stage 2's `relative` and `subject_is_user` decide the rest. User markers are
  protocol tokens only ("me", which the stage-2 prompt asks for, and our own
  speaker label "I").
* **Render-language check**. Removed: the script and Latin-stopword heuristic.
  Stage 2 now returns `statement_language` and `current_language` (ISO 639-1)
  and is told to write "me" in every language; a render needs both tags and
  equal primary subtags. Chosen over a second LLM check: zero extra calls (the
  tags come from the call that writes the sentence, ~10 completion tokens per
  record) against one extra call per rendered record; a translated render is
  the model's own act, which it can name in the same reply.
* `main._TIME_HINT` (request-log only) is removed with its log field.

## Studies and gates

All model and embedding calls through `bench/llm_proxy.py` (cache shared with
the rc4 and round-5 runs; fresh tokens metered; cap 35M gpt-4o-mini, 3M
text-embedding-v4; upstream concurrency 8). Platform answer and judge prompts
(LongMemEval-S pipeline for TempReason, synthetic, KU, MQuAKE; LoCoMo-refined
for LoCoMo), gpt-4o-mini, temperature 0, one replicate unless stated. Paired
per question; exact two-sided sign test on discordant questions. A question
whose returned list is byte-identical in both arms gets the same verdict.

### A. As-of: rc4 regex version (R) vs rc5 (N)

Arms: R = rc4 code, N = rc5 code, both with production settings (update
mechanism v7 on, `AMI_ASOF_SELECT=1`, raw-first, window 1, limit 100, token
budget), in-process Search on the same store, sharing recall questions through
the proxy cache.

| set | n | store | role |
|---|---:|---|---|
| TempReason L2, fresh (seed 20261007, excluding the smoke's and rc4's 600 ids) | 150 | new v4 store, ingested by rc5 | en as-of |
| TempReason L3, fresh (same exclusion) | 100 | same | guard (relation questions) |
| synthetic NEW streams (`bench/rc5_asof_data.py`): en, fr, de, es, zh, ja, 8 streams each, 5 dated + 1 "now" question per stream; question dates rotate month-name-with-digits / entirely in words / native numerals (US/EU numeric, 二〇二三年…日, 二零…号, 令和) | 240 dated + 48 now | same | as-of per language; "now" is a guard |
| LoCoMo dated: the 194 ids of rc4's study (frozen list `dated_B.json`) | 194 | LoCoMo v4 store re-ingested with rc4 code (from the proxy cache; must reproduce rc4's B lists) | guard |
| LoCoMo, the 770 held-out questions of the rc4 L4 study | 770 | same | reported (classification now runs on every question) |
| LongMemEval-S knowledge-update | 78 | BGE guard store (`guards6r-v7` copy) | guard |

Gates (all must hold):

1. **No loss on English/Chinese:** pooled TempReason L2 + synthetic en dated +
   synthetic zh dated (n = 230): N − R ≥ 0; and none of the three below −1.
2. **Gains on the new languages:** synthetic fr + de + es + ja dated pooled
   (n = 160): N − R > 0 with sign-test p < 0.05; and no one of the four below 0.
3. **Guards ≥ −1 each:** LoCoMo dated (194), KU (78), TempReason L3 (100),
   synthetic "now" (48).

Reported: classifier verdicts per set (kind, period correct), item-call
counts, withheld items, and the added cost per Search (proxy ledger purposes
`asof`, `asof_items`) and latency (below).

### B. Updates router and stage 2

1. **Router, LLM only** (no pre-filter): every question of the round-5 frozen
   set (`explicit_update_r5_router_set.json`, sha256 `76a8cb33…`, en/zh/es),
   the round-5b held-out set (`explicit_update_r5b_router_heldout.json`,
   `cd29eb40…`) and the NEW French/German set written now
   (`bench/results/rc5_router_fr_de.json`, sha256 `5b517cbb…`, 20 protect / 20
   not per language: history 8, previously-now 4, time-scoped 4 (two with dates
   in words or numeric), change 4; current 10, from-to-current 5, current-now 5).
   **Gate:** in every language of every set, recall on protect questions
   ≥ 0.95 and false protection ≤ 0.15.
2. **MQuAKE re-check** (all 200 round-3 cases, seed 20261006, streams
   reconstructed from the round-3 store and verified message by message; 400
   edit + multi questions, 2 replicates): B = withholding and render off (rc5
   code, store `mq3-s1`); RW4 = rc4 code, v7, store `mq6-s2-v7` (the RC2
   records and renders); RW5 = rc5 code, v7, a store re-ingested by rc5 (new
   stage-2 prompt), render and withholding on. **Gate:** RW5 − B > 0 with
   p < 0.05, and RW5 − RW4 not significantly negative (sign test on per-question
   mean over replicates, p ≥ 0.05, or positive).
3. **Render language** (reported, no gate): render fallback counts on the
   MQuAKE re-ingest; tag agreement on a small new multilingual probe (en, fr,
   de, es, zh, ja; 4 explicit updates each, `bench/rc5_render_probe.py`), with a
   separate gpt-4o-mini check in the bench (not in the service) of whether each
   stored render is in the statement's language.

### C. Suite

Whole suite network-free; new `tests/test_language_neutral.py` fails on any
regex or word list in `app/` not on its reviewed allowlist (on rc4's `app/`
it flags 13 literal regexes, 10 run-time-built regexes and 10 word lists).

## Development before validation

The prompts are frozen at `0d43865`. If a check on development data only (the
rc4 synthetic streams `asof2_streams.json` and the rc4 smoke's, the round-5
frozen router set — development since version 6 — and hand-written examples)
shows a prompt misclassifying, a revision may be committed before any
validation search above and recorded here as an amendment with its commit.
No validation item (TempReason fresh, synthetic NEW, LoCoMo, KU, r5b,
fr/de set) is used to develop it, and no LoCoMo text enters a prompt.

## Failure

A failed gate is reported as failed. No regex may be reinstated: a language
that fails is fixed by a prompt revision (registered as an amendment, then
re-validated on a newly written set) or reported open.

## Budget

≈ 3.5M as-of (ingest, item calls, changed lists), ≈ 0.2M router, ≈ 3.5M
MQuAKE, ≈ 0.3M render probe; the rest of the 35M for the adaptive-chunk
addendum (`adaptive_chunk_rc5_addendum.md`). Priority if short: this study first.
