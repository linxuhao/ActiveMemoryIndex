# Lexical channel on a coding-memory proxy — BGE, no LLM (2026-10-19)

`bench/grep_study.py` on SWE-ContextBench (MIT; HF `jiayuanz3/SWEContextBench`):
1,007 experience tasks written per repository through the service's own Add
(issue + hints as user turns, fix and test patches as assistant turns, ≤10,000
chars per message), 357 related tasks with a linked experience as queries.
Embeddings `bge-small-en-v1.5` (local, free), no LLM key: Add stores verbatim
turns only, Search uses the plain query. Arms differ only in `AMI_LEXICAL`
(commit d0b98ee: trigram BM25, RRF k=60, 200 candidates). Scored on the returned
set (top_k=100): hit@k = the first item of the linked experience is within k.

| query form | arm | hit@10 | hit@20 | hit@100 |
|---|---|---:|---:|---:|
| full issue text | dense | .838 | .880 | .941 |
| | lexical | .782 | .860 | .938 |
| first 200 chars | dense | .815 | .882 | .938 |
| | lexical | .804 | .874 | .941 |
| file paths of the task's own fix | dense | .608 | .717 | .880 |
| | lexical | .678 | .776 | .894 |

Paired per query (lexical wins / losses, two-sided sign test):

| form | @10 | @20 | @100 |
|---|---|---|---|
| issue | 7 / 27, p=0.001 | 7 / 14, p=0.19 | 2 / 3, p=1.0 |
| title | 13 / 17, p=0.59 | 8 / 11, p=0.65 | 5 / 4, p=1.0 |
| paths | 33 / 8, p<0.001 | 29 / 8, p=0.001 | 7 / 2, p=0.18 |

Returned text per search: dense 160,514 chars, lexical 187,278 (+17 %, same
72.7 items) — BM25 over trigrams favours long items.

Reading:
- The channel does what it is for: an identifier/path query ranks the right
  history higher (+7.0 pt at 10, p<0.001).
- It costs a long natural-language query (−5.6 pt at 10, p=0.001): dense is
  already strong at issue-to-issue similarity, and equal-weight fusion with a
  noisier ranking drags it.
- Inside the 100 the service actually returns, both effects nearly vanish
  (+1.4 pt paths, −0.3 pt issue).
- Variant tried and rejected: score long queries by their 25 most distinctive
  trigrams only (MoreLikeThis-style) — issue @10 fell further to .728, paths
  unchanged (.678). The loss is rare trigrams of a long issue matching the
  wrong history, not common trigrams diluting. Not kept.

Caveats: a proxy, not CAMBench; stores are small (one repository's experience,
~19 tasks on average), so hit@100 is near its ceiling; the platform's query
form is unpublished; BGE, not text-embedding-v4; no extracted facts.
