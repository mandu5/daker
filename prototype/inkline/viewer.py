"""감사 DAG 뷰어 — 본선 시연 화면.

실행 결과 JSON 하나를 받아 자기완결 HTML 한 장을 만든다.
외부 CDN·스크립트 없이 열리므로 폐쇄망에서도 그대로 쓴다.

    python3 prototype/inkline/viewer.py \
        --run prototype/results/runs/demo_selfcorrect.json \
        --out prototype/results/runs/demo_selfcorrect.html

화면이 보여주는 것 (제안서 항목 6의 3막 구조 그대로)
    1막 연역 — 구조 경보와 조항 후보가 템플릿 기저와 함께 쌓인다
    2막 반증 — 기각·하향·기권이 색으로 구분되고 되돌아간 경로가 붉게 표시된다
    3막 대조 — 판정 근거와 감사 해시를 그대로 노출한다

색 규약은 제안서와 동일하다. 청색=결정론, 회색=LLM, 붉은색=반증 기각·기권.
"""

from __future__ import annotations

import argparse
import html
import json
import os

NAVY = "#0F2B46"
DET = "#1F5C99"
REJ = "#B5455F"
OK = "#0E7C7B"
AMBER = "#C98A17"
GRAY = "#5A5A5A"
LINE = "#C3D2E0"
LIGHT = "#EEF3F8"

DECISION = {
    "advance": ("발행", OK),
    "escalate": ("사람 검토", AMBER),
    "abstain": ("기권", REJ),
}

CSS = f"""
*{{box-sizing:border-box;margin:0;padding:0;}}
body{{font-family:-apple-system,'Noto Sans KR',sans-serif;background:#F4F7FA;
     color:#111;padding:20px;line-height:1.5;}}
.wrap{{max-width:1080px;margin:0 auto;}}
h1{{font-size:19px;color:{NAVY};margin-bottom:2px;}}
.sub{{font-size:12px;color:{GRAY};margin-bottom:16px;}}
.card{{background:#fff;border:1px solid {LINE};border-radius:8px;padding:14px 16px;
      margin-bottom:12px;}}
.card h2{{font-size:14px;color:{NAVY};margin-bottom:8px;}}
.act{{display:inline-block;background:{NAVY};color:#fff;font-size:11px;
     padding:2px 8px;border-radius:4px;margin-right:6px;}}
table{{border-collapse:collapse;width:100%;font-size:12px;}}
th{{background:{NAVY};color:#fff;padding:6px 8px;text-align:left;font-weight:600;}}
td{{border-bottom:1px solid #E6ECF2;padding:6px 8px;vertical-align:top;}}
tr:hover td{{background:{LIGHT};}}
.num{{text-align:right;font-variant-numeric:tabular-nums;}}
.pill{{font-weight:700;font-size:11px;padding:2px 7px;border-radius:10px;
      color:#fff;white-space:nowrap;}}
.reason{{font-size:10.5px;color:{GRAY};}}
.trace{{font-size:11.5px;line-height:1.6;}}
.trace .agent{{display:inline-block;min-width:104px;font-weight:700;}}
.trace .row{{padding:2px 0;border-left:3px solid transparent;padding-left:8px;}}
.trace .row.rej{{border-left-color:{REJ};background:#FDF4F6;}}
.trace .row.loop{{border-left-color:{AMBER};background:#FDF8EE;}}
.kv{{display:flex;flex-wrap:wrap;gap:14px;font-size:12px;color:{GRAY};}}
.kv b{{color:#111;font-variant-numeric:tabular-nums;}}
code{{font-size:11px;background:{LIGHT};padding:1px 5px;border-radius:3px;
     word-break:break-all;}}
.legend{{font-size:11px;color:{GRAY};margin-top:8px;}}
.legend span{{margin-right:14px;}}
.dot{{display:inline-block;width:9px;height:9px;border-radius:2px;
     margin-right:4px;vertical-align:middle;}}
.viol{{font-size:11.5px;padding:5px 8px;border-radius:5px;margin-bottom:4px;}}
.viol.blocking{{background:#FDF4F6;border-left:3px solid {REJ};}}
.viol.warning{{background:#FDF8EE;border-left:3px solid {AMBER};}}
"""


def esc(x):
    return html.escape(str(x))


