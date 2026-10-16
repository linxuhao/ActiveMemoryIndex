# As-of times reader truncation — diagnosis (2026-10-15)

Read-only diagnosis. No production change, no deploy, no paid call. Code
under study: rc5 `academic-v4-20261006-rc5` (90bb326), `app/asof.py`
`times()`, `app/llm.py` `asof_times()` / `ASOF_ITEMS_SYSTEM`, cap
`AMI_LLM_MAX_TOKENS_ASOF_ITEMS=3000`, `AMI_ASOF_ITEMS=200`,
`AMI_LLM_TIMEOUT=25`, `AMI_LLM_RETRIES=1`.

Sources: keyed-prompt study `raw/llm_ledger.jsonl` (purpose `asof_times`),
`raw/search/*.json` (`asof`), `raw/search*.log` (`asof stats`, warnings),
`raw/proxy.log`, and the reply bodies in the study proxy's response cache
(`.../kp/run/proxy/llm_cache.sqlite3`, opened `mode=ro&immutable=1`, looked up
by ledger `key`). Analysis scripts: session scratchpad `asof/analyze.py`,
`asof/attrib.py`.

## Summary

1. **The 68 `length` rows overstate the problem about 3×.** The study proxy
   re-calls upstream when the service has already given up: `do_POST` sends
   the reply inside the `try`, so the `BrokenPipeError` raised after the
   service's 25 s client timeout is swallowed and the request is repeated, up
   to 6 times (16 handlers ended with a broken-pipe `upstream failed` 502 in
   `proxy.log`). There are 143 fresh rows but only **77 distinct prompts**,
   and 8 prompts account for 76 rows (7 or 12 copies each).
2. **In terms of what the service saw:** 22 of 77 distinct prompts truncated.
   For LoCoMo, **19 of 72 as-of-state Searches (26%) got no selection**
   (`times_failures` B 4, K 8, T 7). B's 4 are exactly its 4 truncated
   prompts, as the replay below confirms. LME-temporal: 0 of 3. BEAM has one
   as-of-state question (`10:multi_session_reasoning-0`); it truncated in
   both B and K. BEAM prints no `asof stats`, so it is missing from every
   count above. (An earlier draft counted two BEAM questions. The 04:08:05
   classification was LoCoMo `conv9-q75`.)
3. **A correct reply is short. The truncated replies are degenerate output,
   not long answers.** A healthy reply to a 150–200-line prompt takes
   47–473 tokens (p50 185, p90 275; ≈ 10 entries at 18.4 tokens/entry). Of
   the 22 truncated replies:
   - **15 are repetition loops.** After 7–29 distinct entries (≈ 130–530
     tokens), the model repeats one entry, or a block of entries, until it
     hits the cap.
   - **6 enumerate nearly every memory** (157–164 distinct entries, one
     day-precision point per line). The items are about 90% raw dialogue
     turns, so the model is copying each line's `said` date, which the prompt
     explicitly excludes. Finishing would take about 200 × 18 ≈ 3,700 tokens
     of output that the rules would ignore anyway: span 0, and a time after
     the period does not keep an item under rule (b).
   - 1 is flaky: the cache holds a normal 9-entry reply.
4. **The prompt is not deterministic at temperature 0.** 6 of the 22 prompts
   also returned normal replies (77–311 tokens) when the proxy re-sent the
   identical request. For example, prompt `302ef093` returned 3000(length),
   149, 2939, 113.
5. **Item count drives the chance of degeneration, not the length a correct
   reply needs.** The output format (one entry per stated time, only for
   memories that state one) is already sparse.

| prompt tokens (≈ lines) | distinct prompts | ever truncated |
|---|---|---|
| < 3,000 (≲ 70) | 17 | 0 |
| 3,000–6,000 | 7 | 2 |
| 6,000–7,500 | 25 | 7 |
| ≥ 7,500 (≈ 200) | 28 | 13 |

(≈ 450 system tokens + ≈ 35 tokens per line.)

6. **Raising the cap cannot help.** A loop runs to any cap. From the proxy's
   re-call timing, 3,000 tokens take roughly 20 s, so a 6,000-token reply
   would pass `AMI_LLM_TIMEOUT=25` and end in timeout → retry → timeout,
   which uses most of the 85 s Search deadline.

## Which questions

Prompts were not logged, and the as-of questions of a conversation ran
concurrently (`--workers 8`). Attribution is therefore exact at the
arm/conversation level and only "likely" at the question level. Question
candidates are ranked by how many of the reply's day dates match the `said`
stamps of each candidate's returned items, within the arm's time window.

For arm B, the replay identified the questions exactly: these are the
questions where rc5 withheld nothing and option C withholds.

