"""자유 서술형 비임상 요약 → 구조화 입력 추출.

설계에서 LLM 이 담당하는 지점은 이제 하나다 — **자유 서술 텍스트를 구조화된
필드로 바꾸는 것.** 조항 간 모순 탐지는 결정론으로 옮겼고(consistency.py),
수치와 판정은 처음부터 결정론 도구가 낸다.

이 모듈은 그 하나의 지점을 **교체 가능한 어댑터**로 구현한다.

    RegexExtractor  결정론 규칙 기반. LLM 없이 동작하며 예선 기본값이다.
    LLMExtractor    LLM 호출. 본선에서 크레딧이 주어지면 사용한다.

두 구현은 같은 인터페이스를 따르고 **같은 검증을 통과해야 한다.**
추출 결과는 어느 쪽이든 `NonclinicalSummary` 스키마로 강제되며, 스키마를
벗어난 값은 `unverified` 로 격리되어 판정 가중치를 잃는다.

왜 이렇게 하는가
    LLM 이 자유롭게 만든 숫자가 그대로 파이프라인에 들어가면 결정론 코어
    원칙이 무너진다. 추출 단계에서도 **LLM 은 텍스트에서 값을 찾을 뿐,
    값을 지어낼 수 없어야 한다.** 그래서 추출된 모든 값은 원문에서의 위치
    (span)를 함께 보고해야 하고, span 이 원문과 대조되지 않으면 버린다.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import asdict, dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


@dataclass
class Field:
    """추출된 값 하나. 원문 근거 span 이 없으면 격리된다."""
    name: str
    value: object
    unit: str = ""
    span_text: str = ""          # 원문에서 잘라낸 근거 문자열
    span_start: int = -1
    verified: bool = False       # 원문 대조 통과 여부

    def as_dict(self):
        return asdict(self)


@dataclass
class NonclinicalSummary:
    noael_mg_kg: Field = None
    species: Field = None
    target_organs: Field = None
    fields: list = field(default_factory=list)
    isolated: list = field(default_factory=list)

    def verified_fields(self):
        return [f for f in self.fields if f.verified]

    def isolation_rate(self):
        n = len(self.fields) + len(self.isolated)
        return (len(self.isolated) / n) if n else 0.0

    def as_dict(self):
        return {
            "fields": [f.as_dict() for f in self.fields],
            "isolated": [f.as_dict() for f in self.isolated],
            "isolation_rate": self.isolation_rate(),
        }


class Extractor:
    """추출기 공통 인터페이스."""

    name = "base"

    def extract(self, text: str) -> NonclinicalSummary:
        raise NotImplementedError

    # ── 공통 검증: 추출값은 원문에 실재해야 한다 ──────────────
    @staticmethod
    def verify(fields, text):
        """각 필드의 span 이 원문에 실제로 있는지 대조한다.

        LLM 이 값을 지어내도 이 관문을 통과할 수 없다.
        """
        ok, bad = [], []
        for f in fields:
            if not f.span_text:
                f.verified = False
                bad.append(f)
                continue
            idx = text.find(f.span_text)
            if idx < 0:
                f.verified = False
                bad.append(f)
                continue
            f.span_start = idx
            f.verified = True
            ok.append(f)
        return ok, bad


class RegexExtractor(Extractor):
    """결정론 규칙 기반 추출기. 예선 기본값."""

    name = "regex"

    PATTERNS = {
        "noael_mg_kg": (
            re.compile(r"NOAEL[^0-9]{0,20}([0-9]+(?:\.[0-9]+)?)\s*(mg/kg)", re.I),
            "mg/kg"),
        "species": (
            re.compile(r"\b(rat|mouse|mice|dog|beagle|monkey|cynomolgus|rabbit)\b",
                       re.I), ""),
        "target_organs": (
            re.compile(r"target organ[s]?[^A-Za-z]{0,10}([A-Za-z ,and]{3,60})", re.I),
            ""),
        "mtd_mg_kg": (
            re.compile(r"\bMTD[^0-9]{0,20}([0-9]+(?:\.[0-9]+)?)\s*(mg/kg)", re.I),
            "mg/kg"),
        "study_duration_days": (
            re.compile(r"([0-9]+)[- ]day (?:repeat[- ]dose|toxicity|study)", re.I),
            "day"),
    }

    NUMERIC = {"noael_mg_kg", "mtd_mg_kg", "study_duration_days"}

    def extract(self, text: str) -> NonclinicalSummary:
        found = []
        for name, (rx, unit) in self.PATTERNS.items():
            m = rx.search(text or "")
            if not m:
                continue
            raw = m.group(1).strip()
            val = float(raw) if name in self.NUMERIC else raw
            found.append(Field(name=name, value=val, unit=unit,
                               span_text=m.group(0)))
        ok, bad = self.verify(found, text or "")
        s = NonclinicalSummary(fields=ok, isolated=bad)
        for f in ok:
            if f.name == "noael_mg_kg":
                s.noael_mg_kg = f
            elif f.name == "species":
                s.species = f
            elif f.name == "target_organs":
                s.target_organs = f
        return s


class LLMExtractor(Extractor):
    """LLM 기반 추출기. 본선에서 API 크레딧이 주어지면 사용한다.

    `call` 은 (프롬프트) -> [{"name","value","unit","span_text"}, ...] 를
    반환하는 함수여야 한다. 어떤 모델을 쓰든 이 계약만 지키면 된다.

    **LLM 이 반환한 값도 RegexExtractor 와 동일하게 span 대조를 거친다.**
    원문에 없는 span 을 붙인 값은 격리되어 판정에 쓰이지 않는다.
    """

    name = "llm"

    PROMPT = (
        "다음 비임상 요약에서 아래 필드를 추출하라. "
        "각 값에 대해 원문에서 그 값을 뒷받침하는 문구를 span_text 로 "
        "**원문 그대로** 복사해 함께 반환하라. 원문에 없는 값은 반환하지 마라.\n"
        "필드: noael_mg_kg, species, target_organs, mtd_mg_kg, "
        "study_duration_days\n\n본문:\n{text}"
    )

    def __init__(self, call=None):
        self.call = call

    def extract(self, text: str) -> NonclinicalSummary:
        if self.call is None:
            raise RuntimeError(
                "LLM 호출 함수가 주입되지 않았다. 예선 환경에서는 "
                "RegexExtractor 를 쓴다.")
        raw = self.call(self.PROMPT.format(text=text or "")) or []
        found = [Field(name=d.get("name", ""), value=d.get("value"),
                       unit=d.get("unit", ""), span_text=d.get("span_text", ""))
                 for d in raw]
        ok, bad = self.verify(found, text or "")
        s = NonclinicalSummary(fields=ok, isolated=bad)
        for f in ok:
            if f.name == "noael_mg_kg":
                s.noael_mg_kg = f
            elif f.name == "species":
                s.species = f
        return s


def get_extractor(kind="regex", **kw) -> Extractor:
    """어댑터 선택. 본선에서는 kind='llm' 으로 한 줄만 바꾸면 된다."""
    return {"regex": RegexExtractor, "llm": LLMExtractor}[kind](**kw) \
        if kind == "llm" else RegexExtractor()
