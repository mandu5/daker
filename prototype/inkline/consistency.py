"""조항 집합의 내부 정합성 검사.

왜 결정론으로 만드는가
    설계 문서에서 이 기능을 LLM 담당 지점으로 적었으나, 실제로 구현해 보니
    검사 규칙 대부분이 **명시적 술어로 표현 가능**했다. 결정론 코어 원칙
    (P1: 수치와 판정은 결정론 도구가 낸다)에 비추면 LLM 에 맡길 이유가 없다.

    LLM 이 정말 필요한 곳은 **자유 서술형 프로토콜 원문에서 조항을 추출하는
    단계**이지, 추출된 조항 집합의 정합성을 따지는 단계가 아니다.
    이 사실을 확인했으므로 설계에서 해당 지점을 결정론으로 옮긴다.

검사 항목
    C1 발행 조항이 요구하는 후속 조치가 빠졌는가
       (QT 조항을 발행했으면 심전도 모니터링 일정이 있어야 한다)
    C2 서로 배타적인 조항을 동시에 발행했는가
    C3 경고 예산을 초과했는가 (경고 인플레이션 감시)
    C4 안전성 조항을 기권했는데 사람 검토로도 올리지 않았는가
    C5 발행 조항의 근거 위계가 조항 등급 상한을 넘는가
    C6 모집 인구 감소가 임계를 넘는데 대체 탐색을 하지 않았는가

각 위반은 (심각도, 사유코드, 설명, 권고조치) 로 보고되며,
심각도 blocking 은 산출물 발행 자체를 막는다.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from model import SAFETY_CLAUSES  # noqa: E402

# 조항이 발행되면 함께 있어야 하는 후속 조치
REQUIRED_FOLLOWUP = {
    "QT_ECG": ("ecg_schedule", "심전도 측정 시점(투여 전·Cmax 부근·종료)"),
    "CYP_DDI": ("washout_period", "병용금기 약물의 휴약기간"),
    "HEPATIC": ("lft_schedule", "간기능 검사 주기"),
    "RENAL": ("renal_schedule", "신기능 검사 주기"),
    "SEIZURE": ("neuro_monitoring", "신경학적 관찰 계획"),
}

# 동시에 발행하면 모순인 조항 쌍
MUTUALLY_EXCLUSIVE = [
    (("HEPATIC", "exclude"), ("HEPATIC", "enroll_target"),
     "간기능 이상을 제외기준으로 두면서 동시에 간질환을 대상으로 삼을 수 없다"),
]

# 프로토콜당 발행 경고 예산. 초과 시 경고 인플레이션으로 본다.
WARNING_BUDGET = 5

SEVERITY_ORDER = {"blocking": 3, "warning": 2, "info": 1}


class Violation:
    def __init__(self, code, severity, message, action, clause_ids=()):
        self.code = code
        self.severity = severity
        self.message = message
        self.action = action
        self.clause_ids = list(clause_ids)

    def as_dict(self):
        return {"code": self.code, "severity": self.severity,
                "message": self.message, "action": self.action,
                "clause_ids": self.clause_ids}

    def __repr__(self):
        return f"<{self.severity}:{self.code} {self.message[:40]}>"


def check(clauses, context=None, followups=None, feasibility=None,
          budget=WARNING_BUDGET):
    """조항 집합의 정합성을 검사해 위반 목록을 반환한다."""
    context = context or {}
    followups = set(followups or [])
    out = []

    advanced = [c for c in clauses if c.decision == "advance"]
    escalated = [c for c in clauses if c.decision == "escalate"]
    abstained = [c for c in clauses if c.decision == "abstain"]

    # C1 — 발행 조항의 후속 조치 누락
    for c in advanced:
        req = REQUIRED_FOLLOWUP.get(c.clause_type)
        if req and req[0] not in followups:
            out.append(Violation(
                "missing_followup", "blocking",
                f"{c.clause_type} 조항을 발행했으나 {req[1]}이(가) 프로토콜에 없다",
                f"{req[1]}을(를) 추가하거나 조항 발행을 철회하라",
                [c.clause_id]))

    # C3 — 경고 예산 초과 (경고 인플레이션 감시)
    if len(advanced) > budget:
        out.append(Violation(
            "warning_inflation", "warning",
            f"발행 조항 {len(advanced)}건이 예산 {budget}건을 초과했다. "
            f"경고를 늘려 재현율만 올리는 것은 실무자에게 무가치하다",
            "신뢰도 상위 조항만 남기고 나머지는 사람 검토로 내려라",
            [c.clause_id for c in advanced]))

    # C4 — 안전성 조항을 기권했는데 사람 검토로도 안 올림
    for c in abstained:
        if c.clause_type not in SAFETY_CLAUSES:
            continue
        if c.reason_code in ("no_structural_trigger", "not_structure_attributable"):
            continue        # 판단 대상이 아니거나 구조 유래가 아님이 입증된 경우
        out.append(Violation(
            "safety_abstained_without_review", "blocking",
            f"안전성 조항 {c.clause_type}을(를) 사유 '{c.reason_code}'로 기권했는데 "
            f"사람 검토로 승격되지 않았다",
            "안전성 조항의 불확실은 기권이 아니라 사람 검토로 처리해야 한다",
            [c.clause_id]))

    # C5 — 근거 위계가 조항 등급 상한을 넘는지
    for c in advanced:
        ev = getattr(c, "evidence", None) or {}
        if ev.get("isolated"):
            out.append(Violation(
                "issued_without_evidence", "blocking",
                f"{c.clause_type} 조항이 근거 코퍼스에서 격리되었는데 발행되었다",
                "격리된 조항은 발행할 수 없다. 근거를 확보하거나 기권하라",
                [c.clause_id]))
        elif ev.get("weakest_tier") == "qa":
            out.append(Violation(
                "weak_evidence_tier", "warning",
                f"{c.clause_type} 조항의 근거가 Q&A 수준이다. "
                f"조항 등급의 상한이 그만큼 낮아진다",
                "본문 수준 근거를 찾거나 조항 등급을 낮춰 표기하라",
                [c.clause_id]))

    # C6 — 모집 인구 감소가 임계를 넘는데 대체 탐색 없음
    if feasibility and feasibility.get("exceeds"):
        substituted = any(getattr(c, "substituted", False) for c in clauses)
        if not substituted:
            out.append(Violation(
                "recruitment_not_mitigated", "warning",
                f"발행 조항으로 등록 가능 인구가 "
                f"{feasibility['pool_reduction']:.0%} 감소하는데 대체 조항 탐색이 "
                f"수행되지 않았다",
                "제외기준을 모니터링 조항으로 대체하는 경로를 탐색하라",
                []))

    # C2 — 배타 조항 (현재 규칙셋에서는 맥락 정보가 필요해 정보 수준으로만)
    if context.get("indication") and advanced:
        ind = str(context["indication"]).lower()
        for c in advanced:
            if c.clause_type == "HEPATIC" and ("hepat" in ind or "liver" in ind):
                out.append(Violation(
                    "exclusion_conflicts_with_indication", "blocking",
                    "간질환을 대상으로 하는 시험에서 간기능 이상을 제외기준으로 "
                    "발행했다. 대상 인구를 스스로 배제한다",
                    "제외기준 대신 계층화 또는 모니터링 강화로 전환하라",
                    [c.clause_id]))
            if c.clause_type == "RENAL" and ("renal" in ind or "kidney" in ind
                                             or "nephro" in ind):
                out.append(Violation(
                    "exclusion_conflicts_with_indication", "blocking",
                    "신질환 대상 시험에서 신기능 이상을 제외기준으로 발행했다",
                    "제외기준 대신 계층화 또는 모니터링 강화로 전환하라",
                    [c.clause_id]))

    out.sort(key=lambda v: -SEVERITY_ORDER.get(v.severity, 0))
    return out


def summarize(violations):
    n = {"blocking": 0, "warning": 0, "info": 0}
    for v in violations:
        n[v.severity] = n.get(v.severity, 0) + 1
    return {"counts": n, "publishable": n["blocking"] == 0,
            "violations": [v.as_dict() for v in violations]}
