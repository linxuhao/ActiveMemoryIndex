#!/usr/bin/env python3
"""Zero-fact fallback end to end (bench/results/zero_fact_fallback_preregistration.md).

    build    Enemy of the People (Gutenberg #2446) -> Adds with narration-only chunks
    ingest   --arm B|F --server URL         replay the Adds through a running service
    search   --arm B|F                      in-process Search (AMI_DB_PATH is the arm's store)
    score    --arm B|F                      platform ScriptMem answer prompt + exact-option scorer
    compare
    locomo   --db PATH                      zero-fact LoCoMo chunks, and the fallback on them

Public data only, read from /ext (not committed). Outputs in bench/out/rc4-l5.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
OUT = HERE / "out" / "rc4-l5"
EXT = Path(os.environ.get("L5_EXT", "/ext"))
THIRD = HERE / "third_party"
SPEAKER = re.compile(r"^((?:(?:Dr|Mrs|Mr)\.\s)?[A-Z0-9][A-Za-z0-9']*(?:\s[A-Za-z][A-Za-z']*){0,3})"
                     r"(?:(\s*\([^)]*\))[.,]?|[.,])\s*(.+)$")
MAX_MESSAGES, MAX_WORDS = 20, 2000


def paragraphs() -> list[list[dict]]:
    """The smoke's parser: acts -> typed paragraphs."""
    text = (EXT / "enemy_pg2446.txt").read_text(encoding="utf-8")
    start = text.index("AN ENEMY OF THE PEOPLE\n\nACT I")
    end = text.index("*** END OF THE PROJECT GUTENBERG")
    paras = [" ".join(p.split()) for p in re.split(r"\n\s*\n", text[start:end]) if p.strip()]
    acts: list[list[dict]] = []
    for para in paras[1:]:
        if re.fullmatch(r"ACT [IVX]+", para):
            acts.append([])
            continue
        if not acts:
            continue
        match = None if para.startswith("(") else SPEAKER.match(para)
        if match:
            body = f"{(match.group(2) or '').strip()} {match.group(3)}".strip()
            acts[-1].append({"type": "dialogue", "content": f"{match.group(1)}: {body}"})
        else:
            acts[-1].append({"type": "narration", "content": para})
    return acts


def build(_args) -> None:
    adds = []
    for act, turns in enumerate(paragraphs(), 1):
        block, words = [], 0
        for turn in turns:
            n = len(turn["content"].split())
            if block and (len(block) >= MAX_MESSAGES or words + n > MAX_WORDS or block[-1]["type"] != turn["type"]):
                adds.append({"act": act, "types": [t["type"] for t in block], "messages": block})
                block, words = [], 0
            block.append(turn)
            words += n
        if block:
            adds.append({"act": act, "types": [t["type"] for t in block], "messages": block})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "adds.json").write_text(json.dumps(adds, ensure_ascii=False, indent=0))
    narration = sum(all(t == "narration" for t in a["types"]) for a in adds)
    print(f"{len(adds)} Adds, {narration} narration-only, {len(adds) - narration} dialogue")


def ingest(args) -> None:
    from run_bench import post
    adds = json.loads((OUT / "adds.json").read_text())
    user = f"local:l5-{args.arm}:enemy"

    def one(pair):
        number, add = pair
        body = post(f"{args.server}/add", {
            "request_id": f"local:l5-{args.arm}:enemy:a{number}", "user_id": user,
            "session_id": f"local:l5-{args.arm}:enemy:act{add['act']}",
            "messages": [{"role": "user", "content": m["content"]} for m in add["messages"]]})
        assert body.get("success") is True, body

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(one, enumerate(adds)))
    print(f"{len(adds)} Adds -> {user}")


def questions() -> list[dict]:
    data = json.loads((EXT / "ScriptMem" / "data" / "raw" / "enemy.json").read_text(encoding="utf-8"))
    return [{"id": f"enemy-q{k}", **qa} for k, qa in enumerate(data[0]["qa"])]


def search(args) -> None:
    from app import main, store
    store.init()
    user = f"local:l5-{args.arm}:enemy"

    def one(q):
        request = main.SearchRequest(query=q["question"], user_id=user, top_k=100, options=q.get("option"))
        data = main._search(request)["data"]
        return {**q, "ranked": [{"id": d["id"], "content": d["content"]} for d in data]}

    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(one, questions()))
    (OUT / f"retrieval_{args.arm}.json").write_text(json.dumps(rows, ensure_ascii=False))
    print(f"{len(rows)} searched, memories/q {sum(len(r['ranked']) for r in rows) / len(rows):.1f}")


def pipeline():
    import importlib.util
    from run_bench import _placeholder_httpx
    _placeholder_httpx()
    path = THIRD / "agent-memory-leaderboard" / "data" / "scriptmem" / "pipeline.py"
    spec = importlib.util.spec_from_file_location("scriptmem_pipeline", path)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parents[2]))
    spec.loader.exec_module(module)
    return module


