"""근거 코퍼스 — R1 근거 반증이 실제로 작동하기 위한 최소 실물.

원칙
    **URL 접속으로 실재를 확인한 문서만** 넣는다. 확인하지 못한 근거를 요구하는
    조항은 코퍼스에서 찾지 못해 R1에서 기각되고, 재기안을 거쳐 결국 기권한다.
    이것은 결함이 아니라 설계다 — 근거가 없으면 말하지 않는다.

    코퍼스가 작다는 사실을 숨기지 않고 **격리율(Unverified Isolation Rate)** 로
    보고한다. 본선에서 코퍼스를 확장하면 격리율이 내려가는 것으로 개선을 보인다.

문서 위계
    본문(body) > 부록(annex) > Q&A. 조항이 인용한 근거 중 **가장 약한 것이
    조항 등급의 상한**을 결정한다.
"""

from __future__ import annotations

# 확인일 2026-07-26. 각 항목은 검색을 통해 존재와 URL을 확인했다.
CORPUS = {
    "ICH_E14": {
        "title": "E14 Clinical Evaluation of QT/QTc Interval Prolongation and "
                 "Proarrhythmic Potential for Non-Antiarrhythmic Drugs",
        "issuer": "ICH / FDA",
        "url": "https://www.fda.gov/regulatory-information/search-fda-guidance-documents/"
               "e14-clinical-evaluation-qtqtc-interval-prolongation-and-proarrhythmic-"
               "potential-non-antiarrhythmic",
        "tier": "body",
        "verified_at": "2026-07-26",
        "supports": ["QT_ECG"],
        "span_id": "E14-QA-R3",
    },
    "FDA_MRSD_2005": {
        "title": "Estimating the Maximum Safe Starting Dose in Initial Clinical "
                 "Trials for Therapeutics in Adult Healthy Volunteers",
        "issuer": "FDA CDER",
        "url": "https://www.fda.gov/regulatory-information/search-fda-guidance-documents/"
               "estimating-maximum-safe-starting-dose-initial-clinical-trials-"
               "therapeutics-adult-healthy-volunteers",
        "tier": "body",
        "verified_at": "2026-07-26",
        "supports": ["DOSE_MRSD"],
        "span_id": "MRSD-2005-HED",
    },
    "FDA_AI_2025": {
        "title": "Considerations for the Use of Artificial Intelligence to Support "
                 "Regulatory Decision-Making for Drug and Biological Products",
        "issuer": "FDA",
        "url": "https://www.fda.gov/regulatory-information/search-fda-guidance-documents/"
               "considerations-use-artificial-intelligence-support-regulatory-decision-"
               "making-drug-and-biological",
        "tier": "body",
        "verified_at": "2026-07-26",
        "supports": ["COU"],
        "span_id": "FDA-AI-2025-COU",
    },
    "ICH_M12": {
        "title": "M12 Drug Interaction Studies",
        "issuer": "ICH / FDA",
        "url": "https://www.fda.gov/regulatory-information/search-fda-guidance-documents/"
               "m12-drug-interaction-studies",
        "tier": "body",
        "verified_at": "2026-07-27",
        "supports": ["CYP_DDI"],
        "span_id": "M12-2024-08",
        "note": "2024-05-21 ICH 최종화, 2024-08-02 FDA Federal Register 공고. "
                "효소·수송체 매개 약물상호작용 평가의 최초 국제 조화 가이드라인",
    },
    "ICH_M12_QA": {
        "title": "M12 Drug Interaction Studies: Questions and Answers",
        "issuer": "ICH / FDA",
        "url": "https://www.fda.gov/regulatory-information/search-fda-guidance-documents/"
               "m12-drug-interaction-studies-questions-and-answers",
        "tier": "qa",
        "verified_at": "2026-07-27",
        "supports": ["CYP_DDI"],
        "span_id": "M12-QA-2024",
    },
    "FDA_DILI_2009": {
        "title": "Drug-Induced Liver Injury: Premarketing Clinical Evaluation",
        "issuer": "FDA CDER",
        "url": "https://www.fda.gov/regulatory-information/search-fda-guidance-documents/"
               "drug-induced-liver-injury-premarketing-clinical-evaluation",
        "tier": "body",
        "verified_at": "2026-07-27",
        "supports": ["HEPATIC"],
        "span_id": "DILI-2009-07",
        "note": "혈청 효소·빌리루빈 주기 검사로 DILI 를 탐지하는 방법과 "
                "투여 중단·중지 규칙을 다룬다 — 간기능 조항의 직접 근거",
    },
}

