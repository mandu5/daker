"""구조 경보(structural alert) 플래그.

설계 원칙
    파일럿 단계에서 여러 알림을 OR 로 묶으면 매칭률이 과도하게 높아져
    "구조 특이 신호"라고 부를 수 없게 된다. 실제로 티오펜·니트로·방향족아민을
    OR 로 묶은 초기 플래그는 분자의 37%에 매칭됐고, 화학적 기전과 무관한
    피임 조항(템플릿 조항)까지 유의하게 예측했다 — 이는 그 플래그가
    "항암제인가"의 대리변수로 작동했음을 뜻한다.

    따라서 알림은 **개별로 분리해 측정**하고, 결합 규칙은 문헌적 근거가
    분명한 것만 별도로 둔다.

각 플래그에 붙은 rationale 은 왜 그 구조가 특정 임상 조항과 연결될 수
있는지에 대한 통상적 의약화학 근거이며, **가설이지 검증된 사실이 아니다.**
검증은 s2c_analysis.py 가 실제 프로토콜 텍스트로 수행한다.
"""

from __future__ import annotations

from rdkit import Chem

# ── SMARTS 정의 ───────────────────────────────────────────────
SMARTS = {
    # 염기성(양성자화 가능) 3차/2차/1차 아민. 아마이드·설폰아마이드·아닐린 제외.
    "basic_amine": "[NX3;H2,H1,H0;!$(N[#6]=[O,N,S]);!$(N[SX4](=O)=O);!$(N#*);!$(Nc);!$([N+])]",
    "thiophene": "c1ccsc1",
    "nitroaromatic": "[$([NX3](=O)=O),$([NX3+](=O)[O-])][c]",
    "aniline": "[NX3;H2,H1;!$(N[#6]=[O,N,S])][c]",
    "carboxylic_acid": "[CX3](=O)[OX2H1]",
    "sulfonamide": "[SX4](=O)(=O)[NX3]",
    "michael_acceptor": "[CX3]=[CX3][CX3]=[OX1]",
    "halogenated_aromatic": "[F,Cl,Br,I][c]",
    "fused_tricyclic_aromatic": "c1ccc2c(c1)ccc1ccccc12",
    "hydrazine": "[NX3][NX3]",
    "epoxide": "C1OC1",
    "quinone": "O=C1C=CC(=O)C=C1",
}

RATIONALE = {
    "basic_amine":
        "양성자화된 염기성 질소는 hERG 채널 포어의 방향족 잔기와 상호작용하는 "
        "고전적 약리단 요소로 알려져 있다 → QT 관련 조항 가설",
    "herg_pharmacophore":
        "염기성 아민 + 높은 친유성(cLogP ≥ 3.7)의 조합은 hERG 저해 경향과 "
        "연관되어 논의되어 온 휴리스틱 → QT 관련 조항 가설",
    "thiophene":
        "티오펜 고리는 CYP 매개 S-산화로 반응성 대사체를 형성할 수 있다고 "
        "보고되어 왔다 → 간 관련 조항 가설",
    "nitroaromatic":
        "니트로방향족의 환원 대사는 반응성 중간체를 낳을 수 있다 → 간 관련 조항 가설",
    "aniline":
        "방향족 아민은 N-산화·N-아세틸화를 거쳐 반응성 종을 형성할 수 있다 "
        "→ 간 관련 조항 가설",
    "carboxylic_acid":
        "산성 작용기는 낮은 수동확산·높은 단백결합·아실글루쿠로나이드 형성과 "
        "연관된다. 음의 방향(해당 조항이 덜 등장)도 유의미한 신호다",
    "sulfonamide": "과민반응·광과민성 관련 조항 가설",
    "michael_acceptor": "공유결합성 반응성 → 안전성 조항 가설",
    "halogenated_aromatic": "친유성 증가에 따른 대사·축적 관련 조항 가설",
    "fused_tricyclic_aromatic": "광흡수 구조 → 광과민성 조항 가설",
    "hydrazine": "반응성 작용기 → 간 관련 조항 가설",
    "epoxide": "친전자성 알킬화제 → 안전성 조항 가설",
    "quinone": "산화환원 순환·반응성 → 안전성 조항 가설",
}

# hERG 휴리스틱의 친유성 절단점. 문헌에서 통용되는 대략적 기준을 따르며,
# 임의 절단점 의존성은 민감도 분석으로 별도 보고한다.
HERG_CLOGP_CUT = 3.7

_COMPILED = {k: Chem.MolFromSmarts(v) for k, v in SMARTS.items()}
_BAD = [k for k, v in _COMPILED.items() if v is None]
if _BAD:
    raise RuntimeError(f"SMARTS 파싱 실패: {_BAD}")

# RDKit 내장 필터 카탈로그 (PAINS 등). 실재하는 공개 필터 세트다.
_CATALOG = None


def _catalog():
    global _CATALOG
    if _CATALOG is None:
        from rdkit.Chem import FilterCatalog
        params = FilterCatalog.FilterCatalogParams()
        params.AddCatalog(FilterCatalog.FilterCatalogParams.FilterCatalogs.PAINS)
        _CATALOG = FilterCatalog.FilterCatalog(params)
    return _CATALOG


def compute_flags(mol, clogp=None):
    """분자 하나에 대해 모든 구조 플래그를 계산한다."""
    from rdkit.Chem import Crippen
    if clogp is None:
        clogp = Crippen.MolLogP(mol)

    out = {}
    for name, patt in _COMPILED.items():
        out[name] = bool(mol.GetSubstructMatches(patt))

    # 문헌 근거가 있는 결합 규칙만 별도로 둔다
    out["herg_pharmacophore"] = out["basic_amine"] and clogp >= HERG_CLOGP_CUT
    out["lipophilic"] = clogp >= HERG_CLOGP_CUT
    out["pains"] = _catalog().HasMatch(mol)
    return out


FLAG_NAMES = list(SMARTS.keys()) + ["herg_pharmacophore", "lipophilic", "pains"]
