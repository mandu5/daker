"""제안서 도식 생성.

    python3 proposal/figures.py

색 규약 (제안서 전체에서 동일)
    청색  = 결정론 도구가 판정하는 지점 (RDKit·규칙엔진·scipy)
    회색  = LLM 이 관여하는 지점 (텍스트 추출·모순 탐지·서술)
    붉은색 = 되돌아가는 화살표(반증 기각) · 기권
"""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(REPO, "tools", "figures"))

import figure as F  # noqa: E402

OUT = os.path.join(REPO, "assets", "figures")
RESULTS = os.path.join(REPO, "prototype", "results", "s2c_associations.json")

DET = "#1F5C99"      # 결정론
LLM = "#7A7A7A"      # LLM
REJ = "#B5455F"      # 기각·되돌아감
OK = "#0E7C7B"       # 확증
NAVY = "#0F2B46"
LIGHT = "#EEF3F8"
LINE = "#C3D2E0"


# ── 그림 1. 먹줄 아키텍처 ─────────────────────────────────────
def fig_architecture():
    def agent(no, name, role, tools, *, tone=DET):
        return (
            f"<div style='border:1.4px solid {tone};border-left:5px solid {tone};"
            f"border-radius:6px;padding:7px 10px;background:#fff;'>"
            f"<div style='display:flex;align-items:baseline;gap:6px;'>"
            f"<span style='color:{tone};font-weight:700;font-size:12.5px;'>{no}</span>"
            f"<span style='font-weight:700;font-size:12.5px;'>{name}</span>"
            f"<span style='color:#5A5A5A;font-size:10px;'>{role}</span></div>"
            f"<div style='color:#444;font-size:9.6px;margin-top:3px;line-height:1.35;'>"
            f"{tools}</div></div>"
        )

    def flow(label):
        return (f"<div style='text-align:center;color:{DET};font-size:11px;"
                f"line-height:15px;'>▼<span style='color:#5A5A5A;font-size:9px;"
                f"margin-left:4px;'>{label}</span></div>")

    io_in = (
        f"<div style='background:{NAVY};color:#fff;border-radius:6px;padding:7px 10px;"
        f"font-size:10.5px;line-height:1.35;'>"
        f"<b style='font-size:11.5px;'>입력</b>&nbsp; SMILES · 비임상 요약(NOAEL·표적장기) · "
        f"적응증 · 상(phase) · 관할(식약처/FDA)</div>"
    )
    io_out = (
        f"<div style='background:{NAVY};color:#fff;border-radius:6px;padding:7px 10px;"
        f"font-size:10.5px;line-height:1.35;'>"
        f"<b style='font-size:11.5px;'>산출</b>&nbsp; Go/No-Go 조항표(발행·기권·에스컬레이션) · "
        f"COU 카드 · 감사 DAG · 재현성 봉인(seed·버전·해시)</div>"
    )

    spine = F.col([
        io_in,
        flow(""),
        agent("①", "MARKER 표기관", "구조 → 리스크 플래그",
              "RDKit FilterCatalog 8종 · Descriptors · 자체 SMARTS "
              "&nbsp;|&nbsp; 각 플래그에 σ(룰 불일치)·AD(적용범위) 부착 "
              "&nbsp;|&nbsp; 항체·세포·핵산은 소분자 룰 비활성"),
        flow("리스크 플래그 + 신뢰도"),
        agent("②", "SCRIBE 기안관", "리스크 × 맥락 → 조항 후보",
              "조항에 템플릿 기저확률 p_base 부착 → 증분 Δ 산출 "
              "&nbsp;|&nbsp; <b>4-튜플로만 발행</b>: (근거 span, 유발 리스크, 봉인된 반증조건, 신뢰도) "
              f"&nbsp;|&nbsp; <span style='color:{LLM};'>LLM: 자유문 → 구조화 추출 · 조항 간 모순 탐지</span>"),
        flow("조항 후보 + Δ"),
        agent("③", "ACTUARY 계량관", "용량 · 검정력 · 모집",
              "NOAEL→HED→MRSD · 3+3 vs BLRM 몬테카를로 "
              "&nbsp;|&nbsp; <b>검정력 게이트</b>: 탐지 불가 → 판정 보류 + 필요 N 제시 "
              "&nbsp;|&nbsp; 제외기준이 국내 등록가능 인구를 몇 % 깎는가"),
        flow("정량 근거"),
        agent("④", "ADVERSARY 반증관", "3중 반증 — 시스템의 심장",
              "<b>R1 근거</b> 인용 원문 span 부재 → 기각 &nbsp;|&nbsp; "
              "<b>R2 귀속</b> Δ*(c) ≤ 0 → 구조 유래 아님, 기각 &nbsp;|&nbsp; "
              "<b>R3 실행</b> 모집 인구 감소 과다 → 기각"),
        flow("반증 통과분"),
        agent("⑤", "LEDGER 원장관", "선택적 발행 · 감사",
              "T(c) = Δ*(c) / (σ+ε) × AD &nbsp;→&nbsp; "
              f"<b style='color:{OK};'>T≥τ 발행</b> · "
              f"<b style='color:#C98A17;'>사람 검토</b> · "
              f"<b style='color:{REJ};'>T&lt;τ_low 또는 Δ*≤0 기권</b> "
              "&nbsp;|&nbsp; append-only 원장 · DAG 해시"),
        flow(""),
        io_out,
    ], gap=5)

    back = f"""
    <div style='margin-top:9px;border:1.2px dashed {REJ};border-radius:6px;
                padding:7px 10px;background:#FDF4F6;'>
      <div style='color:{REJ};font-weight:700;font-size:11px;margin-bottom:3px;'>
        되돌아가는 화살표 — 자기수정 루프</div>
      <div style='font-size:9.6px;line-height:1.5;color:#333;'>
        <b>A1</b> R1 기각 → SCRIBE 재기안(최대 3회, 이후 기권) &nbsp;·&nbsp;
        <b>A2</b> R2 기각 → MARKER 리스크 등급 하향 + 룰 가중치 국소 재보정(Case Bank 영속화) &nbsp;·&nbsp;
        <b>A3</b> R3 기각 → ACTUARY 회귀(제외기준 대신 용량 상한·모니터링 빈도로 대체 탐색) &nbsp;·&nbsp;
        <b>A4</b> 기권율 &gt; 0.7 또는 동일 reason_code 반복 → 사람에게 계약 개정 요청(<b>자동 완화 금지</b>)
      </div>
    </div>"""

    legend = (
        f"<div style='margin-top:7px;font-size:9.4px;color:#5A5A5A;display:flex;"
        f"gap:14px;justify-content:center;'>"
        f"<span><span style='color:{DET};'>■</span> 결정론 도구가 판정 "
        f"(숫자는 LLM 손에 없다)</span>"
        f"<span><span style='color:{LLM};'>■</span> LLM 관여 지점 (3곳뿐, 각각 ablation)</span>"
        f"<span><span style='color:{REJ};'>■</span> 반증 기각 · 기권</span></div>"
    )
    F.render(spine + back + legend, os.path.join(OUT, "fig1_architecture.png"),
             width=600)


