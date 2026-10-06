# Pre-registration — zero-fact extraction fallback (AMI_EXTRACT_FALLBACK), end to end

Written 2026-10-06 before any run. Code under test: commit `99cba0e`
(`llm.extract_facts`, `EXTRACT_CONTENT_SYSTEM`, token cap
`AMI_LLM_MAX_TOKENS_EXTRACT_FALLBACK=2400`). Lowest priority of the rc4 studies:
run only if budget remains after the others.

## Where this comes from

Lead smoke L5 (`lead_smoke_delivery_20261005.md`): the shipped extraction
prompt returned no facts for 8 of 8 narration-only Adds and 5 of 12 CL-bench
document Adds; "P2" (shipped prompt first, a third-person content prompt only
when it returns nothing) took those to 0/8 and 2/12 and was identical on
LoCoMo whenever the shipped prompt returned a fact. It was never run end to
end, because the smoke's ScriptMem chunking had no narration-only Add.

## Arms

* **B** — rc4 shipped extraction.
* **F** — B + `AMI_EXTRACT_FALLBACK=1`.

Update detection off in both (it does not interact with extraction and is not
what is tested); text-embedding-v4; recall questions shared through the proxy.

## E2E set: ScriptMem, *An Enemy of the People*

Public questions (`memorax-ai/ScriptMem`, `data/raw/enemy.json`, all 94),
public-domain text (Project Gutenberg #2446, the smoke's source and parser).
Adds are built so that narration-only chunks exist, on the official
20-message / 2,000-word bounds: one message per paragraph (dialogue as
`"<Speaker>: <text>"`, stage directions and scene descriptions as their text,
role `user`); a new Add starts at each act, before a 21st message or the
2,001st word, and whenever the paragraph type switches between narration and
dialogue. One user per arm, one session per act, no timestamps. Search with the
question's options, `top_k` 100; answer with the platform's ScriptMem
`CHOICE_ANSWER_TEMPLATE` (all memories under speaker 1), scored with the
platform's exact-option scorer; gpt-4o-mini; one replicate. Questions whose
returned list is identical in both arms share B's result.

CL-bench (document Adds) is extraction-level only here (zero-fact counts on
the smoke's 12-task probe, re-run with F's token cap); its end-to-end needs a
rubric judge and the task's own reference document is already in the question.

## LoCoMo no-change check

F differs from B only for a chunk B extracts nothing from. Count, over the 399
chunks of the fresh v4 LoCoMo store, the chunks with zero stored facts (where F
would fire) and run F's fallback on them.

## Gate (both)

1. ScriptMem: F − B ≥ **+2** questions (net, n = 94).
2. LoCoMo: the fallback fires on ≤ **1 %** of the 399 chunks (≤ 3); everything
   else is identical by construction.

Pass → include in rc4, default off, recommended on. Fail → removed from rc4
and reported.
