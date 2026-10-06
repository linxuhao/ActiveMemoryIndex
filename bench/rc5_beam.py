#!/usr/bin/env python3
"""BEAM-100K B vs L4 for rc5 (bench/results/adaptive_chunk_rc5_addendum.md).

bench/rc4_beam.py with rc5's arms: both with as-of selection on (production),
B with AMI_ADAPTIVE_CHUNK=0, L4 with 4000 and no separate cap. Ingest, score and
compare are rc4_beam's (leaderboard BEAM answer prompt, batched rubric judge).

    search --data FILE --arm B|L4 --out FILE
    (ingest, score, compare: as in bench/rc4_beam.py)
"""
from __future__ import annotations

import json
import math
import random
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import rc4_beam as base  # noqa: E402

ARMS = {"B": {"ADAPTIVE_CHUNK": 0, "ASOF_SELECT": True}, "L4": {"ADAPTIVE_CHUNK": 4000, "ASOF_SELECT": True}}


def search(args) -> None:
    from app import config, main, store, tokens
    store.init()
    jobs = [(conv["adds"][0]["user_id"], q) for conv in json.loads(Path(args.data).read_text())
            for q in conv["questions"]]
    budget = tokens.memory_budget()

    def one(job):
        user, q = job
        request = main.SearchRequest(query=q["question"], user_id=user, top_k=100)
        data = main._search(request)["data"]
        counted = sum(tokens.item_cost(d["content"]) for d in data)
        return {**q, "id": f"{user.rsplit('-', 1)[1]}:{q['id']}", "contents": [d["content"] for d in data],
                "chars": sum(len(d["content"]) for d in data), "tokens": counted,
                "within_budget": counted <= tokens.memory_budget(q["question"], None) <= budget}

    with patch.multiple(config, **ARMS[args.arm]), ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(one, jobs))
    Path(args.out).write_text(json.dumps(rows, ensure_ascii=False))
    n = len(rows)
    print(f"{args.arm}: {n} questions, chars/q {sum(r['chars'] for r in rows) / n:,.0f} (max "
          f"{max(r['chars'] for r in rows):,}), memories/q {sum(len(r['contents']) for r in rows) / n:.1f}, "
          f"counted tokens/q {sum(r['tokens'] for r in rows) / n:,.0f} (max {max(r['tokens'] for r in rows):,}); "
          f"all within the token budget: {all(r['within_budget'] for r in rows)}")


def permutation(args) -> None:
    """Paired sign-flip permutation p (two-sided) and sign test on rubric differences."""
    b = {r["id"]: r["score"] for r in json.loads(Path(args.base).read_text())}
    a = {r["id"]: r["score"] for r in json.loads(Path(args.arm).read_text())}
    diffs = [a[k] - b[k] for k in b if k in a]
    observed = abs(sum(diffs))
    rng = random.Random(20261006)
    hits = sum(abs(sum(d if rng.random() < 0.5 else -d for d in diffs)) >= observed - 1e-12 for _ in range(100_000))
    up, down = sum(d > 0 for d in diffs), sum(d < 0 for d in diffs)
    k = min(up, down)
    sign = min(1.0, 2 * sum(math.comb(up + down, j) for j in range(k + 1)) / 2 ** (up + down)) if up + down else 1.0
    print(f"n={len(diffs)} mean diff {sum(diffs) / len(diffs):+.4f}; up {up} down {down}; sign p {sign:.3f}; "
          f"sign-flip permutation p {hits / 100_000:.3f}")


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "search":
        import argparse
        p = argparse.ArgumentParser()
        p.add_argument("cmd"); p.add_argument("--data", required=True); p.add_argument("--arm", required=True,
                                                                                      choices=sorted(ARMS))
        p.add_argument("--out", required=True)
        return search(p.parse_args())
    if len(sys.argv) > 1 and sys.argv[1] == "permutation":
        import argparse
        p = argparse.ArgumentParser()
        p.add_argument("cmd"); p.add_argument("--base", required=True); p.add_argument("--arm", required=True)
        return permutation(p.parse_args())
    base.main()


if __name__ == "__main__":
    main()