# ── 그림 2. 사전 선언 기전 게이트 실측 결과 ───────────────────
def fig_mechanism_gate():
    d = json.load(open(RESULTS, encoding="utf-8"))
    g = d["mechanism_gate"]
    conf = sorted(g["confirmatory"], key=lambda r: -r["lift"])
    ref = sorted(g["refuted"], key=lambda r: r["lift"])

    KO = {"halogenated_aromatic": "방향족 할로겐", "lipophilic": "친유성 cLogP≥3.7",
          "hydrazine": "하이드라진", "herg_pharmacophore": "hERG 약리단",
          "basic_amine": "염기성 아민", "thiophene": "티오펜",
          "michael_acceptor": "마이클 수용체", "aniline": "방향족 아민",
          "nitroaromatic": "니트로방향족", "epoxide": "에폭사이드",
          "sulfonamide": "설폰아마이드", "carboxylic_acid": "카복실산"}
    KC = {"CYP_DDI": "CYP·약물상호작용", "HEPATIC": "간기능", "QT_ECG": "QT·심전도",
          "RENAL": "신기능", "QT_DRUG": "QT 약물 병용금지", "PHOTO": "광과민성",
          "HEMATO": "혈액학적", "CONTRACEPT": "피임"}

    def bar(lift, tone):
        # lift 1.0 을 중앙으로 하는 막대. 0.4~2.2 범위를 100px 에 사상
        lo, hi, w = 0.4, 2.2, 132
        x1 = (1.0 - lo) / (hi - lo) * w
        xv = (min(max(lift, lo), hi) - lo) / (hi - lo) * w
        left, width = (x1, xv - x1) if lift >= 1 else (xv, x1 - xv)
        return (
            f"<div style='position:relative;width:{w}px;height:11px;"
            f"background:#F2F5F8;border-radius:2px;'>"
            f"<div style='position:absolute;left:{x1:.1f}px;top:0;width:1px;"
            f"height:11px;background:#9AA7B4;'></div>"
            f"<div style='position:absolute;left:{left:.1f}px;top:2px;"
            f"width:{max(width, 1.2):.1f}px;height:7px;background:{tone};"
            f"border-radius:1.5px;'></div></div>")

    def rows(items, tone, show_strat):
        out = []
        for r in items:
            strat = ""
            if show_strat and r.get("lift_onc") == r.get("lift_onc"):
                strat = (f"<td style='font-size:9px;color:#5A5A5A;padding:2px 4px;'>"
                         f"{r['lift_onc']:.2f} / {r['lift_non']:.2f}</td>")
            elif show_strat:
                strat = "<td></td>"
            p = r["p_value"]
            pstr = f"{p:.0e}".replace("e-0", "e-") if p < 0.01 else f"{p:.2f}"
            out.append(
                f"<tr>"
                f"<td style='font-size:10px;padding:2px 6px 2px 0;white-space:nowrap;'>"
                f"{KO.get(r['flag'], r['flag'])}</td>"
                f"<td style='font-size:10px;padding:2px 6px;color:#444;white-space:nowrap;'>"
                f"→ {KC.get(r['clause'], r['clause'])}</td>"
                f"<td style='padding:2px 6px;'>{bar(r['lift'], tone)}</td>"
                f"<td style='font-size:10px;font-weight:700;color:{tone};"
                f"padding:2px 5px;'>{r['lift']:.2f}</td>"
                f"<td style='font-size:9px;color:#777;padding:2px 4px;'>p={pstr}</td>"
                + strat + "</tr>")
        return "".join(out)

    head_c = (f"<div style='color:{OK};font-weight:700;font-size:11.5px;"
              f"margin:0 0 3px 0;'>확증 5 — 사전 선언 + 통계 유의 + 적응증 층화 통과"
              f"<span style='font-weight:400;color:#5A5A5A;font-size:9.5px;'>"
              f"&nbsp; 이것만 가치 주장에 쓴다 (우측: 종양/비종양 lift)</span></div>")
    head_r = (f"<div style='color:{REJ};font-weight:700;font-size:11.5px;"
              f"margin:10px 0 3px 0;'>기각 10 — 선언했으나 통과 실패"
              f"<span style='font-weight:400;color:#5A5A5A;font-size:9.5px;'>"
              f"&nbsp; 아래 둘은 <b>방향이 반대로</b> 유의했다</span></div>")

    tbl = "table style='border-collapse:collapse;'"
    body = (
        f"<div style='background:{LIGHT};border-radius:6px;padding:8px 11px;"
        f"margin-bottom:9px;font-size:11px;line-height:1.45;'>"
        f"<b>결과를 보기 전에</b> 의약화학 기전 가설 <b>18쌍</b>을 선언하고 대조했다. "
        f"실제 임상시험 <b>39,379건</b>의 선정·제외기준 원문 기준. "
        f"<b style='color:{OK};'>확증 5</b> · <b style='color:{REJ};'>기각 10</b> · "
        f"확증률 <b>33.3%</b></div>"
        + head_c + f"<{tbl}>" + rows(conf, OK, True) + "</table>"
        + head_r + f"<{tbl}>" + rows(ref[:6], REJ, False) + "</table>"
    )
    note = (
        f"<div style='margin-top:8px;border-left:4px solid {REJ};background:#FDF4F6;"
        f"padding:7px 10px;font-size:10.2px;line-height:1.45;'>"
        f"티오펜의 <b>반응성 대사체 → 간독성</b>은 의약화학 교과서적 경보다. "
        f"그러나 실제 프로토콜에서는 <b>반대 방향</b>으로 유의했다(lift 0.57, p=8.9e-28). "
        f"<b>검증 없이 구조 경보를 조항으로 번역하면 안 된다</b> — 먹줄이 Δ* 귀속 검정과 "
        f"기권 기제를 두는 이유가 이것이다.</div>")
    F.render(body + note, os.path.join(OUT, "fig2_mechanism_gate.png"), width=600)


