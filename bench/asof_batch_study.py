#!/usr/bin/env python3
"""As-of batched time reading (AMI_ASOF_BATCH) — rc6 candidate study
(bench/results/asof_batch_preregistration.md).

    search  --set tr-l2|tr-l3|syn2 --arm R|C --store TAG --streams FILE --out FILE
            in-process Search, production settings; R = rc5 single call
            (AMI_ASOF_BATCH=0), C = batches of 50, cap AMI_LLM_MAX_TOKENS_ASOF_BATCH
    big     --replay FILE --locomo-out F --lme-out F --beam-out F --beam-data FILE
            turn a replay of the 26 big-list as-of Searches into rc4_study /
            rc4_beam search files (gold answers from the public datasets)
Scoring: bench/rc4_study.py score, bench/rc4_beam.py score.
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

ARMS = {"R": {"ADAPTIVE_CHUNK": 0, "ASOF_SELECT": True, "ASOF_BATCH": 0},
        "C": {"ADAPTIVE_CHUNK": 0, "ASOF_SELECT": True, "ASOF_BATCH": 50}}


def search(args) -> None:
    import rc4_study as base
    from app import asof, config, main, store
    store.init()
    questions = base.question_set(args.set, args.store, args.streams)

    def one(q: dict) -> dict:
        data = main._search(main.SearchRequest(query=q["question"], user_id=q["user"], top_k=100))["data"]
        verdict = asof._cache.get((q["question"], ()))
        return {k: v for k, v in q.items() if k != "user"} | {
            "ranked": [{"id": d["id"], "content": d["content"]} for d in data],
            "chars": sum(len(d["content"]) for d in data), "n": len(data),
            "asof": json.loads(asof.dumps(verdict)) if verdict else None}

    with patch.multiple(config, **ARMS[args.arm]):
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            rows = list(pool.map(one, questions))
    Path(args.out).write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    print(f"{args.set}/{args.arm}: {len(rows)} questions; asof stats {dict(asof.stats)}")


def big(args) -> None:
    import rc4_study as base
    replay = json.loads(Path(args.replay).read_text(encoding="utf-8"))
    gold = {q["id"]: q for name in ("locomo", "lme-t") for q in base.question_set(name, "kp", None)}
    beam = {f"{conv['adds'][0]['user_id'].rsplit('-', 1)[1]}:{q['id']}": q
            for conv in json.loads(Path(args.beam_data).read_text()) for q in conv["questions"]}
    out = {"locomo": [], "lme-t": [], "beam": []}
    for r in replay:
        if r["set"] == "beam":
            q = beam[r["id"]]
            out["beam"].append({**q, "id": r["id"], "contents": r["contents"], "chars": sum(map(len, r["contents"]))})
        else:
            q = gold[r["id"]]
            out[r["set"]].append({k: v for k, v in q.items() if k != "user"} | {
                "ranked": [{"id": i, "content": c} for i, c in zip(r["ranked"], r["contents"])],
                "chars": sum(map(len, r["contents"])), "n": len(r["contents"])})
    for name, path in (("locomo", args.locomo_out), ("lme-t", args.lme_out), ("beam", args.beam_out)):
        Path(path).write_text(json.dumps(out[name], ensure_ascii=False), encoding="utf-8")
        print(name, len(out[name]))


def main_cli() -> None:
    root = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = root.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("search")
    for flag in ("--set", "--arm", "--store", "--streams", "--out"):
        p.add_argument(flag, required=True)
    p.add_argument("--workers", type=int, default=8); p.set_defaults(fn=search)
    p = sub.add_parser("big")
    for flag in ("--replay", "--locomo-out", "--lme-out", "--beam-out", "--beam-data"):
        p.add_argument(flag, required=True)
    p.set_defaults(fn=big)
    args = root.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main_cli()