def score(args) -> None:
    from rc4_study import complete
    pipe = pipeline()
    rows = json.loads((OUT / f"retrieval_{args.arm}.json").read_text())

    def one(row):
        prompt = pipe.render_answer_prompt({"speaker_1_name": "speaker 1",
                                            "speaker_1_memories": "\n".join(m["content"] for m in row["ranked"]),
                                            "speaker_2_name": "speaker 2", "speaker_2_memories": "",
                                            "question": row["question"]})
        answer = complete(prompt, "answer-rep1", 256)
        gold = pipe.gold_letters(row["answer"])
        pred, malformed = pipe.predicted_letters(answer, row["qa_type"])
        return {"id": row["id"], "qa_type": row["qa_type"], "answer": answer,
                "score": pipe.score_item(row["qa_type"], gold, pred, malformed)}

    with ThreadPoolExecutor(max_workers=8) as pool:
        scored = list(pool.map(one, rows))
    (OUT / f"scored_{args.arm}.json").write_text(json.dumps(scored, ensure_ascii=False))
    print(f"{args.arm}: {sum(r['score'] for r in scored):.2f} / {len(scored)}")


def compare(_args) -> None:
    b = {r["id"]: r for r in json.loads((OUT / "scored_B.json").read_text())}
    f = {r["id"]: r for r in json.loads((OUT / "scored_F.json").read_text())}
    rb = {r["id"]: r for r in json.loads((OUT / "retrieval_B.json").read_text())}
    rf = {r["id"]: r for r in json.loads((OUT / "retrieval_F.json").read_text())}
    same = sum(rb[k]["ranked"] == rf[k]["ranked"] for k in rb)
    wins = sum(f[k]["score"] > b[k]["score"] for k in b)
    losses = sum(f[k]["score"] < b[k]["score"] for k in b)
    print(f"B {sum(r['score'] for r in b.values()):.2f}  F {sum(r['score'] for r in f.values()):.2f}  "
          f"net {sum(f[k]['score'] - b[k]['score'] for k in b):+.2f}  W/L {wins}/{losses}  identical lists {same}/{len(b)}")


def facts_per_add(db: str, user: str) -> dict:
    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT id, kind FROM items WHERE user_id = ?", (user,)).fetchall()
    digests: dict[str, int] = {}
    for ident, kind in rows:
        digest = ident.rsplit("-", 1)[0]
        digests.setdefault(digest, 0)
        digests[digest] += kind == "fact"
    return digests


def stats(args) -> None:
    adds = json.loads((OUT / "adds.json").read_text())
    from app import store
    for arm, db in (("B", args.db_b), ("F", args.db_f)):
        user = f"local:l5-{arm}:enemy"
        counts = facts_per_add(db, user)
        by = {"narration": [], "dialogue": []}
        for number, add in enumerate(adds):
            digest = store.item_id(f"local:l5-{arm}:enemy:a{number}", "raw", 0, user).rsplit("-", 1)[0]
            kind = "narration" if all(t == "narration" for t in add["types"]) else "dialogue"
            by[kind].append(counts.get(digest, 0))
        for kind, values in by.items():
            print(f"{arm} {kind}: {len(values)} Adds, zero-fact {sum(v == 0 for v in values)}, facts {sum(values)}")


def locomo(args) -> None:
    """Chunks of the LoCoMo store with no stored fact: where F would fire."""
    from app import config, llm
    conn = sqlite3.connect(args.db)
    rows = conn.execute("SELECT id, kind, content FROM items WHERE user_id LIKE 'local:locomo-v4:%' ORDER BY seq").fetchall()
    chunks: dict[str, dict] = {}
    for ident, kind, content in rows:
        digest = ident.rsplit("-", 1)[0]
        entry = chunks.setdefault(digest, {"raw": [], "facts": 0})
        if kind == "raw":
            entry["raw"].append(content)
        elif kind == "fact":
            entry["facts"] += 1
    zero = {d: c for d, c in chunks.items() if c["raw"] and c["facts"] == 0}
    print(f"{len(chunks)} LoCoMo chunks, {len(zero)} with no stored fact")
    out = {}
    with __import__("unittest.mock").mock.patch.object(config, "EXTRACT_FALLBACK", True):
        for digest, entry in zero.items():
            lines = [re.sub(r"^((?:\[[^\]]*\] )?)Assistant: ", r"\1assistant: ",
                            re.sub(r"^((?:\[[^\]]*\] )?)I: ", r"\1user: ", line)) for line in entry["raw"]]
            out[digest] = {"turns": entry["raw"], "fallback_facts": llm.extract_facts("\n".join(lines))}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "locomo_zero_fact.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    for digest, entry in out.items():
        print(digest, len(entry["turns"]), "turns ->", len(entry["fallback_facts"]), "fallback facts")


def main() -> None:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build").set_defaults(fn=build)
    p = sub.add_parser("ingest"); p.add_argument("--arm", required=True); p.add_argument("--server", required=True)
    p.set_defaults(fn=ingest)
    for name, fn in (("search", search), ("score", score)):
        p = sub.add_parser(name); p.add_argument("--arm", required=True); p.set_defaults(fn=fn)
    sub.add_parser("compare").set_defaults(fn=compare)
    p = sub.add_parser("stats"); p.add_argument("--db-b", required=True); p.add_argument("--db-f", required=True)
    p.set_defaults(fn=stats)
    p = sub.add_parser("locomo"); p.add_argument("--db", required=True); p.set_defaults(fn=locomo)
    args = root.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
