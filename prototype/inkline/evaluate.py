"""E1 — SAFE-INC. 템플릿 베이스라인 대비 증분 측정.

    python3 prototype/inkline/evaluate.py

세 모델(B-TPL / B-RULE / INKLINE)을 동일한 결정론적 분할에서 비교하고,
헤드라인 지표 ΔP@C(커버리지 C에서의 정밀도 증분)와 ΔAUPRC 를 낸다.

이 스크립트가 만드는 숫자가 제안서의 헤드라인이 된다.
결과가 나쁘면 나쁜 대로 적는다.
"""

from __future__ import annotations

import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "trialbench"))

from load import DEFAULT_ROOT, build_dataset  # noqa: E402
from model import (  # noqa: E402
    TARGET_CLAUSES, ApplicabilityDomain, ClauseModel, RuleBaseline,
    TemplateBaseline, auprc, ece, flags_for, precision_at_coverage,
    split_of, wilson,
)

COVERAGES = [0.05, 0.10, 0.20]
OUT = os.path.join(ROOT, "results", "e1_safe_inc.json")
ASSOC = os.path.join(ROOT, "results", "s2c_associations.json")


def confirmed_map():
    """사전 선언 기전 게이트에서 확증된 (조항 → 구조 경보) 매핑."""
    d = json.load(open(ASSOC, encoding="utf-8"))
    out = {}
    for r in d["mechanism_gate"]["confirmatory"]:
        out.setdefault(r["clause"], []).append(r["flag"])
    return out


def main():
    ds = build_dataset(DEFAULT_ROOT,
                       cache=os.path.expanduser("~/.cache/trialbench/ds.pkl"))
    recs = ds["records"]
    train = [r for r in recs if split_of(r["nctid"]) == "train"]
    test = [r for r in recs if split_of(r["nctid"]) == "test"]
    print(f"분할: train {len(train):,} / test {len(test):,} "
          f"(NCT ID 해시 기준 결정론적)")

    conf = confirmed_map()
    print(f"확증된 구조 경보 매핑: {conf}")

    tpl = TemplateBaseline().fit(train, TARGET_CLAUSES)
    rule = RuleBaseline(conf)

    report = {"n_train": len(train), "n_test": len(test),
              "confirmed_map": conf, "coverages": COVERAGES, "clauses": {}}

    hdr = (f"\n{'조항':11s} {'기저율':>7s} {'모델':9s} {'AUPRC':>7s} "
           f"{'ΔAUPRC':>8s} " + " ".join(f"{'P@'+str(int(c*100))+'%':>7s}"
                                         for c in COVERAGES)
           + " " + " ".join(f"{'Δ@'+str(int(c*100)):>7s}" for c in COVERAGES))
    print(hdr)
    print("-" * len(hdr))

    for c in TARGET_CLAUSES:
        y = np.array([r[c] for r in test], dtype=int)
        base_rate = float(y.mean())

        s_tpl = tpl.predict(test, c)
        s_rule = rule.predict(test, c)
        cm = ClauseModel(c).fit(train)
        s_ink = cm.predict(test)
        cmp_ = ClauseModel(c, continuous=True).fit(train)
        s_inkp = cmp_.predict(test)

        MODELS = (("B-TPL", s_tpl), ("B-RULE", s_rule),
                  ("INKLINE", s_ink), ("INKLINE+", s_inkp))
        ap = {k: auprc(y, s) for k, s in MODELS}
        pc = {}
        for k, s in MODELS:
            pc[k] = {}
            for cov in COVERAGES:
                p, n = precision_at_coverage(y, s, cov)
                lo, hi = wilson(int(round(p * n)), n)[1:]
                pc[k][cov] = {"precision": p, "n": n, "ci": [lo, hi]}

        for k in ("B-TPL", "B-RULE", "INKLINE", "INKLINE+"):
            dap = ap[k] - ap["B-TPL"]
            row = (f"{c if k == 'B-TPL' else '':11s} "
                   f"{base_rate if k == 'B-TPL' else float('nan'):7.3f} "
                   f"{k:9s} {ap[k]:7.3f} {dap:+8.3f} "
                   + " ".join(f"{pc[k][cov]['precision']:7.3f}" for cov in COVERAGES)
                   + " " + " ".join(
                       f"{pc[k][cov]['precision'] - pc['B-TPL'][cov]['precision']:+7.3f}"
                       for cov in COVERAGES))
            print(row.replace("    nan", "      -"))
        print()

        report["clauses"][c] = {
            "base_rate_test": base_rate,
            "preregistered_flags": flags_for(c),
            "confirmed_flags": conf.get(c, []),
            "auprc": ap,
            "delta_auprc": {k: ap[k] - ap["B-TPL"] for k in ap},
            "precision_at_coverage": {k: {str(cov): v for cov, v in d.items()}
                                      for k, d in pc.items()},
            "delta_p_at_coverage": {
                k: {str(cov): pc[k][cov]["precision"] - pc["B-TPL"][cov]["precision"]
                    for cov in COVERAGES}
                for k in pc},
            "ece_inkline": ece(y, s_ink),
            "ece_inkline_plus": ece(y, s_inkp),
            "n_positive_test": int(y.sum()),
        }

    # 헤드라인 요약
    head = {}
    for cov in COVERAGES:
        head[str(cov)] = {}
        for mk in ("INKLINE", "INKLINE+"):
            deltas = [report["clauses"][c]["delta_p_at_coverage"][mk][str(cov)]
                      for c in TARGET_CLAUSES]
            head[str(cov)][mk] = {"mean_delta_p": float(np.mean(deltas)),
                                  "min": float(np.min(deltas)),
                                  "max": float(np.max(deltas))}
    report["headline_delta_p"] = head
    report["mean_delta_auprc"] = {
        mk: float(np.mean([report["clauses"][c]["delta_auprc"][mk]
                           for c in TARGET_CLAUSES]))
        for mk in ("B-RULE", "INKLINE", "INKLINE+")}

    print("[헤드라인] 템플릿 베이스라인 대비 증분 (5개 조항 평균)")
    for cov in COVERAGES:
        for mk in ("INKLINE", "INKLINE+"):
            h = head[str(cov)][mk]
            print(f"  커버리지 {cov:.0%} {mk:9s}: ΔP@C = {h['mean_delta_p']:+.3f} "
                  f"(조항별 {h['min']:+.3f} ~ {h['max']:+.3f})")
    for mk, v in report["mean_delta_auprc"].items():
        print(f"  ΔAUPRC {mk:9s}: {v:+.3f}")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(report, open(OUT, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"\n결과 저장: {OUT}")


if __name__ == "__main__":
    main()
