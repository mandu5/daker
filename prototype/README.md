# 먹줄(INKLINE) 프로토타입

분자 구조에서 임상 프로토콜 조항을 연역하되, 템플릿에 이미 있는 조항과
이 분자 때문에 필요한 조항을 데이터로 분리하고, 구조 귀속이 입증되지 않으면
기권하는 5-에이전트 규제과학 시스템.

**LLM·GPU·외부 네트워크 없이 완결 동작한다.**

## 실행

```bash
prototype/trialbench/fetch.sh              # TrialBench 수급 (최초 1회, 약 1GB)
python3 prototype/trialbench/s2c_analysis.py   # 사전 선언 기전 게이트
python3 prototype/inkline/evaluate.py          # E1 템플릿 대비 증분
python3 prototype/inkline/calibrate.py         # 조항별 τ 보정
python3 prototype/inkline/evaluate_e3.py       # E3 기권·오판
python3 prototype/inkline/test_invariants.py   # 안전 불변식 35건

python3 prototype/inkline/run.py --smiles "CC(=O)Oc1ccccc1C(=O)O" \
    --phase "Phase 2" --indication "hypertension" --noael 100 --repeat 3
```

## 구조

```
trialbench/   데이터 수급 · 조항 라벨링 · 구조 경보 · 사전 선언 기전 게이트
  load.py         NCT ID 중복 제거 → SMILES 파싱 → 조항 14종 라벨링
  flags.py        구조 경보 15종 (SMARTS + RDKit FilterCatalog)
  mechanism.py    사전 선언 기전 가설 26쌍. 결과를 보기 전에 확정된다
  s2c_analysis.py Fisher 검정 · BH/Bonferroni · 적응증 층화 · 기전 게이트

inkline/      에이전트와 평가
  model.py        B-TPL(템플릿) · B-RULE(규칙엔진) · INKLINE(로지스틱) · 적용범위
  evidence.py     근거 코퍼스. URL 로 실재 확인한 문서만 넣는다
  agents.py       MARKER · SCRIBE · ACTUARY · ADVERSARY · LEDGER
  consistency.py  조항 집합 내부 정합성 검사 6종
  orchestrator.py 자기수정 루프 A1~A4 · Case Bank · 정지 조건
  calibrate.py    조항별 τ 보정. 목표 정밀도 미달이면 발행 봉인
  evaluate.py     E1 SAFE-INC
  evaluate_e3.py  E3 NULL (FOR_safety · 음성 대조 · risk-coverage)
  run.py          엔드투엔드 실행 + 감사 DAG 해시
  test_invariants.py  안전 불변식 35건
  extraction.py   자유서술 → 구조화 추출 어댑터(정규식/LLM). span 대조 실패 시 격리
  viewer.py       감사 DAG 뷰어(자기완결 HTML)

results/      산출물 (제안서가 이 JSON 들을 직접 읽는다)
```

## 설계상 중요한 결정 다섯 가지

**1. 조항을 촉발할 수 있는 구조 경보는 확증된 기전으로만 제한한다.**
사전 선언 게이트에서 기각된 가설(카복실산→신기능, lift 1.02 p=0.41)이 조항을
발행시키면 시스템이 자기 증거 기준을 어기는 것이 된다.

**2. 물성 기반 경보는 Δ\* 귀속 검정으로 분리할 수 없다.**
`lipophilic`(cLogP≥3.7)은 물성 그 자체이고 decoy 에서 매칭해야 하는 값이므로
부분구조 절제로 죽일 수 없다. Δ\* 는 절제 가능한 경보의 기여만 검정하고
그 범위를 `attribution_scope` 에 남긴다.

**3. 목표 정밀도를 만족하는 임계가 없으면 발행을 봉인한다.**
억지로 임계를 낮춰 발행하느니 "이 조항에 대해 말할 자격이 없다"고 판정한다.
현재 10개 조항 중 2개(QT·CYP/DDI)만 발행 자격을 얻었다.

**4. 안전성 조항의 불확실은 침묵이 아니라 승격이다.**
근거가 없다는 이유로 안전성 조항을 조용히 기권하면 실무자는 그 조항을 검토할
기회 자체를 잃는다. 정합성 검사가 이 결함을 잡아냈고 근본 원인을 고쳤다.

**5. 조항 간 모순 탐지는 LLM 이 아니라 결정론으로 한다.**
설계 초안은 이를 LLM 담당으로 적었으나 구현해 보니 검사 규칙 대부분이 명시적
술어로 표현 가능했다. LLM 이 정말 필요한 곳은 자유 서술형 원문에서 조항을
추출하는 단계다.

## 실측 요약 (2026-07-27, 조항 라벨러 감사 반영)

| 지표 | 값 |
|---|---|
| 분석 대상 임상시험 | 39,379건 (고유 81,786건 중) |
| 사전 선언 기전 가설 | 26쌍 → 확증 8 · 기각 15 (확증률 34.8%) |
| 반대 방향으로 유의한 교과서적 기전 | 3건 (티오펜·마이클수용체·염기성아민→위산) |
| FOR_safety (주지표) | 0.12% [0.02, 0.67] — 목표 2% 이하 통과 |
| 음성 대조 누출 | 0건 / 6,748쌍 |
| 발행분 정밀도 | 0.301 [0.208, 0.414] · 발행 73건 |
| CYP·DDI 정밀도 lift | 3.56배 [2.23, 5.25] |
| QT·심전도 정밀도 lift | 2.93배 [1.57, 4.76] |
| 발행분 오경보율 | 0.007 [0.0057, 0.0098] |
| 기권율 | 91.7% (검토 대상 축소) |
| 감사 DAG 재현성 | 3회 실행 해시 일치 |
| 안전 불변식 테스트 | 35/35 통과 |

**라벨러 감사** — 조항 라벨이 정규식 v1 근사라는 한계를 한계로만 적어 두지 않고
실제로 감사했다. QT 조항 양성의 61.2%가 "12-lead ECG will be performed" 류의
**검사 시행 절차 나열**이었고, 음식효과 양성의 97.2%가 `grapefruit` 을 통해
CYP·DDI 와 같은 신호를 두 번 세고 있었다. 둘을 고치자 모든 하위 지표가
**좋아졌다** — 라벨 노이즈가 사전 선언 기전의 신호를 희석하고 있었다.
