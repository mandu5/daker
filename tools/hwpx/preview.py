"""동일한 블록 DSL을 HTML/PDF로 렌더링하는 미리보기 생성기.

한글(HWP)을 컨테이너에서 실행할 수 없으므로, 제출본과 **같은 용지 기하**로
HTML을 만들어 Chromium으로 PDF를 뽑아 (1) 시각적 완성도 확인 (2) 쪽수 검증을 한다.

용지 기하 (템플릿 secPr 기준)
    A4 210 x 297 mm
    좌/우 여백 30 mm, 위 여백 20 mm + 머리말 15 mm = 35 mm, 아래 15 + 꼬리말 15 = 30 mm
    → 본문 폭 150 mm, 본문 높이 232 mm

주의: 함초롬돋움을 쓸 수 없어 Noto Sans KR로 대체한다. 한글은 전각 기준이라
자간·행수는 거의 동일하지만, 라틴 문자 비중이 높은 줄에서는 오차가 생길 수 있다.
따라서 쪽수는 항상 여유를 두고 판단한다.
"""

from __future__ import annotations

import base64
import html
import os
import re
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
FONT = os.path.join(REPO, "assets", "fonts", "NotoSansKR[wght].ttf")
CHROME = next(
    (p for p in (
        "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
        "/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell",
        "/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome",
    ) if os.path.exists(p)),
    "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
)

NAVY = "#0F2B46"
BLUE = "#1F5C99"
INK = "#111111"
GRAY = "#5A5A5A"
LIGHT = "#EEF3F8"
LINE = "#9AB2C8"

_INLINE = re.compile(r"(\*\*.+?\*\*|__.+?__|~~.+?~~)", re.S)


def inline(text: str) -> str:
    out = []
    for part in _INLINE.split(str(text)):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            out.append("<b>%s</b>" % html.escape(part[2:-2]))
        elif part.startswith("__") and part.endswith("__") and len(part) > 4:
            out.append('<b class="acc">%s</b>' % html.escape(part[2:-2]))
        elif part.startswith("~~") and part.endswith("~~") and len(part) > 4:
            out.append('<span class="gray">%s</span>' % html.escape(part[2:-2]))
        else:
            out.append(html.escape(part))
    return "".join(out)


def _font_css() -> str:
    if not os.path.exists(FONT):
        return ""
    b64 = base64.b64encode(open(FONT, "rb").read()).decode("ascii")
    return (
        "@font-face{font-family:'NotoKR';src:url(data:font/ttf;base64,%s) format('truetype');"
        "font-weight:100 900;font-style:normal;}" % b64
    )