def render(rec):
    m = rec.get("meta", {})
    clauses = rec.get("clauses", [])
    mol = m.get("molecule", {})
    ctx = m.get("context", {})

    # ── 헤더 ──────────────────────────────────────────────────
    head = (
        f"<h1>먹줄(INKLINE) 감사 화면</h1>"
        f"<div class='sub'>run <code>{esc(rec.get('run_id'))}</code> · "
        f"{esc(ctx.get('phase',''))} · {esc(ctx.get('indication',''))}</div>")

    if mol:
        kv = (
            f"<div class='kv'>"
            f"<span>SMILES <code>{esc(mol.get('smiles'))}</code></span>"
            f"<span>MW <b>{mol.get('mw',0):.1f}</b></span>"
            f"<span>cLogP <b>{mol.get('clogp',0):.2f}</b></span>"
            f"<span>TPSA <b>{mol.get('tpsa',0):.1f}</b></span>"
            f"<span>적용범위 AD <b>{m.get('ad',0):.2f}</b></span>"
            f"<span>구조 경보 <b>{len(m.get('risks',[]))}</b>건</span></div>")
        risks = " · ".join(esc(r["flag"]) for r in m.get("risks", []))
        head += (f"<div class='card'><h2><span class='act'>1막</span>연역 — 입력과 "
                 f"구조 경보</h2>{kv}"
                 f"<div style='margin-top:6px;font-size:12px;color:{GRAY};'>"
                 f"{risks or '경보 없음'}</div></div>")

    # ── 조항 판정표 ───────────────────────────────────────────
    rows = []
    for c in clauses:
        lab, tone = DECISION.get(c.get("decision"), ("?", GRAY))
        ds = "—" if c.get("delta_star") is None else f"{c['delta_star']:+.4f}"
        tr = "—" if c.get("trust") is None else f"{c['trust']:.2f}"
        cls = "분자특이" if c.get("clause_class") == "molecule_specific" else "템플릿"
        rows.append(
            f"<tr><td>{esc(c.get('text') or c.get('clause_type'))}"
            f"<div class='reason'>{esc(c.get('clause_type'))} · {cls}</div></td>"
            f"<td class='num'>{c.get('p_base',0):.3f}</td>"
            f"<td class='num'>{c.get('delta',0):+.4f}</td>"
            f"<td class='num'><b>{ds}</b></td>"
            f"<td class='num'>{tr}</td>"
            f"<td><span class='pill' style='background:{tone}'>{lab}</span>"
            f"<div class='reason'>{esc(c.get('reason_code'))}</div></td></tr>")
    n = {k: sum(1 for c in clauses if c.get("decision") == k)
         for k in DECISION}
    tbl = (
        f"<div class='card'><h2><span class='act'>2막</span>반증 — 조항 판정</h2>"
        f"<table><tr><th>조항</th><th>템플릿 기저</th><th>Δ 증분</th>"
        f"<th>Δ* 구조귀속</th><th>신뢰도 T</th><th>판정</th></tr>"
        + "".join(rows) + "</table>"
        f"<div class='legend'>발행 <b>{n['advance']}</b> · "
        f"사람 검토 <b>{n['escalate']}</b> · 기권 <b>{n['abstain']}</b>"
        f" &nbsp;|&nbsp; 기권율 "
        f"<b>{n['abstain']/max(len(clauses),1):.0%}</b></div></div>")

    # ── 정합성 검사 ───────────────────────────────────────────
    cons = m.get("consistency") or {}
    cons_html = ""
    if cons:
        vs = cons.get("violations", [])
        items = "".join(
            f"<div class='viol {esc(v['severity'])}'><b>[{esc(v['severity'])}] "
            f"{esc(v['code'])}</b> {esc(v['message'])}<br>"
            f"<span class='reason'>→ {esc(v['action'])}</span></div>"
            for v in vs) or (
            f"<div style='font-size:12px;color:{OK};'>위반 없음 — 조항 집합이 "
            f"내부적으로 정합하다</div>")
        cons_html = (f"<div class='card'><h2>조항 집합 정합성</h2>{items}"
                     f"<div class='legend'>발행 가능: "
                     f"<b>{'예' if cons.get('publishable') else '아니오'}</b>"
                     f"</div></div>")

    # ── 실행 추적 ─────────────────────────────────────────────
    trace_rows = []
    for t in rec.get("trace", []):
        step = t.get("step", "")
        cls = ""
        if any(k in step for k in ("반증", "기각", "하향", "철회")):
            cls = "rej"
        elif any(k in step for k in ("라운드", "재기안", "대체", "계약", "수렴")):
            cls = "loop"
        trace_rows.append(
            f"<div class='row {cls}'><span class='agent' "
            f"style='color:{REJ if cls=='rej' else DET}'>{esc(t['agent'])}</span>"
            f"<b>{esc(step)}</b> &nbsp;{esc(t.get('detail',''))}</div>")
    hist = m.get("round_history") or []
    hist_s = " → ".join(
        f"R{h['round']}(발행{h['advance']}·검토{h['escalate']}·기권{h['abstain']}"
        + (f"·하향{h['downgraded']}" if h.get("downgraded") else "") + ")"
        for h in hist)
    trace = (
        f"<div class='card'><h2><span class='act'>3막</span>대조 — 실행 추적</h2>"
        f"<div class='trace'>{''.join(trace_rows)}</div>"
        + (f"<div class='legend' style='margin-top:8px;'>라운드 이력: "
           f"<b>{esc(hist_s)}</b></div>" if hist_s else "")
        + f"<div class='legend'>감사 DAG 해시 "
          f"<code>{esc(rec.get('dag_hash',''))}</code></div>"
        + f"<div class='legend'>도구 버전 "
          f"{esc(m.get('tool_versions',{}))} · 시드 {esc(m.get('seed'))}</div>"
        f"<div class='legend'><span><span class='dot' "
        f"style='background:{DET}'></span>결정론 판정</span>"
        f"<span><span class='dot' style='background:{REJ}'></span>반증 기각·기권</span>"
        f"<span><span class='dot' style='background:{AMBER}'></span>"
        f"되돌아가는 화살표</span></div></div>")

    return (f"<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
            f"<title>먹줄 감사 화면 {esc(rec.get('run_id'))}</title>"
            f"<style>{CSS}</style></head><body><div class='wrap'>"
            + head + tbl + cons_html + trace + "</div></body></html>")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, help="실행 결과 JSON")
    ap.add_argument("--out", required=True, help="출력 HTML")
    args = ap.parse_args()
    rec = json.load(open(args.run, encoding="utf-8"))
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    open(args.out, "w", encoding="utf-8").write(render(rec))
    print(f"생성: {args.out} ({os.path.getsize(args.out):,} bytes)")
    print("외부 스크립트·CDN 없이 열린다. 폐쇄망에서 그대로 사용 가능.")


if __name__ == "__main__":
    main()