# 조항 유형 → 필요한 근거 문서.
# 코퍼스에 없는 문서를 요구하는 조항은 R1에서 기각되어 격리된다.
#
# 확장 이력
#   2026-07-26  ICH E14 / FDA MRSD 2005 / FDA AI 2025 (3문서)
#   2026-07-27  ICH M12 + M12 Q&A / FDA DILI 2009 추가 (6문서)
#               → CYP/DDI 와 간기능 조항의 격리가 해소됐다.
#               격리율이 코퍼스 확장으로 내려가는 것을 지표로 보인다.
#
# 여전히 확인하지 못한 문서는 그대로 비워 둔다. 채우지 않은 자리가
# 시스템 동작(격리)으로 드러나는 것이 이 설계의 요점이다.
CLAUSE_EVIDENCE = {
    "QT_ECG": ["ICH_E14"],
    "CYP_DDI": ["ICH_M12"],          # 2026-07-27 확인 후 코퍼스에 추가
    "HEPATIC": ["FDA_DILI_2009"],    # 2026-07-27 확인 후 코퍼스에 추가
    "RENAL": ["FDA_RENAL_IMP"],      # 코퍼스에 없음 → 격리 대상
    "HEMATO": [],                    # 근거 문서를 특정하지 못함
    # 2차 확장분. 어느 것도 실재 확인을 마치지 못해 전부 격리 대상이다.
    # 코퍼스 한계를 그대로 드러내는 것이 이 설계의 요점이다.
    "FOOD_EFFECT": ["FDA_FOOD_EFFECT_BA"],
    "GI_IRRITATION": ["FDA_GI_SAFETY"],
    "SEIZURE": ["FDA_SEIZURE"],
    "GASTRIC_PH": ["FDA_ACID_REDUCING"],
    "THYROID": [],
}

# A1 재기안이 시도할 대체 근거 경로.
# 대체 경로가 없는 조항은 **재기안을 시도하지 않고 즉시 격리한다.**
# 바꿀 것이 없는데 재시도하는 것은 루프가 도는 척하는 것일 뿐이다.
ALTERNATIVES = {
    # QT 조항은 1차 근거가 없을 때 FDA AI 가이던스의 COU 틀로 대체할 수 없다.
    # 현재 코퍼스에서는 어떤 조항도 대체 경로를 갖지 못한다 — 그 사실을 그대로 둔다.
}

TIER_RANK = {"body": 3, "annex": 2, "qa": 1}


def alternatives(clause_type):
    """이 조항에 시도해 볼 대체 근거 경로. 없으면 빈 리스트."""
    return ALTERNATIVES.get(clause_type, [])


def lookup(clause_type):
    """조항이 요구하는 근거를 코퍼스에서 찾는다.

    반환: (찾은 항목 리스트, 못 찾은 문서 ID 리스트)
    """
    need = CLAUSE_EVIDENCE.get(clause_type, [])
    found, missing = [], []
    for doc_id in need:
        if doc_id in CORPUS:
            found.append({"doc_id": doc_id, **CORPUS[doc_id]})
        else:
            missing.append(doc_id)
    return found, missing


def weakest_tier(found):
    """인용한 근거 중 가장 약한 위계. 조항 등급의 상한을 결정한다."""
    if not found:
        return None
    return min(found, key=lambda f: TIER_RANK.get(f["tier"], 0))["tier"]


def isolation_rate(clause_types):
    """근거를 찾지 못해 격리되는 조항 유형의 비율."""
    n = len(clause_types)
    if not n:
        return 0.0
    iso = sum(1 for c in clause_types if lookup(c)[1] or not lookup(c)[0])
    return iso / n
