# 제안서 빌드

```bash
python3 proposal/figures.py         # 도식 5종 생성 (결과 JSON에서 수치를 읽어온다)
python3 proposal/build.py           # 원고 -> 제출용 hwpx + 검증용 PDF
python3 proposal/verify_numbers.py  # 본문 하드코딩 수치와 실측 결과 대조
```

## 제출 전 점검 순서

1. `prototype/trialbench/s2c_analysis.py` — 기전 게이트
2. `prototype/inkline/evaluate.py` — E1 템플릿 대비 증분
3. `prototype/inkline/calibrate.py` — 조항별 τ 보정
4. `prototype/inkline/evaluate_e3.py` — E3 기권·오판
5. `proposal/figures.py` → `proposal/build.py` → `proposal/verify_numbers.py`

**분석을 다시 돌렸으면 반드시 도식을 재생성해야 한다.** 도식은 결과 JSON을
읽어 렌더링되므로, 재생성하지 않으면 본문 수치와 도식 수치가 어긋난다.
`verify_numbers.py` 가 이 어긋남을 잡는다 — 실제로 τ 보정 후 기권율이
94%(구) vs 92.25%(신)로 어긋난 것을 이 스크립트가 발견했다.

## 파일

| 파일 | 역할 |
|---|---|
| `content.py` | 원고 본문 (블록 DSL). 수치는 결과 JSON에서 동적으로 읽는다 |
| `figures.py` | 도식 6종 생성 |
| `build.py` | hwpx + PDF 빌드, 10쪽 제한 검증 |
| `verify_numbers.py` | 하드코딩 수치 24건 실측 대조 |
| `build/` | 산출물 (hwpx 가 제출본) |

## 남은 검증

**hwpx 를 한글에서 직접 열어 확인해야 한다.** 이 저장소의 도구는 한글을 실행할
수 없어 동일 용지 기하의 PDF 로만 검증한다. 확인할 것: 함초롬돋움 13pt·줄간격
130% 적용 여부, 표·이미지 렌더링, 10쪽 초과 여부.
