"""제안서 빌드: 블록 원고 → 제출용 .hwpx + 검증용 PDF/PNG.

    python3 proposal/build.py

hwpx 는 한글에서 열어야 최종 확인이 되지만 컨테이너에 한글이 없다.
그래서 같은 원고를 템플릿과 동일한 용지 기하(A4, 좌우 30mm, 위 35mm, 아래 30mm)의
HTML/PDF 로도 렌더해 10쪽 제한과 시각 완성도를 검증한다.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(REPO, "tools", "hwpx"))
sys.path.insert(0, HERE)

import hwpxbuild  # noqa: E402
import preview  # noqa: E402
from content import AGENT_KO, TEAM, blocks  # noqa: E402

OUT = os.path.join(HERE, "build")
NAME = "제안서_먹줄_INKLINE"

PREVIEW_TEXT = (
    f"제4회 AI 신약개발 경진대회 제안서 / 분야3 규제 대응 및 지능형 임상 설계 / "
    f"팀 {TEAM} / 에이전트 {AGENT_KO}(INKLINE)"
)


def main():
    bl = blocks()
    os.makedirs(OUT, exist_ok=True)

    hwpx_path = os.path.join(OUT, f"{NAME}.hwpx")
    hwpxbuild.build(bl, hwpx_path, preview_text=PREVIEW_TEXT)
    problems = hwpxbuild.validate(hwpx_path)
    print(f"hwpx  : {hwpx_path}  ({os.path.getsize(hwpx_path):,} bytes)")
    print(f"검증  : {'문제 없음' if not problems else problems}")

    _, pdf, pages = preview.preview(bl, OUT, name=NAME, title="제안서 미리보기")
    print(f"PDF   : {pdf}  ({os.path.getsize(pdf):,} bytes)")
    limit = "OK" if pages <= 10 else f"초과 {pages - 10}쪽"
    print(f"쪽수  : {pages} / 10  → {limit}")

    n_fig = sum(1 for x in bl if x["type"] == "img")
    n_tbl = sum(1 for x in bl if x["type"] == "table")
    n_chr = sum(len(x.get("text", "")) for x in bl if x["type"] in ("p", "callout"))
    print(f"구성  : 그림 {n_fig} · 표 {n_tbl} · 본문 약 {n_chr:,}자")
    return 0 if (not problems and pages <= 10) else 1


if __name__ == "__main__":
    raise SystemExit(main())
