#!/usr/bin/env bash
# 미리보기 렌더링용 한글 폰트를 내려받는다.
# (제출본 hwpx 는 함초롬돋움을 참조하므로 이 폰트는 미리보기 전용이다.)
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/assets/fonts"
mkdir -p "$DIR"
base="https://raw.githubusercontent.com/google/fonts/main/ofl"
fetch() {
  local url="$1" out="$2"
  [ -s "$DIR/$out" ] && { echo "skip $out"; return; }
  curl -sSL -m 120 -o "$DIR/$out" "$url"
  echo "fetched $out ($(stat -c%s "$DIR/$out") bytes)"
}
fetch "$base/notosanskr/NotoSansKR%5Bwght%5D.ttf"   "NotoSansKR[wght].ttf"
fetch "$base/notoserifkr/NotoSerifKR%5Bwght%5D.ttf" "NotoSerifKR[wght].ttf"
