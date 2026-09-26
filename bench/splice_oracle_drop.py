#!/usr/bin/env python3
"""Oracle splice: withhold every returned memory carrying the old value of a
stale knowledge-update question (bench/results/supersede_drop_preregistration.md).

    python bench/splice_oracle_drop.py --src kbase --dst kdrop_o --reps 1 2 3 4

Reads bench/out/<src><n>/retrieval.json, keeps the 13 stale questions, removes
ranked items matching that question's old-value pattern (facts and raw turns
alike), writes bench/out/<dst><n>/retrieval.json. Order otherwise unchanged;
nothing backfilled. Prints what it removed so the splice can be inspected.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"

# Fixed before the run. Word-bounded; the two-part questions (031748ae,
# f685340e) are included as the named collateral population.
OLD = {
    "031748ae": r"\b(4|four) engineers\b",
    "07741c45": r"\bunder (my|the) bed\b",
    "0f05491a": r"\b125\b",
    "59524333": r"\b7(:00)? ?(pm|p\.m\.)\b|\b7:00\b",
    "69fee5aa": r"\b37\b",
    "6a1eabeb": r"\b27:12\b|\b27 minutes? and 12\b",
    "7401057b": r"\b(one|a|1) free night",
    "830ce83f": r"\bchicago\b",
    "852ce960": r"\b350,?000\b|\b350k\b|\$350\b",
    "a2f3aa27": r"\b1,?250\b",
    "b6019101": r"\b(4|four) (mcu|marvel)\b",
    "ba61f0b9": r"\b(5|five) women\b|\bhalf of (the|her|my) team\b",
    "f685340e": r"\bweekly\b|\bevery week\b|\bonce a week\b|\beach week\b",
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="kbase")
    ap.add_argument("--dst", default="kdrop_o")
    ap.add_argument("--reps", nargs="+", default=["1", "2", "3", "4"])
    args = ap.parse_args()

    patterns = {q: re.compile(p, re.I) for q, p in OLD.items()}
    for rep in args.reps:
        src = OUT / f"{args.src}{rep}" / "retrieval.json"
        rows = json.loads(src.read_text(encoding="utf-8"))
        kept = []
        for row in rows:
            if row["id"] not in patterns:
                continue
            pat = patterns[row["id"]]
            before = row["ranked"]
            removed = [e for e in before if pat.search(e["content"])]
            row = {**row, "ranked": [e for e in before if not pat.search(e["content"])]}
            kept.append(row)
            kinds = "".join("r" if "-r" in e["id"] else "f" for e in removed)
            print(f"[{args.src}{rep}] {row['id']}: removed {len(removed):2d} of {len(before)} ({kinds})")
            for e in removed[:3]:
                print(f"      - {e['content'][:110]!r}")
        if len(kept) != len(patterns):
            sys.exit(f"expected {len(patterns)} stale questions in {src}, found {len(kept)}")
        dst = OUT / f"{args.dst}{rep}"
        dst.mkdir(parents=True, exist_ok=True)
        (dst / "retrieval.json").write_text(json.dumps(kept, ensure_ascii=False), encoding="utf-8")
        print(f"wrote {dst / 'retrieval.json'} ({len(kept)} questions)\n")


if __name__ == "__main__":
    main()
