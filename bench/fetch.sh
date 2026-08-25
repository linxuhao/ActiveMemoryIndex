#!/usr/bin/env bash
# Download the public benchmark data and the platform's public evaluation code.
# Neither is vendored into this repository.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p third_party

if [ ! -f third_party/locomo10.json ]; then
  echo "fetching LoCoMo (snap-research/locomo)"
  curl -sL -o third_party/locomo10.json \
    https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json
fi

if [ ! -d third_party/agent-memory-leaderboard ]; then
  echo "cloning the platform's public evaluation code"
  git clone --depth 1 https://github.com/AML-memory/agent-memory-leaderboard.git \
    third_party/agent-memory-leaderboard
fi

if [ ! -f third_party/longmemeval_s_cleaned.json ]; then
  # LongMemEval-S. The original xiaowu0162/longmemeval is deprecated upstream in
  # favour of this one; they differ by ~180 turns out of 246,930, so the choice
  # is not load-bearing, but the deprecated copy should not be the default.
  echo "fetching LongMemEval-S (xiaowu0162/longmemeval-cleaned, 277 MB)"
  curl -sL --retry 3 -o third_party/longmemeval_s_cleaned.json \
    https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_s_cleaned.json
fi

echo "ready:"
ls -la third_party
