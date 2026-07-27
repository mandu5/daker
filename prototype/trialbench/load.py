"""TrialBench 적재 · 중복 제거 · 조항 라벨링.

TrialBench 는 8개 태스크 × 상(phase)별로 분할된 CSV 를 제공하는데,
**같은 임상시험이 여러 태스크에 중복 등장한다** (예: mortality-event-prediction 과
serious-adverse-event-forecasting 은 상별 행 수가 완전히 일치한다).
중복을 제거하지 않고 합치면 표본이 부풀려지고 p값이 과대평가된다.

식별자는 CSV 의 **이름 없는 첫 컬럼**(헤더가 빈 문자열)에 담긴 NCT ID 다.

조항 라벨
    임상시험의 선정·제외기준 원문(`eligibility/criteria/textblock`)에
    특정 유형의 조항이 존재하는지를 정규식으로 판정한다. 이는 v1 라벨러이며
    사람 검토로 신뢰도(Cohen's κ)를 별도 측정해야 한다 — 그 전까지는
    라벨 자체가 근사임을 명시한다.
"""

from __future__ import annotations

import csv
import ast
import glob
import os
import pickle
import re
import sys

csv.field_size_limit(10 ** 9)

DEFAULT_ROOT = os.path.expanduser("~/.cache/trialbench/Trialbench/data")

ID_COL = ""                       # 헤더가 빈 문자열인 첫 컬럼 = NCT ID
SMILES_COL = "smiless"
CRIT_COL = "eligibility/criteria/textblock"
COND_COL = "condition"
PHASE_COL = "phase"

# ── 조항 유형 라벨러 v1 ────────────────────────────────────────
# 각 항목: (조항 코드, 설명, 정규식)
CLAUSE_PATTERNS = {
    "QT_ECG": (
        "QT 간격 임계·연장 관련 제외기준",
        # 라벨러 감사(2026-07-27)에서 발견: 기존 패턴은 "12-lead ECG will be
        # performed" 같은 **검사 시행 절차 나열**까지 조항으로 잡았다.
        # 양성의 61.2%가 실제 QT 임계가 아니었다. 임계·연장 맥락을 요구한다.
        r"QTc?[FB]?\s*[<>≤≥]"                       # QTc > 450 형태
        r"|QTc?[FB]?\s*(interval)?\s*(of\s*)?(>|<|greater|less|exceed|above|below)"
        r"|prolong\w*\s+(the\s+)?QT|QT\w*\s+prolong"
        r"|long QT|torsade|congenital QT"
        r"|(abnormal|clinically significant)\s+(12-lead\s+)?(ECG|EKG|electrocardiogram)",
    ),
    "HEPATIC": (
        "간기능 수치 기반 제외기준",
        r"\bALTs?\b|\bASTs?\b|aminotransferase|transaminase|bilirubin"
        r"|hepatic (impairment|dysfunction|function|disease)|Child-Pugh",
    ),
    "RENAL": (
        "신기능 기반 제외기준",
        r"creatinine clearance|\bCrCl\b|\beGFR\b|glomerular filtration"
        r"|renal (impairment|dysfunction|insufficiency)|dialysis",
    ),
    "CYP_DDI": (
        "CYP 효소·수송체 매개 약물상호작용 조항",
        # 라벨러 감사에서 발견: grapefruit 이 이 패턴과 FOOD_EFFECT 양쪽에 있어
        # 같은 신호를 두 조항으로 세고 있었다(음식효과 양성의 97.2%가 중복).
        # grapefruit 은 FOOD_EFFECT 로만 세고, 여기서는 효소·수송체 언급을 요구한다.
        r"CYP\s?-?\s?3A|CYP\s?-?\s?2D6|CYP\s?-?\s?2C|CYP\s?-?\s?1A2|cytochrome"
        r"|strong (inhibitor|inducer)|P-?glycoprotein|\bP-?gp\b|OATP|BCRP",
    ),
    "QT_DRUG": (
        "QT 연장 약물 병용 금지 조항",
        r"(drugs?|medications?|agents?)[^.]{0,60}(prolong|prolonging)[^.]{0,20}QT"
        r"|QT[- ]prolonging",
    ),
    "CONTRACEPT": (
        "피임 요구 조항",
        r"contracept|highly effective method|barrier method",
    ),
    "PHOTO": (
        "광과민성 관련 조항",
        r"photosensit|ultraviolet|\bUV light\b|sun exposure|tanning",
    ),
    "HEMATO": (
        "혈액학적 수치 기반 제외기준",
        r"absolute neutrophil|\bANC\b|platelet count|h(a)?emoglobin"
        r"|neutropeni|thrombocytopeni",
    ),
    # ── 2차 확장 (2026-07-26 추가) ────────────────────────────
    # 기전 가설을 mechanism.py 에 **먼저 선언한 뒤** 이 패턴을 추가했다.
    # 결과를 보고 조항을 고르지 않기 위한 순서다.
    "GASTRIC_PH": (
        "위산분비억제제(PPI·H2 차단제)·제산제 병용 제한 조항",
        r"proton pump inhibitor|\bPPIs?\b|H2[- ]?(receptor )?antagonist"
        r"|antacid|omeprazole|esomeprazole|lansoprazole|pantoprazole"
        r"|ranitidine|famotidine|gastric pH",
    ),
    "HYPERSENS": (
        "특정 약물계열 과민반응 병력 제외기준",
        r"hypersensitivity|allerg(y|ic) (to|reaction)|anaphylax"
        r"|known allergy|sulfa allergy",
    ),
    "FOOD_EFFECT": (
        "음식·자몽 등 섭취 제한 조항",
        r"grapefruit|seville orange|high[- ]fat meal|fasted state|with food"
        r"|food effect|empty stomach",
    ),
    "GI_IRRITATION": (
        "위장관 궤양·출혈 병력 제외기준",
        r"peptic ulcer|gastrointestinal (bleed|h(a)?emorrhage|ulcer)"
        r"|gastric ulcer|duodenal ulcer|\bGI bleed",
    ),
    "SEIZURE": (
        "경련·발작 병력 제외기준",
        r"seizure|epilep|convulsion",
    ),
    "THYROID": (
        "갑상선 기능 관련 조항",
        r"thyroid|\bTSH\b|hypothyroid|hyperthyroid|free T4",
    ),
}

