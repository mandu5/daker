"""자기수정 루프 오케스트레이터.

되돌아가는 화살표 4개를 **실제로 실행한다.** 다이어그램에만 있고 로그에 없으면
그건 설계가 아니라 그림이다.

    A1  R1 근거 기각 → SCRIBE 재기안 (최대 3회, 이후 기권)
    A2  R2 귀속 기각 → MARKER 리스크 등급 하향 + Case Bank 영속화
                       (다음 라운드에서 그 경보는 트리거 자격을 잃는다)
    A3  R3 실행 기각 → ACTUARY 회귀 (제외기준 대신 모니터링 조항으로 대체 탐색)
    A4  기권율 > 0.7 또는 동일 reason_code 반복 → 사람에게 계약 개정 요청
                       (자동 완화 금지)

정지 조건 (라운드 r, 미해결 조항 U_r, 개선량 Δ_r, 예산 B)
    정지 ⇔ (|U_r| = 0) ∨ (최근 3라운드 개선량 합 < ε) ∨ (사용 예산 ≥ 0.8B)
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from agents import Actuary, Adversary, Ledger, Marker, Scribe, _t, sha  # noqa: E402
from run import _versions  # noqa: E402
from consistency import check as consistency_check, summarize  # noqa: E402
from evidence import alternatives, lookup, weakest_tier  # noqa: E402
from model import SAFETY_CLAUSES  # noqa: E402

MAX_ROUNDS = 4
MAX_REDRAFT = 3
EPS_IMPROVE = 1
ABSTAIN_ESCALATION = 0.7

# 모니터링 조항으로 대체했을 때의 모집 인구 비용 (제외기준보다 훨씬 낮다)
MONITORING_POOL_COST = 0.02


class CaseBank:
    """기각 사유를 append-only 로 쌓아 다음 라운드·다음 실행에 재주입한다."""

    def __init__(self, path=None):
        self.path = path
        self.entries = []
        if path and os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                self.entries = [json.loads(l) for l in f if l.strip()]

    def record(self, run_id, round_, clause, reason, detail=""):
        e = {"run_id": run_id, "round": round_, "clause_type": clause.clause_type,
             "trigger_risks": list(clause.trigger_risks),
             "reason_code": reason, "detail": detail,
             "delta": clause.delta,
             "delta_star": (None if clause.delta_star != clause.delta_star
                            else clause.delta_star)}
        self.entries.append(e)
        if self.path:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        return e

    def repeat_count(self, reason_code):
        return sum(1 for e in self.entries if e["reason_code"] == reason_code)

    def downgraded_flags(self, run_id):
        """이번 실행에서 귀속 기각으로 등급이 내려간 경보 목록."""
        out = set()
        for e in self.entries:
            if e["run_id"] == run_id and e["reason_code"] == "not_structure_attributable":
                out.update(e["trigger_risks"])
        return out


class Orchestrator:
    def __init__(self, fit, case_bank_path=None):
        self.fit = fit
        self.marker = Marker(ad=fit["ad"])
        self.scribe = Scribe(fit["tpl"], fit["models"], confirmed=fit["confirmed"])
        self.actuary = Actuary()
        self.adversary = Adversary(fit["tpl"], fit["models"],
                                   confirmed=fit["confirmed"])
        self.ledger = Ledger()
        self.bank = CaseBank(case_bank_path)

    # ── R1: 근거 코퍼스 조회 ─────────────────────────────────
    def attach_evidence(self, clause, trace, quiet=False):
        found, missing = lookup(clause.clause_type)
        if not found:
            clause.reason_code = "evidence_not_in_corpus"
            clause.evidence = {"found": [], "missing": missing,
                               "isolated": True}
            if not quiet:
                _t(trace, "ADVERSARY", "R1 근거 반증",
                   f"{clause.clause_type}: 근거 문서 {missing or '미특정'} 를 "
                   f"코퍼스에서 찾지 못함 → 격리")
            return False
        w = weakest_tier(found)
        clause.provenance.kind = "guideline"
        clause.provenance.url = found[0]["url"]
        clause.provenance.span_id = found[0]["span_id"]
        clause.provenance.verified_at = found[0]["verified_at"]
        clause.evidence = {"found": [f["doc_id"] for f in found],
                           "missing": missing, "weakest_tier": w,
                           "isolated": False}
        if not quiet:
            _t(trace, "ADVERSARY", "R1 근거 확인",
               f"{clause.clause_type}: {found[0]['doc_id']} ({w}) 결박 · "
               f"{found[0]['span_id']}")
        return True

    # ── A3: 제외기준 → 모니터링 조항 대체 ────────────────────
    def substitute_monitoring(self, clause, trace):
        clause.text = clause.text.replace("제외기준", "모니터링 요구")
        clause.substituted = True
        clause.pool_cost_override = MONITORING_POOL_COST
        _t(trace, "ACTUARY", "A3 대체 탐색",
           f"{clause.clause_type}: 제외기준이 모집을 과도하게 깎아 "
           f"**모니터링 조항으로 대체** (인구 비용 {MONITORING_POOL_COST:.0%})")

    # ── 본체 ─────────────────────────────────────────────────
    def run(self, smiles, context, noael=None, species="rat",
            modality="small_molecule", n_enroll=60, budget_rounds=MAX_ROUNDS,
            followups=None):
        """followups: 프로토콜에 이미 들어 있는 후속 조치 식별자 집합.
        비어 있으면 발행 조항이 요구하는 조치가 전부 누락된 것으로 본다."""
        trace = []
        run_id = sha([smiles, context, noael])[:12]

        risks, props = self.marker.run(smiles, modality=modality, trace=trace)
        if risks is None:
            return self.ledger.seal(run_id, [], trace,
                                    {"context": context, "reason": props,
                                     "rounds": 0})

        dose = self.actuary.mrsd(noael, species=species, trace=trace) \
            if noael is not None else None
        power = self.actuary.power_gate(n_enroll, 0.10, 0.25, trace=trace)

        redraft = Counter()
        history, clauses = [], []
        escalate_contract = None

        for rnd in range(1, budget_rounds + 1):
            _t(trace, "ORCHESTRATOR", f"라운드 {rnd} 시작",
               f"하향된 경보 {sorted(self.bank.downgraded_flags(run_id)) or '없음'}")

            # 하향된 경보는 트리거 자격을 잃는다 (A2 의 효과)
            down = self.bank.downgraded_flags(run_id)
            active = [r for r in risks if r.risk_id not in down]
            clauses = self.scribe.run(active, props, context, trace=trace)

            # R1 → A1
            for c in clauses:
                ok = self.attach_evidence(c, trace, quiet=(rnd > 1))
                if ok or rnd > 1:
                    continue
                alts = alternatives(c.clause_type)
                if not alts:
                    # 시도할 대체 경로가 없다. 재기안하는 척하지 않는다.
                    _t(trace, "ORCHESTRATOR", "A1 재기안 불가",
                       f"{c.clause_type}: 대체 근거 경로가 등록되어 있지 않음 "
                       f"→ 즉시 격리 확정 (본선에서 코퍼스 확장 대상)")
                    continue
                redraft[c.clause_type] += 1
                if redraft[c.clause_type] <= MAX_REDRAFT:
                    _t(trace, "ORCHESTRATOR",
                       f"A1 재기안 {redraft[c.clause_type]}/{MAX_REDRAFT}",
                       f"{c.clause_type}: 대체 근거 {alts[0]} 로 재시도")
                else:
                    _t(trace, "ORCHESTRATOR", "A1 재기안 소진",
                       f"{c.clause_type}: {MAX_REDRAFT}회 실패 → 기권 확정")

            # R2
            for c in clauses:
                if not c.trigger_risks:
                    continue          # 트리거가 없으면 귀속을 물을 대상이 아니다
                self.adversary.r2_attribution(c, props, context, trace=trace)

            self.ledger.decide(clauses, trace=trace)

            # 근거 격리된 조항은 발행 불가.
            # 다만 **안전성 조항의 불확실은 침묵이 아니라 승격**이어야 한다.
            # 근거가 없다는 이유로 안전성 조항을 조용히 기권하면, 실무자는
            # 그 조항을 검토할 기회 자체를 잃는다. 정합성 검사(C4)가 이 결함을
            # 잡아냈고 여기서 근본 원인을 고친다.
            for c in clauses:
                if not getattr(c, "evidence", {}).get("isolated"):
                    continue
                if c.clause_type in SAFETY_CLAUSES and c.trigger_risks:
                    # 할 말이 있는데(구조 트리거 존재) 근거를 확인하지 못한 경우만
                    # 승격한다. 트리거조차 없으면 애초에 이 분자의 문제가 아니므로
                    # 승격은 소음이 된다.
                    c.decision = "escalate"
                    c.reason_code = "safety_clause_evidence_missing"
                elif c.decision != "abstain":
                    c.decision = "abstain"
                    c.reason_code = "evidence_not_in_corpus"

            # A2: 귀속 기각된 조항의 경보를 하향
            newly = 0
            for c in clauses:
                if c.reason_code == "not_structure_attributable" and c.trigger_risks:
                    if not set(c.trigger_risks) & down:
                        self.bank.record(run_id, rnd, c, "not_structure_attributable",
                                         "Δ*≤0 → 경보 등급 하향")
                        newly += 1
                        _t(trace, "MARKER", "A2 리스크 등급 하향",
                           f"{c.clause_type}: {c.trigger_risks} 를 트리거 자격에서 제외 "
                           f"(Case Bank 기록)")

            # R3 → A3
            feas = self.adversary.r3_feasibility(clauses, self.actuary, trace=trace)
            substituted = 0
            if feas["exceeds"]:
                cand = sorted([c for c in clauses if c.decision in ("advance", "escalate")
                               and not getattr(c, "substituted", False)],
                              key=lambda c: (c.trust if c.trust == c.trust else 0))
                if cand:
                    self.substitute_monitoring(cand[0], trace)
                    substituted = 1

            unresolved = sum(1 for c in clauses if c.decision == "escalate")
            resolved = sum(1 for c in clauses if c.decision == "advance")
            history.append({"round": rnd, "advance": resolved,
                            "escalate": unresolved,
                            "abstain": sum(1 for c in clauses
                                           if c.decision == "abstain"),
                            "downgraded": newly, "substituted": substituted})

            # A4: 기권율 과다 또는 동일 사유 반복 → 사람에게
            ab_rate = history[-1]["abstain"] / max(len(clauses), 1)
            top_reason, top_n = Counter(
                c.reason_code for c in clauses if c.decision == "abstain"
            ).most_common(1)[0] if history[-1]["abstain"] else ("", 0)
            if ab_rate > ABSTAIN_ESCALATION:
                escalate_contract = {
                    "trigger": "abstain_rate_exceeded",
                    "abstain_rate": ab_rate,
                    "dominant_reason": top_reason,
                    "action": "사람에게 계약 개정 요청 (자동 완화 금지)",
                }
                _t(trace, "ORCHESTRATOR", "A4 계약 개정 요청",
                   f"기권율 {ab_rate:.0%} > {ABSTAIN_ESCALATION:.0%} · "
                   f"주 사유 '{top_reason}' → **사람에게 승격. 임계를 자동으로 "
                   f"낮추지 않는다**")

            # 정지 조건
            improved = newly + substituted
            if newly == 0 and substituted == 0:
                _t(trace, "ORCHESTRATOR", f"라운드 {rnd} 수렴",
                   "이번 라운드 개선량 0 → 정지")
                break
            if rnd == budget_rounds:
                _t(trace, "ORCHESTRATOR", "예산 소진", f"{budget_rounds} 라운드 도달")

        # ── 조항 집합 내부 정합성 검사 ─────────────────────────
        # 개별 조항이 각각 타당해도 집합으로 모순일 수 있다.
        viol = consistency_check(clauses, context=context,
                                 followups=followups, feasibility=feas)
        cons = summarize(viol)
        for v in viol:
            _t(trace, "LEDGER", f"정합성 {v.severity}",
               f"[{v.code}] {v.message} → {v.action}")
        if not cons["publishable"]:
            # blocking 위반이 있으면 발행을 철회하고 전부 사람 검토로 올린다.
            blocked = {cid for v in viol if v.severity == "blocking"
                       for cid in v.clause_ids}
            for c in clauses:
                if c.decision == "advance" and c.clause_id in blocked:
                    c.decision = "escalate"
                    c.reason_code = "blocked_by_consistency_check"
            _t(trace, "LEDGER", "발행 철회",
               f"정합성 blocking {cons['counts']['blocking']}건 → 해당 조항을 "
               f"사람 검토로 되돌린다")

        meta = {
            "consistency": cons,
            "context": context,
            "molecule": {k: props[k] for k in ("smiles", "mw", "clogp", "tpsa", "hbd")},
            "ad": props["ad"],
            "risks": [{"risk_id": r.risk_id, "flag": r.flag} for r in risks],
            "dose": dose, "power_gate": power,
            "feasibility": feas if clauses else None,
            "rounds": len(history), "round_history": history,
            "redrafts": dict(redraft),
            "contract_escalation": escalate_contract,
            "case_bank_entries": len(self.bank.entries),
            "n_train": self.fit["n_train"],
            "confirmed_triggers": self.fit["confirmed"],
            "tool_versions": _versions(),
            "evidence_isolated": [c.clause_type for c in clauses
                                  if getattr(c, "evidence", {}).get("isolated")],
            "seed": 20260807,
        }
        return self.ledger.seal(run_id, clauses, trace, meta)
