#!/usr/bin/env python3
"""rc5 studies (bench/results/rc5_language_neutral_preregistration.md,
bench/results/adaptive_chunk_rc5_addendum.md).

The rc4 harness (bench/rc4_study.py) with rc5's arms and sets. In-process
Search (app.main._search) against a store built by the service; every model
call through bench/llm_proxy.py. The rc4 arm of the as-of comparison is run with
rc4's own tree and its bench/rc4_study.py on the same store and question files.

    B    AMI_ADAPTIVE_CHUNK=0, AMI_ASOF_SELECT off
    P    AMI_ASOF_SELECT on
    L4   AMI_ADAPTIVE_CHUNK=4000 (rc5: no separate cap), as-of off
    L4P  AMI_ADAPTIVE_CHUNK=4000, as-of on
    BP   AMI_ADAPTIVE_CHUNK=0, as-of on (production)

    search  --set S --arm A --store TAG --out FILE [--streams F] [--ids F]
    (score, compare, changed, stats: as in bench/rc4_study.py)
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import rc4_study as base  # noqa: E402

ARMS = {"B": {"ADAPTIVE_CHUNK": 0, "ASOF_SELECT": False}, "P": {"ASOF_SELECT": True},
        "L4": {"ADAPTIVE_CHUNK": 4000, "ASOF_SELECT": False}, "L4P": {"ADAPTIVE_CHUNK": 4000, "ASOF_SELECT": True},
        "BP": {"ADAPTIVE_CHUNK": 0, "ASOF_SELECT": True}}


def question_set(name: str, store: str, streams: str | None, ids: str | None) -> list[dict]:
    if name == "locomo-ids":
        keep = {r["id"] if isinstance(r, dict) else r for r in json.loads(Path(ids).read_text(encoding="utf-8"))}
        return [q for q in base.question_set("locomo", store, None) if q["id"] in keep]
    return base.question_set(name, store, streams)


def search(args) -> None:
    from app import asof, config, main, store, tokens, updates

    store.init()
    questions = question_set(args.set, args.store, args.streams, args.ids)
    if args.n:
        questions = questions[: args.n]

    def one(q: dict) -> dict:
        request = main.SearchRequest(query=q["question"], user_id=q["user"], top_k=100)
        data = main._search(request)["data"]
        contents = [d["content"] for d in data]
        verdict = asof._cache.get((q["question"], ()))
        return {k: v for k, v in q.items() if k != "user"} | {
            "ranked": [{"id": d["id"], "content": d["content"]} for d in data],
            "chars": sum(len(c) for c in contents), "n": len(data),
            "tokens": sum(tokens.item_cost(c) for c in contents),
            "asof": json.loads(asof.dumps(verdict)) if verdict else None}

    with patch.multiple(config, **ARMS[args.arm]):
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            rows = list(pool.map(one, questions))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    base.describe(rows, f"{args.set}/{args.arm}")
    print("asof stats", dict(asof.stats), "| update scope", {k: v for k, v in updates.stats.items() if "scope" in k})


def main_cli() -> None:
    if len(sys.argv) > 1 and sys.argv[1] != "search":
        return base.main_cli()
    root = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = root.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("search")
    p.add_argument("--set", required=True); p.add_argument("--arm", required=True, choices=sorted(ARMS))
    p.add_argument("--store", required=True); p.add_argument("--out", required=True)
    p.add_argument("--streams", default=None); p.add_argument("--ids", default=None)
    p.add_argument("--n", type=int, default=0); p.add_argument("--workers", type=int, default=8)
    p.set_defaults(fn=search)
    args = root.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main_cli()