CLAUSE_RE = {k: re.compile(v[1], re.I) for k, v in CLAUSE_PATTERNS.items()}

ONCOLOGY_RE = re.compile(
    r"cancer|carcinom|tumou?r|neoplas|lymphom|leuk[ae]mi|myelom|sarcom|melanom"
    r"|glioma|glioblastom|mesotheliom|myelodysplas", re.I)


def _read_rows(path):
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            yield row


def collect_trials(root=DEFAULT_ROOT, verbose=True):
    """전 태스크·전 상의 *_x.csv 를 훑어 NCT ID 기준으로 중복 제거한 시험 목록을 만든다.

    Returns: dict[nctid] -> {smiles_raw, criteria, condition, phase, sources:set}
    """
    files = sorted(glob.glob(os.path.join(root, "**", "*_x.csv"), recursive=True))
    if not files:
        raise SystemExit(f"데이터가 없다: {root}\n먼저 prototype/trialbench/fetch.sh 실행")

    trials = {}
    skipped_files = []
    for path in files:
        rel = os.path.relpath(path, root)
        with open(path, newline="", encoding="utf-8", errors="replace") as f:
            head = csv.DictReader(f)
            cols = head.fieldnames or []
            if SMILES_COL not in cols or CRIT_COL not in cols or ID_COL not in cols:
                skipped_files.append(rel)
                continue
        n_new = 0
        for row in _read_rows(path):
            nct = (row.get(ID_COL) or "").strip()
            if not nct.startswith("NCT"):
                continue
            if nct in trials:
                trials[nct]["sources"].add(rel)
                continue
            trials[nct] = {
                "nctid": nct,
                "smiles_raw": (row.get(SMILES_COL) or "").strip(),
                "criteria": row.get(CRIT_COL) or "",
                "condition": str(row.get(COND_COL) or ""),
                "phase": str(row.get(PHASE_COL) or ""),
                "sources": {rel},
            }
            n_new += 1
        if verbose:
            print(f"  {rel:60s} 신규 {n_new:6d}  누적 {len(trials):6d}", file=sys.stderr)
    if verbose and skipped_files:
        print(f"  (SMILES/기준텍스트 없어 제외한 파일 {len(skipped_files)}개: "
              f"{', '.join(skipped_files)})", file=sys.stderr)
    return trials


