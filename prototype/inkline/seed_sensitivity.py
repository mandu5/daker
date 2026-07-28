"""E6 — 분할 시드 민감도.

    python3 prototype/inkline/seed_sensitivity.py [--seeds 4]

왜 필요한가
    학습/평가 분할은 NCT ID 해시 기반 결정론이고 시드를 코드에 고정해 두었다.
    재현성에는 좋지만, 심사위원 입장에서는 이런 질문이 남는다 —
    **"그 시드 하나에서만 좋은 것 아닌가?"**

    시드를 바꾸면 분할이 완전히 달라진다(같은 시험이 train↔test 로 이동).
    헤드라인 지표가 시드에 따라 크게 흔들리면 그 수치는 신뢰할 수 없다.
    흔들리지 않는다면 그 사실을 숫자로 보일 수 있다.

무엇을 재는가
    시드별로 B-TPL 과 INKLINE+ 를 다시 적합하고, 커버리지 5%에서
    조항별 ΔP 와 확증군/미확증군 평균을 다시 낸다.
    **평가 분할이 매번 바뀌므로 모델도 매번 새로 학습된다.**

주의
    이 실험은 시드를 바꿔 여러 번 재는 것이지, 좋은 시드를 고르는 것이
    아니다. **본 제안서의 보고 수치는 처음 고정한 시드 하나에서 나온 것이며
    바꾸지 않는다.** 이 스크립트는 그 수치의 안정성만 보고한다.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "trialbench"))

import model as M  # noqa: E402
from load import DEFAULT_ROOT, build_dataset  # noqa: E402

OUT = os.path.join(ROOT, "results", "e6_seed_sensitivity.json")
ASSOC = os.path.join(ROOT, "results", "s2c_associations.json")
COV = 0.05


def confirmed_map():
    d = json.load(open(ASSOC, encoding="utf-8"))
    out = {}
    for r in d["mechanism_gate"]["confirmatory"]:
        out.setdefault(r["clause"], []).append(r["flag"])
    return out


def run_one(recs, seed, conf):
    """시드 하나에 대해 전체 적합·평가를 다시 수행."""
    orig = M.SPLIT_SEED
    M.SPLIT_SEED = seed
    try:
        tr = [r for r in recs if M.split_of(r["nctid"]) == "train"]
        te = [r for r in recs if M.split_of(r["nctid"]) == "test"]
        tpl = M.TemplateBaseline().fit(tr, M.TARGET_CLAUSES)
        out = {}
        for c in M.TARGET_CLAUSES:
            y = np.array([r[c] for r in te])
            if y.sum() == 0:
                continue
            p_tpl = tpl.predict(te, c)
            m = M.ClauseModel(c, continuous=True).fit(tr)
            p_ink = m.predict(te) if m.model else p_tpl
            a, _ = M.precision_at_coverage(y, p_tpl, COV)
            b, _ = M.precision_at_coverage(y, p_ink, COV)
            out[c] = b - a
        return out, len(tr), len(te)
    finally:
        M.SPLIT_SEED = orig


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=4)
    args = ap.parse_args()

    ds = build_dataset(DEFAULT_ROOT,
                       cache=os.path.expanduser("~/.cache/trialbench/ds.pkl"))
    recs = ds["records"]
    conf = confirmed_map()
    confirmed = sorted(conf)

    seeds = ["inkline-2026"] + [f"inkline-seed-{i}" for i in range(1, args.seeds)]
    rows, meta = {}, {}
    for s in seeds:
        print(f"  시드 {s} …", file=sys.stderr)
        dp, ntr, nte = run_one(recs, s, conf)
        rows[s] = dp
        meta[s] = {"n_train": ntr, "n_test": nte}

    clauses = sorted({c for d in rows.values() for c in d})
    print("\nE6 — 분할 시드 민감도 (커버리지 5% ΔP)")
    print("=" * 74)
    hdr = "".join(f"{s.replace('inkline-','')[:11]:>12s}" for s in seeds)
    print(f"{'조항':14s}{hdr}{'평균':>10s}{'sd':>9s}")
    per = {}
    for c in clauses:
        vs = [rows[s].get(c) for s in seeds]
        got = [v for v in vs if v is not None]
        cells = "".join(f"{(v if v is not None else float('nan')):+12.4f}"
                        for v in vs)
        sd = statistics.pstdev(got) if len(got) > 1 else 0.0
        per[c] = {"values": vs, "mean": statistics.mean(got), "sd": sd}
        print(f"{c:14s}{cells}{statistics.mean(got):+10.4f}{sd:9.4f}")

    grp = {}
    for s in seeds:
        cv = [rows[s][c] for c in confirmed if c in rows[s]]
        ev = [rows[s][c] for c in rows[s] if c not in confirmed]
        grp[s] = {"confirmed": statistics.mean(cv) if cv else None,
                  "exploratory": statistics.mean(ev) if ev else None,
                  "gap": (statistics.mean(cv) - statistics.mean(ev))
                         if cv and ev else None}
    print()
    print(f"{'확증군 평균':14s}" + "".join(
        f"{grp[s]['confirmed']:+12.4f}" for s in seeds))
    print(f"{'미확증군 평균':14s}" + "".join(
        f"{grp[s]['exploratory']:+12.4f}" for s in seeds))
    print(f"{'격차':14s}" + "".join(f"{grp[s]['gap']:+12.4f}" for s in seeds))

    gaps = [grp[s]["gap"] for s in seeds]
    signs = sum(1 for g in gaps if g > 0)
    payload = {
        "coverage": COV, "seeds": seeds, "meta": meta,
        "per_clause": per, "group_means": grp,
        "gap_mean": statistics.mean(gaps),
        "gap_sd": statistics.pstdev(gaps),
        "gap_positive_in": signs, "n_seeds": len(seeds),
        "note": "보고 수치는 최초 고정 시드(inkline-2026) 하나에서 나온 것이며 "
                "바꾸지 않는다. 이 실험은 그 수치의 안정성만 보고한다.",
        "verdict": (
            f"확증군−미확증군 격차가 시드 {len(seeds)}개 중 {signs}개에서 양수, "
            f"평균 {statistics.mean(gaps):+.4f} · sd {statistics.pstdev(gaps):.4f}. "
            + ("방향은 시드에 걸쳐 일관되나 크기가 작아 "
               "여전히 유의성을 주장하지 않는다."
               if signs == len(seeds) else
               "**시드에 따라 부호가 바뀐다 — 격차 주장을 하면 안 된다.**")),
    }
    json.dump(payload, open(OUT, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"\n판정: {payload['verdict']}")
    print(f"결과 저장: {OUT}")


if __name__ == "__main__":
    main()
