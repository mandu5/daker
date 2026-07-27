#!/usr/bin/env bash
# 조항 라벨을 고친 뒤 측정을 처음부터 다시 돌린다.
# 라벨이 바뀌면 기전 게이트 → 모델 적합 → τ 보정 → E3 가 전부 달라진다.
# 중간 하나만 다시 돌리면 결과 JSON 사이가 어긋난다.
set -euo pipefail
cd "$(dirname "$0")/.."
R=prototype/results/runs

echo "== E1 템플릿 대비 증분 =="
python3 prototype/inkline/evaluate.py    > "$R/e1_console.txt"    2>&1
echo "== 조항별 τ 보정 =="
python3 prototype/inkline/calibrate.py   > "$R/calib_console.txt" 2>&1
echo "== E3 기권·오판 =="
python3 prototype/inkline/evaluate_e3.py > "$R/e3_console.txt"    2>&1
echo "== 안전 불변식 =="
python3 prototype/inkline/test_invariants.py | tail -3
echo "RERUN-COMPLETE"
