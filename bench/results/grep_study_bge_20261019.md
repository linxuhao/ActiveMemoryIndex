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

## Grep only, no embedding in the ranking (2026-10-22)

Third arm, same store and queries: rank by trigram BM25 alone (rows with no hit
keep store order). The dense and fused arms reproduced the numbers above exactly.

| query form | dense | fused | grep only | grep vs dense @100 (wins / losses) |
|---|---|---|---|---|
| full issue text, hit@10 / @100 | .838 / .941 | .782 / .938 | .633 / .854 | 4 / 35, p=3e-7 |
| first 200 chars | .815 / .938 | .804 / .941 | .700 / .885 | 6 / 25, p=0.0009 |
| file paths | .608 / .880 | .678 / .894 | .667 / .880 | 8 / 8, p=1 |

Grep alone loses 5-9 points inside the returned 100 on natural-language
queries and only ties on path queries; it also returns the most text (202k
chars vs 161k dense). As a coding retrieval it is not a substitute for
embeddings; fusion stays roughly neutral at 100.

## Grouped return instead of fusion (2026-10-22, `bench/grep_split.py`)

Semantic block first, then a grep block of the best BM25 matches not already
shown (zvec-grep keeps query groups apart the same way). Share of slots given
to the grep block; wins/losses vs semantic alone:

| query | k | semantic | grep 20 % | grep 30 % | grep 50 % |
|---|---|---|---|---|---|
| issue text | 10 | .838 | .835 (+7/-8) | .832 (+8/-10) | .815 (+9/-17, p=0.17) |
| issue text | 100 | .941 | .941 | .941 | .938 |
| file paths | 10 | .608 | .641 (+22/-10, p=0.05) | .655 (+28/-11, p=0.01) | .683 (+37/-10, p=1e-4) |
| file paths | 100 | .880 | .882 | .877 | .880 |

Grouping keeps the semantic ranking intact for natural-language queries,
which rank fusion did not (.782), and still gives identifier queries most of
the grep gain. 30 % is used by the coding routes (feature/coding-endpoint-20261022).