def parse_smiles(raw):
    """`smiless` 는 SMILES 문자열의 리스트 리터럴. 가장 큰 분자를 대표로 삼는다."""
    from rdkit import Chem
    if raw in ("", "[]", "nan", "None"):
        return None
    try:
        lst = ast.literal_eval(raw)
    except Exception:
        return None
    if not isinstance(lst, list) or not lst:
        return None
    best = None
    for smi in lst:
        if not isinstance(smi, str):
            continue
        m = Chem.MolFromSmiles(smi)
        if m is None:
            continue
        if best is None or m.GetNumHeavyAtoms() > best.GetNumHeavyAtoms():
            best = m
    return best


def label_clauses(criteria_text):
    return {k: (1 if rx.search(criteria_text) else 0) for k, rx in CLAUSE_RE.items()}


def build_dataset(root=DEFAULT_ROOT, cache=None, min_criteria_len=50,
                  max_mw=900, min_heavy=8, verbose=True):
    """중복 제거 → SMILES 파싱 → 조항 라벨링까지 마친 레코드 리스트를 반환."""
    if cache and os.path.exists(cache):
        with open(cache, "rb") as f:
            return pickle.load(f)

    from rdkit import RDLogger, Chem
    from rdkit.Chem import Descriptors, Crippen, rdMolDescriptors
    RDLogger.DisableLog("rdApp.*")

    if verbose:
        print("[1/3] CSV 적재 및 NCT ID 중복 제거", file=sys.stderr)
    trials = collect_trials(root, verbose=verbose)
    if verbose:
        print(f"  고유 임상시험 {len(trials):,}건", file=sys.stderr)

    if verbose:
        print("[2/3] SMILES 파싱 및 물성 계산", file=sys.stderr)
    recs = []
    stats = {"no_smiles": 0, "unparsable": 0, "short_criteria": 0, "filtered": 0}
    for t in trials.values():
        if len(t["criteria"]) < min_criteria_len:
            stats["short_criteria"] += 1
            continue
        if not t["smiles_raw"] or t["smiles_raw"] in ("[]", "nan"):
            stats["no_smiles"] += 1
            continue
        mol = parse_smiles(t["smiles_raw"])
        if mol is None:
            stats["unparsable"] += 1
            continue
        mw = Descriptors.MolWt(mol)
        if mw > max_mw or mol.GetNumHeavyAtoms() < min_heavy:
            stats["filtered"] += 1
            continue
        rec = {
            "nctid": t["nctid"],
            "phase": t["phase"],
            "condition": t["condition"],
            "smiles": Chem.MolToSmiles(mol),
            "mw": mw,
            "clogp": Crippen.MolLogP(mol),
            "tpsa": rdMolDescriptors.CalcTPSA(mol),
            "hbd": rdMolDescriptors.CalcNumHBD(mol),
            "oncology": bool(ONCOLOGY_RE.search(t["condition"])),
            "n_sources": len(t["sources"]),
        }
        rec.update(label_clauses(t["criteria"]))
        rec["_mol"] = mol
        recs.append(rec)

    if verbose:
        print(f"  사용 가능 {len(recs):,}건 / 제외: {stats}", file=sys.stderr)
        print("[3/3] 구조 플래그 계산", file=sys.stderr)

    from flags import compute_flags
    for r in recs:
        r.update(compute_flags(r["_mol"], r["clogp"]))
        del r["_mol"]

    out = {"records": recs, "stats": stats, "n_trials": len(trials)}
    if cache:
        os.makedirs(os.path.dirname(os.path.abspath(cache)), exist_ok=True)
        with open(cache, "wb") as f:
            pickle.dump(out, f)
    return out


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ROOT
    d = build_dataset(root)
    print(f"\n고유 시험 {d['n_trials']:,} → 분석 가능 {len(d['records']):,}")
