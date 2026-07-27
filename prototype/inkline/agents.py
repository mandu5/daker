"""먹줄(INKLINE) 5-에이전트 파이프라인.

    ① MARKER    구조 → 리스크 플래그 (+ σ 불확실성, AD 적용범위)
    ② SCRIBE    리스크 × 맥락 → 조항 후보 (+ 템플릿 기저확률, 증분 Δ)
    ③ ACTUARY   용량·검정력·모집 게이트
    ④ ADVERSARY 3중 반증 (R1 근거 / R2 Δ* 구조귀속 / R3 실행가능성)
    ⑤ LEDGER    선택적 발행 · append-only 원장 · 감사 DAG

설계 원칙
    수치와 판정은 전부 결정론 도구(RDKit·scikit-learn·scipy)가 낸다.
    LLM 은 자유문 → 구조화 추출, 조항 간 모순 탐지, 상충 서술에만 관여하며
    이 모듈은 LLM 없이 완결 동작한다(오프라인 실행 가능).

    모든 조항은 4-튜플이 채워져야만 발행된다:
        (근거, 유발 리스크, 봉인된 반증 조건, 신뢰도)
    하나라도 비면 발행이 거부된다.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "trialbench"))

from flags import (  # noqa: E402
    _COMPILED, FLAG_NAMES, RATIONALE, SMARTS, compute_flags,
)
from mechanism import PREREGISTERED, mechanism_of  # noqa: E402
from model import (  # noqa: E402
    SAFETY_CLAUSES, TARGET_CLAUSES, ApplicabilityDomain, ClauseModel,
    TemplateBaseline, context_key, flags_for, phase_group,
)

CLAUSE_KO = {
    "QT_ECG": "QT 간격·심전도 모니터링 및 제외기준",
    "CYP_DDI": "CYP 효소 매개 약물상호작용 병용 제한",
    "HEPATIC": "간기능 수치 기반 제외기준",
    "RENAL": "신기능 기반 제외기준",
    "HEMATO": "혈액학적 수치 기반 제외기준",
    "FOOD_EFFECT": "음식·자몽 등 섭취 제한 조항",
    "GI_IRRITATION": "위장관 궤양·출혈 병력 제외기준",
    "SEIZURE": "경련·발작 병력 제외기준",
    "GASTRIC_PH": "위산분비억제제·제산제 병용 제한 조항",
    "THYROID": "갑상선 기능 관련 조항",
}

# 부분구조로 정의된 경보만 decoy 절제가 가능하다.
# lipophilic(cLogP≥3.7)은 물성 그 자체이고, decoy 에서 물성을 매칭해야 하므로
# 원리적으로 절제할 수 없다. herg_pharmacophore 는 basic_amine 성분을 통해
# 간접 절제된다.
ABLATABLE_FLAGS = set(SMARTS.keys()) | {"herg_pharmacophore"}

# 신뢰도 임계. τ 는 홀드아웃에서 목표 정밀도를 만족하도록 보정한다(calibrate_tau).
TAU_DEFAULT = 1.0
TAU_LOW_DEFAULT = 0.4


def sha(obj):
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, ensure_ascii=False,
                   default=str).encode()).hexdigest()


# ══ 자료형 ═══════════════════════════════════════════════════
@dataclass
class Provenance:
    kind: str                       # computed | guideline | corpus | user_input
    detail: str
    url: str = ""
    span_id: str = ""
    verified_at: str = ""

    def is_verified(self):
        """computed 가 아니면 url 또는 span_id 가 반드시 있어야 한다."""
        return self.kind == "computed" or bool(self.url or self.span_id)


@dataclass
class RiskFlag:
    risk_id: str
    flag: str
    present: bool
    rationale: str
    sigma: float = 0.0
    ad: float = 0.0
    provenance: Provenance = None


@dataclass
class Clause:
    clause_id: str
    clause_type: str
    text: str
    clause_class: str               # template_baseline | molecule_specific
    trigger_risks: list = field(default_factory=list)
    p_base: float = 0.0
    p_hat: float = 0.0
    delta: float = 0.0
    delta_star: float = float("nan")
    sigma: float = 0.0
    ad: float = 0.0
    trust: float = float("nan")
    decision: str = "pending"       # advance | escalate | abstain
    reason_code: str = ""
    provenance: Provenance = None
    sealed_falsifier: dict = None
    mechanism: str = ""
    attribution_scope: dict = None
    tau: float = None
    tau_low: float = None
    issuance_sealed: bool = False

    def four_tuple_complete(self):
        return bool(self.provenance and self.provenance.is_verified()
                    and self.trigger_risks and self.sealed_falsifier
                    and self.trust == self.trust)   # NaN 아님


# ══ ① MARKER ════════════════════════════════════════════════
class Marker:
    """구조 → 리스크 플래그. 모달리티 범위 밖이면 스스로 기권한다."""

    def __init__(self, ad: ApplicabilityDomain = None):
        self.ad = ad

    def run(self, smiles, modality="small_molecule", trace=None):
        from rdkit import Chem, RDLogger
        from rdkit.Chem import Crippen, Descriptors, rdMolDescriptors
        RDLogger.DisableLog("rdApp.*")

        if modality != "small_molecule":
            _t(trace, "MARKER", "범위 외 선언",
               f"모달리티 {modality} — 소분자 구조 룰 비활성화, 기권")
            return None, {"out_of_scope": True, "modality": modality}

        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            _t(trace, "MARKER", "파싱 실패", "SMILES 해석 불가 → UNKNOWN(기각 아님)")
            return None, {"unparsable": True}

        props = {
            "smiles": Chem.MolToSmiles(mol),
            "mw": Descriptors.MolWt(mol),
            "clogp": Crippen.MolLogP(mol),
            "tpsa": rdMolDescriptors.CalcTPSA(mol),
            "hbd": rdMolDescriptors.CalcNumHBD(mol),
        }
        fl = compute_flags(mol, props["clogp"])
        ad_score = self.ad.score(props["smiles"]) if self.ad else 0.0

        risks = []
        for i, name in enumerate(FLAG_NAMES):
            if not fl.get(name):
                continue
            risks.append(RiskFlag(
                risk_id=f"R-{name}-{i:02d}", flag=name, present=True,
                rationale=RATIONALE.get(name, ""), ad=ad_score,
                provenance=Provenance(
                    kind="computed",
                    detail=f"RDKit SMARTS 매칭 · cLogP={props['clogp']:.2f}"),
            ))
        _t(trace, "MARKER", "구조 경보 산출",
           f"{len(risks)}건 검출: {[r.flag for r in risks]} · AD={ad_score:.2f}")
        props["flags"] = fl
        props["ad"] = ad_score
        return risks, props


# ══ ② SCRIBE ════════════════════════════════════════════════
class Scribe:
    """리스크 × 맥락 → 조항 후보. 템플릿 기저확률과 증분을 함께 붙인다."""

    def __init__(self, tpl: TemplateBaseline, models: dict, confirmed=None):
        self.tpl = tpl
        self.models = models        # clause -> ClauseModel
        # 조항을 촉발할 수 있는 구조 경보는 **사전 선언 기전 게이트에서
        # 확증된 것만**으로 제한한다. 기각된 가설(예: 카복실산→신기능,
        # lift 1.02 p=0.41)이 조항을 발행시키면 시스템이 자기 증거 기준을
        # 어기는 것이 된다. 모델 특징에는 사전 선언 전체가 들어가지만,
        # 발행 자격은 확증된 기전에만 준다.
        self.confirmed = confirmed or {}

    def triggers_for(self, clause_type):
        return self.confirmed.get(clause_type, [])

    def run(self, risks, props, context, trace=None):
        rec = _rec(props, context)
        out = []
        for i, ct in enumerate(TARGET_CLAUSES):
            m = self.models.get(ct)
            p_base = float(self.tpl.p(rec, ct))
            p_hat = float(m.predict([rec])[0]) if m and m.model else p_base
            sigma = float(m.sigma([rec])[0]) if m and m.model else 0.0
            allowed = self.triggers_for(ct)
            trig = [r.risk_id for r in risks if r.flag in allowed]
            mech = "; ".join(
                filter(None, (mechanism_of(r.flag, ct) for r in risks
                              if r.flag in allowed)))
            out.append(Clause(
                clause_id=f"C-{ct}-{i:02d}", clause_type=ct,
                text=CLAUSE_KO[ct],
                clause_class="molecule_specific" if trig else "template_baseline",
                trigger_risks=trig, p_base=p_base, p_hat=p_hat,
                delta=p_hat - p_base, sigma=sigma, ad=props.get("ad", 0.0),
                mechanism=mech,
                provenance=Provenance(
                    kind="computed",
                    detail=f"템플릿 기저 p_base={p_base:.3f} "
                           f"({context['phase']}, "
                           f"{'종양' if context['oncology'] else '비종양'}) · "
                           f"모델 p_hat={p_hat:.3f}"),
                sealed_falsifier={
                    "predicate": "delta_star<=0 OR evidence_span_absent "
                                 "OR kr_pool_reduction>0.4",
                    "recorded_at": "pre-judgment",
                },
            ))
        for c in out:
            c.sealed_falsifier["hash"] = sha(c.sealed_falsifier["predicate"]
                                             + c.clause_id)
        _t(trace, "SCRIBE", "조항 후보 기안",
           f"{len(out)}종 · 분자특이 {sum(1 for c in out if c.clause_class=='molecule_specific')}종 · "
           f"Δ 범위 [{min(c.delta for c in out):+.3f}, {max(c.delta for c in out):+.3f}]")
        return out


# ══ ③ ACTUARY ═══════════════════════════════════════════════
class Actuary:
    """용량 산출과 게이트. 판정할 수 없으면 판정하지 않는다."""

    HED_FACTOR = {"rat": 6.2, "mouse": 12.3, "dog": 1.8, "monkey": 3.1}

    def mrsd(self, noael_mg_kg, species="rat", safety_factor=10.0,
             human_kg=60.0, trace=None):
        f = self.HED_FACTOR.get(species, 6.2)
        hed = noael_mg_kg / f
        mrsd_mg_kg = hed / safety_factor
        total = mrsd_mg_kg * human_kg
        _t(trace, "ACTUARY", "개시용량 산출",
           f"NOAEL {noael_mg_kg} mg/kg ({species}) → HED {hed:.3f} "
           f"→ SF{safety_factor:.0f} → MRSD {mrsd_mg_kg:.4f} mg/kg "
           f"= {total:.2f} mg/60kg")
        return {"noael_mg_kg": noael_mg_kg, "species": species,
                "hed_factor": f, "hed_mg_kg": hed,
                "safety_factor": safety_factor,
                "mrsd_mg_kg": mrsd_mg_kg, "mrsd_total_mg": total,
                "basis": "FDA 2005 Estimating the Maximum Safe Starting Dose "
                         "(체표면적 환산)"}

    def power_gate(self, n, p0, p1, alpha=0.05, trace=None):
        """이 표본수로 요구 효과크기를 탐지할 수 있는가. 없으면 판정 보류."""
        from scipy.stats import norm
        if not (0 < p0 < 1 and 0 < p1 < 1) or n <= 0:
            return {"detectable": False, "power": 0.0, "required_n": None}
        pbar = (p0 + p1) / 2
        se = np.sqrt(2 * pbar * (1 - pbar) / n)
        if se == 0:
            return {"detectable": False, "power": 0.0, "required_n": None}
        z = norm.ppf(1 - alpha / 2)
        power = float(1 - norm.cdf(z - abs(p1 - p0) / se))
        req = None
        if power < 0.8:
            zb = norm.ppf(0.8)
            req = int(np.ceil(2 * pbar * (1 - pbar) * (z + zb) ** 2
                              / (p1 - p0) ** 2))
        _t(trace, "ACTUARY", "검정력 게이트",
           f"N={n}, {p0:.3f}→{p1:.3f} · power={power:.2f}"
           + (f" · 부족 → 필요 N≈{req}" if req else " · 통과"))
        return {"detectable": power >= 0.8, "power": power, "required_n": req}

    def recruitment_gate(self, clauses, prevalence_cost=None, trace=None):
        """제외기준이 등록 가능 인구를 얼마나 깎는가 (독립 가정 근사)."""
        prevalence_cost = prevalence_cost or {
            "QT_ECG": 0.08, "CYP_DDI": 0.22, "HEPATIC": 0.06,
            "RENAL": 0.07, "HEMATO": 0.09}
        keep = 1.0
        for c in clauses:
            if c.decision == "advance":
                keep *= (1 - prevalence_cost.get(c.clause_type, 0.05))
        red = 1 - keep
        _t(trace, "ACTUARY", "모집 게이트",
           f"발행 조항 기준 등록가능 인구 {red:.1%} 감소"
           + (" · 임계(40%) 초과 → 사람 승격" if red > 0.4 else " · 통과"))
        return {"pool_reduction": red, "exceeds": red > 0.4,
                "assumption": "제외기준 간 독립 가정. 실제로는 상관이 있어 "
                              "감소폭이 과대추정될 수 있음"}


# ══ ④ ADVERSARY ═════════════════════════════════════════════
class Adversary:
    """3중 반증. 시스템이 자기 산출물을 죽이는 자리."""

    def __init__(self, tpl, models, confirmed=None, n_decoy=12, seed=20260807):
        self.tpl, self.models = tpl, models
        self.confirmed = confirmed or {}
        self.n_decoy, self.seed = n_decoy, seed

    # ── R2: Δ* 구조 귀속 검정 ────────────────────────────────
    def make_decoys(self, smiles, target_flags):
        """물성은 최대한 보존하고 지목된 구조 경보만 파괴한 대조 분자.

        경보를 이루는 부분구조에 실제로 매칭된 원자만 골라 치환한다.
        무작위 원자를 바꾸면 경보가 죽지 않거나 분자가 과도하게 변형된다.
        """
        from rdkit import Chem
        from rdkit.Chem import Crippen, Descriptors, rdMolDescriptors
        base = Chem.MolFromSmiles(smiles)
        if base is None:
            return []
        rng = np.random.default_rng(self.seed)
        p0 = (Descriptors.MolWt(base), Crippen.MolLogP(base),
              rdMolDescriptors.CalcTPSA(base))

        # 지목된 경보에 매칭된 원자 집합 (치환 후보)
        hits = set()
        for f in target_flags:
            patt = _COMPILED.get(f)
            if patt is None:
                continue
            for m in base.GetSubstructMatches(patt):
                for idx in m:
                    if base.GetAtomWithIdx(idx).GetAtomicNum() != 6:
                        hits.add(idx)
        if not hits:
            return []
        hits = sorted(hits)

        # 경보를 죽이려면 매칭 원자를 모두 치환해야 하는 경우가 많아,
        # 그것만으로는 decoy 가 1개밖에 안 나온다. Δ* 의 평균이 불안정해지므로
        # 경보와 무관한 위치에 중립적 치환을 추가해 앙상블을 만든다.
        neutral = [a.GetIdx() for a in base.GetAtoms()
                   if a.GetIdx() not in set(hits)
                   and a.GetSymbol() in ("C", "N", "O", "F", "Cl")
                   and not a.GetIsAromatic()]
        SWAP = {6: [7, 8], 7: [6, 8], 8: [6, 7], 9: [17, 6], 17: [9, 6]}

        out, seen, tries = [], set(), 0
        max_tries = self.n_decoy * 60
        while len(out) < self.n_decoy and tries < max_tries:
            tries += 1
            # 매칭 원자의 부분집합을 치환. 작은 부분집합부터 시도한다.
            k = 1 + (tries % len(hits))
            pick = rng.choice(hits, size=min(k, len(hits)), replace=False)
            rw = Chem.RWMol(base)
            replaced = []
            for idx in sorted(int(i) for i in pick):
                a = rw.GetAtomWithIdx(idx)
                replaced.append(a.GetAtomicNum())
                a.SetAtomicNum(6)
                a.SetFormalCharge(0)
                a.SetNoImplicit(False)
                a.SetNumExplicitHs(0)
            # 앙상블 다양화: 경보와 무관한 원자 0~2개를 중립 치환
            if neutral and len(out) > 0:
                for j in rng.choice(neutral,
                                    size=min(int(rng.integers(1, 3)),
                                             len(neutral)),
                                    replace=False):
                    a = rw.GetAtomWithIdx(int(j))
                    opts = SWAP.get(a.GetAtomicNum())
                    if not opts:
                        continue
                    a.SetAtomicNum(int(rng.choice(opts)))
                    a.SetFormalCharge(0)
                    a.SetNoImplicit(False)
                    a.SetNumExplicitHs(0)
            try:
                m = rw.GetMol()
                Chem.SanitizeMol(m)
                smi = Chem.MolToSmiles(m)
            except Exception:
                continue
            if smi in seen:
                continue
            clogp = Crippen.MolLogP(m)
            fl = compute_flags(m, clogp)
            if any(fl.get(f) for f in target_flags):
                continue                     # 경보가 안 죽었으면 버린다
            p1 = (Descriptors.MolWt(m), clogp, rdMolDescriptors.CalcTPSA(m))
            # 벌크 물성이 크게 달라지면 대조군 자격 없음
            if abs(p1[0] - p0[0]) > 45 or abs(p1[1] - p0[1]) > 1.5 \
               or abs(p1[2] - p0[2]) > 40:
                continue
            seen.add(smi)
            out.append({"smiles": smi, "mol": m, "clogp": p1[1], "mw": p1[0],
                        "tpsa": p1[2], "hbd": rdMolDescriptors.CalcNumHBD(m),
                        "replaced_atomic_nums": replaced})
        return out

    def r2_attribution(self, clause, props, context, trace=None):
        tf = self.confirmed.get(clause.clause_type, [])
        present = [f for f in tf if props["flags"].get(f)]
        if not present:
            clause.delta_star = clause.delta
            return clause

        # 물성 기반 경보는 부분구조 절제로 죽일 수 없다. cLogP≥3.7 은 우리가
        # decoy 에서 매칭해야 하는 벌크 물성 그 자체이기 때문이다.
        # 따라서 Δ* 는 절제 가능한 경보의 기여만 검정하며, 그 사실을 남긴다.
        ablatable = [f for f in present if f in ABLATABLE_FLAGS]
        property_only = [f for f in present if f not in ABLATABLE_FLAGS]
        clause.attribution_scope = {
            "ablatable": ablatable, "property_only": property_only}
        if not ablatable:
            clause.delta_star = float("nan")
            clause.reason_code = "attribution_not_ablatable"
            _t(trace, "ADVERSARY", "R2 귀속 검정 불가",
               f"{clause.clause_type}: 지목 경보가 물성 기반({property_only})이라 "
               f"부분구조 절제로 분리 불가 → 판정 보류")
            return clause

        decoys = self.make_decoys(props["smiles"], ablatable)
        if not decoys:
            clause.delta_star = float("nan")
            clause.reason_code = "decoy_unavailable"
            _t(trace, "ADVERSARY", "R2 귀속 검정 불가",
               f"{clause.clause_type}: 물성 매칭 decoy 생성 실패 → 판정 보류")
            return clause
        m = self.models.get(clause.clause_type)
        deltas = []
        for d in decoys:
            rec = _rec({**props, **{k: d[k] for k in
                                    ("smiles", "clogp", "mw", "tpsa", "hbd")},
                        "flags": compute_flags(d["mol"], d["clogp"])}, context)
            pb = float(self.tpl.p(rec, clause.clause_type))
            ph = float(m.predict([rec])[0]) if m and m.model else pb
            deltas.append(ph - pb)
        mean_decoy = float(np.mean(deltas))
        sd_decoy = float(np.std(deltas))
        clause.delta_star = clause.delta - max(0.0, mean_decoy)
        clause.attribution_scope.update(
            {"n_decoy": len(decoys), "mean_decoy_delta": mean_decoy,
             "sd_decoy_delta": sd_decoy,
             "structure_share": (clause.delta_star / clause.delta)
             if clause.delta > 0 else None})
        share = clause.attribution_scope["structure_share"]
        _t(trace, "ADVERSARY", "R2 구조 귀속 검정",
           f"{clause.clause_type}: Δ={clause.delta:+.4f} · "
           f"decoy {len(decoys)}개 평균 Δ={mean_decoy:+.4f}(sd {sd_decoy:.4f}) → "
           f"Δ*={clause.delta_star:+.4f}"
           + (f" · 구조 귀속분 {share:.0%}" if share is not None else "")
           + (" → 구조 유래 아님, 기각" if clause.delta_star <= 0 else ""))
        return clause

    # ── R1: 근거 반증 ────────────────────────────────────────
    def r1_evidence(self, clause, trace=None):
        ok = clause.provenance is not None and clause.provenance.is_verified()
        if not ok:
            clause.decision = "abstain"
            clause.reason_code = "evidence_span_absent"
            _t(trace, "ADVERSARY", "R1 근거 반증",
               f"{clause.clause_type}: provenance 미검증 → 기각")
        return ok

    # ── R3: 실행가능성 반증 ──────────────────────────────────
    def r3_feasibility(self, clauses, actuary, trace=None):
        g = actuary.recruitment_gate(clauses, trace=trace)
        if g["exceeds"]:
            for c in clauses:
                if c.decision == "advance" and c.clause_type not in SAFETY_CLAUSES:
                    c.decision = "escalate"
                    c.reason_code = "recruitment_pool_reduction"
        return g


# ══ ⑤ LEDGER ════════════════════════════════════════════════
class Ledger:
    """선택적 발행 · append-only 원장 · 감사 DAG.

    조항별 τ 는 보정 분할에서 목표 정밀도를 만족하도록 산출한 값을 쓴다
    (prototype/results/tau_calibration.json). 목표를 만족하는 임계가 없는
    조항은 **발행 자체가 봉인**되어 사람검토·기권만 가능하다.
    전역 τ 하나로 모든 조항을 판정하면 조항마다 신뢰도 분포가 달라
    어떤 조항은 과다 발행되고 어떤 조항은 정밀도 0 으로 발행된다.
    """

    CALIB_PATH = os.path.join(ROOT, "results", "tau_calibration.json")

    def __init__(self, tau=TAU_DEFAULT, tau_low=TAU_LOW_DEFAULT, eps=0.02,
                 calibration=None):
        self.tau, self.tau_low, self.eps = tau, tau_low, eps
        self.entries = []
        self.calib = calibration if calibration is not None else self._load()

    @classmethod
    def _load(cls):
        try:
            with open(cls.CALIB_PATH, encoding="utf-8") as f:
                return json.load(f).get("per_clause", {})
        except Exception:
            return {}

    def thresholds(self, clause_type):
        """(τ, τ_low, 봉인 여부)."""
        v = self.calib.get(clause_type)
        if not v:
            return self.tau, self.tau_low, False
        if v.get("sealed"):
            return None, None, True
        return v["tau"], v["tau_low"], False

    def trust(self, c):
        if c.delta_star != c.delta_star:      # NaN
            return float("nan")
        return c.delta_star / (c.sigma + self.eps) * max(c.ad, 1e-3)

    def decide(self, clauses, trace=None):
        n_sealed = 0
        for c in clauses:
            c.trust = self.trust(c)
            tau, tau_low, sealed = self.thresholds(c.clause_type)
            c.tau, c.tau_low, c.issuance_sealed = tau, tau_low, sealed
            if not c.trigger_risks:
                c.decision, c.reason_code = "abstain", "no_structural_trigger"
            elif c.delta_star != c.delta_star:
                c.decision, c.reason_code = "abstain", (
                    c.reason_code or "attribution_undetermined")
            elif not c.four_tuple_complete():
                c.decision, c.reason_code = "abstain", "four_tuple_incomplete"
            elif c.delta_star <= 0:
                c.decision, c.reason_code = "abstain", "not_structure_attributable"
            elif sealed:
                # 보정에서 목표 정밀도를 만족하는 임계를 찾지 못한 조항.
                # 발행하지 않고 사람검토로만 올린다. 억지로 발행하느니 낫다.
                c.decision, c.reason_code = "escalate", "issuance_sealed_by_calibration"
                n_sealed += 1
            elif c.trust >= tau:
                c.decision, c.reason_code = "advance", "trust_above_tau"
            elif c.trust >= tau_low:
                c.decision, c.reason_code = "escalate", "trust_in_review_band"
            else:
                c.decision, c.reason_code = "abstain", "trust_below_floor"
            # 안전성 조항은 신뢰도 미달 시 무조건 사람에게
            if (c.clause_type in SAFETY_CLAUSES and c.decision == "abstain"
                    and c.reason_code == "trust_below_floor"):
                c.decision, c.reason_code = "escalate", "safety_clause_mandatory_review"
        n = {k: sum(1 for c in clauses if c.decision == k)
             for k in ("advance", "escalate", "abstain")}
        _t(trace, "LEDGER", "선택적 발행",
           f"발행 {n['advance']} · 사람검토 {n['escalate']} · 기권 {n['abstain']} "
           f"(기권율 {n['abstain']/max(len(clauses),1):.0%})"
           + (f" · 보정에서 발행 봉인된 조항 {n_sealed}종" if n_sealed else ""))
        return clauses

    def seal(self, run_id, clauses, trace, meta):
        rec = {
            "run_id": run_id,
            "clauses": [_clause_dict(c) for c in clauses],
            "trace": trace,
            "meta": meta,
        }
        rec["dag_hash"] = sha({"trace": [(t["agent"], t["step"]) for t in trace],
                               "clauses": [(c.clause_id, c.decision,
                                            round(c.delta_star, 6)
                                            if c.delta_star == c.delta_star else None)
                                           for c in clauses]})
        self.entries.append(rec)
        return rec


# ══ 보조 ═════════════════════════════════════════════════════
def _t(trace, agent, step, detail):
    if trace is not None:
        trace.append({"seq": len(trace), "agent": agent, "step": step,
                      "detail": detail})


def _rec(props, context):
    r = {"phase": context["phase"], "oncology": context["oncology"],
         "smiles": props["smiles"], "clogp": props["clogp"],
         "mw": props["mw"], "tpsa": props["tpsa"], "hbd": props["hbd"]}
    r.update({f: bool(props["flags"].get(f)) for f in FLAG_NAMES})
    return r


def _clause_dict(c):
    d = asdict(c)
    if c.provenance:
        d["provenance"] = asdict(c.provenance)
    for k in ("delta_star", "trust"):
        if d[k] != d[k]:
            d[k] = None
    return d