| arm | conv | truncated prompts | as-of Searches in conv | likeliest questions |
|---|---|---|---|---|
| B | 3 | 1 (loop) | 3 | **conv3-q187** (confirmed) |
| B | 5 | 1 (loop) | 4 | **conv5-q78** (confirmed; date matching had guessed q45) |
| B | 6 | 1 (enumerate) | 6 | **conv6-q12** (confirmed) |
| B | 9 | 1 (loop, `8fc7fdb5`) | 1 | **conv9-q75** (confirmed) |
| K/T | 3 | 2 (1 enum, 1 loop) | 6 | conv3-q136 + one other |
| K/T | 4 | 3 (1 enum, 2 loop) | 8 | conv4-q130 / q148 / q134 / q24 |
| K/T | 5 | 2 (enumerate) | 8 | conv5-q78 / q8 |
| K/T | 6 | 2 (loop) | 12 | conv6-q73 / q148 / q12 |
| K/T | 7 | 5 (1 enum, 3 loop, 1 flaky) | 12 | conv7-q102, q28, q0 / q26 |
| K/T | 9 | 2 (loop) | 2 | **conv9-q75 in both K and T** (only as-of question in conv 9) |
| B | BEAM | 1 (loop, `19bf0802`) | 1 | `10:multi_session_reasoning-0` (period 2023-04-01..09) |
| K | BEAM | 1 (loop, `38e17ee7`) | 1 | the same question |

So `conv9-q75` truncated in all three arms.

B also had one timeout (04:04:09). K had three (04:12:05, 04:12:13,
04:13:08).

The B rate (3 of 24) and the K/T rate (16 of 48) differ, but the samples are
too small to say why. The items sent are about 90% the same raw turns in all
three arms.

## Options (cost per as-of-state Search)

Assumed gpt-4o-mini list price: $0.15 / M input, $0.60 / M output. Measured
inputs: about 7,500 input tokens for 200 lines, healthy output about 185
tokens, truncation rate about 28% at 200 lines. As-of-state Searches are
about 1.4% of all Searches (27 of ~1,951 questions in this study). Per
average Search, every option below therefore differs by less than $0.00003.
What matters is correctness and latency.

| option | change | input / output tokens | ≈ $ / as-of Search | fixes loops? | notes |
|---|---|---|---|---|---|
| 0. rc5 today | — | 7,500 / 0.72·185 + 0.28·3,000 ≈ 970 | 0.0017 | no | ~26% of as-of Searches silently get no selection |
| A. cap 6,000 | env | 7,500 (×2 on timeout) / up to 6,000 ×2 | ≈ 0.0035 | **no** | loops run to 6,000; ~40 s > 25 s timeout → retry → fail; worse |
| B. `AMI_ASOF_ITEMS=100` | env only | ≈ 3,950 / ≈ 700 expected | ≈ 0.0010 | partly (2/7 truncated in that bin) | no refill pool beyond the returned 100. Below 100, returned items go unjudged and are never withheld |
| **C. batch: 200 lines as 4 parallel calls of 50, per-call cap ≈ 800** | code (`asof.times`) | 4 × (450 + 50·35) ≈ 8,800 / ≈ 200 | **≈ 0.0014** | **yes in practice** (0/17 truncated under 3,000 prompt tokens) | a failed batch leaves only its 50 items unjudged (never withheld) instead of voiding all 200; latency ≈ one ~2,200-token call |
| D. more compact output (e.g. omit `end` when equal, `n,s,e,k` rows) | prompt | 7,500 / ≈ 110 healthy | ≈ 0.0016 | no | saves ~40% of output tokens; does nothing about degeneration; could go with C |
| E. lower cap (≈ 1,000) + parse complete entries from a truncated reply | code | 7,500 / ≤ 1,000 | ≈ 0.0013 | salvages loop prefixes | a cut-off reply cannot show which lines it skipped, so a skipped item that does state a time looks like "no time" and can be wrongly withheld under rule (b). This breaks rc5's "any failure withholds nothing" |
| F. one re-ask on truncation | code | +1 call when truncated | ≈ 0.0022 | sometimes (6/22 prompts recovered on a re-sample) | adds ~20 s on the failing path; does not fix the cause |

**Recommendation: C**, with a per-call cap around 800. A healthy 50-line reply
should be well under 300 tokens. It keeps the 200-item judged pool and the
rc5 failure semantics (unjudged → never withheld). It costs no more than
today, cuts latency, and limits the damage from any remaining degeneration to
one batch. D is an optional add-on. A is not recommended.

## Validation of option C (approved 2026-10-15, run on arm B only)

Implementation: branch `research/asof-batch-20261015` (from `4131e4e`, the
study's code). `AMI_ASOF_BATCH` (default 0 = rc5's single call, prompt
byte-identical) and `AMI_LLM_MAX_TOKENS_ASOF_BATCH` (default 800). Batches
run in parallel, each numbered from 0. A failed batch's items are not cached
and are left out of withholding. All batches failing → withhold nothing, as
in rc5. `tests/test_asof.py`: 4 new tests; the full suite passes.

