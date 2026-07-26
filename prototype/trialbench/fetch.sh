#!/usr/bin/env bash
# TrialBench 데이터셋을 sparse-clone 으로 내려받는다.
#
#   TrialBench: Multi-Modal AI-Ready Datasets for Clinical Trial Prediction
#   Scientific Data 12 (2025).  https://www.nature.com/articles/s41597-025-05680-8
#   저장소: https://github.com/ML2Health/ML2ClinicalTrials
#
# blob:none + sparse-checkout 으로 data/ 만 받는다(약 1 GB).
set -euo pipefail

DEST="${1:-$HOME/.cache/trialbench}"
REPO="https://github.com/ML2Health/ML2ClinicalTrials.git"

if [ -d "$DEST/Trialbench/data" ]; then
  echo "이미 존재: $DEST/Trialbench/data"
  exit 0
fi

mkdir -p "$DEST"
cd "$DEST"
if [ ! -d .git ]; then
  git clone --filter=blob:none --no-checkout --depth 1 "$REPO" .
fi
git sparse-checkout init --no-cone
printf '/Trialbench/data/*\n/Trialbench/README.md\n' > "$(git rev-parse --git-dir)/info/sparse-checkout"
git read-tree -mu HEAD

echo "완료: $DEST/Trialbench/data"
du -sh "$DEST/Trialbench/data"
