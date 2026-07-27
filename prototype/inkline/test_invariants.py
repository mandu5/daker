"""안전 불변식 테스트.

제안서에 "이 시스템은 …하지 않는다"고 적은 것들이 코드에서 실제로 보장되는지
기계적으로 확인한다. 주장과 구현이 어긋나면 그건 제안서가 아니라 광고다.

    python3 prototype/inkline/test_invariants.py

각 테스트는 실패 시 무엇이 왜 깨졌는지 출력한다. 모두 통과해야 제출한다.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "trialbench"))

from agents import Clause, Ledger, Provenance, sha  # noqa: E402
from consistency import check as consistency_check  # noqa: E402
from evidence import lookup  # noqa: E402
from model import SAFETY_CLAUSES, split_of  # noqa: E402

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append((name, detail))
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))


def mk(clause_type="QT_ECG", *, delta_star=0.1, sigma=0.01, ad=0.9,
       trigger=("R-x",), prov=True, falsifier=True, evidence=None):
    c = Clause(
        clause_id=f"C-{clause_type}", clause_type=clause_type, text="t",
        clause_class="molecule_specific" if trigger else "template_baseline",
        trigger_risks=list(trigger), p_base=0.2, p_hat=0.3, delta=0.1,
        delta_star=delta_star, sigma=sigma, ad=ad,
        provenance=Provenance(kind="computed", detail="d") if prov else None,
        sealed_falsifier={"predicate": "p", "hash": "h"} if falsifier else None,
    )
    if evidence is not None:
        c.evidence = evidence
    return c


# ── 1. 4-튜플이 불완전하면 절대 발행되지 않는다 ────────────────
def test_four_tuple():
    print("\n[1] 4-튜플 미완성 조항은 발행되지 않는다")
    for label, kw in (("근거 없음", {"prov": False}),
                      ("반증조건 없음", {"falsifier": False}),
                      ("트리거 없음", {"trigger": ()})):
        led = Ledger(calibration={})       # 보정 없음 → 전역 임계
        c = mk(**kw)
        led.decide([c])
        ok(f"{label} → 발행 안 됨", c.decision != "advance",
           f"decision={c.decision} reason={c.reason_code}")


# ── 2. Δ* ≤ 0 이면 절대 발행되지 않는다 ────────────────────────
def test_delta_star():
    print("\n[2] 구조 귀속이 입증되지 않으면 발행되지 않는다")
    for ds, label in ((0.0, "Δ*=0"), (-0.05, "Δ*<0"), (float("nan"), "Δ* 판정불가")):
        led = Ledger(calibration={})
        c = mk(delta_star=ds)
        led.decide([c])
        ok(f"{label} → 발행 안 됨", c.decision != "advance",
           f"decision={c.decision} reason={c.reason_code}")


# ── 3. 보정에서 봉인된 조항은 절대 발행되지 않는다 ─────────────
def test_sealed():
    print("\n[3] 보정에서 봉인된 조항은 발행되지 않는다")
    calib = {"FOOD_EFFECT": {"sealed": True, "reason": "목표 미달"}}
    led = Ledger(calibration=calib)
    c = mk("FOOD_EFFECT", delta_star=9.9, sigma=1e-6, ad=1.0)   # 신뢰도 극대
    led.decide([c])
    ok("신뢰도가 아무리 높아도 봉인 조항은 발행 안 됨",
       c.decision != "advance", f"decision={c.decision}")
    ok("봉인 조항은 사람 검토로 올라감", c.decision == "escalate",
       f"decision={c.decision}")


# ── 4. 안전성 조항의 불확실은 침묵이 아니라 승격 ───────────────
def test_safety_escalation():
    print("\n[4] 안전성 조항의 불확실은 사람 검토로 승격된다")
    led = Ledger(calibration={})
    c = mk("QT_ECG", delta_star=0.001, sigma=10.0, ad=0.01)   # 신뢰도 바닥
    led.decide([c])
    ok("신뢰도 미달 안전성 조항 → 기권 아님", c.decision != "abstain",
       f"decision={c.decision} reason={c.reason_code}")
    ok("사람 검토로 승격", c.decision == "escalate", f"decision={c.decision}")


# ── 5. 근거가 격리된 조항은 발행될 수 없다 (정합성 검사) ───────
def test_isolated_evidence():
    print("\n[5] 근거 격리 조항이 발행되면 정합성 검사가 막는다")
    c = mk("QT_ECG", evidence={"isolated": True, "found": [], "missing": ["X"]})
    c.decision = "advance"
    v = consistency_check([c], followups={"ecg_schedule"})
    codes = {x.code for x in v}
    ok("issued_without_evidence 위반 검출",
       "issued_without_evidence" in codes, f"codes={codes}")
    ok("심각도 blocking",
       any(x.severity == "blocking" for x in v if x.code == "issued_without_evidence"))


# ── 6. 후속 조치 누락을 잡는다 ─────────────────────────────────
def test_missing_followup():
    print("\n[6] 발행 조항이 요구하는 후속 조치 누락을 잡는다")
    c = mk("QT_ECG", evidence={"isolated": False, "weakest_tier": "body"})
    c.decision = "advance"
    v = consistency_check([c], followups=set())          # 후속 조치 없음
    ok("missing_followup 검출", "missing_followup" in {x.code for x in v})
    v2 = consistency_check([c], followups={"ecg_schedule"})
    ok("후속 조치가 있으면 위반 없음",
       "missing_followup" not in {x.code for x in v2})


# ── 7. 적응증과 배타적인 제외기준을 잡는다 ─────────────────────
def test_indication_conflict():
    print("\n[7] 대상 인구를 스스로 배제하는 조항을 잡는다")
    c = mk("HEPATIC", evidence={"isolated": False, "weakest_tier": "body"})
    c.decision = "advance"
    v = consistency_check([c], context={"indication": "chronic hepatitis B"},
                          followups={"lft_schedule"})
    ok("간질환 시험 + 간기능 제외기준 → blocking",
       any(x.code == "exclusion_conflicts_with_indication"
           and x.severity == "blocking" for x in v))


# ── 8. 경고 인플레이션을 감시한다 ──────────────────────────────
def test_warning_budget():
    print("\n[8] 경고 예산 초과를 감시한다")
    cs = []
    for i in range(7):
        c = mk("QT_ECG", evidence={"isolated": False, "weakest_tier": "body"})
        c.clause_id = f"C{i}"
        c.decision = "advance"
        cs.append(c)
    v = consistency_check(cs, followups={"ecg_schedule"})
    ok("발행 7건 > 예산 5건 → warning_inflation",
       "warning_inflation" in {x.code for x in v})


# ── 9. 분할이 결정론적이다 ─────────────────────────────────────
def test_split_determinism():
    print("\n[9] 학습/평가 분할이 결정론적이다")
    ids = [f"NCT{i:08d}" for i in range(2000)]
    a = [split_of(i) for i in ids]
    b = [split_of(i) for i in ids]
    ok("같은 ID → 같은 분할", a == b)
    frac = sum(1 for x in a if x == "test") / len(a)
    ok(f"평가 비율이 30% 근처 (실측 {frac:.1%})", 0.27 <= frac <= 0.33)


# ── 10. 감사 해시가 입력에 민감하다 ────────────────────────────
def test_hash_sensitivity():
    print("\n[10] 감사 해시가 판정 변화에 민감하다")
    base = {"trace": [("A", "s1")], "clauses": [("C1", "advance", 0.1)]}
    same = {"trace": [("A", "s1")], "clauses": [("C1", "advance", 0.1)]}
    diff = {"trace": [("A", "s1")], "clauses": [("C1", "abstain", 0.1)]}
    ok("같은 내용 → 같은 해시", sha(base) == sha(same))
    ok("판정이 바뀌면 해시도 바뀜", sha(base) != sha(diff))


# ── 11. 근거 코퍼스에 없는 문서를 요구하면 격리된다 ────────────
def test_evidence_isolation():
    print("\n[11] 코퍼스에 없는 근거를 요구하는 조항은 격리된다")
    found, missing = lookup("CYP_DDI")
    ok("CYP_DDI 는 근거를 찾지 못한다 (ICH M12 미확인)",
       not found and missing, f"found={found} missing={missing}")
    found2, _ = lookup("QT_ECG")
    ok("QT_ECG 는 ICH E14 로 결박된다", bool(found2) and found2[0]["url"])


def main():
    print("먹줄 안전 불변식 테스트")
    print("=" * 60)
    for fn in (test_four_tuple, test_delta_star, test_sealed,
               test_safety_escalation, test_isolated_evidence,
               test_missing_followup, test_indication_conflict,
               test_warning_budget, test_split_determinism,
               test_hash_sensitivity, test_evidence_isolation):
        fn()
    print("\n" + "=" * 60)
    print(f"통과 {len(PASS)} · 실패 {len(FAIL)}")
    if FAIL:
        print("\n실패 항목:")
        for name, detail in FAIL:
            print(f"  - {name}  {detail}")
        return 1
    print("모든 안전 불변식이 코드에서 보장된다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
