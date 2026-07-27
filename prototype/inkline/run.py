"""먹줄 엔드투엔드 실행.

    python3 prototype/inkline/run.py --smiles "CC(=O)Oc1ccccc1C(=O)O" \
        --phase "Phase 1" --indication "solid tumor" --noael 25

같은 시드로 3회 실행하면 감사 DAG 해시가 일치해야 한다(E4 재현성 지표).
LLM 호출 없이 완결 동작한다.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "trialbench"))

from agents import (  # noqa: E402
    Actuary, Adversary, CLAUSE_KO, Ledger, Marker, Scribe, sha,
)
from evaluate import confirmed_map  # noqa: E402
from load import DEFAULT_ROOT, ONCOLOGY_RE, build_dataset  # noqa: E402
from model import (  # noqa: E402
    TARGET_CLAUSES, ApplicabilityDomain, ClauseModel, TemplateBaseline,
    split_of,
)

CACHE = os.path.expanduser("~/.cache/trialbench/inkline_fit.pkl")


def fit_or_load(verbose=True):
    """모델 적합 (캐시). 학습 분할만 사용한다."""
    import pickle
    if os.path.exists(CACHE):
        with open(CACHE, "rb") as f:
            return pickle.load(f)
    ds = build_dataset(DEFAULT_ROOT,
                       cache=os.path.expanduser("~/.cache/trialbench/ds.pkl"),
                       verbose=verbose)
    train = [r for r in ds["records"] if split_of(r["nctid"]) == "train"]
    tpl = TemplateBaseline().fit(train, TARGET_CLAUSES)
    models = {c: ClauseModel(c, continuous=True).fit(train)
              for c in TARGET_CLAUSES}
    ad = ApplicabilityDomain().fit(train)
    obj = {"tpl": tpl, "models": models, "ad": ad, "n_train": len(train),
           "confirmed": confirmed_map()}
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "wb") as f:
        pickle.dump(obj, f)
    return obj


def run_one(smiles, phase, indication, noael=None, species="rat",
            modality="small_molecule", n_enroll=60, fit=None, quiet=False):
    fit = fit or fit_or_load(verbose=not quiet)
    trace = []
    context = {"phase": phase, "indication": indication,
               "oncology": bool(ONCOLOGY_RE.search(indication or ""))}

    marker = Marker(ad=fit["ad"])
    scribe = Scribe(fit["tpl"], fit["models"], confirmed=fit["confirmed"])
    actuary = Actuary()
    adversary = Adversary(fit["tpl"], fit["models"], confirmed=fit["confirmed"])
    ledger = Ledger()

    risks, props = marker.run(smiles, modality=modality, trace=trace)
    if risks is None:
        rec = ledger.seal("aborted", [], trace,
                          {"context": context, "reason": props})
        return rec

    clauses = scribe.run(risks, props, context, trace=trace)

    dose = None
    if noael is not None:
        dose = actuary.mrsd(noael, species=species, trace=trace)
    power = actuary.power_gate(n_enroll, 0.10, 0.25, trace=trace)

    for c in clauses:
        adversary.r1_evidence(c, trace=trace)
        adversary.r2_attribution(c, props, context, trace=trace)

    ledger.decide(clauses, trace=trace)
    feas = adversary.r3_feasibility(clauses, actuary, trace=trace)

    meta = {
        "context": context,
        "molecule": {k: props[k] for k in ("smiles", "mw", "clogp", "tpsa", "hbd")},
        "ad": props["ad"],
        "risks": [{"risk_id": r.risk_id, "flag": r.flag} for r in risks],
        "dose": dose, "power_gate": power, "feasibility": feas,
        "n_train": fit["n_train"],
        "confirmed_triggers": fit["confirmed"],
        "tool_versions": _versions(),
        "seed": 20260807,
    }
    return ledger.seal(sha([smiles, phase, indication, noael])[:12],
                       clauses, trace, meta)


def _versions():
    import rdkit
    import sklearn
    import scipy
    return {"rdkit": rdkit.__version__, "scikit-learn": sklearn.__version__,
            "scipy": scipy.__version__, "python": sys.version.split()[0]}


def render(rec):
    m = rec["meta"]
    print("=" * 74)
    print(f"먹줄(INKLINE) 실행 보고서   run_id={rec['run_id']}")
    print("=" * 74)
    if "molecule" not in m:
        # MARKER 단계에서 범위 밖으로 판정되어 조항을 하나도 기안하지 않은 경우.
        # 이것도 정상 산출물이다 — 시스템이 스스로 말하지 않기로 한 결과다.
        print(f"맥락   {m['context']['phase']} · {m['context']['indication']}")
        print(f"판정   조항 발행 없음 — {m.get('reason')}")
        print(f"\n감사 DAG 해시  {rec['dag_hash']}")
        print("\n── 실행 추적 " + "─" * 60)
        for t in rec["trace"]:
            print(f"[{t['seq']:2d}] {t['agent']:10s} {t['step']:16s} {t['detail']}")
        return
    mol = m["molecule"]
    print(f"분자   {mol['smiles']}")
    print(f"       MW {mol['mw']:.1f} · cLogP {mol['clogp']:.2f} · "
          f"TPSA {mol['tpsa']:.1f} · HBD {mol['hbd']}  |  AD {m['ad']:.2f}")
    print(f"맥락   {m['context']['phase']} · {m['context']['indication']} "
          f"({'종양' if m['context']['oncology'] else '비종양'})")
    print(f"구조경보 {len(m['risks'])}건: {[r['flag'] for r in m['risks']]}")
    if m.get("dose"):
        d = m["dose"]
        print(f"개시용량 MRSD {d['mrsd_total_mg']:.2f} mg/60kg "
              f"(NOAEL {d['noael_mg_kg']} mg/kg {d['species']} → HED "
              f"{d['hed_mg_kg']:.3f} → SF{d['safety_factor']:.0f})")
    pg = m["power_gate"]
    print(f"검정력 power={pg['power']:.2f}"
          + (f" · 부족 → 필요 N≈{pg['required_n']}" if pg.get("required_n")
             else " · 통과"))

    print("\n── 조항 판정 " + "─" * 60)
    hdr = (f"{'조항':10s} {'분류':14s} {'p_base':>7s} {'p_hat':>7s} "
           f"{'Δ':>7s} {'Δ*':>8s} {'σ':>6s} {'T':>7s}  {'판정':10s} 사유")
    print(hdr)
    ICON = {"advance": "발행", "escalate": "사람검토", "abstain": "기권"}
    for c in rec["clauses"]:
        ds = "  —" if c["delta_star"] is None else f"{c['delta_star']:+8.4f}"
        tr = "  —" if c["trust"] is None else f"{c['trust']:7.2f}"
        print(f"{c['clause_type']:10s} {c['clause_class']:14s} "
              f"{c['p_base']:7.3f} {c['p_hat']:7.3f} {c['delta']:+7.4f} {ds} "
              f"{c['sigma']:6.3f} {tr}  {ICON[c['decision']]:10s} {c['reason_code']}")

    n = {k: sum(1 for c in rec["clauses"] if c["decision"] == k)
         for k in ("advance", "escalate", "abstain")}
    print(f"\n요약   발행 {n['advance']} · 사람검토 {n['escalate']} · "
          f"기권 {n['abstain']}  (기권율 "
          f"{n['abstain']/max(len(rec['clauses']),1):.0%})")
    print(f"모집   등록가능 인구 {m['feasibility']['pool_reduction']:.1%} 감소")
    print(f"\n감사 DAG 해시  {rec['dag_hash']}")
    print(f"도구 버전       {m['tool_versions']}")

    print("\n── 실행 추적 " + "─" * 60)
    for t in rec["trace"]:
        print(f"[{t['seq']:2d}] {t['agent']:10s} {t['step']:16s} {t['detail']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smiles", required=True)
    ap.add_argument("--phase", default="Phase 1")
    ap.add_argument("--indication", default="solid tumor")
    ap.add_argument("--noael", type=float, default=None)
    ap.add_argument("--species", default="rat")
    ap.add_argument("--modality", default="small_molecule")
    ap.add_argument("--n-enroll", type=int, default=60)
    ap.add_argument("--json", default=None, help="결과 JSON 저장 경로")
    ap.add_argument("--repeat", type=int, default=1,
                    help="N회 반복 실행해 DAG 해시 일치 확인 (E4)")
    args = ap.parse_args()

    fit = fit_or_load()
    hashes = []
    rec = None
    for i in range(args.repeat):
        t0 = time.time()
        rec = run_one(args.smiles, args.phase, args.indication, args.noael,
                      args.species, args.modality, args.n_enroll, fit=fit,
                      quiet=True)
        hashes.append(rec["dag_hash"])
        if i == 0:
            render(rec)
        print(f"\n[{i+1}/{args.repeat}] {time.time()-t0:.2f}s  "
              f"dag={rec['dag_hash'][:16]}")
    if args.repeat > 1:
        ok = len(set(hashes)) == 1
        print(f"\nE4 재현성(DPR): {args.repeat}회 실행 해시 "
              f"{'일치 ✓' if ok else '불일치 ✗'}")
    if args.json:
        json.dump(rec, open(args.json, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1, default=str)
        print(f"저장: {args.json}")


if __name__ == "__main__":
    main()
