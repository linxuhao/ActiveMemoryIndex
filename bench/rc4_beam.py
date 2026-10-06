#!/usr/bin/env python3
"""BEAM-100K pilot for adaptive chunk delivery: B vs L4, descriptive only
(bench/results/adaptive_chunk_preregistration.md, "BEAM").

Input: a JSON file of conversations prepared with bench/beam_pilot.py's own
loader and Add mapping (20 messages / 2,000 words per Add, session time anchor
as timestamp; from the public BEAM parquet, not committed).

    ingest   --data FILE --server URL       replay the Adds through a running service
    search   --data FILE --arm B|L4 --out   in-process Search
    score    --data FILE --file F           leaderboard BEAM answer prompt + batched rubric judge
    compare  --base F --arm F

The answer prompt, judge prompt and parser are the public leaderboard
pipeline's (bench/third_party/agent-memory-leaderboard/data/beam/pipeline.py);
model calls go through bench/llm_proxy.py (gpt-4o-mini; the pipeline default
Qwen3-14B is not available). Event ordering's extra LLM alignment is not run:
the rubric score is reported for every category.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
THIRD = HERE / "third_party"


def pipeline():
    from run_bench import _placeholder_httpx
    _placeholder_httpx()
    path = THIRD / "agent-memory-leaderboard" / "data" / "beam" / "pipeline.py"
    spec = importlib.util.spec_from_file_location("beam_pipeline", path)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parents[2]))
    spec.loader.exec_module(module)
    return module


def ingest(args) -> None:
    from run_bench import post
    adds = [a for conv in json.loads(Path(args.data).read_text()) for a in conv["adds"]]

    def one(body):
        reply = post(f"{args.server}/add", body)
        assert reply.get("success") is True, reply

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(one, adds))
    print(f"{len(adds)} Adds")


def search(args) -> None:
    from app import config, main, store, tokens
    store.init()
    jobs = [(conv["adds"][0]["user_id"], q) for conv in json.loads(Path(args.data).read_text())
            for q in conv["questions"]]
    settings = {"B": {"ADAPTIVE_CHUNK": 0}, "L4": {"ADAPTIVE_CHUNK": 4000, "ADAPTIVE_CHUNK_TOTAL": 120_000}}[args.arm]

    def one(job):
        user, q = job
        data = main._search(main.SearchRequest(query=q["question"], user_id=user, top_k=100))["data"]
        return {**q, "id": f"{user.rsplit('-', 1)[1]}:{q['id']}", "contents": [d["content"] for d in data],
                "chars": sum(len(d["content"]) for d in data),
                "tokens": sum(tokens.item_cost(d["content"]) for d in data)}

    with patch.multiple(config, **settings), ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(one, jobs))
    Path(args.out).write_text(json.dumps(rows, ensure_ascii=False))
    n = len(rows)
    print(f"{args.arm}: {n} questions, chars/q {sum(r['chars'] for r in rows) / n:,.0f}, memories/q "
          f"{sum(len(r['contents']) for r in rows) / n:.1f}, counted tokens/q {sum(r['tokens'] for r in rows) / n:,.0f}")


def chat(prompt: str, salt: str, max_tokens: int, json_mode: bool = False) -> str:
    import urllib.request
    from rc4_study import PROXY
    payload = {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": prompt}],
               "temperature": 0, "max_tokens": max_tokens}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    request = urllib.request.Request(PROXY.rstrip("/") + "/chat/completions", data=json.dumps(payload).encode(),
                                     method="POST", headers={"Content-Type": "application/json", "X-Cache-Salt": salt})
    with urllib.request.urlopen(request, timeout=900) as response:
        return (json.loads(response.read())["choices"][0]["message"]["content"] or "").strip()


def score(args) -> None:
    pipe = pipeline()
    rows = json.loads(Path(args.file).read_text())

    def one(row):
        answer = chat(pipe.render_answer_prompt({"id": row["id"], "question": row["question"],
                                                 "context": row["contents"]}), "beam-answer-rep1", 512)
        rubrics = pipe.rubric_items(row)
        verdict = chat(pipe.render_batch_judge_prompt(row["question"], answer, rubrics), "beam-judge-rep1", 1024, True)
        scores = pipe.parse_rubric_scores(verdict, len(rubrics))
        return {"id": row["id"], "question_type": row["question_type"], "answer": answer,
                "score": sum(s["score"] for s in scores) / len(scores)}

    with ThreadPoolExecutor(max_workers=8) as pool:
        scored = list(pool.map(one, rows))
    out = Path(args.file).with_suffix(".scored.json")
    out.write_text(json.dumps(scored, ensure_ascii=False))
    print(f"{Path(args.file).name}: mean rubric score {sum(r['score'] for r in scored) / len(scored):.3f} over {len(scored)}")


def compare(args) -> None:
    base = {r["id"]: r for r in json.loads(Path(args.base).read_text())}
    arm = {r["id"]: r for r in json.loads(Path(args.arm).read_text())}
    diffs = [arm[k]["score"] - base[k]["score"] for k in base]
    by = {}
    for k in base:
        by.setdefault(base[k]["question_type"], []).append((base[k]["score"], arm[k]["score"]))
    print(f"n={len(diffs)} base {sum(r['score'] for r in base.values()) / len(base):.3f} "
          f"arm {sum(r['score'] for r in arm.values()) / len(arm):.3f} up {sum(d > 0 for d in diffs)} "
          f"down {sum(d < 0 for d in diffs)}")
    for kind, pairs in sorted(by.items()):
        print(f"  {kind:26s} {sum(b for b, _ in pairs) / len(pairs):.3f} -> {sum(a for _, a in pairs) / len(pairs):.3f}")


def main() -> None:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("ingest"); p.add_argument("--data", required=True); p.add_argument("--server", required=True)
    p.set_defaults(fn=ingest)
    p = sub.add_parser("search"); p.add_argument("--data", required=True); p.add_argument("--arm", required=True)
    p.add_argument("--out", required=True); p.set_defaults(fn=search)
    p = sub.add_parser("score"); p.add_argument("--file", required=True); p.set_defaults(fn=score)
    p = sub.add_parser("compare"); p.add_argument("--base", required=True); p.add_argument("--arm", required=True)
    p.set_defaults(fn=compare)
    args = root.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
