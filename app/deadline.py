"""A wall-clock deadline for one Add or Search, and the retry loop that honours it.

The public endpoint sits behind Cloudflare, which cuts the origin at ~100 s
whatever the platform allows. An Add makes up to three gpt-4o-mini calls
(extraction beside two update-detection stages) and then several
text-embedding-v4 batches; a Search makes the recall rewrite, one embedding
call and optional router/verifier calls. With per-call timeouts and retries
alone, the worst case is their sum: 40 s x 2 attempts x 4 batches is already
320 s for the embeddings of one Add.

So each request carries a deadline, measured from its arrival at the ASGI app
(before any wait in the admission valve). Every upstream attempt's timeout is
clipped to the time left, a retry is made only while time is left, and a call
that cannot be made in time raises DeadlineExceeded, which the app answers
with 503 + Retry-After. Persistence comes after every upstream call, so a 503
from here has persisted nothing and the platform's retry is a clean first
attempt.

Without a deadline in the context (offline tools, tests) every function here
behaves as before: full timeouts, full retries.
"""
from __future__ import annotations

import contextvars
import random
import time

from . import config

_deadline: contextvars.ContextVar[float | None] = contextvars.ContextVar("ami_deadline", default=None)
# Seconds kept back from the last attempt, for the response to be written.
RESERVE = 0.5
# An attempt shorter than this is not worth starting.
MIN_ATTEMPT = 1.0


class DeadlineExceeded(Exception):
    """Not enough time left for an upstream call; answered 503 + Retry-After."""

    status = 503

    def __init__(self, reason: str = "request deadline reached before the upstream call completed"):
        super().__init__(reason)
        self.reason = reason
        self.retry_after = config.RETRY_AFTER


def start(seconds: float, origin: float | None = None) -> None:
    """Set the deadline for the current context: *seconds* after *origin*
    (time.monotonic(); default now). 0 or less: no deadline."""
    if seconds and seconds > 0:
        _deadline.set((origin if origin is not None else time.monotonic()) + seconds)
    else:
        _deadline.set(None)


def clear() -> None:
    _deadline.set(None)


def remaining() -> float | None:
    """Seconds left, or None without a deadline."""
    value = _deadline.get()
    return None if value is None else value - time.monotonic()


def clip(timeout: float) -> float:
    """*timeout*, shortened to the time left. Raises DeadlineExceeded when
    less than MIN_ATTEMPT is left."""
    left = remaining()
    if left is None:
        return timeout
    left -= RESERVE
    if left < MIN_ATTEMPT:
        raise DeadlineExceeded()
    return min(timeout, left)


def wait_budget() -> float | None:
    """How long a caller may block (on a semaphore), or None for no limit."""
    left = remaining()
    if left is None:
        return None
    left -= RESERVE + MIN_ATTEMPT
    if left <= 0:
        raise DeadlineExceeded()
    return left


def acquire(gate) -> None:
    """Acquire *gate* (a semaphore), waiting no longer than the deadline allows."""
    budget = wait_budget()
    if budget is None:
        gate.acquire()
    elif not gate.acquire(timeout=budget):
        raise DeadlineExceeded("request deadline reached while waiting for an upstream slot")


def call(attempt, retries: int, retryable, retry_after=None):
    """Run ``attempt()`` up to 1 + *retries* times.

    *attempt* clips its own timeout with clip() once it holds whatever slot it
    needs. *retryable(exc)* says whether an exception may be retried;
    *retry_after(exc)* may give the provider's requested wait in seconds. A
    retry whose wait would not leave time for another attempt is not made:
    DeadlineExceeded is raised instead. With the retries used up, the last
    exception is raised.
    """
    last: Exception | None = None
    for number in range(1 + max(0, retries)):
        if number:
            wait = retry_after(last) if retry_after else None
            if wait is None:
                wait = min(8.0, 0.5 * 2 ** (number - 1)) * (0.75 + 0.5 * random.random())
            wait = min(float(wait), 60.0)
            left = remaining()
            if left is not None and left - wait - RESERVE < MIN_ATTEMPT:
                raise DeadlineExceeded() from last
            time.sleep(wait)
        try:
            return attempt()
        except DeadlineExceeded:
            raise
        except Exception as exc:  # noqa: BLE001 - classified below
            if not retryable(exc):
                raise
            last = exc
    raise last
