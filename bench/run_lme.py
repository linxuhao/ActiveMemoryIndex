#!/usr/bin/env python3
"""LongMemEval-S harness — the multi-evidence instrument LoCoMo is not.

LoCoMo answers 73.2% of its questions from a single evidence turn (and its
largest category, cat4 at 841/1540, from a single turn 94.5% of the time).
LongMemEval-S needs evidence from two or more distinct sessions for 69% of its
questions: 113/133 temporal-reasoning, 133/133 multi-session, 78/78
knowledge-update.

Every retrieval knob in this project was chosen on the first shape. This
harness measures the second one, and reports *completeness* — did the returned
set cover ALL the evidence a question needs — alongside per-turn recall,
because a single-target metric cannot see the failure mode that matters here.
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import re
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_bench import CHUNK_MESSAGES, OUT, THIRD, _placeholder_httpx, chunk_hash, post  # noqa: E402

DATE_FORMAT = "%Y/%m/%d (%a) %H:%M"
ITEM_ID = re.compile(r"([0-9a-f]{16})-([rf])(\d+)")


def dataset_path(name: str) -> Path:
    return THIRD / name


def platform_pipeline(benchmark: str = "longmemeval-s"):
    """Import the platform's answer/judge prompts for one benchmark.

    Upstream moved the pipelines under `data/` after this project first cloned
    them, so both layouts are tried rather than failing on the older path.
    """
    _placeholder_httpx()
    for candidate in (THIRD / "agent-memory-leaderboard" / "data" / benchmark / "pipeline.py",
                      THIRD / "agent-memory-leaderboard" / benchmark / "pipeline.py"):
        if candidate.is_file():
            spec = importlib.util.spec_from_file_location(f"{benchmark}_pipeline", candidate)
            module = importlib.util.module_from_spec(spec)
            sys.path.insert(0, str(candidate.parents[2]))
            spec.loader.exec_module(module)
            return module
    raise SystemExit(f"no pipeline.py for {benchmark}; run bench/fetch.sh")


def completer(model: str, base_url: str | None, api_key: str, max_tokens: int = 256):
    """Chat completions over the standard library.

    run_bench uses the openai SDK; neither machine this harness runs on has it,
    and neither has pip. The service calls in run_bench already go through
    urllib, so the answer and judge stages do too. Backoff is long enough to
    ride out a per-minute limit, and the final failure RAISES — the caller
    decides what a failure means, never a silent empty string.
    """
    import time as _time
    import urllib.error
    import urllib.request

    endpoint = (base_url or "https://api.openai.com/v1").rstrip("/") + "/chat/completions"

    def complete(prompt: str) -> str:
        payload = json.dumps({
            "model": model, "messages": [{"role": "user", "content": prompt}],
            "temperature": 0, "max_tokens": max_tokens,
        }).encode("utf-8")
        last: Exception | None = None
        for attempt in range(6):
            request = urllib.request.Request(
                endpoint, data=payload, method="POST",
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            )
            try:
                with urllib.request.urlopen(request, timeout=600) as response:
                    body = json.loads(response.read())
                return (body["choices"][0]["message"]["content"] or "").strip()
            except Exception as error:  # noqa: BLE001
                last = error
                _time.sleep(min(5 * 2 ** attempt, 120))
        raise RuntimeError(f"completion failed after 6 attempts: {last}")

    return complete


def epoch_ms(stamp: str) -> int:
    moment = dt.datetime.strptime(stamp, DATE_FORMAT).replace(tzinfo=dt.timezone.utc)
    return int(moment.timestamp() * 1000)


def load(args) -> list[dict]:
    data = json.loads(dataset_path(args.data).read_text(encoding="utf-8"))
    if args.types:
        data = [d for d in data if d["question_type"] in args.types]
    # Abstention items have no supporting memory, the way LoCoMo category 5 has
    # none; they cannot be scored for retrieval and are excluded from both
    # layers rather than counted as misses.
    data = [d for d in data if d.get("answer_session_ids")]
    data.sort(key=lambda d: d["question_id"])
    if args.limit and args.limit < len(data):
        # Stride, not head: question_ids cluster by source, so the first N would
        # be a biased slice of one generator run.
        stride = len(data) / args.limit
        data = [data[int(i * stride)] for i in range(args.limit)]
    return data


def user_of(tag: str, question_id: str) -> str:
    # One haystack per question, so one user per question. Sharing a user_id
    # across instances would let one question's distractors answer another's.
    return f"local:{tag}:lme:{question_id}"


# --- phases ------------------------------------------------------------------
def ingest(args) -> None:
    instances = load(args)
    chunks: dict[str, dict] = {}
    pending: list[dict] = []
    for instance in instances:
        question_id = instance["question_id"]
        user_id = user_of(args.tag, question_id)
        triples = zip(instance["haystack_session_ids"], instance["haystack_dates"],
                      instance["haystack_sessions"])
        for session_index, (session_id, date, session) in enumerate(triples):
            base = epoch_ms(date)
            for offset in range(0, len(session), CHUNK_MESSAGES):
                block = session[offset: offset + CHUNK_MESSAGES]
                request_id = f"local:{args.tag}:lme:{question_id}:s{session_index}:chunk-{offset // CHUNK_MESSAGES}"
                messages: list[dict] = []
                evidence: list[str] = []
                for position, turn in enumerate(block):
                    text = (turn.get("content") or "").strip()
                    if not text:
                        continue
                    messages.append({
                        "role": turn.get("role") or "user",
                        # LongMemEval dates one session, not one turn. Spacing
                        # turns a minute apart inside a session keeps the order
                        # legible without inventing a precision it does not have.
                        # It does push a turn past midnight when a session
                        # starts just before it: measured on the temporal
                        # subset, 280 of 65,519 turns (0.43%) and 0 of 259
                        # evidence turns. Seconds would avoid it entirely; the
                        # store in bench/results was built with minutes, so the
                        # two agree as written.
                        "timestamp": base + (offset + position) * 60_000,
                        "content": text,
                    })
                    if turn.get("has_answer"):
                        evidence.append(str(len(messages) - 1))
                if not messages:
                    continue
                pending.append({
                    "request_id": request_id, "messages": messages, "user_id": user_id,
                    "session_id": f"local:{args.tag}:{question_id}:{session_id}",
                })
                chunks[chunk_hash(request_id, user_id)] = {
                    "qid": question_id, "session": session_id, "evidence": evidence,
                }

    def send(payload: dict) -> None:
        body = post(f"{args.server}/add", payload)
        assert body.get("success") is True, body

    print(f"{len(instances)} instances -> {len(pending)} /add calls", flush=True)
    if args.map_only:
        print("map-only: skipping the /add calls")
    else:
        done = 0
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for _ in pool.map(send, pending):
                done += 1
                if done % 100 == 0:
                    print(f"  {done}/{len(pending)}", flush=True)
    target = OUT / args.tag
    target.mkdir(parents=True, exist_ok=True)
    (target / "chunks.json").write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")
    (target / "instances.json").write_text(json.dumps(
        [{k: v for k, v in d.items() if k != "haystack_sessions"} for d in instances],
        ensure_ascii=False), encoding="utf-8")
    print(f"ingested {len(chunks)} chunks -> {target / 'chunks.json'}")


def retrieve(args) -> None:
    instances = load(args)
    target = OUT / args.tag
    target.mkdir(parents=True, exist_ok=True)
    store_tag = args.store_tag or args.tag

    def one(instance: dict) -> dict:
        query = instance["question"]
        if args.with_question_date:
            # The platform's answer prompt has no slot for "now", so questions
            # like "how many weeks ago" are unanswerable unless the current date
            # reaches the system some other way. This arm measures what knowing
            # it is worth; it is not something the contract promises.
            query = f"[today is {instance['question_date']}] {query}"
        body = post(f"{args.server}/search", {
            "query": query,
            "user_id": user_of(store_tag, instance["question_id"]),
            "top_k": args.top_k,
        })
        data = body.get("data", [])
        return {
            "id": instance["question_id"],
            "question_type": instance["question_type"],
            "question": instance["question"],
            "question_date": instance["question_date"],
            "gold_answer": str(instance["answer"]),
            "ranked": [{"id": d["id"], "content": d["content"]} for d in data],
        }

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(one, instances))
    (target / "retrieval.json").write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")
    print(f"searched {len(results)} questions -> {target / 'retrieval.json'}")


def report(args) -> None:
    target = OUT / args.tag
    chunks = json.loads((OUT / (args.store_tag or args.tag) / "chunks.json").read_text(encoding="utf-8"))
    results = json.loads((target / "retrieval.json").read_text(encoding="utf-8"))

    gold_turns: dict[str, set[tuple[str, str]]] = defaultdict(set)
    gold_sessions: dict[str, set[str]] = defaultdict(set)
    for digest, meta in chunks.items():
        for position in meta["evidence"]:
            gold_turns[meta["qid"]].add((digest, position))
            gold_sessions[meta["qid"]].add(meta["session"])
    if not gold_turns:
        raise SystemExit("no evidence turns in the chunk map — the join key is wrong, not the score")

    rows = []
    for result in results:
        gold = gold_turns.get(result["id"], set())
        if not gold:
            continue
        # Score the prefix the answer stage will actually be given. Coverage at
        # 100 says nothing about coverage at 20, and an accuracy quoted without
        # the token budget that produced it is not interpretable.
        ranked = result["ranked"][: args.prefix] if args.prefix else result["ranked"]
        exact: set[tuple[str, str]] = set()
        digests: set[str] = set()
        for entry in ranked:
            match = ITEM_ID.fullmatch(entry["id"])
            if not match:
                continue
            digests.add(match.group(1))
            if match.group(2) == "r":
                exact.add((match.group(1), match.group(3)))
        # A fact's provenance is its whole chunk, so chunk cover is the generous
        # measure and per-turn is the strict one. Read them as a bracket.
        covered = {pair for pair in gold if pair[0] in digests}
        seen_sessions = {chunks[d]["session"] for d in digests if d in chunks}
        rows.append({
            "type": result["question_type"],
            "turn": len(gold & exact) / len(gold),
            "chunk": len(covered) / len(gold),
            "complete_turn": gold <= exact,
            "complete_chunk": covered == gold,
            "complete_session": gold_sessions[result["id"]] <= seen_sessions,
            "n_gold": len(gold),
            "returned": len(ranked),
            "chars": sum(len(e["content"]) for e in ranked),
        })

    def summarise(label: str, subset: list[dict]) -> None:
        if not subset:
            return
        n = len(subset)
        print(f"{label:26s} {n:4d} "
              f"{sum(r['turn'] for r in subset) / n:9.3f} "
              f"{sum(r['chunk'] for r in subset) / n:9.3f} "
              f"{sum(r['complete_turn'] for r in subset) / n:11.3f} "
              f"{sum(r['complete_chunk'] for r in subset) / n:12.3f} "
              f"{sum(r['complete_session'] for r in subset) / n:10.3f} "
              f"{sum(r['returned'] for r in subset) / n:8.1f} "
              f"{sum(r['chars'] for r in subset) / n:9.0f}")

    print(f"\ntag={args.tag}  questions={len(rows)}"
          + (f"  prefix={args.prefix}" if args.prefix else "  prefix=all") + "\n")
    print(f"{'subset':26s} {'n':>4s} {'turn@k':>9s} {'chunk@k':>9s} "
          f"{'all-turns':>11s} {'all-chunks':>12s} {'all-sess':>10s} {'items':>8s} {'chars':>9s}")
    summarise("ALL", rows)
    for question_type in sorted({r["type"] for r in rows}):
        summarise(question_type, [r for r in rows if r["type"] == question_type])
    print()
    for bucket, label in ((1, "single-evidence"), (2, "2 evidence turns"), (3, ">=3 evidence turns")):
        subset = [r for r in rows if (r["n_gold"] == bucket if bucket < 3 else r["n_gold"] >= 3)]
        summarise(label, subset)


def answer(args) -> None:
    pipeline = platform_pipeline()
    target = OUT / args.tag
    results = json.loads((target / "retrieval.json").read_text(encoding="utf-8"))
    complete = completer(args.model, args.base_url, args.api_key, args.max_tokens)

    def one(result: dict) -> dict:
        memories = "\n".join(e["content"] for e in result["ranked"][: args.prefix])
        question = result["question"]
        if args.with_question_date:
            question = f"Today is {result['question_date']}. {question}"
        item = {
            "id": result["id"], "question": question, "gold_answer": result["gold_answer"],
            "speaker_1_name": "the user", "speaker_1_memories": memories,
            "speaker_2_name": "the assistant", "speaker_2_memories": "",
            "retrieved_context": memories,
        }
        return {**item, "generated_answer": complete(pipeline.render_answer_prompt(item))}

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        answers = list(pool.map(one, results))
    path = target / f"answers_p{args.prefix}.json"
    path.write_text(json.dumps(answers, ensure_ascii=False), encoding="utf-8")
    print(f"answered {len(answers)} -> {path}")


def judge(args) -> None:
    pipeline = platform_pipeline()
    target = OUT / args.tag
    answers = json.loads((target / f"answers_p{args.prefix}.json").read_text(encoding="utf-8"))
    complete = completer(args.model, args.base_url, args.api_key, args.max_tokens)

    def one(row: dict) -> dict:
        # A judge failure is a MISSING measurement, never a WRONG verdict.
        try:
            label = pipeline.parse_judge_label(complete(pipeline.render_accuracy_prompt(row, row["generated_answer"])))
        except Exception as error:  # noqa: BLE001
            print(f"  judge FAILED for {row['id']}: {error}", flush=True)
            label = None
        return {"id": row["id"], "label": label}

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        judged = list(pool.map(one, answers))
    path = target / f"judged_p{args.prefix}.json"
    path.write_text(json.dumps(judged, ensure_ascii=False), encoding="utf-8")
    types = {r["id"]: r["question_type"] for r in json.loads((target / "retrieval.json").read_text(encoding="utf-8"))}
    valid = [r for r in judged if r["label"] is not None]
    correct = sum(1 for r in valid if r["label"] == "CORRECT")
    excluded = len(judged) - len(valid)
    note = f", {excluded} judge-failures EXCLUDED" if excluded else ""
    print(f"prefix {args.prefix}: accuracy {correct / max(len(valid), 1):.3f} ({correct}/{len(valid)}{note})")
    by_type: dict[str, list[bool]] = defaultdict(list)
    for row in valid:
        by_type[types.get(row["id"], "?")].append(row["label"] == "CORRECT")
    for question_type in sorted(by_type):
        hits = by_type[question_type]
        print(f"  {question_type:28s} {sum(hits) / len(hits):.3f}  ({sum(hits)}/{len(hits)})")
    if excluded:
        sys.exit(2)


# --- cli ---------------------------------------------------------------------
def main() -> None:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)

    def shared(parser, server: bool = False):
        parser.add_argument("--tag", required=True)
        parser.add_argument("--data", default="longmemeval_s_cleaned.json")
        parser.add_argument("--types", nargs="*", default=["temporal-reasoning"])
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--workers", type=int, default=8)
        if server:
            parser.add_argument("--server", default="http://127.0.0.1:8010")

    ingest_parser = commands.add_parser("ingest")
    shared(ingest_parser, server=True)
    ingest_parser.add_argument("--map-only", action="store_true")
    ingest_parser.set_defaults(run=ingest)

    retrieve_parser = commands.add_parser("retrieve")
    shared(retrieve_parser, server=True)
    retrieve_parser.add_argument("--store-tag", default=None)
    retrieve_parser.add_argument("--top-k", type=int, default=100)
    retrieve_parser.add_argument("--with-question-date", action="store_true")
    retrieve_parser.set_defaults(run=retrieve)

    report_parser = commands.add_parser("report")
    shared(report_parser)
    report_parser.add_argument("--store-tag", default=None)
    report_parser.add_argument("--prefix", type=int, default=0,
                               help="score only the first N returned memories (0 = all)")
    report_parser.set_defaults(run=report)

    for name, function in (("answer", answer), ("judge", judge)):
        parser = commands.add_parser(name)
        shared(parser)
        parser.add_argument("--prefix", type=int, default=100)
        parser.add_argument("--model", default="gpt-4o-mini")
        parser.add_argument("--base-url", default=None)
        parser.add_argument("--api-key", default=None)
        parser.add_argument("--max-tokens", type=int, default=256)
        parser.add_argument("--with-question-date", action="store_true")
        parser.set_defaults(run=function)

    args = root.parse_args()
    if getattr(args, "api_key", None) is None and hasattr(args, "api_key"):
        import os
        args.api_key = os.environ.get("OPENAI_API_KEY", "")
    args.run(args)


if __name__ == "__main__":
    main()
