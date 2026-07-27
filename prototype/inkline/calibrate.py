"""신뢰도 임계 τ 의 조항별 보정.

왜 필요한가
    전역 τ 하나로 모든 조항을 판정하면, 조항마다 기저율과 신뢰도 T 의 분포가
    달라 어떤 조항은 과다 발행되고 어떤 조항은 아예 발행되지 않는다.
    실제로 E3 에서 음식·자몽 조항은 연관이 가장 강한데(lift 1.91) 발행분
    정밀도가 0 이었다 — 전역 τ 가 그 조항에 맞지 않았기 때문이다.

무엇을 하는가
    학습 분할에서 떼어낸 **보정 분할(calibration split)** 로 조항별 τ 를 찾는다.
    평가 분할은 건드리지 않는다.

        τ(c) = 목표 정밀도 π 를 만족하는 최소 임계
             = min { t : precision(발행 | T ≥ t) ≥ π }

    목표를 만족하는 t 가 없으면 그 조항은 **발행 자체를 봉인**한다.
    억지로 임계를 낮춰 발행하는 것보다 기권이 낫다.

    τ_low 는 사람검토 밴드의 하한이며, 재현율을 일정 수준 확보하는 지점으로 잡는다.
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

from agents import Adversary, Marker, Scribe  # noqa: E402
from load import DEFAULT_ROOT, build_dataset  # noqa: E402
from model import TARGET_CLAUSES, split_of, wilson  # noqa: E402
from run import fit_or_load  # noqa: E402

OUT = os.path.join(ROOT, "results", "tau_calibration.json")

# 보정 분할: 학습 분할 중 이 비율을 τ 보정 전용으로 뗀다.
CALIB_FRAC = 0.25
TARGET_PRECISION = 0.30      # 발행 밴드 목표 정밀도
MIN_ADVANCE_N = 20           # 이보다 적게 발행되면 추정 불안정 → 봉인
ESCALATE_RECALL = 0.50       # 사람검토 밴드까지 포함해 확보하려는 재현율


def calib_split(nctid, seed="inkline-calib"):
    import hashlib
    h = hashlib.sha256((seed + str(nctid)).encode()).hexdigest()
    return (int(h[:8], 16) / 0xFFFFFFFF) < CALIB_FRAC


def collect_scores(recs, fit, verbose=True):
    """보정 분할에서 (조항, 신뢰도 T, 정답) 을 모은다."""
    marker = Marker(ad=fit["ad"])
    scribe = Scribe(fit["tpl"], fit["models"], confirmed=fit["confirmed"])
    adversary = Adversary(fit["tpl"], fit["models"], confirmed=fit["confirmed"],
                          n_decoy=6)
    eps = 0.02
    rows = []
    for i, r in enumerate(recs):
        if verbose and i % 200 == 0:
            print(f"  {i}/{len(recs)}", file=sys.stderr)
        ctx = {"phase": r["phase"], "indication": r["condition"],
               "oncology": bool(r["oncology"])}
        risks, props = marker.run(r["smiles"], trace=None)
        if risks is None:
            continue
        for c in scribe.run(risks, props, ctx, trace=None):
            if not c.trigger_risks:
                continue                    # 구조 트리거가 없으면 판정 대상 아님
            adversary.r2_attribution(c, props, ctx)
            if c.delta_star != c.delta_star or c.delta_star <= 0:
                continue                    # 귀속 미입증은 어차피 기권
            t = c.delta_star / (c.sigma + eps) * max(c.ad, 1e-3)
            rows.append({"clause": c.clause_type, "trust": float(t),
                         "truth": int(r[c.clause_type])})
    return rows


def calibrate(rows, target=TARGET_PRECISION):
    out = {}
    for c in TARGET_CLAUSES:
        sub = sorted([r for r in rows if r["clause"] == c],
                     key=lambda r: -r["trust"])
        n = len(sub)
        if n == 0:
            out[c] = {"n_candidates": 0, "tau": None, "tau_low": None,
                      "sealed": True, "reason": "보정 분할에 후보 없음"}
            continue
        base = sum(r["truth"] for r in sub) / n

        # 상위 k 개를 발행했을 때의 정밀도를 훑어 목표를 만족하는 최대 k 를 찾는다.
        best_k, best_prec = None, None
        hit = 0
        for k in range(1, n + 1):
            hit += sub[k - 1]["truth"]
            prec = hit / k
            if k >= MIN_ADVANCE_N and prec >= target:
                best_k, best_prec = k, prec
        if best_k is None:
            out[c] = {
                "n_candidates": n, "base_rate": base, "tau": None,
                "tau_low": None, "sealed": True,
                "reason": f"목표 정밀도 {target:.2f} 를 만족하는 임계가 없음 "
                          f"(최소 발행 {MIN_ADVANCE_N}건 조건). 발행을 봉인하고 "
                          f"사람검토·기권만 사용한다",
            }
            continue

        tau = sub[best_k - 1]["trust"]
        # τ_low: 목표 재현율을 확보하는 지점
        total_pos = sum(r["truth"] for r in sub)
        need = ESCALATE_RECALL * total_pos
        acc, tau_low = 0, sub[-1]["trust"]
        for r in sub:
            acc += r["truth"]
            if acc >= need:
                tau_low = r["trust"]
                break
        tau_low = min(tau_low, tau)
        _, lo, hi = wilson(int(round(best_prec * best_k)), best_k)
        out[c] = {"n_candidates": n, "base_rate": base, "tau": float(tau),
                  "tau_low": float(tau_low), "sealed": False,
                  "advance_n": best_k, "advance_precision": best_prec,
                  "precision_ci": [lo, hi],
                  "lift_vs_base": best_prec / base if base > 0 else None}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=float, default=TARGET_PRECISION)
    ap.add_argument("--n", type=int, default=2500)
    args = ap.parse_args()

    ds = build_dataset(DEFAULT_ROOT,
                       cache=os.path.expanduser("~/.cache/trialbench/ds.pkl"))
    train = [r for r in ds["records"] if split_of(r["nctid"]) == "train"]
    calib = [r for r in train if calib_split(r["nctid"])]
    rng = np.random.default_rng(20260807)
    if len(calib) > args.n:
        idx = rng.choice(len(calib), args.n, replace=False)
        calib = [calib[i] for i in sorted(idx)]
    print(f"보정 분할 {len(calib):,}건 (학습 분할에서 분리, 평가 분할 미사용)")

    fit = fit_or_load(verbose=False)
    rows = collect_scores(calib, fit)
    print(f"신뢰도 산출 대상 (조항, 시험) 쌍: {len(rows):,}")

    res = calibrate(rows, target=args.target)
    print(f"\n조항별 τ 보정 (목표 정밀도 {args.target:.2f})")
    print(f"{'조항':14s} {'후보':>6s} {'기저':>6s} {'τ':>8s} {'τ_low':>8s} "
          f"{'발행n':>6s} {'정밀도':>7s} {'lift':>6s}  상태")
    for c, v in res.items():
        if v.get("sealed"):
            print(f"{c:14s} {v['n_candidates']:6d} "
                  f"{v.get('base_rate', 0):6.3f} {'—':>8s} {'—':>8s} {'—':>6s} "
                  f"{'—':>7s} {'—':>6s}  **발행 봉인** {v['reason'][:38]}")
        else:
            print(f"{c:14s} {v['n_candidates']:6d} {v['base_rate']:6.3f} "
                  f"{v['tau']:8.3f} {v['tau_low']:8.3f} {v['advance_n']:6d} "
                  f"{v['advance_precision']:7.3f} "
                  f"{v['lift_vs_base']:6.2f}x  보정 완료")

    payload = {"target_precision": args.target, "n_calib_trials": len(calib),
               "n_pairs": len(rows), "min_advance_n": MIN_ADVANCE_N,
               "escalate_recall": ESCALATE_RECALL, "per_clause": res,
               "note": "평가 분할을 사용하지 않는다. 학습 분할에서 떼어낸 "
                       "보정 분할만 사용한다."}
    json.dump(payload, open(OUT, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"\n결과 저장: {OUT}")


if __name__ == "__main__":
    main()
