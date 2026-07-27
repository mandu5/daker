"""조항 발행 확률 모델과 베이스라인.

세 모델을 같은 분할에서 비교한다.

    B-TPL   템플릿 베이스라인. 상(phase) × 적응증군의 조항 기저 빈도만 사용.
            분자를 전혀 보지 않는다. **모든 헤드라인 수치는 이것 대비 증분으로 보고한다.**
    B-RULE  규칙 엔진. LLM 0개, 학습 0회. 사전 선언 기전 가설에서 확증된
            구조 경보가 있으면 조항을 발행한다. 토큰 비용 0.
    INKLINE 로지스틱 회귀. 맥락(상·적응증) + **해당 조항에 대해 사전 선언된
            구조 경보만** 특징으로 쓴다. 사후에 고른 특징을 넣지 않는다.

분할
    NCT ID 해시 기준 결정론적 70/30. 같은 시험이 학습·평가에 동시에
    들어가지 않는다. 시드를 고정하므로 재실행 시 동일 분할이 나온다.
"""

from __future__ import annotations

import hashlib
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "trialbench"))

from mechanism import PREREGISTERED  # noqa: E402

SPLIT_SEED = "inkline-2026"
TEST_FRAC = 0.30

# 가치 주장 대상 조항 (관례적 포함 성격이 강한 피임 조항은 제외)
TARGET_CLAUSES = ["QT_ECG", "CYP_DDI", "HEPATIC", "RENAL", "HEMATO"]

# 안전성 조항 — 이것을 '불필요'로 오판하면 FOR_safety 에 잡힌다
SAFETY_CLAUSES = {"QT_ECG", "CYP_DDI", "HEPATIC", "RENAL"}

PHASES = ["Phase 1", "Phase 2", "Phase 3", "Phase 4"]


def split_of(nctid):
    """NCT ID 해시로 결정론적 train/test 배정."""
    h = hashlib.sha256((SPLIT_SEED + str(nctid)).encode()).hexdigest()
    return "test" if (int(h[:8], 16) / 0xFFFFFFFF) < TEST_FRAC else "train"


def flags_for(clause):
    """해당 조항에 대해 사전 선언된 구조 경보 목록 (선언 순서 유지)."""
    return [f for (f, c) in PREREGISTERED if c == clause]


def phase_group(p):
    p = (p or "").strip()
    for ph in PHASES:
        if ph.lower() in p.lower():
            return ph
    return "Other"


def context_key(rec):
    return (phase_group(rec.get("phase")), bool(rec.get("oncology")))


# ── B-TPL : 템플릿 베이스라인 ─────────────────────────────────
class TemplateBaseline:
    """상 × 적응증군별 조항 기저 빈도. 분자를 보지 않는다."""

    def __init__(self, alpha=1.0):
        self.alpha = alpha          # 라플라스 평활
        self.table = {}             # (ctx, clause) -> p
        self.global_ = {}           # clause -> p

    def fit(self, recs, clauses):
        from collections import defaultdict
        cnt = defaultdict(lambda: [0, 0])
        tot = defaultdict(lambda: [0, 0])
        for r in recs:
            ctx = context_key(r)
            for c in clauses:
                cnt[(ctx, c)][0] += r[c]
                cnt[(ctx, c)][1] += 1
                tot[c][0] += r[c]
                tot[c][1] += 1
        for c in clauses:
            k, n = tot[c]
            self.global_[c] = (k + self.alpha) / (n + 2 * self.alpha)
        for (ctx, c), (k, n) in cnt.items():
            self.table[(ctx, c)] = (k + self.alpha * self.global_[c] * 2) / \
                                   (n + 2 * self.alpha)
        return self

    def p(self, rec, clause):
        return self.table.get((context_key(rec), clause),
                              self.global_.get(clause, 0.0))

    def predict(self, recs, clause):
        return np.array([self.p(r, clause) for r in recs])


# ── B-RULE : 규칙 엔진 (LLM 0, 학습 0) ────────────────────────
class RuleBaseline:
    """확증된 구조 경보가 하나라도 있으면 조항 발행. 토큰 0."""

    def __init__(self, confirmed):
        # confirmed: {clause: [flag, ...]}
        self.confirmed = confirmed

    def predict(self, recs, clause):
        fl = self.confirmed.get(clause, [])
        if not fl:
            return np.zeros(len(recs))
        return np.array([1.0 if any(r[f] for f in fl) else 0.0 for r in recs])


# ── INKLINE : 맥락 + 사전 선언 구조 경보 ──────────────────────
# 연속 물성. 구조 경보 다수가 이 값들의 이진화이므로(예: lipophilic = cLogP≥3.7),
# 이진 플래그만 쓰면 구조 모델을 부당하게 불리하게 만든다.
# 다만 사전 선언의 엄격한 범위를 넘어서므로 별도 변형(INKLINE+)으로 분리 보고한다.
CONT_FEATURES = ["clogp", "mw", "tpsa", "hbd"]


