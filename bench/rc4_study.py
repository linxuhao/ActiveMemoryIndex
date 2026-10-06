#!/usr/bin/env python3
"""rc4 confirmation studies: as-of selection and adaptive chunk delivery.

Pre-registrations: bench/results/asof_selection_preregistration.md and
bench/results/adaptive_chunk_preregistration.md.

Search runs in-process (app.main._search, the code /search runs) against a
store built by the service, with every model call through bench/llm_proxy.py:
recall questions and router calls are cached there, so every arm of a question
sees the same ranking. Arms change configuration only:

    B    the shipped configuration (the container's environment)
    L4   B + AMI_ADAPTIVE_CHUNK=4000 (AMI_ADAPTIVE_CHUNK_TOTAL 120,000)
    C    equal-text control: B's unit (turn +-1, facts, raw-first) with the
         100-item limit lifted and the character budget set, per question, to
         what L4 delivered on that question (--match L4's retrieval file)
    P    B + AMI_ASOF_SELECT=1

    search   --set S --arm A --store TAG --out FILE [--match FILE]
    score    --file FILE --style locomo|lme [--only IDS.json] [--rep 1]
    compare  --base FILE --arm FILE [--group KEY]
    stats    FILE...
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import threading
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
THIRD = HERE / "third_party"
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

PROXY = os.environ.get("STUDY_PROXY", "http://127.0.0.1:8199/v1")
SMOKE_SEED = 20261005


# --- question sets ------------------------------------------------------------------
def locomo_items() -> list[dict]:
    samples = json.loads((THIRD / "locomo10.json").read_text(encoding="utf-8"))
    items = []
    for conv, sample in enumerate(samples):
        for pos, qa in enumerate(sample["qa"]):
            if qa.get("category") == 5 or "answer" not in qa:
                continue
            items.append({"id": f"conv{conv}-q{pos}", "conv": conv, "question": qa["question"],
                          "gold_answer": str(qa["answer"]), "group": f"cat{qa.get('category')}"})
    return items


def question_set(name: str, store: str, streams: str | None) -> list[dict]:
    if name in ("locomo", "locomo-l4", "locomo-dated"):
        items = locomo_items()
        if name == "locomo-l4":
            # The lead smoke answered the first 150 of this shuffle; the
            # confirmation takes the next 770 (pre-registered).
            random.Random(SMOKE_SEED).shuffle(items)
            items = items[150:920]
        elif name == "locomo-dated":
            from app import asof
            items = [q for q in items if asof.candidate(q["question"]) is not None]
        return [{**q, "user": f"local:{store}:locomo:conv-{q['conv']}"} for q in items]
    if name in ("lme-t", "lme-ku"):
        kind = {"lme-t": "temporal-reasoning", "lme-ku": "knowledge-update"}[name]
        data = json.loads((THIRD / "longmemeval_s_cleaned.json").read_text(encoding="utf-8"))
        rows = sorted((d for d in data if d["question_type"] == kind and d.get("answer_session_ids")),
                      key=lambda d: d["question_id"])
        return [{"id": d["question_id"], "question": d["question"], "gold_answer": str(d["answer"]),
                 "group": kind, "user": f"local:{store}:lme:{d['question_id']}"} for d in rows]
    if name in ("tr-l2", "tr-l3", "syn2"):
        built = json.loads(Path(streams).read_text(encoding="utf-8"))
        key = {"tr-l2": "tr_l2", "tr-l3": "tr_l3", "syn2": "synthetic"}[name]
        return [{**q, "user": f"local:{store}:asof:{s['id']}"} for s in built[key] for q in s["questions"]]
    raise SystemExit(f"unknown set {name}")


# --- ingest (as-of streams) -------------------------------------------------------------
def ingest_streams(args) -> None:
    """Replay as-of streams through a running service's /add."""
    from run_bench import post
    built = json.loads(Path(args.streams).read_text(encoding="utf-8"))
    streams = [s for key in args.keys for s in built[key]]

    def one(stream: dict) -> int:
        for number, messages in enumerate(stream["adds"]):
            body = post(f"{args.server}/add", {
                "request_id": f"local:{args.store}:asof:{stream['id']}:a{number}",
                "user_id": f"local:{args.store}:asof:{stream['id']}",
                "session_id": f"local:{args.store}:asof:{stream['id']}:s{number}", "messages": messages})
            assert body.get("success") is True, body
        return len(stream["adds"])

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        total = sum(pool.map(one, streams))
    print(f"{total} Adds for {len(streams)} streams")


# --- search -------------------------------------------------------------------------------
_local = threading.local()


