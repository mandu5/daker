"""E3 — NULL. 기권·오판·커버리지 측정.

    python3 prototype/inkline/evaluate_e3.py [--n 800]

무엇을 재는가
    제안서가 **주지표로 선언한** FOR_safety 를 실제로 측정한다.
    선언만 하고 숫자가 없으면 평가 체계가 아니라 수사다.

    FOR_safety = 실제 프로토콜에 존재하는 안전성 조항인데
                 시스템이 '불필요'(=발행 안 함, 기권도 아닌 명시적 미발행)로
                 판정한 비율.

    기권(abstain)은 '모르겠다'이지 '불필요'가 아니므로 분자에서 제외하고
    커버리지로 따로 보고한다. 이 구분이 없으면 기권을 늘려 지표를 속일 수 있다.

    함께 재는 것
      - 커버리지 / 기권율 / 사람검토 승격률
      - 발행분 정밀도 (issued precision) 와 오경보율 (FAR)
      - risk-coverage 곡선과 그 아래 면적 (AURC)
      - 음성 대조: 확증 경보가 하나도 없는 분자에서 발행이 일어나는가
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "trialbench"))

from agents import Adversary, Ledger, Marker, Scribe  # noqa: E402
from flags import compute_flags  # noqa: E402
from load import DEFAULT_ROOT, build_dataset  # noqa: E402
from model import SAFETY_CLAUSES, TARGET_CLAUSES, split_of, wilson  # noqa: E402
from run import fit_or_load  # noqa: E402

OUT = os.path.join(ROOT, "results", "e3_null.json")


def evaluate(recs, fit, verbose=True):
    marker = Marker(ad=fit["ad"])
    scribe = Scribe(fit["tpl"], fit["models"], confirmed=fit["confirmed"])
    adversary = Adversary(fit["tpl"], fit["models"], confirmed=fit["confirmed"],
                          n_decoy=6)
    ledger = Ledger()

    rows = []
    for i, r in enumerate(recs):
        if verbose and i % 100 == 0:
            print(f"  {i}/{len(recs)}", file=sys.stderr)
        ctx = {"phase": r["phase"], "indication": r["condition"],
               "oncology": bool(r["oncology"])}
        risks, props = marker.run(r["smiles"], trace=None)
        if risks is None:
            continue
        clauses = scribe.run(risks, props, ctx, trace=None)
        for c in clauses:
            adversary.r1_evidence(c)
            adversary.r2_attribution(c, props, ctx)
        ledger.decide(clauses)
        for c in clauses:
            rows.append({
                "nctid": r["nctid"], "clause": c.clause_type,
                "truth": int(r[c.clause_type]),
                "decision": c.decision, "reason": c.reason_code,
                "trust": None if c.trust != c.trust else float(c.trust),
                "delta_star": (None if c.delta_star != c.delta_star
                               else float(c.delta_star)),
                "has_trigger": bool(c.trigger_risks),
            })
    return rows


def report(rows):
    out = {"n_pairs": len(rows)}

    dec = {k: sum(1 for r in rows if r["decision"] == k)
           for k in ("advance", "escalate", "abstain")}
    n = max(len(rows), 1)
    out["decision_mix"] = {k: {"n": v, "rate": v / n} for k, v in dec.items()}

    # ── FOR_safety: 실제 존재하는 안전성 조항을 '불필요'로 판정한 비율 ──
    # '불필요' = 구조 트리거가 있는데도 Δ*≤0 등으로 명시적으로 기각한 경우.
    # 트리거 자체가 없어 판단 대상이 아니었던 것(no_structural_trigger)과
    # 판정 보류(attribution_undetermined)는 '모르겠다'이므로 제외한다.
    EXPLICIT_REJECT = {"not_structure_attributable", "trust_below_floor"}
    safety = [r for r in rows if r["clause"] in SAFETY_CLAUSES and r["truth"] == 1]
    fo = [r for r in safety if r["decision"] == "abstain"
          and r["reason"] in EXPLICIT_REJECT]
    p, lo, hi = wilson(len(fo), max(len(safety), 1))
    out["FOR_safety"] = {"n_safety_true": len(safety), "n_false_omission": len(fo),
                         "rate": p, "ci": [lo, hi], "target": 0.02,
                         "pass": p <= 0.02,
                         "definition": "실제 존재하는 안전성 조항 중 시스템이 "
                                       "명시적으로 '구조 유래 아님/신뢰도 미달'로 "
                                       "기각한 비율. 판단 보류(기권)는 제외."}

    # ── 발행분 정밀도와 오경보율 ────────────────────────────────
    for label, sel in (("advance", lambda r: r["decision"] == "advance"),
                       ("advance_or_escalate",
                        lambda r: r["decision"] in ("advance", "escalate"))):
        sub = [r for r in rows if sel(r)]
        tp = sum(r["truth"] for r in sub)
        pr, plo, phi = wilson(tp, max(len(sub), 1))
        neg = [r for r in rows if r["truth"] == 0]
        fp = sum(1 for r in neg if sel(r))
        fr, flo, fhi = wilson(fp, max(len(neg), 1))
        out[label] = {"n": len(sub), "coverage": len(sub) / n,
                      "precision": pr, "precision_ci": [plo, phi],
                      "false_alarm_rate": fr, "far_ci": [flo, fhi]}

    # ── 비교 기준 ─────────────────────────────────────────────
    # 주의: 전체를 풀링한 "발행분 정밀도 / 전체 유병률" 은 **심슨의 역설**에
    # 빠진다. 조항 유형마다 기저율이 3배 넘게 차이나는데(간기능 0.385 vs
    # CYP 0.101), 시스템은 기저율 높은 조항을 거의 발행하지 않기 때문이다.
    # 풀링 지표는 참고로만 남기고, **조항별 lift 와 기저율 가중 집계**를 쓴다.
    base = sum(r["truth"] for r in rows) / n
    out["issue_everything_precision_pooled"] = base
    out["precision_lift_pooled_MISLEADING"] = (
        out["advance"]["precision"] / base if base > 0 else None)

    # ── 조항별 ────────────────────────────────────────────────
    out["by_clause"] = {}
    for c in TARGET_CLAUSES:
        sub = [r for r in rows if r["clause"] == c]
        adv = [r for r in sub if r["decision"] == "advance"]
        esc = [r for r in sub if r["decision"] == "escalate"]
        out["by_clause"][c] = {
            "n": len(sub), "base_rate": sum(r["truth"] for r in sub) / max(len(sub), 1),
            "advance_rate": len(adv) / max(len(sub), 1),
            "escalate_rate": len(esc) / max(len(sub), 1),
            "advance_precision": (sum(r["truth"] for r in adv) / len(adv)
                                  if adv else None),
            "escalate_precision": (sum(r["truth"] for r in esc) / len(esc)
                                   if esc else None),
        }
        br = out["by_clause"][c]["base_rate"]
        ap_ = out["by_clause"][c]["advance_precision"]
        out["by_clause"][c]["precision_lift"] = (ap_ / br) if (ap_ and br) else None
        if adv:
            k = sum(r["truth"] for r in adv)
            _, lo_, hi_ = wilson(k, len(adv))
            out["by_clause"][c]["advance_precision_ci"] = [lo_, hi_]
            out["by_clause"][c]["lift_ci"] = [lo_ / br, hi_ / br] if br else None

    # 발행이 일어난 조항만 대상으로, 발행 건수로 가중한 lift
    wnum = wden = 0.0
    for c, v in out["by_clause"].items():
        if v["precision_lift"] is None:
            continue
        w = v["n"] * v["advance_rate"]
        wnum += w * v["precision_lift"]
        wden += w
    out["weighted_precision_lift"] = (wnum / wden) if wden else None

    # ── risk-coverage 곡선 (신뢰도 T 로 정렬) ──────────────────
    scored = [r for r in rows if r["trust"] is not None]
    scored.sort(key=lambda r: -r["trust"])
    curve, risks = [], []
    correct = 0
    for i, r in enumerate(scored, 1):
        correct += r["truth"]
        if i % max(1, len(scored) // 40) == 0 or i == len(scored):
            cov = i / len(scored)
            risk = 1 - correct / i
            curve.append({"coverage": cov, "risk": risk, "precision": correct / i})
            risks.append(risk)
    out["risk_coverage"] = curve
    out["aurc"] = float(np.trapezoid(
        [c["risk"] for c in curve], [c["coverage"] for c in curve])) if curve else None

    # ── 음성 대조: 확증 경보 없는 분자 ─────────────────────────
    no_trig = [r for r in rows if not r["has_trigger"]]
    out["negative_control"] = {
        "n": len(no_trig),
        "advance_rate": sum(1 for r in no_trig if r["decision"] == "advance")
                        / max(len(no_trig), 1),
        "note": "확증된 구조 경보가 없는 (시험, 조항) 쌍에서는 발행이 0이어야 한다",
    }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=800, help="평가 분할에서 표집할 시험 수")
    ap.add_argument("--seed", type=int, default=20260807)
    args = ap.parse_args()

    ds = build_dataset(DEFAULT_ROOT,
                       cache=os.path.expanduser("~/.cache/trialbench/ds.pkl"))
    test = [r for r in ds["records"] if split_of(r["nctid"]) == "test"]
    rng = np.random.default_rng(args.seed)
    idx = rng.choice(len(test), min(args.n, len(test)), replace=False)
    sample = [test[i] for i in sorted(idx)]
    print(f"평가 분할 {len(test):,}건 중 {len(sample):,}건 표집 "
          f"(시드 {args.seed}, 결정론적)")

    fit = fit_or_load(verbose=False)
    rows = evaluate(sample, fit)
    rep = report(rows)
    rep["n_trials"] = len(sample)
    rep["seed"] = args.seed

    d = rep["decision_mix"]
    print(f"\n판정 구성  발행 {d['advance']['rate']:.1%} · "
          f"사람검토 {d['escalate']['rate']:.1%} · 기권 {d['abstain']['rate']:.1%}"
          f"  (조항 쌍 {rep['n_pairs']:,}개)")

    f = rep["FOR_safety"]
    print(f"\n★ FOR_safety = {f['rate']:.3%}  "
          f"[{f['ci'][0]:.3%}, {f['ci'][1]:.3%}]  목표 ≤2%  "
          f"→ {'통과' if f['pass'] else '실패 — 절감 주장 철회'}")
    print(f"   (실제 존재하는 안전성 조항 {f['n_safety_true']:,}건 중 "
          f"명시적 오기각 {f['n_false_omission']}건)")

    a, ae = rep["advance"], rep["advance_or_escalate"]
    print(f"\n발행분      커버리지 {a['coverage']:.1%} · 정밀도 {a['precision']:.3f} "
          f"[{a['precision_ci'][0]:.3f},{a['precision_ci'][1]:.3f}] · "
          f"오경보율 {a['false_alarm_rate']:.3f}")
    print(f"발행+검토   커버리지 {ae['coverage']:.1%} · 정밀도 {ae['precision']:.3f} · "
          f"오경보율 {ae['false_alarm_rate']:.3f}")
    print(f"~풀링 기준 정밀도 {rep['issue_everything_precision_pooled']:.3f} "
          f"→ 풀링 lift {rep['precision_lift_pooled_MISLEADING']:.2f}배 "
          f"(심슨의 역설 — 아래 조항별을 볼 것)")
    if rep["weighted_precision_lift"]:
        print(f"발행 가중 정밀도 lift {rep['weighted_precision_lift']:.2f}배")
    print(f"AURC {rep['aurc']:.4f}  (낮을수록 좋음)")

    nc = rep["negative_control"]
    print(f"\n음성 대조   확증 경보 없는 {nc['n']:,}쌍의 발행률 "
          f"{nc['advance_rate']:.4f} "
          f"{'✓ 0' if nc['advance_rate'] == 0 else '✗ 누출'}")

    print("\n조항별")
    for c, v in rep["by_clause"].items():
        ap_ = "—" if v["advance_precision"] is None else f"{v['advance_precision']:.3f}"
        ep = "—" if v["escalate_precision"] is None else f"{v['escalate_precision']:.3f}"
        lf = "—" if v.get("precision_lift") is None else f"{v['precision_lift']:.2f}x"
        print(f"  {c:9s} 기저 {v['base_rate']:.3f} · 발행 {v['advance_rate']:5.1%}"
              f"(정밀도 {ap_} · lift {lf:>6s}) · 검토 {v['escalate_rate']:5.1%}"
              f"(정밀도 {ep})")

    json.dump(rep, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n결과 저장: {OUT}")


if __name__ == "__main__":
    main()
