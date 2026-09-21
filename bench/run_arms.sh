#!/usr/bin/env bash
# Run the pre-registered LongMemEval arms against one shared store.
#
# Every arm is retrieval-only: they read the store `bench/run_lme.py ingest`
# built and never rebuild it, so the ~6,400 extraction calls are paid once and
# no arm can differ by what was written. The container is recreated per arm so
# that the only thing separating two arms is the environment printed below.
#
#   bash bench/run_arms.sh base chrono nowindow agentic qdate
#
# Decision rule lives in bench/results/lme_temporal_preregistration.md; read it
# before reading any number this produces.
set -euo pipefail

SERVER=${SERVER:-http://127.0.0.1:8010}
STORE=${STORE:-lme-t}
TYPES=${TYPES:-temporal-reasoning}
IMAGE=${IMAGE:-activememoryindex:lme}
ENV_FILE=${ENV_FILE:-$HOME/ActiveMemoryIndex/.env}
HERE="$(cd "$(dirname "$0")/.." && pwd)"

restart() {
  docker rm -f ami-bench >/dev/null 2>&1 || true
  docker run -d --name ami-bench \
    --env-file "$ENV_FILE" \
    -e AMI_AUTH_SCHEME=none -e AMI_DB_PATH=/data/bench.sqlite3 \
    -e AMI_CACHE_MAX_ITEMS=30000 -e MALLOC_ARENA_MAX=2 -e OMP_NUM_THREADS=1 \
    "$@" \
    -v ami-bench-data:/data -p 127.0.0.1:8010:8000 \
    --memory=3g --cpus=12 --restart=no "$IMAGE" >/dev/null
  # The cache is cold after a restart, so the first search reloads a user from
  # SQLite. Wait for health rather than sleeping a guessed number of seconds.
  for _ in $(seq 1 40); do
    curl -sf -m 5 "$SERVER/health" >/dev/null && return 0
    sleep 3
  done
  echo "ami-bench did not come up" >&2; exit 1
}

arm() {
  local tag="$1"; shift
  local extra_retrieve="$1"; shift
  echo "=== arm ${tag}: $* ${extra_retrieve}"
  restart "$@"
  python3 "$HERE/bench/run_lme.py" retrieve --tag "$tag" --store-tag "$STORE" \
    --types $TYPES --server "$SERVER" --top-k 100 --workers 8 $extra_retrieve
  python3 "$HERE/bench/run_lme.py" report --tag "$tag" --store-tag "$STORE" --types $TYPES \
    | tee "$HERE/bench/results/lme_${tag}_retrieval.txt"
}

for name in "$@"; do
  case "$name" in
    # Shipped configuration. Every other arm is this with one thing changed.
    base)     arm base     ""  -e AMI_RAW_FIRST=1 -e AMI_WINDOW_RADIUS=1 -e AMI_AGENTIC_SEARCH=0 -e AMI_CHRONO_ORDER=0 ;;
    # Order only: each block oldest-first instead of relevance-first.
    chrono)   arm chrono   ""  -e AMI_RAW_FIRST=1 -e AMI_WINDOW_RADIUS=1 -e AMI_AGENTIC_SEARCH=0 -e AMI_CHRONO_ORDER=1 ;;
    # The neighbour window was chosen on LoCoMo; here its slots may be wanted
    # for the second event instead of for the turn next to the first one.
    nowindow) arm nowindow ""  -e AMI_RAW_FIRST=1 -e AMI_WINDOW_RADIUS=0 -e AMI_AGENTIC_SEARCH=0 -e AMI_CHRONO_ORDER=0 ;;
    # Second targeted recall when the first round looks incomplete. Costs one
    # extra LLM call per search, so it must clear the noise floor by more than
    # the others to be worth shipping.
    agentic)  arm agentic  ""  -e AMI_RAW_FIRST=1 -e AMI_WINDOW_RADIUS=1 -e AMI_AGENTIC_SEARCH=1 -e AMI_CHRONO_ORDER=0 ;;
    # Ceiling probe, NOT a shippable arm: 42/133 questions are anchored to
    # "now" and no published pipeline conveys the question date.
    qdate)    arm qdate "--with-question-date" -e AMI_RAW_FIRST=1 -e AMI_WINDOW_RADIUS=1 -e AMI_AGENTIC_SEARCH=0 -e AMI_CHRONO_ORDER=0 ;;
    # Delivery only: the shipped selection, but each selected memory is returned
    # as the whole Add chunk it belongs to, one slot instead of eighteen.
    chunkmem) arm chunkmem "" -e AMI_RAW_FIRST=1 -e AMI_WINDOW_RADIUS=1 -e AMI_AGENTIC_SEARCH=0 -e AMI_CHRONO_ORDER=0 -e AMI_CHUNK_MEMORY=1 ;;
    # The arm: facts do the selecting, chunks come back whole. Decision rule in
    # bench/results/chunk_memory_preregistration.md.
    factsel)  arm factsel  "" -e AMI_RAW_FIRST=1 -e AMI_WINDOW_RADIUS=1 -e AMI_AGENTIC_SEARCH=0 -e AMI_CHRONO_ORDER=0 -e AMI_FACT_SELECT=1 -e AMI_CHUNK_MEMORY=1 ;;
    # Same configuration as base, run twice: the noise floor of this instrument,
    # measured before any arm is judged against it.
    base2)    arm base2    ""  -e AMI_RAW_FIRST=1 -e AMI_WINDOW_RADIUS=1 -e AMI_AGENTIC_SEARCH=0 -e AMI_CHRONO_ORDER=0 ;;
    *) echo "unknown arm: $name" >&2; exit 2 ;;
  esac
done
