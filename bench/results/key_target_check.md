# Key-target check — the lexical key channel has a target on LoCoMo, and it is too small to read (2026-09-26)

Pre-registration: `key_target_check_preregistration.md`. Script:
`bench/key_target_check.py`. Data: `bench/out/lc-smoke` (base) and
`bench/out/lc-h30` (`AMI_HOP2_SLOTS=30`), conversations 2–3, 351 questions,
`top_k=100`; turn text from `bench/third_party/locomo10.json`. Offline; no
model, no training, no new retrieval. Outputs `bench/out/key_target_check*.json`
on the server.

## Populations, as recomputed on the retrieval files

* NEITHER (evidence complete in neither arm): **42 questions, 57 missing turns**
  — matches the end-to-end decomposition's "neither did" cell exactly.
  Categories: multi-hop 23, temporal 4, open-domain 5, single-hop 10.
* GAINED (complete only under hop2=30): 16 questions, 21 missing turns.

## Result — strict tokenisation, as registered (no window)

| | turns reached / 57 | questions reachable / 42 (all missing turns reached, hit set ≤ 30) |
|---|---:|---:|
| T1 question terms, any | 16 | — |
| T1r question terms, rare (df ≤ 5%) | 12 | **7** |
| T2 gold-answer terms (oracle key) | 35 | **12** |
| T2 verbatim answer string | 6 | — |
| T1r ∪ T2 | 37 | **8** |
| neither | 20 | **34** |

T2 adds **10** questions beyond T1r. Hit-set medians: T1r 15 turns, T2 22
(max 45 / 122).

## Two declared post-hoc readings (both weaken it)

1. **Generous matching** (stemming + ≥4-char substring, because gold answers
   contain glued words like "threeturtles" and "localzoo"): turn reach rises
   (T2 35 → 39, T1r|T2 37 → 45) but hit sets balloon (medians 35 / 33), so
   question-level reach *falls*: T1r 5, T2 11, union 4. Loosening the key
   buys reach and pays it back in precision.
2. **±1 neighbour window** (what the shipped `WINDOW_RADIUS=1` returns,
   neighbours charged to the hit set as they are to `top_k`): T2 38/57 turns,
   but question-level T2 8, union 3; generous+window T2 5. The window reaches
   a few more turns and spends the slots doing it.

| question-level reach / 42 | strict | strict + window | generous | generous + window |
|---|---:|---:|---:|---:|
| T1r | 7 | 3 | 5 | 3 |
| T2 (oracle answer key) | 12 | 8 | 11 | 5 |
| T2 beyond T1r | 10 | 8 | 10 | 5 |
| T1r ∪ T2 | 8 | 3 | 4 | 3 |

## Decision, against the rules as written

* Rule 1 (T1r ≥ 21 → plain FTS arm): **no**, 7. Consistent with the
  cycle-1 hybrid BM25/RRF arm (`hybrid_replicates_all10.txt`): +1.8pt on
  all10, p 0.09–0.18, dominated by raw-first and removed.
* Rule 2 (T2 adds ≥ 10 → adapter has a distinct target): **10, exactly at
  the line**, strict and unwindowed only; 8 with the shipped window, 5
  generous+window.
* Rule 3 (T1r ∪ T2 < 10 → stop): **8 → stop.**

Rules 2 and 3 both fire. The pre-registration did not anticipate that the
union hit set can exceed 30 turns while the answer-key set alone fits, so it
wrote two rules that are not exclusive. Resolution, stated rather than
chosen quietly: the design as written in `docs/index_agent_design.md` §3
(adapter keys ∪ query terms) is the union rule, and it stops at 8. An
answer-keys-only variant is the rule-2 reading: **an oracle key reaches at
most 12 of 42 (10 beyond question terms), i.e. 2.8% of 351 on completeness**,
before two discounts the check cannot measure — whether a 2B adapter emits
that token in question form (the key-window result "partially holds" at 2B),
and the reader's conversion of gained evidence (3 of 16 in this very run).
Expected end-to-end effect ≈ 1–2 questions on an instrument whose
between-replicate discordance is ~23. **Not readable. Report, no build.**

Prediction (tenth) scored: "T1r reaches a third, T2 adds few" — T1r reached
a sixth and T2 added ten. Wrong in both directions, on the side that makes
the channel look better, and it still does not clear the noise.

## Why the other 34 are out of reach — the finding

Split exactly in half:

* **17 fail on precision.** Every missing turn shares a term with the answer,
  but the answer's terms are common in the conversation: "homeless shelter"
  is in 37 turns, "made dinner together" in 61, "toy drive, food drive,
  veterans…" in 78. A key that names the answer drags in a session's worth of
  turns; 30 reserved slots cannot hold them.
* **17 fail on reach.** The missing turn contains no term from the question
  or the answer, under any matching:
  * "I've had them for 3 years now" — answer *three years*, subject *turtles*, both absent (pronoun + numeral).
  * "I just got a new addition to the family, this is Max!" — answer *a dog*.
  * "They make me think of strength and perseverance" — answer *turtles*.
  * "Here ya go, a pic of my cork board" — answer *corkboard*, plus "quotes, photos, keepsakes".
  * "I got a rejection letter" / "someone wrote me a letter" — answer *two* (a count).
  The content of these turns is in their *binding* (what "them", "this", "they"
  refer to), not in their strings. No key string reaches them; the ±1 window
  reaches a few and pays in slots.

The GAINED contrast says the same from the other side: hop2's reflected
*embedding* round completed 16 questions of which only 4 are T1r-reachable —
the second-hop gap on multi-hop is semantic, not lexical.

## What this leaves

* The search-time key arm is not built and the Q8 application is not
  submitted on this evidence. The draft stays in `docs/index_agent_design.md`.
* The design's other half — the adapter as a *record* that a stronger or
  trained reader could use — is untouched by this check, which only asked
  whether a correct key has anything to hit on LoCoMo conversations 2–3.
* If a corpus where answers are named entities (cycle 2's PersonaMem or
  ScriptMem may be) shows a larger oracle-T2 share, re-run this script
  there first; it is corpus-only and costs nothing. Replication, not tuning.