**Scope change.** The K, T, Ts1, Ts2 and F stores were deleted from the
`ami-kp` volume after the study (04:35), and T cannot be re-thinned without
`K.sqlite3`. Only B could be replayed without paying to re-ingest K. To keep
roughly the planned ~79 Searches, C ran as **3 independent replicates of B's
26 as-of-state Searches** (24 LoCoMo, 1 LME-t, 1 BEAM), 78 Searches in all.

Harness: rc5 image, worktree code, a copy of `B.sqlite3` in volume
`ami-asofb`, and a private proxy per run inside the container's own network
namespace on 127.0.0.1:8261 (the store's embedding identity). Each proxy
cache was seeded with the study's Search-time replies (recall, classifier,
embeddings, 6,631 keys) and no times-reader replies. A no-selection replay
(`AMI_ASOF_SELECT=0`) made **0 fresh calls**. Comparing it with the study's
rc5 returned sets reproduces rc5's stats exactly: applied 16, withheld 890 on
LoCoMo; 44 on LME-t. Driver and runner are in the session scratchpad
(`replay/driver.py`, `replay/run.sh`, `replay/compare.py`).

| | rc5 (study, B) | C rep 1 | C rep 2 | C rep 3 |
|---|---|---|---|---|
| times-reader calls | 26 | 64 batches | 64 | 64 |
| `finish_reason=length` | 5 prompts (4 LoCoMo + BEAM) | 0 | 0 | **1** |
| `times_failures` (whole Search unjudged) | 4 LoCoMo + BEAM | 0 | 0 | 0 |
| items judged | — | 200/200 every Search | 200/200 | 200/200 except 150/200 on conv3-q136 |
| applied (withheld ≥ 1 returned item) | 17 | 21 | 21 | 21 |
| withheld from returned | 934 | 1,140 | 1,140 | 1,141 |
| reply tokens p50 / max (cap 800) | — | 59 / 275 | — / 665 | — / 800 |
| `times()` latency p50 / max | — | 1.3 s / 7.0 s (all reps) | | |
| fresh tokens in / out | — | 129.6k / 4.7k | 129.6k / 6.1k | 130.5k / 5.8k |

- **Gate, `times_failures` = 0: met** (78 of 78 Searches).
- **Gate, same or more applied/withheld than rc5: met.** On the 17
  questions rc5 applied, C withheld the same items: mean Jaccard 0.994,
  min 0.968, counts within ±1, in every replicate. C also applies on the 4
  questions whose rc5 call truncated: conv3-q187 (3), conv5-q78 (63),
  conv6-q12 (61), conv9-q75 (78). The replicates agree with each other (mean
  Jaccard 0.999). BEAM's question was now judged (200/200) and withholds
  nothing.
- **Gate, zero truncated batches: missed by 1 of 192.** The failure was a
  50-line conv3 batch in the "copy each said date" enumeration mode, cut at
  800 tokens. That mode needs ≈ 50 × 18.4 ≈ 920 tokens. Two replies in
  rep 2 used the same mode and finished at 627 and 665 tokens. The damage
  stayed local: conv3-q136 still withheld the same 47 items as rc5, from 150
  judged items. Only those 50 items were re-read by the next conv3 question.
- Answer accuracy was **not** measured (no answer or judge calls). Whether
  withholding on the 4 newly applied questions helps the answers is untested.

**Cost:** 389.8k input + 16.6k output tokens ≈ **$0.068** (at $0.15 / $0.60
per M), under the approved ~$0.12. No embedding or other fresh calls.

**Next step (not done):** raise `AMI_LLM_MAX_TOKENS_ASOF_BATCH` to ≈ 1,200 so
a 50-line enumeration completes. A completed said-date enumeration changes
no rule outcome: the entries are span 0, and a time after the period does not
keep an item under rule (b). A loop is still capped at about $0.0007 per
batch. One failure in 192 batches is too rare for another ~$0.02 replicate
to show the difference, so this is a reasoned default, not a measured one.

## Study-infrastructure finding (not production)

`bench/llm_proxy.py` (4131e4e) `do_POST`: `self.reply(200, text)` sits inside
the retry `try`, so a client disconnect counts as an upstream failure and is
re-sent up to 6 times. Each re-send is billed. The response was already
cached, so the extra calls only add cost and inflate the ledger counts. In
this ledger, only `asof_times` is materially affected: 66 duplicate fresh
rows. The extraction purposes have 5–10 duplicates each, and every one of
their `length` rows is a distinct key, so the keyed-prompt study's extraction
`length` counts (54 / 64 / 50) are unaffected. De-duplicate by `key` before
computing any `finish_reason` share.