CSS = """
*{box-sizing:border-box;}
@page{size:A4;margin:35mm 30mm 30mm 30mm;}
html,body{margin:0;padding:0;}
body{font-family:'NotoKR','Noto Sans KR',sans-serif;font-size:13pt;line-height:1.30;
     color:%(INK)s;text-align:justify;word-break:keep-all;}
p{margin:0 0 0.8mm 0;}
p.body{margin:0 0 0.81mm 0;}
p.tight{margin:0 0 0.32mm 0;}
p.fine{font-size:9pt;line-height:1.32;color:%(GRAY)s;margin:0 0 0.4mm 0;}
h1.band{background:%(NAVY)s;color:#fff;font-size:14pt;font-weight:700;
        padding:1.7mm 3.2mm;margin:0 0 2.0mm 0;border-radius:0.6mm;
        break-after:avoid;line-height:1.30;}
h1.band .no{opacity:.62;font-weight:700;margin-right:2.2mm;letter-spacing:.02em;}
h2{font-size:13pt;font-weight:700;color:%(NAVY)s;margin:2.9mm 0 1.2mm 0;
   break-after:avoid;line-height:1.30;}
h3{font-size:13pt;font-weight:700;color:%(INK)s;margin:2.0mm 0 0.9mm 0;
   break-after:avoid;line-height:1.30;}
ul{margin:0 0 0.9mm 0;padding-left:5.6mm;}
li{margin:0 0 0.38mm 0;line-height:1.30;}
table{border-collapse:collapse;width:100%%;margin:1.2mm 0 0 0;font-size:10pt;
      line-height:1.25;break-inside:avoid;}
th{background:%(NAVY)s;color:#fff;font-weight:700;border:0.12mm solid %(LINE)s;
   padding:1.0mm 1.8mm;text-align:center;}
th.lightth{background:#DCE7F1;color:%(NAVY)s;}
td{border:0.12mm solid %(LINE)s;padding:1.0mm 1.8mm;vertical-align:middle;}
tr.alt td{background:#F7FAFC;}
td.c{text-align:center;} td.l{text-align:left;} td.r{text-align:right;}
.cap{font-size:9pt;color:%(GRAY)s;text-align:center;margin:0.7mm 0 2.6mm 0;}
.figure{text-align:center;margin:1.4mm 0 0 0;break-inside:avoid;}
.figure img{max-width:100%%;}
.callout{background:%(LIGHT)s;border-left:0.5mm solid %(BLUE)s;padding:1.9mm 3.0mm;
         margin:1.4mm 0 2.4mm 0;font-size:13pt;line-height:1.30;break-inside:avoid;}
.acc{color:%(BLUE)s;}
.gray{color:%(GRAY)s;}
.pagebreak{break-before:page;}
.title{font-size:20pt;font-weight:700;color:%(NAVY)s;text-align:center;margin:0 0 1.2mm 0;}
.subtitle{font-size:11pt;color:%(GRAY)s;text-align:center;margin:0 0 3mm 0;}
""" % dict(INK=INK, NAVY=NAVY, LINE=LINE, GRAY=GRAY, LIGHT=LIGHT, BLUE=BLUE)


def render_html(blocks, *, title="제안서 미리보기") -> str:
    out = []
    for b in blocks:
        t = b["type"]
        if t == "h1":
            no = f'<span class="no">{html.escape(str(b["no"]))}</span>' if b.get("no") else ""
            out.append(f'<h1 class="band">{no}{inline(b["text"])}</h1>')
        elif t == "h2":
            out.append(f"<h2>▌ {inline(b['text'])}</h2>")
        elif t == "h3":
            out.append(f"<h3>{inline(b['text'])}</h3>")
        elif t == "p":
            cls = "tight" if b.get("tight") else "body"
            out.append(f'<p class="{cls}">{inline(b["text"])}</p>')
        elif t == "fine":
            out.append(f'<p class="fine">{inline(b["text"])}</p>')
        elif t == "ul":
            lis = "".join(f"<li>{inline(i)}</li>" for i in b["items"])
            out.append(f"<ul>{lis}</ul>")
        elif t == "table":
            align = b.get("align") or ["c"] * len(b["rows"][0])
            thcls = "" if b.get("dark_header", True) else ' class="lightth"'
            head = ""
            if b.get("header"):
                head = "<tr>" + "".join(
                    f"<th{thcls}>{inline(h)}</th>" for h in b["header"]) + "</tr>"
            body = ""
            for i, row in enumerate(b["rows"]):
                cls = ' class="alt"' if (b.get("zebra", True) and i % 2 == 1) else ""
                tds = "".join(
                    f'<td class="{align[c]}">{inline(v).replace(chr(10), "<br>")}</td>'
                    for c, v in enumerate(row))
                body += f"<tr{cls}>{tds}</tr>"
            colg = ""
            if b.get("widths"):
                s = sum(b["widths"])
                colg = "<colgroup>" + "".join(
                    f'<col style="width:{w / s * 100:.3f}%">' for w in b["widths"]
                ) + "</colgroup>"
            out.append(f"<table>{colg}{head}{body}</table>")
            out.append(f'<div class="cap">{inline(b["caption"])}</div>'
                       if b.get("caption") else '<div style="height:2.4mm"></div>')
        elif t == "img":
            p = b["path"]
            ext = os.path.splitext(p)[1].lstrip(".").lower() or "png"
            data = base64.b64encode(open(p, "rb").read()).decode("ascii")
            w = b.get("width_mm", 150.0)
            out.append(
                f'<div class="figure"><img src="data:image/{ext};base64,{data}" '
                f'style="width:{w}mm"></div>')
            out.append(f'<div class="cap">{inline(b["caption"])}</div>'
                       if b.get("caption") else '<div style="height:2.4mm"></div>')
        elif t == "callout":
            ttl = f"<b>{html.escape(b['title'])}</b>  " if b.get("title") else ""
            out.append(f'<div class="callout">{ttl}{inline(b["text"])}</div>')
        elif t == "spacer":
            out.append('<div style="height:%.2fmm"></div>' % (b.get("h", 200) / 283.46))
        elif t == "pagebreak":
            out.append('<div class="pagebreak"></div>')
        elif t == "raw_para":
            pass
    return (
        "<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
        f"<title>{html.escape(title)}</title><style>{_font_css()}{CSS}</style></head>"
        f"<body>{''.join(out)}</body></html>"
    )


