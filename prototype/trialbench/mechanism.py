"""사전 선언 기전 가설 (pre-registered mechanistic hypotheses).

왜 필요한가
    구조 플래그 15종 × 조항 8종 = 120쌍을 전수 검정하면, 다중검정 보정을
    하더라도 **기전으로 설명되지 않는 유의한 연관**이 다수 나온다.
    실제로 첫 실행에서 `PAINS → 피임 조항`, `아닐린 → 피임 조항` 같은
    쌍이 유의하게 나왔다. 이는 화학적 기전이 아니라 적응증·약물계열
    교락일 가능성이 훨씬 높다.

    따라서 **결과를 보기 전에** 어떤 (플래그 → 조항) 쌍이 의약화학적으로
    타당한지를 선언해 두고, 검정 결과를 두 갈래로 나눈다.

    - confirmatory : 사전 선언된 쌍이며 통계·층화를 통과 → **가치 주장에 사용**
    - exploratory  : 사전 선언되지 않았으나 유의 → **보고하되 주장하지 않음**
    - refuted      : 사전 선언했으나 통과 실패 → **실패로 보고**

    이 구분이 없으면 "유의한 것만 골라 썼다"는 비판을 방어할 수 없다.

기전 근거는 통상적 의약화학·약물대사 지식에 기반한 **가설**이며,
검증은 실제 프로토콜 텍스트가 수행한다.
"""

from __future__ import annotations

# (플래그, 조항) → 기전 가설
# 이 표는 s2c_analysis.py 를 실행하기 전에 확정되었고, 결과에 따라 수정하지 않는다.
PREREGISTERED = {
    # ── hERG / QT ─────────────────────────────────────────────
    ("basic_amine", "QT_ECG"):
        "양성자화 염기성 질소가 hERG 포어 방향족 잔기와 상호작용하는 고전적 약리단 요소",
    ("herg_pharmacophore", "QT_ECG"):
        "염기성 아민 + 높은 친유성 조합이 hERG 저해와 연관되어 논의되어 온 휴리스틱",
    ("basic_amine", "QT_DRUG"):
        "동일 기전. QT 연장 약물 병용 금지 조항으로도 반영될 수 있음",
    ("herg_pharmacophore", "QT_DRUG"):
        "동일 기전",

    # ── CYP 매개 대사 / 약물상호작용 ──────────────────────────
    ("lipophilic", "CYP_DDI"):
        "친유성 화합물은 CYP 기질·저해제가 될 가능성이 높아 병용 제한 조항을 유발",
    ("halogenated_aromatic", "CYP_DDI"):
        "방향족 할로겐화는 친유성을 높여 CYP 매개 대사 의존도를 증가시킴",

    # ── 반응성 대사체 → 간독성 ────────────────────────────────
    ("thiophene", "HEPATIC"):
        "티오펜 고리의 CYP 매개 S-산화가 반응성 대사체를 형성할 수 있다고 보고됨",
    ("nitroaromatic", "HEPATIC"):
        "니트로방향족의 환원 대사가 반응성 중간체를 생성할 수 있음",
    ("aniline", "HEPATIC"):
        "방향족 아민의 N-산화·N-아세틸화 경로가 반응성 종을 형성할 수 있음",
    ("hydrazine", "HEPATIC"):
        "하이드라진 계열은 간독성 보고가 있는 반응성 작용기",
    ("michael_acceptor", "HEPATIC"):
        "공유결합성 친전자체는 단백 부가체 형성을 통해 간 관련 조항을 유발할 수 있음",
    ("epoxide", "HEPATIC"):
        "에폭사이드는 친전자성 알킬화제로 반응성 대사 경로와 연관",
    ("quinone", "HEPATIC"):
        "퀴논의 산화환원 순환은 산화 스트레스와 연관",

    # ── 신배설 ────────────────────────────────────────────────
    ("carboxylic_acid", "RENAL"):
        "산성 작용기는 신세뇨관 능동수송 기질이 되는 경우가 많아 신기능 조항과 연관 가능",
    ("sulfonamide", "RENAL"):
        "설폰아마이드계의 결정뇨(crystalluria) 보고와 연관",

    # ── 광과민성 ──────────────────────────────────────────────
    ("sulfonamide", "PHOTO"):
        "설폰아마이드계 광과민성 보고",
    ("fused_tricyclic_aromatic", "PHOTO"):
        "확장된 공액 방향족계의 UV/가시광 흡수",
    ("quinone", "PHOTO"):
        "발색단 구조의 광반응성",
}

# 명시적으로 기전이 없다고 선언하는 플래그.
# PAINS 는 생화학 어세이 간섭 필터이며 임상 안전성 지표가 아니다.
# 통계적으로 유의하게 나와도 임상 조항의 기전적 근거로 쓰지 않는다.
NO_MECHANISM_CLAIM = {
    "pains": "PAINS 는 어세이 간섭 필터로, 임상 안전성 조항의 기전적 근거가 아니다. "
             "유의한 연관이 나오면 약물계열·적응증 교락의 지표로만 해석한다.",
}

# 템플릿 조항 판정 시 참고할 주의 사항.
# 피임 조항은 가임 여성 대상 시험에서 관례적으로 포함되므로, 기저율이 높지 않아도
# 구조 특이 신호로 해석할 때 각별히 주의한다.
CLAUSE_CAVEATS = {
    "CONTRACEPT": "가임 여성 포함 시험에서 관례적으로 포함되는 조항. 기저율이 "
                  "템플릿 임계값 아래여도 구조 귀속 주장에는 사용하지 않는다.",
    "HEMATO": "항암제 시험에서 골수억제 관련 조항이 관례적으로 포함된다. "
              "적응증 층화 없이 해석하지 않는다.",
}

# 구조 귀속 주장 자체를 금지하는 조항 (관례적 포함 성격이 강한 것)
EXCLUDED_FROM_CLAIMS = {"CONTRACEPT"}


def classify_pair(flag, clause, passed_stats, passed_strat):
    """(플래그, 조항) 쌍을 confirmatory / exploratory / refuted 로 분류."""
    pre = (flag, clause) in PREREGISTERED
    if flag in NO_MECHANISM_CLAIM:
        return "no_mechanism_claim"
    if clause in EXCLUDED_FROM_CLAIMS:
        return "excluded_clause"
    if pre and passed_stats and passed_strat:
        return "confirmatory"
    if pre:
        return "refuted"
    if passed_stats and passed_strat:
        return "exploratory"
    return "null"


def mechanism_of(flag, clause):
    return PREREGISTERED.get((flag, clause))
