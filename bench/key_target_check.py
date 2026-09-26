#!/usr/bin/env python3
"""Does the lexical key channel have a target? (bench/results/key_target_check_preregistration.md)

Offline, on existing retrievals. For questions whose evidence neither the base
nor the hop2=30 arm completed at k=100, ask whether the missing evidence turns
are reachable by lexical search on question terms (T1 / T1r) or on gold-answer
terms (T2), and how many turns each rule would drag in (hit-set size).

    python bench/key_target_check.py --base lc-smoke --hop2 lc-h30
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from run_bench import OUT, item_dias, load_locomo, session_keys  # noqa: E402

STOP = set("""
a an the and or but if then else when while of at by for with about against
between into through during before after above below to from up down in out on
off over under again further once here there where why how all any both each
few more most other some such no nor not only own same so than too very can
will just don should now is are was were be been being have has had having do
does did doing i me my myself we our ours ourselves you your yours yourself
yourselves he him his himself she her hers herself it its itself they them
their theirs themselves what which who whom this that these those am would
could ought also get got one two like yes yeah really know think thing things
something anything nothing say said says tell told make made much many well
still even ever never always maybe sure okay ok lol haha hey hi thanks thank
day time way year years back new old good great nice love
""".split())

TOKEN = re.compile(r"[a-z0-9]+")


def tokens(text: str) -> set[str]:
    return {t for t in TOKEN.findall(text.lower()) if len(t) >= 3 and t not in STOP}


def turn_texts(sample: dict) -> dict[str, str]:
    conversation = sample["conversation"]
    out = {}
    for number in session_keys(conversation):
        for turn in conversation[f"session_{number}"]:
            out[turn.get("dia_id", "")] = (turn.get("text") or "").strip()
    return out


def covered(row: dict, chunks: dict, k: int = 100) -> set[str]:
    ranked = row["ranked"][:k]
    return set().union(*(item_dias(e["id"], chunks) for e in ranked)) if ranked else set()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="lc-smoke")
    ap.add_argument("--hop2", default="lc-h30")
    ap.add_argument("--chunks", default=None, help="tag whose chunks.json maps ids (default: --base)")
    ap.add_argument("--slots", type=int, default=30)
    ap.add_argument("--rare", type=float, default=0.05)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    chunks = json.loads((OUT / (args.chunks or args.base) / "chunks.json").read_text(encoding="utf-8"))
    base = {r["id"]: r for r in json.loads((OUT / args.base / "retrieval.json").read_text(encoding="utf-8"))}
    hop2 = {r["id"]: r for r in json.loads((OUT / args.hop2 / "retrieval.json").read_text(encoding="utf-8"))}
    samples = load_locomo()

    # per conversation: dia_id -> text, token sets, document frequency
    texts: dict[int, dict[str, str]] = {}
    toks: dict[int, dict[str, set[str]]] = {}
    df: dict[int, Counter] = {}
    for conv in sorted({r["conv"] for r in base.values()}):
        texts[conv] = turn_texts(samples[conv])
        toks[conv] = {d: tokens(t) for d, t in texts[conv].items()}
        df[conv] = Counter(t for ts in toks[conv].values() for t in ts)

    def rare(conv: int, ts: set[str]) -> set[str]:
        n = len(toks[conv])
        return {t for t in ts if df[conv][t] <= max(1, args.rare * n)}

    def hits(conv: int, keys: set[str]) -> set[str]:
        return {d for d, ts in toks[conv].items() if ts & keys}

    rows = []
    for qid, b in base.items():
        if not b["evidence"]:
            continue
        gold = set(b["evidence"])
        h = hop2.get(qid)
        cb, ch = covered(b, chunks), (covered(h, chunks) if h else set())
        complete_b, complete_h = gold <= cb, gold <= ch
        pop = "NEITHER" if not complete_b and not complete_h else ("GAINED" if complete_h and not complete_b else "other")
        if pop == "other":
            continue
        conv = b["conv"]
        missing = sorted(gold - (cb | ch)) if pop == "NEITHER" else sorted(gold - cb)
        qt = tokens(b["question"])
        qr = rare(conv, qt)
        answer = b["gold_answer"]
        at = tokens(answer)
        per_turn = []
        for d in missing:
            tt = toks[conv].get(d, set())
            text = texts[conv].get(d, "")
            per_turn.append({
                "dia": d,
                "t1": bool(tt & qt),
                "t1r": bool(tt & qr),
                "t2": (answer.lower() in text.lower() and bool(answer.strip())) or bool(tt & at),
                "t2_verbatim": bool(answer.strip()) and answer.lower() in text.lower(),
            })
        hit_t1r = hits(conv, qr)
        hit_t2 = hits(conv, at)
        reach = {
            "t1r": all(t["t1r"] for t in per_turn) and len(hit_t1r) <= args.slots,
            "t2": all(t["t2"] for t in per_turn) and len(hit_t2) <= args.slots,
        }
        reach["union"] = all(t["t1r"] or t["t2"] for t in per_turn) and len(hit_t1r | hit_t2) <= args.slots
        rows.append({
            "id": qid, "pop": pop, "category": b["category"], "question": b["question"],
            "gold_answer": answer, "n_evidence": len(gold), "missing": missing,
            "hit_t1r": len(hit_t1r), "hit_t2": len(hit_t2), "per_turn": per_turn, "reach": reach,
        })

    for pop in ("NEITHER", "GAINED"):
        sub = [r for r in rows if r["pop"] == pop]
        turns = [t for r in sub for t in r["per_turn"]]
        print(f"\n### {pop}: {len(sub)} questions, {len(turns)} missing turns")
        for key in ("t1", "t1r", "t2", "t2_verbatim"):
            n = sum(t[key] for t in turns)
            print(f"  turns reached by {key:12s}: {n}/{len(turns)}")
        print(f"  turns reached by t1r|t2     : {sum(t['t1r'] or t['t2'] for t in turns)}/{len(turns)}")
        print(f"  question-level (all missing turns reached AND union hit set <= {args.slots}):")
        for key in ("t1r", "t2", "union"):
            print(f"    {key:6s}: {sum(r['reach'][key] for r in sub)}/{len(sub)}")
        print(f"    neither: {sum(not r['reach']['union'] for r in sub)}/{len(sub)}")
        t2_adds = sum(r["reach"]["t2"] and not r["reach"]["t1r"] for r in sub)
        print(f"    t2 adds beyond t1r: {t2_adds}")
        hs1 = sorted(r["hit_t1r"] for r in sub)
        hs2 = sorted(r["hit_t2"] for r in sub)
        med = lambda xs: xs[len(xs) // 2] if xs else None  # noqa: E731
        print(f"  hit-set size median: t1r {med(hs1)}  t2 {med(hs2)}   (max t1r {max(hs1, default=0)}, t2 {max(hs2, default=0)})")
        cats = Counter(r["category"] for r in sub)
        print(f"  by category: {dict(sorted(cats.items()))}")

    if args.out:
        Path(args.out).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
