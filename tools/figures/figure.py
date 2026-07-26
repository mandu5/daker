"""제안서용 도식(아키텍처도·플로우·타임라인) 렌더러.

matplotlib 대신 HTML/CSS로 그린 뒤 Chromium으로 고해상도 PNG를 캡처한다.
한글 타이포그래피 품질과 레이아웃 제어력이 훨씬 좋고, 제안서 본문과
같은 디자인 토큰을 공유할 수 있기 때문이다.

인쇄 품질
    제안서 본문 폭 150 mm 에 300 dpi 로 넣으려면 약 1772 px 이 필요하다.
    CSS 폭 590 px + device-scale-factor 3 => 1770 px.
"""

from __future__ import annotations

import base64
import os
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
FONT = os.path.join(REPO, "assets", "fonts", "NotoSansKR[wght].ttf")
CHROME = next(
    (p for p in (
        "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
        "/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome",
    ) if os.path.exists(p)),
    "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
)

# ── 디자인 토큰 (제안서 본문과 공유) ──────────────────────────
TOKENS = {
    "navy": "#0F2B46",
    "navy2": "#1B4A73",
    "blue": "#1F5C99",
    "sky": "#4E9CD6",
    "teal": "#0E7C7B",
    "mint": "#3FAE9E",
    "amber": "#C98A17",
    "rose": "#B5455F",
    "violet": "#6A4C93",
    "ink": "#111111",
    "gray": "#5A5A5A",
    "gray2": "#8A8A8A",
    "line": "#C3D2E0",
    "light": "#EEF3F8",
    "light2": "#F7FAFC",
    "white": "#FFFFFF",
}


def _font_css() -> str:
    if not os.path.exists(FONT):
        return ""
    b64 = base64.b64encode(open(FONT, "rb").read()).decode("ascii")
    return (
        "@font-face{font-family:'NotoKR';src:url(data:font/ttf;base64,%s) "
        "format('truetype');font-weight:100 900;font-style:normal;}" % b64
    )


BASE_CSS = """
*{box-sizing:border-box;margin:0;padding:0;}
html,body{background:#fff;}
body{font-family:'NotoKR',sans-serif;color:%(ink)s;-webkit-font-smoothing:antialiased;}
.fig{padding:2px 0;}
.t{font-weight:700;}
.sub{color:%(gray)s;}
""" % TOKENS


def render(body_html: str, out_png: str, *, width=590, extra_css="", scale=3,
           timeout=180) -> str:
    """HTML 조각을 PNG로 캡처. width 는 CSS px, 실제 픽셀은 width*scale."""
    html = (
        "<!doctype html><html lang='ko'><head><meta charset='utf-8'><style>"
        + _font_css() + BASE_CSS + extra_css +
        f"body{{width:{width}px;}}</style></head><body><div class='fig'>"
        + body_html + "</div></body></html>"
    )
    os.makedirs(os.path.dirname(os.path.abspath(out_png)), exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False,
                                     encoding="utf-8") as f:
        f.write(html)
        tmp = f.name
    try:
        subprocess.run([
            CHROME, "--headless", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
            "--default-background-color=FFFFFFFF",
            f"--force-device-scale-factor={scale}",
            "--virtual-time-budget=20000",
            # 창 높이가 콘텐츠보다 낮으면 아래가 잘린다. 넉넉히 잡고 _trim 으로 정리.
            f"--window-size={width},2400",
            f"--screenshot={out_png}", f"file://{tmp}",
        ], capture_output=True, timeout=timeout)
    finally:
        os.unlink(tmp)
    if not os.path.exists(out_png):
        raise RuntimeError("도식 캡처 실패: " + out_png)
    _trim(out_png)
    return out_png


def _trim(path, pad=6):
    """흰 여백을 잘라내고 약간의 패딩만 남긴다."""
    try:
        from PIL import Image, ImageChops
    except ImportError:
        return
    im = Image.open(path).convert("RGB")
    bg = Image.new("RGB", im.size, (255, 255, 255))
    diff = ImageChops.difference(im, bg)
    box = diff.getbbox()
    if not box:
        return
    l, t, r, b = box
    l, t = max(0, l - pad), max(0, t - pad)
    r, b = min(im.width, r + pad), min(im.height, b + pad)
    out = Image.new("RGB", (r - l, b - t), (255, 255, 255))
    out.paste(im.crop((l, t, r, b)), (0, 0))
    out.save(path)


# ── 자주 쓰는 컴포넌트 ────────────────────────────────────────
def box(label, sub=None, *, bg="light", fg="ink", border="line", w=None,
        pad="8px 10px", radius=7, size=12, sub_size=10, bold=True, grow=None,
        border_w=1.2, style=""):
    st = (
        f"background:{TOKENS.get(bg, bg)};color:{TOKENS.get(fg, fg)};"
        f"border:{border_w}px solid {TOKENS.get(border, border)};"
        f"border-radius:{radius}px;padding:{pad};text-align:center;"
        f"line-height:1.30;font-size:{size}px;"
        + (f"font-weight:{700 if bold else 500};")
        + (f"width:{w}px;" if w else "")
        + (f"flex:{grow};" if grow else "")
        + style
    )
    inner = f"<div>{label}</div>"
    if sub:
        inner += (f"<div style='font-size:{sub_size}px;font-weight:400;opacity:.78;"
                  f"margin-top:2px;'>{sub}</div>")
    return f"<div style=\"{st}\">{inner}</div>"


def row(children, *, gap=8, align="stretch", justify="center", style=""):
    return (
        f"<div style=\"display:flex;gap:{gap}px;align-items:{align};"
        f"justify-content:{justify};{style}\">" + "".join(children) + "</div>"
    )


def col(children, *, gap=8, align="stretch", style=""):
    return (
        f"<div style=\"display:flex;flex-direction:column;gap:{gap}px;"
        f"align-items:{align};{style}\">" + "".join(children) + "</div>"
    )


def arrow(direction="down", label=None, *, color="blue", size=13, length=14):
    c = TOKENS.get(color, color)
    glyph = {"down": "▼", "up": "▲", "right": "▶", "left": "◀"}[direction]
    lbl = (f"<span style='font-size:9.5px;color:{TOKENS['gray']};margin-left:3px;'>"
           f"{label}</span>") if label else ""
    return (f"<div style='text-align:center;color:{c};font-size:{size}px;"
            f"line-height:{length}px;'>{glyph}{lbl}</div>")


def band(text, *, bg="navy", fg="white", size=12, pad="5px 10px", radius=5):
    return (f"<div style='background:{TOKENS.get(bg, bg)};color:{TOKENS.get(fg, fg)};"
            f"font-weight:700;font-size:{size}px;padding:{pad};border-radius:{radius}px;"
            f"letter-spacing:.01em;'>{text}</div>")


def caption(text, size=9.5):
    return (f"<div style='font-size:{size}px;color:{TOKENS['gray']};margin-top:5px;"
            f"text-align:center;'>{text}</div>")
