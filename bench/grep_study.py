"""Lexical channel on a public coding-memory proxy (SWE-ContextBench).

Per repository, a user's memory is that repository's past tasks ("experience":
issue text, the fix and its tests), written through the service's own Add as a
trajectory of user/assistant messages, ≤10,000 characters each. Each "related"
task asks Search for help; the relevant memory is the experience task the
dataset links it to. Three query forms stand in for what the platform's agent
might send, which is not published: the related issue's full text, its first
200 characters, and the file paths its own fix touches (what an agent searches
once it has localised the change). Scored on the service's returned set
(top_k=100): rank of the first item from the linked experience, hit@10/20/100.

Runs the service in-process with whatever embedding backend the environment
selects; with no LLM key Add stores verbatim turns only and Search uses the
plain query, so the only difference between arms is AMI_LEXICAL.

    python3 bench/grep_study.py DATA_DIR OUT.json
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config, main, store  # noqa: E402

DIFF_FILE = re.compile(r"^diff --git a/(\S+) b/", re.M)
PIECE = 10_000


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.open()]


def pieces(text: str) -> list[str]:
    text = (text or "").strip()
    return [text[i:i + PIECE] for i in range(0, len(text), PIECE)] if text else []


def messages(task: dict) -> list[dict]:
    when = int(dt.datetime.fromisoformat(task["created_at"].replace("Z", "+00:00")).timestamp() * 1000)
    turns = [("user", p) for p in pieces(task["problem_statement"] + ("\n\n" + task["hints_text"]
                                                                       if task["hints_text"] else ""))]
    turns += [("assistant", p) for p in pieces("Fix:\n" + task["patch"])]
    turns += [("assistant", p) for p in pieces("Tests:\n" + task["test_patch"])]
    return [{"role": role, "content": content, "timestamp": when + i * 1000} for i, (role, content) in enumerate(turns)]


def main_(data: Path, out: Path) -> None:
    experience = {t["instance_id"]: t for t in load(data / "SWEContextBench_Experience.jsonl")}
    related = {t["instance_id"]: t for t in load(data / "SWEContextBench_Related.jsonl")}
    links = collections.defaultdict(set)
    for row in load(data / "SWEContextBench_Relationship.jsonl"):
        links[row["related_instance_id"]].add(row["experience_instance_id"])

    store.init()
    owner: dict[str, str] = {}
    started = time.monotonic()
    for task in sorted(experience.values(), key=lambda t: t["created_at"]):
        user = task["repo"]
        request = main.AddRequest(request_id=task["instance_id"], user_id=user, session_id=task["instance_id"],
                                  messages=messages(task))
        main.add(request, None, None)
        digest = store.item_id(task["instance_id"], "raw", 0, user).rsplit("-", 1)[0]
        owner[digest] = task["instance_id"]
    print(f"ingested {len(experience)} tasks in {time.monotonic() - started:.0f}s", flush=True)

    queries = []
    for rid, task in sorted(related.items()):
        gold = links[rid] & set(experience)
        if not gold:
            continue
        paths = " ".join(dict.fromkeys(DIFF_FILE.findall(task["patch"])))
        for form, text in (("issue", task["problem_statement"]), ("title", task["problem_statement"][:200]),
                           ("paths", paths)):
            if text.strip():
                queries.append((rid, form, text, task["repo"], gold))

    results = []
    for arm in ("dense", "lexical"):
        config.LEXICAL = arm == "lexical"
        for rid, form, text, user, gold in queries:
            data = main.search(main.SearchRequest(query=text, user_id=user, top_k=100), None, None)["data"]
            sources = [owner.get(d["id"].rsplit("-", 1)[0]) for d in data]
            ranks = [i + 1 for i, s in enumerate(sources) if s in gold]
            results.append({"arm": arm, "related": rid, "form": form, "returned": len(data),
                            "first": ranks[0] if ranks else None, "gold_items": len(ranks),
                            "chars": sum(len(d["content"]) for d in data)})
        print(f"arm {arm} done", flush=True)
    out.write_text(json.dumps({"backend": config.EMBED_BACKEND, "queries": len(queries), "results": results}))

    table = collections.defaultdict(list)
    for r in results:
        table[(r["form"], r["arm"])].append(r)
    print(f"{'form':6} {'arm':8} {'n':>4} {'hit@10':>7} {'hit@20':>7} {'hit@100':>8} {'median first':>13}")
    for (form, arm), rows in sorted(table.items()):
        firsts = sorted(r["first"] for r in rows if r["first"])
        hit = lambda k: sum(1 for r in rows if r["first"] and r["first"] <= k) / len(rows)
        median = firsts[len(firsts) // 2] if firsts else None
        print(f"{form:6} {arm:8} {len(rows):4} {hit(10):7.3f} {hit(20):7.3f} {hit(100):8.3f} {str(median):>13}")


if __name__ == "__main__":
    main_(Path(sys.argv[1]), Path(sys.argv[2]))
