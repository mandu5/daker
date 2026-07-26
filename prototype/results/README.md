# 실측 결과

`prototype/trialbench/s2c_analysis.py` 의 산출물. 재현 방법:

```bash
prototype/trialbench/fetch.sh                 # TrialBench 수급 (약 1 GB)
python3 prototype/trialbench/s2c_analysis.py  # 분석 실행
```

## s2c_associations.json

구조 경보 × 프로토콜 조항 연관 분석 결과. 주요 필드:

| 필드 | 내용 |
|---|---|
| `n_unique_trials` | NCT ID 기준 중복 제거 후 고유 임상시험 수 |
| `n_analyzed` | SMILES 파싱 + 기준텍스트 보유 + 물성 필터 통과 건수 |
| `clause_classification` | 조항별 기저율과 템플릿/분자특이/희소 분류 |
| `flag_match_rates` | 구조 플래그별 매칭률 (과다포괄 진단용) |
| `associations_all` | 전체 표본의 (플래그×조항) 연관, Fisher p·Bonferroni·BH FDR |
| `associations_oncology` / `associations_non_oncology` | 적응증 층화 결과 |
| `preregistered_pairs` | 결과를 보기 전에 선언한 기전 가설 18쌍 |
| `mechanism_gate` | confirmatory / refuted / exploratory 분류 |
| `confirmatory_rate` | 사전 선언 쌍의 확증률 |
| `rule_adoption_rate` | 전체 검정 쌍 중 통계·층화 통과 비율 |

## 핵심 수치 (2026-07-26 실행)

- 고유 임상시험 **81,786건** → 분석 대상 **39,379건**
- 사전 선언 기전 가설 18쌍 중 **확증 5, 기각 10** (확증률 33.3%)
- 전체 검정 78쌍 중 통계·층화 통과 18쌍 (채택률 23.1%)

확증된 5쌍 (종양/비종양 양쪽에서 방향 유지):

| 구조 경보 | 조항 | lift (전체) | 종양 | 비종양 |
|---|---|---|---|---|
| 방향족 할로겐 | CYP/약물상호작용 | 1.83 | 2.13 | 1.62 |
| 친유성 (cLogP≥3.7) | CYP/약물상호작용 | 1.78 | 2.01 | 1.54 |
| 하이드라진 | 간기능 | 1.39 | 1.26 | 1.56 |
| hERG 약리단 (염기성아민+친유성) | QT/심전도 | 1.36 | 1.30 | 1.38 |
| 염기성 아민 | QT/심전도 | 1.29 | 1.39 | 1.26 |

기각된 가설 중 주목할 것 — **방향이 반대로 유의**하게 나온 두 건:

| 구조 경보 | 조항 | lift | p |
|---|---|---|---|
| 티오펜 | 간기능 | **0.57** | 8.9e-28 |
| 마이클 수용체 | 간기능 | **0.84** | 5.3e-15 |

티오펜의 반응성 대사체 → 간독성 가설은 이 데이터에서 **반대 방향으로 기각**됐다.
이는 실제 프로토콜 텍스트가 구조 경보를 그대로 반영하지 않는다는 증거이며,
검증 없이 구조 룰을 조항으로 번역하면 안 된다는 우리 설계의 근거가 된다.

## 한계

- 조항 라벨은 정규식 기반 v1 라벨러이며, 사람 검토로 신뢰도(Cohen's κ)를
  측정하기 전까지 근사다.
- TrialBench는 ClinicalTrials.gov 2024-02-16 이전 등록 시험 기반이다.
- `smiless` 는 시험의 개입 약물 SMILES 리스트이며, 가장 큰 분자를 대표로
  삼았다. 병용요법 시험에서는 대표 분자 선택이 신호를 희석시킬 수 있다.
- 적응증 층화는 종양/비종양 2분할이며, 더 세분한 층화가 필요하다.
- 데이터셋 라이선스가 저장소에 명시되어 있지 않다. 학술적 이용을 전제로 하되
  논문의 data availability 항목으로 재확인이 필요하다.