# ── 그림 3. Δ* 구조 귀속 검정 ─────────────────────────────────
def fig_delta_star():
    def card(title, sub, val, tone, note=""):
        return (
            f"<div style='flex:1;border:1.3px solid {tone};border-radius:6px;"
            f"padding:7px 9px;background:#fff;'>"
            f"<div style='font-size:10.5px;font-weight:700;color:{tone};'>{title}</div>"
            f"<div style='font-size:9.3px;color:#5A5A5A;margin:2px 0 4px;line-height:1.35;'>"
            f"{sub}</div>"
            f"<div style='font-size:12px;font-weight:700;'>{val}</div>"
            + (f"<div style='font-size:9px;color:#777;margin-top:2px;'>{note}</div>"
               if note else "")
            + "</div>")

    top = F.row([
        card("① 우리 예측", "이 분자·상·적응증에서<br>조항이 필요할 확률", "p̂", DET),
        card("② 템플릿 기저", "같은 상·적응증에서<br>조항의 기저 출현율", "p_base", "#8A8A8A"),
        card("③ 템플릿 증분", "①−②", "Δ = p̂ − p_base", DET),
    ], gap=7)

    decoy = (
        f"<div style='margin-top:9px;border:1.3px solid {REJ};border-radius:6px;"
        f"padding:8px 10px;background:#FDF4F6;'>"
        f"<div style='font-size:10.8px;font-weight:700;color:{REJ};'>"
        f"④ Decoy 대조군 — 물성은 같고 구조 경보만 파괴한 분자</div>"
        f"<div style='font-size:9.8px;color:#333;margin-top:4px;line-height:1.45;'>"
        f"MW · cLogP · TPSA · HBD · 고리수는 <b>매칭</b>하고, 우리가 원인이라 주장한 "
        f"<b>구조 경보만 제거</b>한 분자 집합 D(m)을 RDKit RWMol 로 생성한다. "
        f"decoy 에서도 같은 조항이 제안된다면, 그 조항은 구조가 아니라 <b>물성·템플릿의 산물</b>이다."
        f"</div></div>")

    formula = (
        f"<div style='margin-top:9px;background:{NAVY};color:#fff;border-radius:6px;"
        f"padding:9px 12px;text-align:center;'>"
        f"<div style='font-size:12.5px;font-weight:700;letter-spacing:.01em;'>"
        f"Δ*(c) &nbsp;=&nbsp; Δ(c) &nbsp;−&nbsp; max(0, &nbsp;평균<sub>m′∈D(m)</sub>[ p̂(c|m′) − p_base(c) ])</div>"
        f"<div style='font-size:10px;opacity:.85;margin-top:4px;'>"
        f"구조 경보를 없앤 분자에서도 나오는 만큼을 빼낸, <b>순수하게 구조에 귀속되는 증분</b></div>"
        f"</div>")

    verdict = F.row([
        F.box("Δ*(c) &gt; 0", "구조 유래로 입증<br>→ 신뢰도 T 계산 후 발행 판단",
              bg="#fff", fg="ink", border=OK, grow=1, size=11, sub_size=9.5,
              border_w=1.4),
        F.box("Δ*(c) ≤ 0", "구조 유래 아님<br><b>→ 조항 기각</b>",
              bg="#FDF4F6", fg="ink", border=REJ, grow=1, size=11, sub_size=9.5,
              border_w=1.4),
    ], gap=7, style="margin-top:9px;")

    note = (
        f"<div style='margin-top:8px;font-size:9.8px;color:#444;line-height:1.45;"
        f"border-left:4px solid {DET};background:{LIGHT};padding:7px 10px;'>"
        f"<b>decoy 는 정답이 아니다.</b> 정답은 실제 임상시험 프로토콜의 선정·제외기준 "
        f"원문이다(평가 E1). decoy 는 조항이 <b>구조 때문인지 물성 때문인지 분리</b>하는 "
        f"음성 대조군이다. 자기 코드가 만든 정답을 자기 코드로 채점하는 순환을 구조적으로 피한다."
        f"</div>")
    F.render(top + decoy + formula + verdict + note,
             os.path.join(OUT, "fig3_delta_star.png"), width=600)


