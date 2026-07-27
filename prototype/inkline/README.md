# 먹줄(INKLINE) 5-에이전트 파이프라인

LLM 호출 없이 완결 동작한다. 외부 네트워크도 필요 없다.

```bash
prototype/trialbench/fetch.sh                  # TrialBench 수급 (최초 1회)
python3 prototype/inkline/evaluate.py          # E1 템플릿 대비 증분 측정
python3 prototype/inkline/run.py --smiles "..." --phase "Phase 1" \
    --indication "advanced solid tumor" --noael 25 --repeat 3
```

## 구성

| 파일 | 역할 |
|---|---|
| `model.py` | B-TPL(템플릿 베이스라인) · B-RULE(규칙엔진) · INKLINE(로지스틱) · 적용범위(AD) |
| `agents.py` | MARKER · SCRIBE · ACTUARY · ADVERSARY · LEDGER |
| `evaluate.py` | E1 SAFE-INC. ΔP@C · ΔAUPRC · ECE |
| `run.py` | 엔드투엔드 실행 + 감사 DAG 해시 + E4 재현성 확인 |

## 설계상 중요한 결정

**1. 조항을 촉발할 수 있는 구조 경보는 확증된 기전으로 제한한다.**
사전 선언 기전 게이트에서 기각된 가설(예: 카복실산→신기능, lift 1.02 p=0.41)이
조항을 발행시키면 시스템이 자기 증거 기준을 어기는 것이 된다. 모델 특징에는
사전 선언 전체가 들어가지만, **발행 자격은 확증된 기전에만** 준다.

**2. 물성 기반 경보는 Δ* 귀속 검정으로 분리할 수 없다.**
`lipophilic`(cLogP≥3.7)은 물성 그 자체이고 decoy 에서 매칭해야 하는 값이므로,
부분구조 절제로 죽일 수 없다. Δ* 는 절제 가능한 경보의 기여만 검정하며
`attribution_scope` 에 그 범위를 남긴다. 절제 가능한 경보가 없으면 판정을 보류한다.

**3. 기권은 실패가 아니라 산출물이다.**
4-튜플(근거·유발리스크·봉인된 반증조건·신뢰도)이 하나라도 비면 발행이 거부된다.
안전성 조항이 신뢰도 미달이면 기권하지 않고 사람에게 승격한다.

## 실행 예시 (prototype/results/runs/)

| 파일 | 사례 | 결과 |
|---|---|---|
| `demo_kinase_like.txt` | 염기성아민 + 방향족할로겐 + 친유성, 1상 종양 | 사람검토 2 · 기권 3 |
| `demo_aspirin.txt` | 카복실산만 보유, 2상 비종양 | 기권 5 (확증된 기전 트리거 없음) |
| `demo_out_of_scope.txt` | 모달리티가 항체 | 조항 기안 자체를 하지 않고 기권 |

세 사례 모두 3회 반복 실행 시 감사 DAG 해시가 일치한다(E4 재현성).
