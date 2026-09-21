# Nineteen LoCoMo arms this repository never recorded

Recovered 2026-09-21 from `bench/out/*/judged_p100.json` on the bench host.
They were run 2026-08-08, during cycle 1, and **nothing in `bench/results/`,
`run_arms.sh` or the git history mentions any of them.** They are written down
here because a result that only exists as a file on one machine is not a result,
and because two of them change what we believe.

The store they ran against (`all10`, ten LoCoMo conversations, 399 chunks) no
longer exists — the LongMemEval stores overwrote it. Their `retrieval.json`
files survive, so composition and coverage are re-derivable; accuracy is not
re-runnable without rebuilding the store.

## The numbers

All LoCoMo, n=1540, prefix 100, same store. Replicates as run.

| arm | what it returns | raw share | chars/q | accuracy |
|---|---|---:|---:|---:|
| `factonly` | facts only | 0.0% | 9,853 | .5156 / .5097 |
| `fact` | fact-weighted mix | 14.5% | — | .5565 / .5688 |
| `parentcap` | whole chunks, few | — | 13,212 | .5708 / .5727 |
| `pooled` | — | — | — | .5734 / .5753 |
| `diverse` | — | — | — | .5844 / .5753 |
| `rand` | random order | — | — | .5825 / .5838 |
| `factfirst` | facts ordered first | 47.2% | — | .5831 / .5825 |
| `ctrl` | base | 47.5% | — | .5877 / .5909 / .5877 |
| `lw200` | — | — | — | .5890 / .5844 |
| `lw50` | — | — | — | .5968 / .5929 |
| `hyb` | BM25 hybrid | — | — | .6052 / .6058 / .6091 |
| `rawonly` | turns only | 100% | — | .6253 / .6227 |
| `rawfirst` | turns first | 47% | — | .6331 / .6396 / .6273 |
| `sandwich` | — | — | — | .6338 / .6338 |
| `window2` / `window3` | turns + radius 2 / 3 | — | — | .6701 / .6688 · .6773 / .6753 |
| **`window1`** | **turns + radius 1 — shipped** | 62.6% | **14,193** | **.6812 / .6792** |
| **`parent`** | **whole chunks as single memories** | — | **61,531** | **.7084 / .7143** |

## What they say

**A monotone gradient in how much verbatim text the reader gets.** 0% raw
.5127 → 14.5% .5627 → 47.5% .5877 → 100% .6240 → turns+window .6802. Five arms,
one direction. This is the strongest single piece of evidence behind
`AMI_RAW_FIRST`, and it was never written down.

**Coverage is inverted against accuracy, harder than anywhere else on record.**
`factonly` has the best retrieval coverage measured anywhere in this project —
complete@100 **0.904** against `window1`'s 0.850, and **0.732 against 0.497** on
questions needing three or more evidence turns — and the worst accuracy of any
non-degenerate arm. It selects the right chunks and delivers a lossy paraphrase
of them. Any argument of the form "this finds more of the evidence, so it should
answer better" has to explain this row first.

## `parent`, and a retraction

`parent` returns whole Add chunks as single memories and scores **.7114**, above
the shipped configuration's .6802.

> **Retracted 2026-09-21.** Earlier today I dismissed this result as an artifact
> of sending 4.3× the text, on the grounds that `parentcap` — the same delivery
> held to the shipped config's character budget — collapses to .5718. The
> attribution was right and the dismissal was wrong. Matched text volume is an
> experimental control I imposed, not a constraint the platform imposes: the
> cycle-2 Answer budget is 117,760 input tokens, and 61,531 characters is about
> 15k tokens. The text fits. "It only wins by sending more text" is not a reason
> to discard an arm when sending that much text is allowed.

What `parentcap` actually shows is narrower and still useful: **at a fixed
character budget, whole chunks are much worse than turns plus a window**
(.5718 vs .6802). The unit of delivery matters, and so does how many slots it
costs. A returned memory costs one slot whatever its length, and `top_k` counts
memories — so a chunk delivered turn-by-turn costs ~18 slots and a chunk
delivered whole costs one.

## What is still unknown

`factonly`'s selection has never been paired with `parent`'s delivery. That
diagonal — facts choose the chunks, the chunks come back whole — is the arm
pre-registered in `chunk_memory_preregistration.md`.

Also unrecorded and not recovered here: what `pooled`, `diverse`, `rand`,
`lw50`, `lw200` and `sandwich` actually varied. Their tags are all that survives.
They are listed above so the accuracies are not lost a second time, not because
we can interpret them.
