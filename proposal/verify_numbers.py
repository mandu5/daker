"""제안서 본문의 하드코딩 수치를 실측 결과와 대조한다.

    python3 proposal/verify_numbers.py

대부분의 수치는 결과 JSON에서 동적으로 읽어오지만, 문장 안에 직접 적은
숫자가 남아 있다. 분석을 다시 돌리면 그 숫자만 낡은 채로 남는다.
제출 전 이 스크립트가 통과해야 한다.
"""

from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

RES = os.path.join(REPO, "prototype", "results")
S2C = json.load(open(os.path.join(RES, "s2c_associations.json"), encoding="utf-8"))
E1 = json.load(open(os.path.join(RES, "e1_safe_inc.json"), encoding="utf-8"))
E3 = json.load(open(os.path.join(RES, "e3_null.json"), encoding="utf-8"))
TAU = json.load(open(os.path.join(RES, "tau_calibration.json"), encoding="utf-8"))
RUN = json.load(open(os.path.join(RES, "runs", "demo_kinase_like.json"),
                    encoding="utf-8"))


def gate(name):
    g = S2C["mechanism_gate"]
    return {(r["flag"], r["clause"]): r for r in g[name]}


CONF = gate("confirmatory")
REFU = gate("refuted")


def pair(flag, clause):
    return CONF.get((flag, clause)) or REFU.get((flag, clause))


# (본문에 적힌 값, 실측값, 설명, 허용오차)
CHECKS = [
    ("확증 쌍 수", len(CONF), len(S2C["mechanism_gate"]["confirmatory"]), 0),
    ("분석 대상 시험 수", 39379, S2C["n_analyzed"], 0),
    ("티오펜→간기능 lift", 0.57, pair("thiophene", "HEPATIC")["lift"], 0.005),
    ("마이클수용체→간기능 lift", 0.84,
     pair("michael_acceptor", "HEPATIC")["lift"], 0.005),
    ("염기성아민→위산 lift", 0.79,
     pair("basic_amine", "GASTRIC_PH")["lift"], 0.005),
    ("친유성→음식효과 lift", 1.91, pair("lipophilic", "FOOD_EFFECT")["lift"], 0.005),
    ("확증률(%)", 34.8, S2C["confirmatory_rate"] * 100, 0.05),
    ("B-RULE ΔAUPRC", -0.086, E1["mean_delta_auprc"]["B-RULE"], 0.0005),
    ("FOR_safety(%)", 1.08, E3["FOR_safety"]["rate"] * 100, 0.005),
    ("음성대조 쌍 수", 6748, E3["negative_control"]["n"], 0),
    ("음성대조 발행률", 0.0, E3["negative_control"]["advance_rate"], 1e-9),
    ("기권율(%)", 92, E3["decision_mix"]["abstain"]["rate"] * 100, 0.5),
    ("CYP·DDI 정밀도 lift", 2.90,
     E3["by_clause"]["CYP_DDI"]["precision_lift"], 0.005),
    ("발행분 정밀도", 0.236, E3["advance"]["precision"], 0.0005),
    ("발행분 오경보율", 0.014, E3["advance"]["false_alarm_rate"], 0.0005),
    ("CYP·DDI τ", 2.278, TAU["per_clause"]["CYP_DDI"]["tau"], 0.001),
    ("QT τ", 1.499, TAU["per_clause"]["QT_ECG"]["tau"], 0.001),
    ("보정 후 발행 자격 조항 수", 2,
     sum(1 for v in TAU["per_clause"].values() if not v.get("sealed")), 0),
    ("E1 확증군 ΔP@5%", 0.035,
     E1["mechanism_split"]["confirmed_delta_p"]["0.05"], 0.0005),
    ("E1 미확증군 ΔP@5%", 0.044,
     E1["mechanism_split"]["exploratory_delta_p"]["0.05"], 0.0005),
    ("CYP·DDI 템플릿 P@5%", 0.234,
     E1["clauses"]["CYP_DDI"]["precision_at_coverage"]["B-TPL"]["0.05"]["precision"],
     0.0005),
    ("CYP·DDI 먹줄 P@5%", 0.314,
     E1["clauses"]["CYP_DDI"]["precision_at_coverage"]["INKLINE+"]["0.05"]["precision"],
     0.0005),
]


def check_delta_star():
    """시연 분자의 Δ* 구조 귀속분 27% 주장을 확인."""
    for c in RUN["clauses"]:
        if c["clause_type"] == "QT_ECG":
            share = c["delta_star"] / c["delta"] if c["delta"] else None
            return ("시연분자 QT 구조귀속분(%)", 27, share * 100 if share else None, 1.0)
    return ("시연분자 QT 구조귀속분(%)", 27, None, 1.0)


def main():
    checks = list(CHECKS) + [check_delta_star()]
    bad = []
    print(f"{'항목':28s} {'본문':>10s} {'실측':>10s}  판정")
    print("-" * 60)
    for name, claimed, actual, tol in checks:
        if actual is None:
            ok = False
            act_s = "없음"
        else:
            ok = abs(float(claimed) - float(actual)) <= tol
            act_s = f"{actual:.4f}" if isinstance(actual, float) else str(actual)
        print(f"{name:28s} {claimed:>10} {act_s:>10}  {'OK' if ok else '불일치'}")
        if not ok:
            bad.append((name, claimed, actual))

    # 25% 검토량 절감 주장 재계산
    c = E1["clauses"]["CYP_DDI"]["precision_at_coverage"]
    tpl = c["B-TPL"]["0.05"]["precision"]
    ink = c["INKLINE+"]["0.05"]["precision"]
    saving = 1 - tpl / ink
    ok = abs(saving - 0.254) <= 0.005
    print(f"{'검토량 절감(%)':28s} {25.4:>10} {saving*100:>10.1f}  "
          f"{'OK' if ok else '불일치'}")
    if not ok:
        bad.append(("검토량 절감", 25.4, saving * 100))

    print()
    if bad:
        print(f"불일치 {len(bad)}건 — 제안서 본문을 갱신해야 한다:")
        for n, c_, a in bad:
            print(f"  - {n}: 본문 {c_} vs 실측 {a}")
        return 1
    print(f"전체 {len(checks)+1}건 일치. 제안서 수치가 실측과 정합한다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