def search(args) -> None:
    from app import config, main, store, tokens

    store.init()
    questions = question_set(args.set, args.store, args.streams)
    if args.n:
        questions = questions[: args.n]
    patches = {"B": {"ADAPTIVE_CHUNK": 0, "ASOF_SELECT": False}, "L4": {"ADAPTIVE_CHUNK": 4000, "ADAPTIVE_CHUNK_TOTAL": 120_000},
               "C": {"ADAPTIVE_CHUNK": 0}, "P": {"ASOF_SELECT": True}}[args.arm]
    target_chars = {}
    if args.arm == "C":
        target_chars = {r["id"]: r["chars"] for r in json.loads(Path(args.match).read_text(encoding="utf-8"))}
    original = main.select

    def control_select(index, scores, top_k, **kw):
        if getattr(_local, "chars", None) is None:
            return original(index, scores, top_k, **kw)
        kw = dict(kw, limit_override=10_000, budget_override=_local.chars)
        return original(index, scores, top_k, **kw)

    def one(q: dict) -> dict:
        _local.chars = target_chars.get(q["id"]) if args.arm == "C" else None
        request = main.SearchRequest(query=q["question"], user_id=q["user"], top_k=100)
        data = main._search(request)["data"]
        contents = [d["content"] for d in data]
        return {k: v for k, v in q.items() if k != "user"} | {
            "ranked": [{"id": d["id"], "content": d["content"]} for d in data],
            "chars": sum(len(c) for c in contents), "n": len(data),
            "tokens": sum(tokens.item_cost(c) for c in contents)}

    with patch.multiple(config, **patches), patch.object(main, "select", control_select if args.arm == "C" else original):
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            rows = list(pool.map(one, questions))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    describe(rows, f"{args.set}/{args.arm}")
    from app import asof, updates
    print("asof stats", dict(asof.stats), "| update scope", {k: v for k, v in updates.stats.items() if "scope" in k})


def describe(rows: list[dict], label: str) -> None:
    chars = sorted(r["chars"] for r in rows)
    n = [r["n"] for r in rows]
    toks = sorted(r["tokens"] for r in rows)
    print(f"{label}: {len(rows)} questions; chars/q mean {sum(chars) / len(rows):,.0f} p50 {chars[len(chars) // 2]:,} "
          f"max {chars[-1]:,}; memories/q {sum(n) / len(rows):.1f}; counted tokens/q mean "
          f"{sum(toks) / len(rows):,.0f} max {toks[-1]:,}")


# --- answer and judge -----------------------------------------------------------------
def platform(style: str):
    from run_lme import platform_pipeline
    return platform_pipeline("locomo-refined" if style == "locomo" else "longmemeval-s")


def complete(prompt: str, salt: str, max_tokens: int) -> str:
    payload = json.dumps({"model": "gpt-4o-mini", "messages": [{"role": "user", "content": prompt}],
                          "temperature": 0, "max_tokens": max_tokens}).encode("utf-8")
    request = urllib.request.Request(PROXY.rstrip("/") + "/chat/completions", data=payload, method="POST",
                                     headers={"Content-Type": "application/json", "X-Cache-Salt": salt})
    with urllib.request.urlopen(request, timeout=900) as response:
        body = json.loads(response.read())
    return (body["choices"][0]["message"]["content"] or "").strip()


def render(pipeline, row: dict, style: str) -> str:
    # Exactly bench/run_xupd.py's rendering for lists of up to 100 memories
    # (so identical inputs hit the proxy cache), without its 100-item cut: the
    # control arm returns more.
    ranked = row["ranked"] if len(row["ranked"]) > 100 else row["ranked"][:100]
    memories = "\n".join(entry["content"] for entry in ranked)
    if style == "locomo":
        return pipeline.render_answer_prompt({"retrieved_context": memories, "question": row["question"]})
    return pipeline.render_answer_prompt({
        "question": row["question"], "speaker_1_name": "the user", "speaker_1_memories": memories,
        "speaker_2_name": "the assistant", "speaker_2_memories": "", "retrieved_context": memories})


def score(args) -> None:
    pipeline = platform(args.style)
    path = Path(args.file)
    rows = json.loads(path.read_text(encoding="utf-8"))
    if args.only:
        keep = set(json.loads(Path(args.only).read_text()))
        rows = [r for r in rows if r["id"] in keep]
    out = path.with_name(path.stem + f".scored{args.rep}.json")
    done = {r["id"]: r for r in json.loads(out.read_text())} if out.exists() else {}
    todo = [r for r in rows if not (r["id"] in done and done[r["id"]].get("label"))]
    max_tokens = 1024 if args.style == "locomo" else 256

    def one(row: dict) -> dict:
        answer = complete(render(pipeline, row, args.style), f"answer-rep{args.rep}", max_tokens)
        label = None
        try:
            verdict = complete(pipeline.render_accuracy_prompt(
                {"question": row["question"], "gold_answer": row["gold_answer"]}, answer), f"judge-rep{args.rep}", 256)
            label = pipeline.parse_judge_label(verdict)
        except Exception as error:  # noqa: BLE001 - a missing verdict, never a wrong one
            print(f"  judge failed for {row['id']}: {error}", flush=True)
        return {"id": row["id"], "answer": answer, "label": label}

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for result in pool.map(one, todo):
            done[result["id"]] = result
    out.write_text(json.dumps(list(done.values()), ensure_ascii=False), encoding="utf-8")
    labels = [done[r["id"]]["label"] for r in rows if r["id"] in done]
    print(f"{path.name}: {sum(l == 'CORRECT' for l in labels)}/{sum(l is not None for l in labels)} correct "
          f"({len(rows) - sum(l is not None for l in labels)} missing) -> {out.name}")


