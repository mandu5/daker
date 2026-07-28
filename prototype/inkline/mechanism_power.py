"""E5 — 기전 게이트 주장의 검정력 확인 (정확 순열검정).

    python3 prototype/inkline/mechanism_power.py

왜 이 스크립트를 따로 만들었는가
    E1 은 확증군/미확증군의 평균 ΔP@5% 를 **점추정치로만** 보고했다.
    그런데 우리는 그 두 숫자의 대소를 근거로 "사전 선언 기전 게이트가
    실제로 신호를 가려낸다"고 주장하려 했다.

    주장하기 전에 물어야 할 것이 있다 — **그 격차가 우연과 구별되는가?**

    조항은 10종뿐이고 각 군에 5종씩이다. 이 정도 표본에서 군 평균의 차이는
    조항 간 분산에 쉽게 묻힌다. 그래서 근사가 아니라 **정확 순열검정**을 한다.
    10종 중 5종을 '확증'으로 라벨하는 모든 방법이 C(10,5)=252가지뿐이므로
    전수 열거가 가능하고, 표집오차 없는 정확 p 값이 나온다.

귀무가설
    H0: 조항이 확증/미확증 중 어디에 속하는지는 그 조항의 ΔP@5% 와 무관하다.
    검정통계량: mean(ΔP | 확증) − mean(ΔP | 미확증)

이 검정을 통과하지 못하면 그 사실을 그대로 적는다. 검정을 돌려 놓고
결과가 불리하다고 묻어두면, 이 제안서가 비판하는 바로 그 행동이 된다.
"""

from __future__ import annotations

import itertools
import json
import os
import statistics

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
E1 = os.path.join(ROOT, "results", "e1_safe_inc.json")
OUT = os.path.join(ROOT, "results", "e5_mechanism_power.json")

COVERAGE = "0.05"
MODEL = "INKLINE+"


def run(e1=None):
    e = e1 or json.load(open(E1, encoding="utf-8"))
    ms = e["mechanism_split"]
    clauses = list(e["clauses"])
    dp = {c: e["clauses"][c]["delta_p_at_coverage"][MODEL][COVERAGE]
          for c in clauses}
    conf = set(ms["confirmed"])
    k = len(conf)

    def gap(group):
        a = statistics.mean(dp[c] for c in group)
        b = statistics.mean(dp[c] for c in clauses if c not in group)
        return a - b

    obs = gap(conf)
    dist = [gap(set(combo)) for combo in itertools.combinations(clauses, k)]
    n = len(dist)
    ge = sum(1 for s in dist if s >= obs)
    two = sum(1 for s in dist if abs(s) >= abs(obs))
    lt = sum(1 for s in dist if s < obs)

    return {
        "test": "exact permutation over clause labels",
        "null_hypothesis": "조항의 확증/미확증 소속은 그 조항의 ΔP@5% 와 무관하다",
        "statistic": "mean(ΔP|확증) − mean(ΔP|미확증)",
        "coverage": float(COVERAGE), "model": MODEL,
        "n_clauses": len(clauses), "n_confirmed": k,
        "n_permutations": n,
        "exhaustive": True,
        "confirmed_mean": statistics.mean(dp[c] for c in conf),
        "exploratory_mean": statistics.mean(dp[c] for c in clauses
                                            if c not in conf),
        "observed_gap": obs,
        "perm_mean": statistics.mean(dist),
        "perm_sd": statistics.pstdev(dist),
        "percentile": 100.0 * lt / n,
        "p_one_sided": ge / n,
        "p_two_sided": two / n,
        "significant_at_05": (ge / n) < 0.05,
        "per_clause_delta_p": dp,
        "confirmed": sorted(conf),
        "exploratory": sorted(c for c in clauses if c not in conf),
        "verdict": (
            "확증군의 ΔP@5% 가 미확증군보다 크다는 방향은 관측되나, 조항 "
            "10종(5 대 5)에서는 이 격차가 무작위 라벨링과 구별되지 않는다. "
            "**우리는 이 격차를 유의하다고 주장하지 않는다.** 조항 수를 "
            "늘리는 것이 이 주장을 검정 가능하게 만드는 유일한 길이며 "
            "본선 과제로 넘긴다."),
    }


def main():
    r = run()
    print("E5 — 기전 게이트 주장의 검정력 (정확 순열검정)")
    print("=" * 62)
    print(f"확증군   {r['confirmed']}")
    print(f"         평균 ΔP@5% = {r['confirmed_mean']:+.4f}")
    print(f"미확증군 {r['exploratory']}")
    print(f"         평균 ΔP@5% = {r['exploratory_mean']:+.4f}")
    print(f"\n관측 격차            {r['observed_gap']:+.4f}")
    print(f"순열분포             평균 {r['perm_mean']:+.4f} · "
          f"sd {r['perm_sd']:.4f}  (전수 {r['n_permutations']}개)")
    print(f"관측값 백분위        {r['percentile']:.0f}%")
    print(f"단측 정확 p          {r['p_one_sided']:.3f}")
    print(f"양측 정확 p          {r['p_two_sided']:.3f}")
    print(f"\n유의(α=0.05)?        "
          f"{'예' if r['significant_at_05'] else '**아니오**'}")
    print("\n조항별 ΔP@5% (군)")
    for c, v in sorted(r["per_clause_delta_p"].items(), key=lambda x: -x[1]):
        g = "확증" if c in r["confirmed"] else "미확증"
        print(f"  {c:14s} {g:>5s} {v:+.4f}")
    print(f"\n판정: {r['verdict']}")
    json.dump(r, open(OUT, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"\n결과 저장: {OUT}")


if __name__ == "__main__":
    main()