def to_pdf(html_path, pdf_path, timeout=180):
    cmd = [
        CHROME, "--headless", "--disable-gpu", "--no-sandbox",
        "--no-pdf-header-footer", "--run-all-compositor-stages-before-draw",
        "--virtual-time-budget=20000",
        f"--print-to-pdf={pdf_path}", f"file://{os.path.abspath(html_path)}",
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if not os.path.exists(pdf_path):
        raise RuntimeError("PDF 생성 실패:\n" + r.stderr.decode("utf-8", "replace")[-3000:])
    return pdf_path


def pdf_page_count(pdf_path) -> int:
    data = open(pdf_path, "rb").read()
    counts = [int(m.group(1)) for m in re.finditer(rb"/Count\s+(\d+)", data)]
    if counts:
        return max(counts)
    return len(re.findall(rb"/Type\s*/Page[^s]", data))


def screenshot(html_path, png_path, width=794, timeout=180):
    """미리보기 HTML을 통짜 PNG로 저장 (육안 확인용)."""
    cmd = [
        CHROME, "--headless", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
        "--virtual-time-budget=20000", f"--window-size={width},1123",
        f"--screenshot={png_path}", f"file://{os.path.abspath(html_path)}",
    ]
    subprocess.run(cmd, capture_output=True, timeout=timeout)
    if not os.path.exists(png_path):
        raise RuntimeError("스크린샷 생성 실패")
    return png_path


def split_pdf_pages_png(pdf_path, out_dir, prefix="page"):
    """PDF를 쪽별 PNG로 (poppler 있을 때만). 없으면 빈 리스트."""
    if not shutil_which("pdftoppm"):
        return []
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.join(out_dir, prefix)
    subprocess.run(["pdftoppm", "-png", "-r", "110", pdf_path, base],
                   capture_output=True, timeout=300)
    return sorted(
        os.path.join(out_dir, f) for f in os.listdir(out_dir)
        if f.startswith(prefix) and f.endswith(".png")
    )


def shutil_which(name):
    from shutil import which
    return which(name)


def preview(blocks, out_dir, name="proposal", title="제안서 미리보기", png=True):
    os.makedirs(out_dir, exist_ok=True)
    hp = os.path.join(out_dir, f"{name}.html")
    pp = os.path.join(out_dir, f"{name}.pdf")
    open(hp, "w", encoding="utf-8").write(render_html(blocks, title=title))
    to_pdf(hp, pp)
    if png:
        try:
            screenshot(hp, os.path.join(out_dir, f"{name}.png"))
        except Exception:
            pass
    return hp, pp, pdf_page_count(pp)