# ── 그림 4. 선택적 발행 ───────────────────────────────────────
def fig_selective():
    def lane(tone, label, cond, action, detail, bg):
        return (
            f"<div style='flex:1;border-top:4px solid {tone};background:{bg};"
            f"border-radius:0 0 6px 6px;padding:8px 10px;'>"
            f"<div style='font-size:11.5px;font-weight:700;color:{tone};'>{label}</div>"
            f"<div style='font-size:10px;font-family:monospace;color:#333;margin:3px 0;'>"
            f"{cond}</div>"
            f"<div style='font-size:10.3px;font-weight:700;margin-top:4px;'>{action}</div>"
            f"<div style='font-size:9.3px;color:#5A5A5A;margin-top:2px;line-height:1.4;'>"
            f"{detail}</div></div>")

    formula = (
        f"<div style='background:{NAVY};color:#fff;border-radius:6px;padding:8px 12px;"
        f"text-align:center;margin-bottom:8px;'>"
        f"<span style='font-size:12.5px;font-weight:700;'>"
        f"T(c) &nbsp;=&nbsp; Δ*(c) / (σ(c) + ε) &nbsp;×&nbsp; AD(m)</span>"
        f"<span style='font-size:9.6px;opacity:.85;margin-left:10px;'>"
        f"σ = 룰 앙상블 불일치 &nbsp;·&nbsp; AD = 캘리브레이션 코퍼스 근접도</span></div>")

    lanes = F.row([
        lane(OK, "발행 advance", "T(c) ≥ τ", "조항을 프로토콜에 제안",
             "근거 span·유발 리스크·봉인된 반증조건을 함께 발행", "#F1F8F7"),
        lane("#C98A17", "검토 escalate", "τ_low ≤ T(c) &lt; τ", "사람에게 승격",
             "안전성 조항·규제 상충·모달리티 범위 외는 무조건 여기로", "#FDF8EE"),
        lane(REJ, "기권 abstain", "T(c) &lt; τ_low  또는  Δ* ≤ 0", "발행하지 않는다",
             "기권은 실패가 아니라 산출물이다. 기권율을 스스로 보고", "#FDF4F6"),
    ], gap=7)

    guard = (
        f"<div style='margin-top:9px;border:1.3px solid {LINE};border-radius:6px;"
        f"padding:8px 10px;'>"
        f"<div style='font-size:10.8px;font-weight:700;color:{NAVY};'>"
        f"에이전트는 자기 합격 기준을 낮출 수 없다</div>"
        f"<div style='font-size:9.8px;color:#333;margin-top:3px;line-height:1.45;'>"
        f"τ 완화·kill criteria 변경은 사람의 서명 없이 불가능하며, 변경 차분이 원장에 "
        f"기록된다. 기권율이 0.7을 넘거나 같은 사유로 반복 기각되면 <b>자동 완화 대신 "
        f"사람에게 계약 개정을 요청</b>한다. 유전독성·위험시약 hard veto 는 사람도 우회할 수 없다."
        f"</div></div>")

    metric = (
        f"<div style='margin-top:8px;font-size:9.8px;color:#444;line-height:1.45;"
        f"border-left:4px solid {DET};background:{LIGHT};padding:7px 10px;'>"
        f"<b>주지표는 재현율이 아니다.</b> 안전성 조항을 '불필요'로 오판한 비율"
        f"(FOR<sub>safety</sub>)을 주지표로 삼고 목표를 2% 이하로 둔다. "
        f"<b>초과하면 절감 주장 자체를 철회</b>한다고 제안서에 미리 적는다. "
        f"precision@k 와 오경보율을 항상 나란히 보고해, 경고를 늘려 점수를 얻는 게이밍을 막는다."
        f"</div>")
    F.render(formula + lanes + guard + metric,
             os.path.join(OUT, "fig4_selective.png"), width=600)


