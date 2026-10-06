# Token-aware return budget — the numbers behind the defaults (rc4, 2026-10-06)

`app/tokens.py`, `AMI_ANSWER_*`, `AMI_TOKEN_SAFETY`. Measurement only; no model
calls.

## The limit

Official API guide (verified 2026-10-06): "The shared 128,000-token Answer
window reserves 8,192 output tokens and 2,048 safety tokens, leaving 117,760
input tokens. If needed, Answer keeps a token-counted prefix of Search
candidates in returned rank order; the question, options, instructions, and
archived Search response remain intact." The answer model and its tokenizer
are not public. Until rc3 the only bound was `AMI_RETURN_CHAR_BUDGET=400000`
characters (≈ 100k o200k tokens of English), which ignores the question —
some official queries are whole task prompts of tens of KB — and counts a
Chinese character as a quarter of what it costs.

## Budget per Search

    memory budget = (117,760 − 1,024) / 1.15 − tokens(query) − Σ(tokens(option) + 2)
    cost(memory)  = tokens(content) + 20

`select()` takes a memory only if its cost fits what is left (never cut, no
exception for the first memory), stops after 50 consecutive misses, and the
rendered response is cut to the budget as a final guard (re-rendering and the
DCI agent's picks). A query that leaves ≤ 20 tokens returns `[]` without any
model or embedding call. The character budget stays as an extra cap.

## Instruction overhead: 1,024 tokens

Answer templates of the public leaderboard pipelines, placeholders removed,
o200k_base:

| pipeline | template | tokens |
|---|---|---:|
| ScriptMem | `CHOICE_ANSWER_TEMPLATE` | **374** |
| LongMemEval-S, LoCoMo-refined | `OPEN_ENDED_ANSWER_TEMPLATE` | 284 |
| CL-bench | `_CLBENCH_ANSWER_PROMPT_TEMPLATE` | 103 (+ the task's own system prompt) |
| BEAM | `ANSWER_GENERATION_FOR_RAG` | 73 |

1,024 is 2.7× the largest, for chat framing and an instruction block not seen
here. Residual risk: CL-bench's answer prompt also carries the task's own
system prompt, which Search never sees; for that benchmark the platform's
prefix rule, not this budget, decides what is cut.

## Per-memory overhead: 20 tokens

"- [2026-07-01T12:00:00Z] " plus a newline is 17 o200k tokens (the CL-bench
pipeline's memory line format); 20 rounds up.

## Safety factor: 1.15

Token counts of other plausible answer tokenizers relative to o200k_base
(the gpt-4o family), same text:

| text | cl100k | Qwen3 | DeepSeek-V3 | GLM-4.5 | Llama-3 | Mistral-Nemo |
|---|---:|---:|---:|---:|---:|---:|
| LoCoMo turns (185k chars) | 1.041 | 1.042 | 1.043 | 1.041 | 1.041 | 1.056 |
| LongMemEval messages (797k chars) | 1.014 | 1.022 | 1.011 | 1.014 | 1.014 | 1.045 |
| service code (184k chars) | 0.996 | 1.007 | 1.062 | 0.997 | 0.995 | 1.059 |
| Chinese, mixed doc (8k chars) | 1.353 | 0.946 | 0.874 | 0.884 | 1.055 | 1.267 |
| Chinese, chat (synthetic) | 1.498 | 0.805 | 0.754 | 0.763 | 1.036 | 1.145 |
| Japanese | 1.571 | 1.048 | 1.095 | 1.048 | 1.143 | 1.048 |
| Korean | 1.500 | 1.250 | 1.200 | 1.450 | 1.050 | 1.000 |
| Russian | 1.773 | 1.227 | 1.182 | 1.045 | 1.137 | 1.046 |
| digits only | 1.000 | 2.156 | 1.000 | 1.310 | 1.000 | 2.156 |

1.15 covers every tokenizer measured on English chat, documents and code (max
1.062) and the o200k/Qwen/DeepSeek/GLM/Llama families on Chinese (max 1.077).
It does not cover cl100k or Mistral-Nemo on CJK and Cyrillic text, or
digit-per-token tokenizers on digit runs. If the answer model is one of those
and a response is CJK-heavy, the platform drops the tail of the returned list
(the lowest-ranked facts, after raw-first ordering) — the outcome without
this budget, on a smaller scale. The platform's own 2,048 safety tokens sit on
top.

## Without tiktoken

The image bakes tiktoken 0.8.0 and o200k_base (`TIKTOKEN_CACHE_DIR`). If either
is missing the service logs it and counts with a character-class estimate
(ASCII letter 1/3, digit 1/2, space 1/4, punctuation 1, other UTF-8 bytes / 3,
+1): over LoCoMo turns 1.60×, LongMemEval messages 1.70×, Chinese 1.35–1.39×,
code 1.70×, digit runs 1.01× of o200k_base — safe, at the price of returning
less.
