#!/usr/bin/env python3
"""Real-provider step test for the rc4 embedding settings
(bench/results/embed_c16_preregistration.md).

Runs the service's own embedding path (app.embed.encode: concurrent batches,
deadline-clipped attempts, AMI_EMBED_RETRIES) with Add-shaped calls under a
per-call deadline equal to AMI_ADD_DEADLINE, from N closed-loop workers. Texts
are synthetic (no user data). Every provider attempt is recorded.

    python3 bench/rc4_embed_step.py --calls 55 --workers 16 --out FILE
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config, deadline, embed  # noqa: E402

WORDS = ("garden river budget morning ticket station window coffee market planet lesson harbor engine "
         "letter forest signal kitchen summer valley bridge island mirror pocket record silver thunder "
         "anchor basket candle desert feather garage helmet jacket ladder marble needle orchard pepper").split()


def text(rng: random.Random, low: int, high: int) -> str:
    length = rng.randint(low, high)
    out = []
    while sum(len(w) + 1 for w in out) < length:
        out.append(rng.choice(WORDS))
    return " ".join(out).capitalize() + "."


def add_shaped(rng: random.Random) -> list[str]:
    """20 turns of 300-1,500 characters and 24 facts of 60-160: one Add."""
    return [text(rng, 300, 1500) for _ in range(20)] + [text(rng, 60, 160) for _ in range(24)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calls", type=int, default=55)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    attempts: list[dict] = []
    lock = threading.Lock()
    client, gate = embed._get_remote_client()
    real = client.embeddings.create

    def recorded(**kw):
        started = time.monotonic()
        row = {"timeout": kw.get("timeout"), "texts": len(kw.get("input") or [])}
        try:
            response = real(**kw)
            usage = getattr(response, "usage", None)
            row.update(ok=True, tokens=getattr(usage, "total_tokens", None) or getattr(usage, "prompt_tokens", 0))
            return response
        except Exception as error:  # noqa: BLE001 - recorded and re-raised
            row.update(ok=False, error=type(error).__name__)
            raise
        finally:
            row["seconds"] = round(time.monotonic() - started, 3)
            with lock:
                attempts.append(row)

    client.embeddings.create = recorded
    rngs = [random.Random(1000 + n) for n in range(args.calls)]
    results = []

    def one(n: int) -> dict:
        texts = add_shaped(rngs[n])
        deadline.start(config.ADD_DEADLINE)
        started = time.monotonic()
        try:
            embed.encode(texts)
            outcome = "ok"
        except deadline.DeadlineExceeded:
            outcome = "deadline"
        except Exception as error:  # noqa: BLE001
            outcome = type(error).__name__
        finally:
            deadline.clear()
        return {"n": n, "outcome": outcome, "seconds": round(time.monotonic() - started, 3),
                "chars": sum(len(t) for t in texts)}

    wall = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(one, range(args.calls)))
    wall = time.monotonic() - wall
    ok = [r for r in results if r["outcome"] == "ok"]
    lat = sorted(r["seconds"] for r in results)
    timeouts = [a for a in attempts if not a["ok"] and "Timeout" in a.get("error", "")]
    summary = {
        "settings": {"concurrency": config.EMBED_CONCURRENCY, "timeout": config.EMBED_TIMEOUT,
                     "retries": config.EMBED_RETRIES, "batch": config.EMBED_BATCH,
                     "add_deadline": config.ADD_DEADLINE, "workers": args.workers},
        "calls": len(results), "calls_ok": len(ok),
        "call_outcomes": {o: sum(r["outcome"] == o for r in results) for o in {r["outcome"] for r in results}},
        "adds_per_s": round(len(ok) / wall, 3), "wall_s": round(wall, 1),
        "call_latency_p50_p95_max": [lat[len(lat) // 2], lat[int(len(lat) * 0.95) - 1], lat[-1]],
        "attempts": len(attempts), "attempt_timeouts": len(timeouts),
        "attempt_timeout_rate": round(len(timeouts) / max(1, len(attempts)), 4),
        "attempt_errors": {e: sum(a.get("error") == e for a in attempts) for e in {a.get("error") for a in attempts if not a["ok"]}},
        "attempt_latency_p50_p95_max": (lambda s: [s[len(s) // 2], s[int(len(s) * 0.95) - 1], s[-1]])(
            sorted(a["seconds"] for a in attempts)),
        "embedding_tokens": sum(a.get("tokens") or 0 for a in attempts if a["ok"]),
    }
    Path(args.out).write_text(json.dumps({"summary": summary, "calls": results, "attempts": attempts}, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