class ClauseModel:
    """조항 1종에 대한 로지스틱 회귀 + 등위회귀 보정 + 부트스트랩 분산.

    continuous=False → 사전 선언된 이진 구조 경보만 사용 (엄격 INKLINE)
    continuous=True  → 연속 물성을 추가 (INKLINE+, 확장 특징임을 명시 보고)
    """

    def __init__(self, clause, n_boot=20, seed=20260807, continuous=False):
        self.clause = clause
        self.flags = flags_for(clause)
        self.n_boot = n_boot
        self.seed = seed
        self.continuous = continuous
        self.model = None
        self.calibrator = None
        self.boots = []
        self._mu = None
        self._sd = None

    def _raw(self, recs):
        rows = []
        for r in recs:
            ph = phase_group(r.get("phase"))
            row = [1.0 if ph == p else 0.0 for p in PHASES]
            row.append(1.0 if bool(r.get("oncology")) else 0.0)
            row += [1.0 if r[f] else 0.0 for f in self.flags]
            if self.continuous:
                row += [float(r.get(k, 0.0) or 0.0) for k in CONT_FEATURES]
            rows.append(row)
        return np.array(rows, dtype=float)

    def _X(self, recs):
        X = self._raw(recs)
        if not self.continuous:
            return X
        k = len(CONT_FEATURES)
        if self._mu is None:
            self._mu = X[:, -k:].mean(axis=0)
            self._sd = np.maximum(X[:, -k:].std(axis=0), 1e-6)
        X[:, -k:] = (X[:, -k:] - self._mu) / self._sd
        return X

    def fit(self, recs):
        from sklearn.linear_model import LogisticRegression
        from sklearn.isotonic import IsotonicRegression
        X = self._X(recs)
        y = np.array([r[self.clause] for r in recs], dtype=int)
        if y.sum() < 20 or (len(y) - y.sum()) < 20:
            return self
        self.model = LogisticRegression(max_iter=2000, C=1.0)
        self.model.fit(X, y)

        # 등위회귀 보정 (학습셋 내 교차 예측 대신 단순 적합 — 보고 시 ECE 병기)
        p = self.model.predict_proba(X)[:, 1]
        self.calibrator = IsotonicRegression(out_of_bounds="clip").fit(p, y)

        # 부트스트랩 재적합 → 예측 분산 σ 추정
        rng = np.random.default_rng(self.seed)
        n = len(y)
        for _ in range(self.n_boot):
            idx = rng.integers(0, n, n)
            if y[idx].sum() < 5 or (len(idx) - y[idx].sum()) < 5:
                continue
            m = LogisticRegression(max_iter=1000, C=1.0)
            try:
                m.fit(X[idx], y[idx])
                self.boots.append(m)
            except Exception:
                pass
        return self

    def predict(self, recs):
        if self.model is None:
            return np.zeros(len(recs))
        p = self.model.predict_proba(self._X(recs))[:, 1]
        return self.calibrator.predict(p) if self.calibrator is not None else p

    def sigma(self, recs):
        """부트스트랩 모델 간 예측 불일치 = 인식적 불확실성."""
        if not self.boots:
            return np.zeros(len(recs))
        X = self._X(recs)
        P = np.stack([m.predict_proba(X)[:, 1] for m in self.boots])
        return P.std(axis=0)


# ── 적용범위(AD) ──────────────────────────────────────────────
class ApplicabilityDomain:
    """학습 분자 집합에 대한 최대 Tanimoto(ECFP4) 근접도."""

    def __init__(self, n_bits=1024, radius=2, max_ref=8000, seed=20260807):
        self.n_bits, self.radius = n_bits, radius
        self.max_ref, self.seed = max_ref, seed
        self.ref = None

    @staticmethod
    def _fp(smiles, radius, n_bits):
        from rdkit import Chem
        from rdkit.Chem import rdFingerprintGenerator
        m = Chem.MolFromSmiles(smiles)
        if m is None:
            return None
        gen = rdFingerprintGenerator.GetMorganGenerator(
            radius=radius, fpSize=n_bits)
        arr = np.zeros(n_bits, dtype=np.uint8)
        for b in gen.GetFingerprint(m).GetOnBits():
            arr[b] = 1
        return arr

    def fit(self, recs):
        rng = np.random.default_rng(self.seed)
        smis = [r["smiles"] for r in recs]
        if len(smis) > self.max_ref:
            idx = rng.choice(len(smis), self.max_ref, replace=False)
            smis = [smis[i] for i in idx]
        fps = [self._fp(s, self.radius, self.n_bits) for s in smis]
        self.ref = np.stack([f for f in fps if f is not None]).astype(np.uint8)
        self._pop = self.ref.sum(axis=1).astype(np.float32)
        return self

    def score(self, smiles):
        """0~1. 1에 가까울수록 학습 분포 안쪽."""
        q = self._fp(smiles, self.radius, self.n_bits)
        if q is None or self.ref is None:
            return 0.0
        inter = (self.ref & q).sum(axis=1).astype(np.float32)
        union = self._pop + float(q.sum()) - inter
        return float(np.max(inter / np.maximum(union, 1.0)))


# ── 평가 지표 ─────────────────────────────────────────────────
def auprc(y, s):
    from sklearn.metrics import average_precision_score
    if len(set(y)) < 2:
        return float("nan")
    return float(average_precision_score(y, s))


def precision_at_coverage(y, s, coverage):
    """상위 coverage 비율만 발행했을 때의 정밀도."""
    n = max(1, int(round(len(s) * coverage)))
    idx = np.argsort(-np.asarray(s, dtype=float))[:n]
    return float(np.asarray(y)[idx].mean()), n


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (p, (c - m) / d, (c + m) / d)


def ece(y, p, bins=10):
    """기대 캘리브레이션 오차."""
    y, p = np.asarray(y, dtype=float), np.asarray(p, dtype=float)
    edges = np.linspace(0, 1, bins + 1)
    e = 0.0
    for i in range(bins):
        m = (p > edges[i]) & (p <= edges[i + 1])
        if m.sum():
            e += m.mean() * abs(y[m].mean() - p[m].mean())
    return float(e)