# ── 그림 5. 평가 체계 ─────────────────────────────────────────
def fig_eval():
    def ev(tag, name, what, n, offline, tone):
        return (
            f"<tr>"
            f"<td style='padding:4px 6px;font-weight:700;color:{tone};font-size:10.5px;"
            f"white-space:nowrap;'>{tag}</td>"
            f"<td style='padding:4px 6px;font-weight:700;font-size:10.3px;"
            f"white-space:nowrap;'>{name}</td>"
            f"<td style='padding:4px 6px;font-size:9.8px;color:#333;line-height:1.4;'>{what}</td>"
            f"<td style='padding:4px 6px;font-size:9.8px;text-align:center;"
            f"white-space:nowrap;'>{n}</td>"
            f"<td style='padding:4px 6px;font-size:9.5px;text-align:center;color:{OK};'>"
            f"{offline}</td></tr>")

    head = (f"<tr style='background:{NAVY};color:#fff;'>"
            + "".join(f"<th style='padding:4px 6px;font-size:9.8px;font-weight:700;'>{h}</th>"
                      for h in ["", "평가셋", "무엇을 재는가", "규모", "오프라인"])
            + "</tr>")
    rows = (
        ev("E1", "SAFE-INC", "구조 경보가 실제 프로토콜 조항을 템플릿 기저 대비 "
           "얼마나 더 맞히는가 (ΔP@C, ΔAUPRC)", "39,379건", "100%", DET)
        + ev("E2", "DECOY", "그 조항이 구조 때문인가 물성 때문인가 (Δ* 귀속 검정)",
             "매칭 생성", "100%", DET)
        + ev("E3", "NULL", "경고를 내면 <b>안 되는</b> 경우에 기권하는가 "
             "(오경보율·기권율·상충 탐지)", "60~80건", "100%", REJ)
        + ev("E4", "AUDIT", "같은 시드로 3회 실행 시 감사 DAG 해시가 일치하는가 "
             "· 조항당 토큰·시간", "3회 반복", "100%", DET))

    base = (
        f"<div style='margin-top:9px;display:flex;gap:7px;'>"
        f"<div style='flex:1;border:1.3px solid {NAVY};border-radius:6px;padding:7px 9px;'>"
        f"<div style='font-size:10.5px;font-weight:700;color:{NAVY};'>"
        f"B-TPL — 절대 축소 금지 1순위</div>"
        f"<div style='font-size:9.6px;color:#333;margin-top:3px;line-height:1.45;'>"
        f"상×적응증별 조항 기저 빈도. <b>모든 헤드라인 수치를 이 베이스라인 대비 "
        f"증분으로만 보고</b>한다. 실측 결과 간기능 36.3%·피임 38.3%는 사실상 템플릿이고, "
        f"CYP·DDI 10.9%·QT 19.7%에서만 구조 신호가 잡힌다.</div></div>"
        f"<div style='flex:1;border:1.3px solid {LLM};border-radius:6px;padding:7px 9px;'>"
        f"<div style='font-size:10.5px;font-weight:700;color:{LLM};'>"
        f"B-RULE — LLM 0개, 토큰 0</div>"
        f"<div style='font-size:9.6px;color:#333;margin-top:3px;line-height:1.45;'>"
        f"순수 규칙 엔진. <b>에이전트가 이것을 얼마나 이겼는지</b>를 정직하게 보고한다. "
        f"작으면 작다고 쓴다. LLM 이 필요한 지점 3곳을 각각 ablation 으로 분리 측정한다."
        f"</div></div></div>")

    limit = (
        f"<div style='margin-top:8px;border-left:4px solid #C98A17;background:#FDF8EE;"
        f"padding:7px 10px;font-size:9.8px;line-height:1.45;color:#333;'>"
        f"<b>한계를 우리가 먼저 쓴다.</b> 조항 라벨은 정규식 v1 라벨러이며 사람 검토로 "
        f"Cohen's κ 를 측정하기 전까지 근사다. 병용요법 시험에서 대표 분자 1개 선택은 "
        f"신호를 희석시킨다. 적응증 층화는 종양/비종양 2분할로 거칠다. "
        f"광과민성(0.9%)·QT 병용금지(1.5%) 조항은 <b>검정력 부족으로 판정 보류</b>를 선언한다."
        f"</div>")

    F.render("<table style='border-collapse:collapse;width:100%;'>" + head + rows
             + "</table>" + base + limit,
             os.path.join(OUT, "fig5_eval.png"), width=600)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for fn in (fig_architecture, fig_mechanism_gate, fig_delta_star,
               fig_selective, fig_eval):
        fn()
        print("생성:", fn.__name__)