# --- comparison ------------------------------------------------------------------------
def sign_p(wins: int, losses: int) -> float:
    n, k = wins + losses, min(wins, losses)
    if n == 0:
        return 1.0
    return min(1.0, 2 * sum(math.comb(n, j) for j in range(k + 1)) / 2 ** n)


def verdicts(path: Path, rep: int) -> dict[str, bool]:
    scored = path.with_name(path.stem + f".scored{rep}.json")
    return {r["id"]: r["label"] == "CORRECT" for r in json.loads(scored.read_text()) if r["label"]}


def same(a: dict, b: dict) -> bool:
    return [(e["id"], e["content"]) for e in a["ranked"]] == [(e["id"], e["content"]) for e in b["ranked"]]


def compare(args) -> None:
    base_rows = {r["id"]: r for r in json.loads(Path(args.base).read_text())}
    arm_rows = {r["id"]: r for r in json.loads(Path(args.arm).read_text())}
    base_v, arm_v = verdicts(Path(args.base), args.rep), verdicts(Path(args.arm), args.rep)
    groups = defaultdict(list)
    missing = 0
    for qid, row in base_rows.items():
        if qid not in arm_rows:
            continue
        identical = same(row, arm_rows[qid])
        b = base_v.get(qid)
        a = b if identical and qid not in arm_v else arm_v.get(qid)
        if a is None or b is None:
            missing += 1
            continue
        groups["ALL"].append((b, a, identical))
        groups[str(row.get(args.group, "all"))].append((b, a, identical))
    print(f"{Path(args.arm).name} vs {Path(args.base).name}; {missing} without a verdict")
    print(f"{'group':16s} {'n':>5s} {'changed':>8s} {'base':>6s} {'arm':>6s} {'diff':>6s} {'pt':>7s} {'W':>4s} {'L':>4s} {'sign p':>8s}")
    for name in ["ALL"] + sorted(g for g in groups if g != "ALL"):
        rows = groups[name]
        b = sum(x[0] for x in rows)
        a = sum(x[1] for x in rows)
        w = sum(x[1] and not x[0] for x in rows)
        l = sum(x[0] and not x[1] for x in rows)
        print(f"{name:16s} {len(rows):5d} {sum(not x[2] for x in rows):8d} {b:6d} {a:6d} {a - b:+6d} "
              f"{100 * (a - b) / max(1, len(rows)):+7.2f} {w:4d} {l:4d} {sign_p(w, l):8.4f}")


def changed(args) -> None:
    base_rows = {r["id"]: r for r in json.loads(Path(args.base).read_text())}
    arm_rows = {r["id"]: r for r in json.loads(Path(args.arm).read_text())}
    ids = sorted(q for q in arm_rows if q in base_rows and not same(base_rows[q], arm_rows[q]))
    Path(args.out).write_text(json.dumps(ids))
    print(f"{len(ids)}/{len(arm_rows)} returned lists differ -> {args.out}")


def stats(args) -> None:
    for path in args.files:
        describe(json.loads(Path(path).read_text()), Path(path).name)


def main_cli() -> None:
    root = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = root.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("ingest-streams")
    p.add_argument("--streams", required=True); p.add_argument("--keys", nargs="+", required=True)
    p.add_argument("--store", required=True); p.add_argument("--server", required=True)
    p.add_argument("--workers", type=int, default=8)
    p.set_defaults(fn=ingest_streams)
    p = sub.add_parser("search")
    p.add_argument("--set", required=True); p.add_argument("--arm", required=True, choices=["B", "L4", "C", "P"])
    p.add_argument("--store", required=True); p.add_argument("--out", required=True)
    p.add_argument("--streams", default=None); p.add_argument("--match", default=None)
    p.add_argument("--n", type=int, default=0); p.add_argument("--workers", type=int, default=8)
    p.set_defaults(fn=search)
    p = sub.add_parser("score")
    p.add_argument("--file", required=True); p.add_argument("--style", choices=["locomo", "lme"], required=True)
    p.add_argument("--only", default=None); p.add_argument("--rep", type=int, default=1)
    p.add_argument("--workers", type=int, default=8)
    p.set_defaults(fn=score)
    p = sub.add_parser("compare")
    p.add_argument("--base", required=True); p.add_argument("--arm", required=True)
    p.add_argument("--group", default="group"); p.add_argument("--rep", type=int, default=1)
    p.set_defaults(fn=compare)
    p = sub.add_parser("changed")
    p.add_argument("--base", required=True); p.add_argument("--arm", required=True); p.add_argument("--out", required=True)
    p.set_defaults(fn=changed)
    p = sub.add_parser("stats"); p.add_argument("files", nargs="+"); p.set_defaults(fn=stats)
    args = root.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main_cli()
