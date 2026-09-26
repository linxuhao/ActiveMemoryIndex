# Requests to the platform — status and drafts (2026-09-26)

Things this project needs from the organisers, with the evidence, the exact
ask, and whether it has been sent. Kept in the repo so that an open request
cannot be forgotten in a to-do list.

| # | request | evidence | status |
|---|---|---|---|
| 1 | a question-time field on `/search` (or confirmation that the platform's Answer prompt already carries it) | `bench/results/lme_now_hint.md`: +11.00/133, p = 0.029 | **NOT SENT.** Open since 2026-09-20. Must be resolved before the first Full (~10-05). |
| 2 | written confirmation that per-user online LoRA (Q8) is admissible | `docs/index_agent_design.md` §7 | not sent — deliberately; gate failed (`key_target_check.md`), draft only |

## 1. Question time on `/search`

### Why (the measurement)

LongMemEval-S temporal-reasoning, 133 questions, four replicates per arm,
gpt-4o-mini reader, platform prompts:

| arm | what the reader saw | mean / 133 | vs base |
|---|---|---:|---:|
| base | memories only | 58.50 | — |
| ungated date hint | `[today's date is …]` on every question | 58.00 | −0.50 |
| **routed, true date** | the same line, only when the question needs a present (52 of 133 by a fixed regex) | **69.50** | **+11.00, p = 0.029, complete separation** |
| routed, *estimated* date (newest returned memory) | as above, date guessed | 57.00 | −1.50 |

49 of the 133 questions are anchored on "now" ("how long ago", "how many weeks
since", "what is my current…"). Without a present the reader scores 0.286 on
them; with the true date 0.551. Guessing the present from the newest memory
does not work on this benchmark because 56 haystacks contain sessions *after*
the question. So the effect exists only with the real question time, which
the cycle-2 API does not send: `/search` is `query`, `options`, `user_id`,
`top_k` (`docs/cycle2_official_qa_zh.md`, Q14/Q16). Add's
`messages[].timestamp` carries event time (Q15); Search carries none.

### What to ask (two questions, either answer settles it)

1. Does the platform's Answer step already give the answer model the
   question's date (e.g. LongMemEval's `question_date`, LoCoMo's session
   dates)? If yes, the hint is redundant on the platform and we stop.
2. If not: can `/search` carry an optional ISO field — `question_time` or
   `timestamp` — with the same event-time semantics as Add's
   `messages[].timestamp`, optional like that one, absent when the source
   has no date? We would use it only to render a date line beside returned
   memories for questions that ask about the present; never to select or
   rewrite memories.

### Draft — email to contactus@agentmemoryleaderboard.ai (Chinese)

> 主题：文本赛道 `/search` 接口能否携带问题时间（可选字段）？
>
> 组委会好，
>
> 我们是学术开源组文本赛道参赛队 ActiveMemoryIndex（第一期学术榜第 3，AML Key 见报名信息）。想确认一个接口细节，它决定我们要不要保留一个已测量的功能。
>
> 背景：LongMemEval 中约三分之一的时间推理题以"现在"为锚（"多久以前"、"距今几周"、"目前"）。我们在本地用平台公开的 Answer/Judge 提示词测得：在返回的记忆旁附一行问题日期，且只对这类题附，gpt-4o-mini 的时间推理准确率从 58.5/133 提到 69.5/133（四次重复，置换检验 p = 0.029）。不加门控时为 −0.5，用最新记忆估计"现在"为 −1.5。也就是说，效果只在**真实的问题时间**存在。
>
> 目前 `/search` 的请求体只有 `query`、`options`、`user_id`、`top_k`，没有问题时间。请问：
>
> 1. 平台 Answer 环节是否已向作答模型提供问题日期（例如 LongMemEval 的 question_date）？若已提供，我们这边的处理是多余的，不再保留。
> 2. 若未提供，`/search` 能否增加一个**可选**的 ISO 时间字段（如 `question_time`），语义与 Add 的 `messages[].timestamp` 一致（事件时间；来源无日期时缺省）？我们只会用它在返回的记忆旁渲染一行日期，不用于选择或改写记忆，不会因缺省而报错。
>
> 无论结论如何，我们都会在参赛材料中如实披露该处理是否启用。谢谢。
>
> 林旭浩（Xuhao Lin），独立研究者，linxuhao84@gmail.com

### Draft — English

> Subject: Text track — can `/search` carry an optional question-time field?
>
> Hello,
>
> We are ActiveMemoryIndex (academic open-source, text track; 3rd on the cycle-1 academic board). One interface question decides whether we keep a measured feature.
>
> About a third of LongMemEval's temporal-reasoning questions are anchored on "now" ("how long ago", "how many weeks since", "currently"). Measured locally with the platform's public Answer/Judge prompts: rendering one line with the question's date beside the returned memories, only for those questions, moves gpt-4o-mini from 58.5/133 to 69.5/133 (four replicates, permutation p = 0.029). Ungated it is −0.5; estimating "now" from the newest memory is −1.5. The effect exists only with the real question time.
>
> `/search` currently carries `query`, `options`, `user_id`, `top_k` and no question time. Two questions:
>
> 1. Does the platform's Answer step already give the answer model the question's date (e.g. LongMemEval's `question_date`)? If so, our handling is redundant and we will drop it.
> 2. If not, could `/search` accept an optional ISO field (e.g. `question_time`) with the same event-time semantics as Add's `messages[].timestamp` — optional, absent when the source has no date? We would use it only to render a date line beside returned memories, never to select or rewrite them, and would not fail when it is absent.
>
> Either way we will disclose in our materials whether this handling is enabled. Thank you.
>
> Xuhao Lin, independent researcher, linxuhao84@gmail.com

### Registration-form note (submission-notes field, one paragraph)

> 本系统可在 `/search` 请求包含可选的问题时间字段时，对"以现在为锚"的问题在返回记忆旁渲染一行日期（本地测量 +11.0/133，p = 0.029）；该字段缺省时功能不启用，系统行为与不带该功能时完全一致。是否启用将随该字段是否提供而定，并在材料中如实说明。

### After sending

Record the send date and the reply here. If the answer to question 1 is
"yes", close `AMI_NOW_HINT`-style rendering and note it in
`lme_now_hint.md`. If question 2 is granted, the routed hint needs one
pre-registered end-to-end run against the field name they choose before it
ships. If both are "no", the +11 stays a bench finding and the feature stays
off.
