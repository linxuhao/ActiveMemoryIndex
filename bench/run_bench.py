"""Local LoCoMo harness for tuning the two retrieval knobs before the one formal run.

Phases:
    ingest    replay conversations through /add exactly as the platform does
    retrieve  one /search per question at top_k=100, ranked ids recorded
    report    recall@k of the ranked ids against LoCoMo's own evidence field
    answer    end-to-end answers with the platform's verbatim answer prompt
    judge     the platform's verbatim judge prompt over those answers

See bench/README.md for the deviations from the official evaluation.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
THIRD = HERE / "third_party"
OUT = HERE / "out"
CHUNK_MESSAGES = 20
EXCLUDED_CATEGORY = 5  # adversarial: no supporting memory exists


def _load_dotenv() -> None:
    """Read .env from the project root so scripts work without manual export."""
    env_path = HERE.parent / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, val = stripped.partition("=")
        # Strip inline comments the way Docker Compose does, so a value read here
        # matches the value the container actually receives. Without this,
        # `AMI_AUTH_SCHEME=bearer   # none | bearer` parses as the whole comment
        # and every authenticated request silently 401s.
        val = val.split(" #", 1)[0].split("\t#", 1)[0]
        key, val = key.strip(), val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


_load_dotenv()

# Auth: read from the same env vars the service uses.
_AUTH_SCHEME = os.environ.get("AMI_AUTH_SCHEME", "none").lower()
_AUTH_TOKEN = os.environ.get("AMI_AUTH_TOKEN", "")
_AUTH_HEADERS: dict[str, str] = {}
if _AUTH_SCHEME == "bearer":
    _AUTH_HEADERS["Authorization"] = f"Bearer {_AUTH_TOKEN}"
elif _AUTH_SCHEME == "token":
    _AUTH_HEADERS["Authorization"] = f"Token {_AUTH_TOKEN}"
elif _AUTH_SCHEME == "x-api-key":
    _AUTH_HEADERS["X-API-Key"] = _AUTH_TOKEN


# --- data --------------------------------------------------------------------
def load_locomo() -> list[dict]:
    return json.loads((THIRD / "locomo10.json").read_text(encoding="utf-8"))


def session_keys(conversation: dict) -> list[int]:
    numbers = set()
    for key in conversation:
        match = re.fullmatch(r"session_(\d+)", key)
        if match and isinstance(conversation[key], list):
            numbers.add(int(match.group(1)))
    return sorted(numbers)


def session_epoch_ms(conversation: dict, number: int) -> int:
    raw = conversation.get(f"session_{number}_date_time", "")
    for fmt in ("%I:%M %p on %d %B, %Y", "%I:%M %p on %d %b, %Y"):
        try:
            moment = dt.datetime.strptime(raw.strip(), fmt).replace(tzinfo=dt.timezone.utc)
            return int(moment.timestamp() * 1000)
        except ValueError:
            continue
    return int(dt.datetime(2023, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)


def post(url: str, payload: dict, timeout: int = 900) -> dict:
    headers = {"Content-Type": "application/json", "User-Agent": "AMI-Bench/1.0", **_AUTH_HEADERS}
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers=headers, method="POST",
    )
    # Transient network hiccups (RemoteDisconnected, timeouts) retry; HTTP error
    # codes do not — a 4xx/5xx from the service is a real result, not weather.
    import http.client
    import time as _time
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError, ConnectionError) as error:
            if attempt == 3:
                raise
            _time.sleep(5 * (attempt + 1))
            print(f"  transient {type(error).__name__} on {url}, retrying", flush=True)


def chunk_hash(request_id: str) -> str:
    return hashlib.sha1(request_id.encode("utf-8")).hexdigest()[:16]


# --- phases ------------------------------------------------------------------
def ingest(args) -> None:
    samples = load_locomo()
    chunks: dict[str, dict] = {}
    pending: list[dict] = []
    for index in args.conv:
        sample = samples[index]
        conversation = sample["conversation"]
        speaker_a = conversation.get("speaker_a")
        user_id = f"local:{args.tag}:locomo:conv-{index}"
        for number in session_keys(conversation):
            turns = conversation[f"session_{number}"]
            base = session_epoch_ms(conversation, number)
            for offset in range(0, len(turns), CHUNK_MESSAGES):
                block = turns[offset: offset + CHUNK_MESSAGES]
                request_id = f"local:{args.tag}:locomo:conv-{index}:s{number}:chunk-{offset // CHUNK_MESSAGES}"
                messages = []
                message_dias: dict[str, str] = {}
                for position, turn in enumerate(block):
                    text = (turn.get("text") or "").strip()
                    if not text:
                        continue
                    messages.append({
                        "role": "user" if turn.get("speaker") == speaker_a else "assistant",
                        "timestamp": base + (offset + position) * 60_000,
                        "content": text,
                    })
                    message_dias[str(len(messages) - 1)] = turn.get("dia_id", "")
                if not messages:
                    continue
                pending.append({
                    "request_id": request_id, "messages": messages, "user_id": user_id,
                    "session_id": f"local:{args.tag}:conv-{index}:s{number}",
                })
                chunks[chunk_hash(request_id)] = {
                    "conv": index,
                    "dias": [d for d in message_dias.values() if d],
                    "msg_dias": message_dias,
                }

    def send(payload: dict) -> None:
        body = post(f"{args.server}/add", payload)
        assert body.get("success") is True, body
        print(f"  added {payload['request_id']} ({len(payload['messages'])} messages)", flush=True)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(send, pending))
    target = OUT / args.tag
    target.mkdir(parents=True, exist_ok=True)
    (target / "chunks.json").write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")
    print(f"ingested {len(chunks)} chunks -> {target/'chunks.json'}")


def questions_for(samples: list[dict], conv: list[int]) -> list[dict]:
    items = []
    for index in conv:
        for position, qa in enumerate(samples[index]["qa"]):
            if qa.get("category") == EXCLUDED_CATEGORY or "answer" not in qa:
                continue
            evidence = [e for e in (qa.get("evidence") or []) if isinstance(e, str)]
            items.append({
                "id": f"conv{index}-q{position}",
                "conv": index,
                "question": qa["question"],
                "gold_answer": str(qa["answer"]),
                "category": qa.get("category"),
                "evidence": evidence,
            })
    return items


def retrieve(args) -> None:
    samples = load_locomo()
    items = questions_for(samples, args.conv)
    target = OUT / args.tag
    target.mkdir(parents=True, exist_ok=True)

    store = args.store_tag or args.tag

    def one(item: dict) -> dict:
        body = post(f"{args.server}/search", {
            "query": item["question"],
            "user_id": f"local:{store}:locomo:conv-{item['conv']}",
            "top_k": args.top_k,
        })
        data = body.get("data", [])
        return {**item, "ranked": [{"id": d["id"], "content": d["content"]} for d in data]}

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(one, items))
    (target / "retrieval.json").write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")
    print(f"searched {len(results)} questions -> {target/'retrieval.json'}")


def item_dias(item_id: str, chunks: dict) -> set[str]:
    match = re.fullmatch(r"([0-9a-f]{16})-([rf])(\d+)", item_id)
    if not match:
        return set()
    chunk = chunks.get(match.group(1))
    if not chunk:
        return set()
    if match.group(2) == "r":
        dia = chunk["msg_dias"].get(match.group(3))
        return {dia} if dia else set()
    return set(chunk["dias"])  # a fact's provenance is its whole chunk


def report(args) -> None:
    target = OUT / args.tag
    chunk_source = OUT / (args.store_tag or args.tag)
    chunks = json.loads((chunk_source / "chunks.json").read_text(encoding="utf-8"))
    results = json.loads((target / "retrieval.json").read_text(encoding="utf-8"))
    scored = [r for r in results if r["evidence"]]
    cutoffs = [5, 10, 20, 40, 100]
    print(f"tag={args.tag}  questions with evidence={len(scored)}/{len(results)}")
    print("  k     recall   (a question counts when any evidence turn is inside the top k)")
    for k in cutoffs:
        hits = 0
        for row in scored:
            gold = set(row["evidence"])
            if any(item_dias(entry["id"], chunks) & gold for entry in row["ranked"][:k]):
                hits += 1
        print(f"  {k:<5} {hits/len(scored):.3f}   ({hits}/{len(scored)})")
    for kind, label in (("r", "verbatim turns only"), ("f", "extracted facts only")):
        hits = 0
        for row in scored:
            gold = set(row["evidence"])
            filtered = [e for e in row["ranked"] if re.fullmatch(rf"[0-9a-f]{{16}}-{kind}\d+", e["id"])]
            if any(item_dias(entry["id"], chunks) & gold for entry in filtered[:20]):
                hits += 1
        print(f"  recall@20 using {label}: {hits/len(scored):.3f}")
    by_category: dict[int, list[int]] = {}
    for row in scored:
        gold = set(row["evidence"])
        hit = any(item_dias(entry["id"], chunks) & gold for entry in row["ranked"][:20])
        by_category.setdefault(row["category"], []).append(int(hit))
    print("  recall@20 by LoCoMo category:")
    for category in sorted(by_category):
        values = by_category[category]
        print(f"    category {category}: {sum(values)/len(values):.3f}  (n={len(values)})")


# --- end-to-end layer --------------------------------------------------------
def platform_pipeline():
    path = THIRD / "agent-memory-leaderboard" / "locomo-refined" / "pipeline.py"
    spec = importlib.util.spec_from_file_location("locomo_pipeline", path)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent.parent))
    spec.loader.exec_module(module)
    return module


def completer(model: str, base_url: str | None, api_key: str, args_max_tokens: int = 1024):
    """Completion helper with explicit exponential backoff.

    Lesson from the 2026-08-06 incident: the SDK's own retries exhaust within
    seconds under a daily-quota 429, hundreds of calls then fail silently, and
    empty answers judged WRONG masquerade as a dilution effect. Backoff here is
    long enough to ride out per-minute limits, and the final failure RAISES —
    the caller decides what a failure means, never a silent empty string.
    """
    import time as _time

    from openai import OpenAI

    client = OpenAI(api_key=api_key or "none", base_url=base_url, timeout=600, max_retries=0)

    reasoning = re.compile(r"<think>.*?</think>\s*", re.DOTALL)

    def complete(prompt: str) -> str:
        last: Exception | None = None
        for attempt in range(6):
            try:
                response = client.chat.completions.create(
                    model=model, messages=[{"role": "user", "content": prompt}], temperature=0,
                    max_tokens=args_max_tokens,
                )
                text = reasoning.sub("", response.choices[0].message.content or "")
                return "" if "<think>" in text else text.strip()
            except Exception as error:  # noqa: BLE001
                last = error
                _time.sleep(min(5 * 2 ** attempt, 120))
        raise RuntimeError(f"completion failed after 6 attempts: {last}")

    return complete


def answer(args) -> None:
    pipeline = platform_pipeline()
    target = OUT / args.tag
    results = json.loads((target / "retrieval.json").read_text(encoding="utf-8"))
    complete = completer(args.model, args.base_url, args.api_key, args.max_tokens)

    # Resume: keep existing non-empty answers, regenerate only the gaps.
    path = target / f"answers_p{args.prefix}.json"
    kept: dict[str, dict] = {}
    if path.exists():
        kept = {row["id"]: row for row in json.loads(path.read_text(encoding="utf-8"))
                if row.get("generated_answer", "").strip()}
        if kept:
            print(f"  resuming: {len(kept)} non-empty answers kept, {len(results)-len(kept)} to generate")

    def one(row: dict) -> dict:
        if row["id"] in kept:
            return kept[row["id"]]
        memories = "\n".join(entry["content"] for entry in row["ranked"][: args.prefix])
        prompt = pipeline.render_answer_prompt({"retrieved_context": memories, "question": row["question"]})
        try:
            generated = complete(prompt)
        except Exception as error:  # noqa: BLE001
            generated = ""
            print(f"  answer FAILED for {row['id']}: {error}", flush=True)
        return {"id": row["id"], "question": row["question"], "gold_answer": row["gold_answer"],
                "category": row["category"], "generated_answer": generated}

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        answers = list(pool.map(one, results))
    path.write_text(json.dumps(answers, ensure_ascii=False), encoding="utf-8")
    empty = sum(1 for row in answers if not row["generated_answer"].strip())
    print(f"answered {len(answers)} questions at prefix {args.prefix} -> {path}")
    if empty:
        print(f"  *** {empty} EMPTY answers remain — rerun this command to fill them; do NOT judge yet ***")
        sys.exit(2)


def judge(args) -> None:
    pipeline = platform_pipeline()
    target = OUT / args.tag
    answers = json.loads((target / f"answers_p{args.prefix}.json").read_text(encoding="utf-8"))
    complete = completer(args.model, args.base_url, args.api_key, args.max_tokens)

    def one(row: dict) -> dict:
        # A judge failure is a MISSING measurement, never a WRONG verdict.
        prompt = pipeline.render_accuracy_prompt(row, row["generated_answer"])
        try:
            raw = complete(prompt)
            label = pipeline.parse_judge_label(raw)
        except Exception as error:  # noqa: BLE001
            print(f"  judge FAILED for {row['id']}: {error}", flush=True)
            raw, label = f"JUDGE_ERROR: {error}", None
        return {**row, "label": label, "judge_raw": raw[:400]}

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        judged = list(pool.map(one, answers))
    path = target / f"judged_p{args.prefix}.json"
    path.write_text(json.dumps(judged, ensure_ascii=False), encoding="utf-8")
    valid = [row for row in judged if row["label"] is not None]
    correct = sum(1 for row in valid if row["label"] == "CORRECT")
    excluded = len(judged) - len(valid)
    note = f", {excluded} judge-failures EXCLUDED" if excluded else ""
    print(f"prefix {args.prefix}: accuracy {correct/max(len(valid),1):.3f} ({correct}/{len(valid)}{note}) -> {path}")
    if excluded:
        sys.exit(2)


# --- cli ---------------------------------------------------------------------
def main() -> None:
    root = argparse.ArgumentParser()
    commands = root.add_subparsers(dest="command", required=True)

    def shared(parser, server=False):
        parser.add_argument("--tag", required=True)
        parser.add_argument("--workers", type=int, default=8)
        if server:
            parser.add_argument("--server", default="http://127.0.0.1:8000")
            parser.add_argument("--conv", type=int, nargs="+", default=[0])

    ingest_parser = commands.add_parser("ingest")
    shared(ingest_parser, server=True)
    ingest_parser.set_defaults(run=ingest)

    retrieve_parser = commands.add_parser("retrieve")
    shared(retrieve_parser, server=True)
    retrieve_parser.add_argument("--top-k", type=int, default=100)
    retrieve_parser.add_argument("--store-tag", default=None,
                                 help="search a store ingested under a different tag (for knob sweeps)")
    retrieve_parser.set_defaults(run=retrieve)

    report_parser = commands.add_parser("report")
    report_parser.add_argument("--tag", required=True)
    report_parser.add_argument("--store-tag", default=None)
    report_parser.set_defaults(run=report)

    for name, function in (("answer", answer), ("judge", judge)):
        parser = commands.add_parser(name)
        shared(parser)
        parser.add_argument("--prefix", type=int, default=100)
        parser.add_argument("--model", default=os.environ.get("BENCH_MODEL", "gpt-4o-mini"))
        parser.add_argument("--base-url", default=os.environ.get("BENCH_BASE_URL") or None)
        parser.add_argument("--api-key", default=os.environ.get("BENCH_API_KEY", ""))
        parser.add_argument("--max-tokens", type=int, default=int(os.environ.get("BENCH_MAX_TOKENS", 1024)))
        parser.set_defaults(run=function)

    args = root.parse_args()
    args.run(args)


if __name__ == "__main__":
    main()
