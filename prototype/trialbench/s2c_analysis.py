"""구조 → 프로토콜 조항(Structure-to-Clause) 연관 분석.

가설
    후보물질의 분자 구조에는 임상 프로토콜이 나중에 조항으로 반영하게 될
    위험 신호가 이미 들어 있다. 그렇다면 구조 경보와 실제 프로토콜의
    선정·제외기준 조항 사이에 통계적 연관이 관측되어야 한다.

이 스크립트가 하는 일
    1. 조항 유형별 기저 출현율을 측정해 **템플릿 조항과 분자 특이 조항을 분리**한다.
       (기저율이 매우 높은 조항은 분자와 무관하게 거의 모든 프로토콜에 들어간다)
    2. 각 (구조 플래그 × 조항) 쌍의 연관을 Fisher 정확검정으로 측정하고
       Benjamini-Hochberg FDR 과 Bonferroni 를 모두 보고한다.
    3. **적응증(종양/비종양)과 상(phase)으로 층화**해 교락을 확인한다.
       층화 후 무너지는 연관은 그 사실을 그대로 보고한다.
    4. 모든 비율에 Wilson 95% 신뢰구간을 병기한다.

정직성 원칙
    유의하지 않았던 쌍, 층화 후 소멸한 연관, 채택되지 못한 룰의 비율을
    모두 출력한다. 결과를 취사선택하지 않는다.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flags import FLAG_NAMES, RATIONALE, HERG_CLOGP_CUT  # noqa: E402
from load import CLAUSE_PATTERNS, DEFAULT_ROOT, build_dataset  # noqa: E402
from mechanism import (  # noqa: E402
    PREREGISTERED, CLAUSE_CAVEATS, EXCLUDED_FROM_CLAIMS, NO_MECHANISM_CLAIM,
    classify_pair, mechanism_of,
)

CLAUSES = list(CLAUSE_PATTERNS.keys())

# 기저율이 이 값을 넘으면 "템플릿 조항"으로 분류한다.
# 거의 모든 프로토콜에 들어가는 조항에서는 분자 특이 가치를 주장하지 않는다.
TEMPLATE_BASERATE = 0.40
# 기저율이 이 값 미만이면 표본이 희소해 판정 보류.
SPARSE_BASERATE = 0.02


def wilson(k, n, z=1.96):
    """이항 비율의 Wilson 95% 신뢰구간."""
    if n == 0:
        return (0.0, 0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (p, (c - m) / d, (c + m) / d)


def contingency(records, flag, clause):
    a = b = c = d = 0
    for r in records:
        f, y = r[flag], r[clause]
        if f and y:
            a += 1
        elif f and not y:
            b += 1
        elif (not f) and y:
            c += 1
        else:
            d += 1
    return a, b, c, d


def assoc(records, flag, clause):
    from scipy.stats import fisher_exact
    a, b, c, d = contingency(records, flag, clause)
    n_flag, n_noflag = a + b, c + d
    if n_flag == 0 or n_noflag == 0:
        return None
    p1, lo1, hi1 = wilson(a, n_flag)
    p0, lo0, hi0 = wilson(c, n_noflag)
    odds, pval = fisher_exact([[a, b], [c, d]])
    return {
        "flag": flag, "clause": clause,
        "n_flag": n_flag, "n_noflag": n_noflag,
        "p_clause_given_flag": p1, "ci_flag": [lo1, hi1],
        "p_clause_given_noflag": p0, "ci_noflag": [lo0, hi0],
        "lift": (p1 / p0) if p0 > 0 else float("nan"),
        "odds_ratio": odds, "p_value": pval,
        "table": [a, b, c, d],
    }


def benjamini_hochberg(pvals, alpha=0.05):
    """BH 보정. 각 검정의 기각 여부와 임계값을 반환."""
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    reject = [False] * m
    thresh = 0.0
    for rank, i in enumerate(order, start=1):
        if pvals[i] <= alpha * rank / m:
            thresh = alpha * rank / m
    for i in range(m):
        reject[i] = pvals[i] <= thresh
    return reject, thresh


def run(records, label, flags=None, clauses=None):
    flags = flags or FLAG_NAMES
    clauses = clauses or CLAUSES
    results = []
    for f in flags:
        for c in clauses:
            r = assoc(records, f, c)
            if r:
                r["stratum"] = label
                results.append(r)
    pvals = [r["p_value"] for r in results]
    if pvals:
        reject_bh, thr = benjamini_hochberg(pvals)
        bonf = 0.05 / len(pvals)
        for r, rej in zip(results, reject_bh):
            r["sig_bh"] = bool(rej)
            r["sig_bonferroni"] = bool(r["p_value"] < bonf)
            r["n_tests"] = len(pvals)
            r["bonferroni_alpha"] = bonf
            r["bh_threshold"] = thr
    return results


def classify_clauses(records):
    """기저율로 조항을 템플릿 / 분자특이후보 / 희소 로 분류."""
    n = len(records)
    out = {}
    for c in CLAUSES:
        k = sum(r[c] for r in records)
        p, lo, hi = wilson(k, n)
        if p >= TEMPLATE_BASERATE:
            kind = "template"
        elif p < SPARSE_BASERATE:
            kind = "sparse"
        else:
            kind = "molecule_specific_candidate"
        out[c] = {"count": k, "n": n, "base_rate": p, "ci": [lo, hi],
                  "kind": kind, "desc": CLAUSE_PATTERNS[c][0]}
    return out


def fmt_table(rows, title):
    lines = [f"\n{title}",
             f"{'flag':24s} {'clause':12s} {'n_flag':>7s} {'P|flag':>8s} "
             f"{'P|~flag':>8s} {'lift':>6s} {'p':>10s} {'BH':>3s} {'Bonf':>5s}"]
    for r in rows:
        lines.append(
            f"{r['flag']:24s} {r['clause']:12s} {r['n_flag']:7d} "
            f"{r['p_clause_given_flag']:8.3f} {r['p_clause_given_noflag']:8.3f} "
            f"{r['lift']:6.2f} {r['p_value']:10.2e} "
            f"{'Y' if r.get('sig_bh') else '.':>3s} "
            f"{'Y' if r.get('sig_bonferroni') else '.':>5s}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=DEFAULT_ROOT)
    ap.add_argument("--cache", default=os.path.expanduser("~/.cache/trialbench/ds.pkl"))
    ap.add_argument("--out", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "results"))
    ap.add_argument("--min-flag-n", type=int, default=100,
                    help="이보다 적게 매칭된 플래그는 검정에서 제외")
    args = ap.parse_args()

    ds = build_dataset(args.root, cache=args.cache)
    recs = ds["records"]
    print(f"\n고유 임상시험 {ds['n_trials']:,}건 → 분석 대상 {len(recs):,}건")
    print(f"제외 내역: {ds['stats']}")

    # 플래그 매칭률
    print("\n[구조 플래그 매칭률]")
    usable_flags = []
    for f in FLAG_NAMES:
        k = sum(1 for r in recs if r[f])
        p, lo, hi = wilson(k, len(recs))
        mark = ""
        if k < args.min_flag_n:
            mark = "  (표본 부족 → 제외)"
        elif p > 0.35:
            mark = "  (과다포괄 주의)"
        else:
            usable_flags.append(f)
        if k >= args.min_flag_n:
            usable_flags.append(f) if f not in usable_flags else None
        print(f"  {f:24s} {k:6d} / {len(recs):6d} = {p:5.1%} [{lo:.3f},{hi:.3f}]{mark}")
    usable_flags = [f for f in FLAG_NAMES
                    if sum(1 for r in recs if r[f]) >= args.min_flag_n]

    # 조항 분류
    cls = classify_clauses(recs)
    print("\n[조항 유형 기저율 — 템플릿 조항과 분자 특이 후보의 분리]")
    for c, v in sorted(cls.items(), key=lambda x: -x[1]["base_rate"]):
        print(f"  {c:12s} {v['base_rate']:6.1%} [{v['ci'][0]:.3f},{v['ci'][1]:.3f}]"
              f"  {v['kind']:28s} {v['desc']}")

    target_clauses = [c for c, v in cls.items()
                      if v["kind"] == "molecule_specific_candidate"]
    print(f"\n→ 가치 주장 대상 조항: {target_clauses}")
    print(f"→ 템플릿으로 분류되어 제외: "
          f"{[c for c, v in cls.items() if v['kind'] == 'template']}")
    print(f"→ 희소로 판정 보류: {[c for c, v in cls.items() if v['kind'] == 'sparse']}")

    # 전체 분석 (모든 조항 대상 — 템플릿 조항 포함해서 대조군으로 확인)
    all_rows = run(recs, "ALL", flags=usable_flags, clauses=CLAUSES)
    sig = [r for r in all_rows if r.get("sig_bonferroni") and r["lift"] > 1.0]
    sig.sort(key=lambda r: -r["lift"])
    print(fmt_table(sig[:25], "[전체 표본 · Bonferroni 유의 · lift>1 상위]"))

    # 템플릿 조항에 대한 유의 연관은 교락 경고 신호다
    tmpl_sig = [r for r in all_rows
                if r.get("sig_bonferroni") and cls[r["clause"]]["kind"] == "template"]
    if tmpl_sig:
        print(fmt_table(sorted(tmpl_sig, key=lambda r: -abs(r["lift"] - 1))[:12],
                        "[경고] 템플릿 조항과 유의하게 연관된 플래그 "
                        "— 해당 플래그는 적응증 등의 대리변수일 가능성"))

    # 층화 분석
    onc = [r for r in recs if r["oncology"]]
    non = [r for r in recs if not r["oncology"]]
    print(f"\n[적응증 층화] 종양 {len(onc):,}건 / 비종양 {len(non):,}건")
    onc_rows = run(onc, "ONCOLOGY", flags=usable_flags, clauses=target_clauses)
    non_rows = run(non, "NON_ONCOLOGY", flags=usable_flags, clauses=target_clauses)

    idx_o = {(r["flag"], r["clause"]): r for r in onc_rows}
    idx_n = {(r["flag"], r["clause"]): r for r in non_rows}
    print(f"\n{'flag':24s} {'clause':12s} {'전체lift':>9s} {'종양lift':>9s} "
          f"{'비종양lift':>11s} {'판정':>14s}")
    survivors, collapsed = [], []
    for r in all_rows:
        if r["clause"] not in target_clauses:
            continue
        if not r.get("sig_bonferroni"):
            continue
        key = (r["flag"], r["clause"])
        ro, rn = idx_o.get(key), idx_n.get(key)
        lo = ro["lift"] if ro else float("nan")
        ln = rn["lift"] if rn else float("nan")
        # 층화 결과를 원본 레코드에도 붙여 기전 게이트에서 참조할 수 있게 한다
        r["lift_onc"], r["lift_non"] = lo, ln
        # 층화 후에도 양쪽 모두에서 방향이 유지되는가
        keep = (ro and rn and ro["lift"] > 1.05 and rn["lift"] > 1.05)
        verdict = "채택" if keep else "층화 후 약화/소멸"
        (survivors if keep else collapsed).append(
            {**r, "lift_onc": lo, "lift_non": ln, "verdict": verdict})
        print(f"{r['flag']:24s} {r['clause']:12s} {r['lift']:9.2f} "
              f"{lo:9.2f} {ln:11.2f} {verdict:>14s}")

    n_tested = len([r for r in all_rows if r["clause"] in target_clauses])
    print(f"\n[룰 채택률 — 정직성 지표]")
    print(f"  검정한 (플래그×분자특이조항) 쌍: {n_tested}")
    print(f"  Bonferroni 유의 + 층화 통과: {len(survivors)}")
    print(f"  층화 후 무너진 것: {len(collapsed)}")
    print(f"  채택률: {len(survivors)}/{n_tested} = "
          f"{len(survivors) / n_tested:.1%}" if n_tested else "")

    # ── 사전 선언 기전 게이트 ─────────────────────────────────
    # 통계적 유의성만으로는 "골라 썼다"는 비판을 방어할 수 없다.
    # 결과를 보기 전에 선언한 기전 가설과 대조한다.
    sig_strat = {(r["flag"], r["clause"]) for r in survivors}
    sig_stats = {(r["flag"], r["clause"]) for r in all_rows
                 if r.get("sig_bonferroni") and r["lift"] > 1.0}
    buckets = {"confirmatory": [], "refuted": [], "exploratory": [],
               "no_mechanism_claim": [], "excluded_clause": [], "null": []}
    for r in all_rows:
        key = (r["flag"], r["clause"])
        kind = classify_pair(r["flag"], r["clause"],
                             key in sig_stats, key in sig_strat)
        r["mechanism_class"] = kind
        r["mechanism"] = mechanism_of(*key)
        buckets[kind].append(r)

    # 사전 선언했으나 검정에서 제외된(희소 조항 등) 쌍도 refuted 로 집계된다
    print("\n[사전 선언 기전 게이트]")
    print(f"  사전 선언한 (플래그→조항) 쌍: {len(PREREGISTERED)}")
    conf = sorted(buckets["confirmatory"], key=lambda r: -r["lift"])
    print(f"  ├ confirmatory (선언 + 통계 + 층화 통과): {len(conf)}  "
          f"→ 가치 주장에 사용")
    for r in conf:
        print(f"  │   {r['flag']:22s} → {r['clause']:11s} lift={r['lift']:.2f} "
              f"(종양 {r.get('lift_onc', float('nan')):.2f} / "
              f"비종양 {r.get('lift_non', float('nan')):.2f})")
    print(f"  ├ refuted (선언했으나 통과 실패): {len(buckets['refuted'])}  "
          f"→ 실패로 보고")
    for r in sorted(buckets["refuted"], key=lambda r: -r["lift"])[:14]:
        print(f"  │   {r['flag']:22s} → {r['clause']:11s} lift={r['lift']:.2f} "
              f"p={r['p_value']:.1e}")
    expl = sorted(buckets["exploratory"], key=lambda r: -r["lift"])
    print(f"  ├ exploratory (선언 안 했으나 유의): {len(expl)}  "
          f"→ 보고만, 기전 주장 안 함")
    for r in expl[:10]:
        print(f"  │   {r['flag']:22s} → {r['clause']:11s} lift={r['lift']:.2f}")
    print(f"  ├ 기전 주장 금지 플래그(PAINS) 관련: "
          f"{len(buckets['no_mechanism_claim'])}")
    print(f"  └ 관례적 조항으로 주장 제외(피임): "
          f"{len(buckets['excluded_clause'])}")

    pre_tested = len(conf) + len(buckets["refuted"])
    if pre_tested:
        print(f"\n  사전 선언 쌍의 확증률: {len(conf)}/{pre_tested} = "
              f"{len(conf) / pre_tested:.1%}")

    os.makedirs(args.out, exist_ok=True)
    payload = {
        "generated_from": "TrialBench (Nature Sci Data 2025, "
                          "github.com/ML2Health/ML2ClinicalTrials)",
        "n_unique_trials": ds["n_trials"],
        "n_analyzed": len(recs),
        "exclusions": ds["stats"],
        "herg_clogp_cut": HERG_CLOGP_CUT,
        "clause_classification": cls,
        "target_clauses": target_clauses,
        "flag_match_rates": {f: sum(1 for r in recs if r[f]) / len(recs)
                             for f in FLAG_NAMES},
        "flag_rationale": RATIONALE,
        "associations_all": all_rows,
        "associations_oncology": onc_rows,
        "associations_non_oncology": non_rows,
        "survivors": survivors,
        "collapsed": collapsed,
        "rule_adoption_rate": (len(survivors) / n_tested) if n_tested else None,
        "preregistered_pairs": {f"{k[0]}->{k[1]}": v
                                for k, v in PREREGISTERED.items()},
        "clause_caveats": CLAUSE_CAVEATS,
        "excluded_from_claims": sorted(EXCLUDED_FROM_CLAIMS),
        "no_mechanism_claim": NO_MECHANISM_CLAIM,
        "mechanism_gate": {k: [{"flag": r["flag"], "clause": r["clause"],
                                "lift": r["lift"], "p_value": r["p_value"],
                                "lift_onc": r.get("lift_onc"),
                                "lift_non": r.get("lift_non"),
                                "mechanism": r.get("mechanism")}
                               for r in v]
                           for k, v in buckets.items()},
        "confirmatory_rate": (len(conf) / pre_tested) if pre_tested else None,
    }
    path = os.path.join(args.out, "s2c_associations.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    print(f"\n결과 저장: {path}")


if __name__ == "__main__":
    main()
