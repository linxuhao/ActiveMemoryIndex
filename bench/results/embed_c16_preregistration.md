# Pre-registration — text-embedding-v4 at concurrency 16, timeout 40 s (rc4 step test)

Written 2026-10-06 before the run. Code: commit `99cba0e` (`app/embed.py`,
`app/deadline.py`). Runner: `bench/rc4_embed_step.py`.

## Context

The settings are a user decision for rc4 (`AMI_EMBED_CONCURRENCY=16`,
`AMI_EMBED_TIMEOUT=40`, `AMI_EMBED_RETRIES=1`); this test does not decide them.
It measures what they do with the rc4 transport: an Add's batches now run side
by side inside the shared gate, every attempt is clipped to the request
deadline (`AMI_ADD_DEADLINE=85`), and a call that cannot finish in time ends in
`DeadlineExceeded` (503 + Retry-After at the API) before anything is
persisted. The lead smoke (L3) saw 20 s timeouts in 15–33 % of requests at
every concurrency, including 4.

## Run

* The rc4 image, the academic env file's embedding endpoint and key, real
  provider; nothing else running from this session against it.
* 55 Add-shaped calls (20 synthetic turns of 300–1,500 characters + 24
  synthetic facts of 60–160 characters = 5 batches of ≤ 10), 16 closed-loop
  workers, each call under an 85 s deadline. ≈ 0.25M embedding tokens; cap
  0.3M (the run is sized so that it cannot exceed it).

## Report

Per attempt: timeout rate (attempts that hit their timeout / all attempts),
other errors, latency p50/p95/max. Per call: outcomes (ok / deadline / other),
latency p50/p95/max, Adds/s over the wall time (embedding-bound Adds/s, an
upper bound on Add throughput because extraction is not included). Compared
descriptively with L3's c16 row (1.15–1.61 requests/s, 10 texts per request,
timeouts at 20 s).

No gate: the settings ship either way. A call outcome other than ok/deadline,
or any call slower than the deadline + 1 s, is reported as a defect.
