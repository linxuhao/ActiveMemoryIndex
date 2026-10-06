#!/usr/bin/env python3
"""rc5 router check (bench/results/rc5_language_neutral_preregistration.md, B.1):
every question of a frozen set through app.updates.question_protected -- the
gpt-4o-mini classifier alone, no pattern pre-filter -- with timing.

    python3 bench/rc5_router.py --set SET.json [SET.json ...] --out FILE
"""
import argparse
import collections
import json
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
parser = argparse.ArgumentParser()
parser.add_argument("--set", nargs="+", required=True); parser.add_argument("--out", required=True)
args = parser.parse_args()
from app import updates  # noqa: E402

items = [{**item, "set": Path(path).stem} for path in args.set for item in json.loads(Path(path).read_text())["items"]]


def one(item):
    started = time.monotonic()
    protected = updates.question_protected(item["question"], None)
    return {**item, "predicted": protected, "seconds": time.monotonic() - started}


with ThreadPoolExecutor(max_workers=8) as pool:
    rows = list(pool.map(one, items))
Path(args.out).write_text(json.dumps(rows, ensure_ascii=False, indent=0))
for name in dict.fromkeys(r["set"] for r in rows):
    for lang in dict.fromkeys(r["lang"] for r in rows if r["set"] == name):
        sub = [r for r in rows if r["set"] == name and r["lang"] == lang]
        tp = sum(r["protect"] and r["predicted"] for r in sub); fn = sum(r["protect"] and not r["predicted"] for r in sub)
        fp = sum(not r["protect"] and r["predicted"] for r in sub); tn = sum(not r["protect"] and not r["predicted"] for r in sub)
        recall, false = tp / max(tp + fn, 1), fp / max(fp + tn, 1)
        print(f"{name} {lang}: recall {recall:.3f} (TP {tp}, FN {fn}); false protection {false:.3f} (FP {fp}, TN {tn}) "
              f"{'pass' if recall >= 0.95 and false <= 0.15 else 'FAIL'}")
        for r in sub:
            if r["protect"] != r["predicted"]:
                print(f"    {'MISS' if r['protect'] else 'FALSE-PROTECT'} [{r['kind']}] {r['question']}")
lat = [r["seconds"] for r in rows]
print(f"calls {len(lat)}: latency mean {statistics.mean(lat):.2f}s, p50 {statistics.median(lat):.2f}s, "
      f"p90 {sorted(lat)[int(0.9 * len(lat))]:.2f}s, max {max(lat):.2f}s; failures {updates.stats['scope_failures']}")
