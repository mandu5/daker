"""제안서 .hwpx 생성기.

대회에서 배포한 제안서 템플릿(assets/proposal_template.hwpx)을 베이스로 삼아
header.xml 에 우리 스타일을 주입하고 section0.xml 을 통째로 생성한다.
템플릿의 secPr(용지·여백 설정)는 그대로 승계하므로 심사자가 여는 문서의
페이지 기하 구조는 배포본과 동일하다.

블록 DSL
    {"type": "title",   "text": ..., "subtitle": ...}
    {"type": "metatable", "rows": [(label, value), ...]}
    {"type": "h1",      "text": "1. ...", "no": "01"}
    {"type": "h2",      "text": ...}
    {"type": "h3",      "text": ...}
    {"type": "p",       "text": ...}            # **굵게**, __강조__ 인라인 지원
    {"type": "ul",      "items": [...], "level": 1}
    {"type": "table",   "header": [...], "rows": [[...]], "widths": [...],
                        "caption": ..., "align": ["c","l",...], "dark_header": bool}
    {"type": "img",     "path": ..., "width_mm": ..., "caption": ...}
    {"type": "callout", "text": ..., "title": ...}
    {"type": "spacer",  "h": 200}
    {"type": "pagebreak"}
"""

from __future__ import annotations

import io
import os
import re
import shutil
import zipfile
from dataclasses import dataclass, field

from styles import (
    BASE_BORDERFILL_CNT, BASE_CHARPR_CNT, BASE_PARAPR_CNT,
    EXTRA_BORDERFILLS, EXTRA_CHARPRS, EXTRA_PARAPRS, HWPUNIT_PER_MM,
    BF_TBL_HEAD, BF_TBL_CELL, BF_TBL_ALT, BF_CALLOUT, BF_NONE, BF_BAND,
    BF_TBL_HEAD_D, BF_ACCENT,
    CP_BODY, CP_BODY_B, CP_BODY_ACC, CP_H1, CP_H2, CP_TH, CP_TD, CP_TD_B,
    CP_CAPTION, CP_TITLE, CP_SUBTITLE, CP_SMALL, CP_SMALL_B, CP_H3, CP_TH_D,
    CP_META_K, CP_META_V, CP_TD_ACC, CP_TINY, CP_BODY_GRAY,
    PP_BODY, PP_H1, PP_H2, PP_UL1, PP_UL2, PP_TD_C, PP_TD_L, PP_CAPTION,
    PP_CENTER, PP_TIGHT, PP_FIG, PP_H3, PP_TITLE, PP_UL1_TIGHT, PP_TD_R,
    PP_BODY_TIGHT, PP_PAGEBREAK,
)

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
TEMPLATE = os.path.join(REPO, "assets", "proposal_template.hwpx")

# 템플릿 용지 기하 (HWPUNIT)
PAGE_W, PAGE_H = 59528, 84188
MARGIN = dict(left=8504, right=8504, top=5668, bottom=4252, header=4252, footer=4252)
TEXT_W = PAGE_W - MARGIN["left"] - MARGIN["right"]           # 42520
TEXT_H = PAGE_H - MARGIN["top"] - MARGIN["bottom"] - MARGIN["header"] - MARGIN["footer"]
TABLE_W = 42520

_ESC = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}


def esc(s: str) -> str:
    return "".join(_ESC.get(c, c) for c in str(s))


# ── 인라인 마크업 ─────────────────────────────────────────────
_INLINE = re.compile(r"(\*\*.+?\*\*|__.+?__|~~.+?~~)", re.S)


def runs(text: str, base_cp: int, bold_cp: int, acc_cp: int, gray_cp: int | None = None) -> str:
    """**굵게** / __강조색__ / ~~회색~~ 인라인 마크업을 run 시퀀스로 변환."""
    out = []
    for part in _INLINE.split(str(text)):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            cp, body = bold_cp, part[2:-2]
        elif part.startswith("__") and part.endswith("__") and len(part) > 4:
            cp, body = acc_cp, part[2:-2]
        elif part.startswith("~~") and part.endswith("~~") and len(part) > 4:
            cp, body = (gray_cp or base_cp), part[2:-2]
        else:
            cp, body = base_cp, part
        out.append(f'<hp:run charPrIDRef="{cp}"><hp:t>{esc(body)}</hp:t></hp:run>')
    return "".join(out) or f'<hp:run charPrIDRef="{base_cp}"><hp:t></hp:t></hp:run>'


def strip_markup(text: str) -> str:
    return re.sub(r"\*\*|__|~~", "", str(text))


class IdGen:
    def __init__(self, start=1000000000):
        self.n = start

    def __call__(self):
        self.n += 7
        return self.n


@dataclass
class Builder:
    idgen: IdGen = field(default_factory=IdGen)
    paras: list = field(default_factory=list)
    images: list = field(default_factory=list)   # (item_id, filename, bytes, w_px, h_px)
    _secpr: str = ""

    # ── 문단 primitive ────────────────────────────────────────
    def para(self, parapr: int, inner: str, style=0) -> None:
        self.paras.append(
            f'<hp:p id="{self.idgen()}" paraPrIDRef="{parapr}" styleIDRef="{style}" '
            f'pageBreak="0" columnBreak="0" merged="0">{inner}</hp:p>'
        )

    def text_para(self, parapr: int, text: str, cp=CP_BODY, cp_b=CP_BODY_B,
                  cp_a=CP_BODY_ACC) -> None:
        self.para(parapr, runs(text, cp, cp_b, cp_a, CP_BODY_GRAY))

    def empty(self, parapr=PP_TIGHT, cp=CP_TINY) -> None:
        self.para(parapr, f'<hp:run charPrIDRef="{cp}"><hp:t></hp:t></hp:run>')

    # ── 표 ────────────────────────────────────────────────────
    def _cell(self, text, *, w, h, col, row, cp, pp, bf, colspan=1, rowspan=1,
              valign="CENTER", margin=(510, 510, 200, 200)):
        ml, mr, mt, mb = margin
        lines = str(text).split("\n")
        inner = "".join(
            f'<hp:p id="{self.idgen()}" paraPrIDRef="{pp}" styleIDRef="0" '
            f'pageBreak="0" columnBreak="0" merged="0">'
            f"{runs(ln, cp, CP_TD_B if cp == CP_TD else cp, CP_TD_ACC, CP_TINY)}</hp:p>"
            for ln in lines
        )
        return (
            f'<hp:tc name="" header="0" hasMargin="1" protect="0" editable="0" dirty="0" '
            f'borderFillIDRef="{bf}">'
            f'<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" '
            f'vertAlign="{valign}" linkListIDRef="0" linkListNextIDRef="0" textWidth="0" '
            f'textHeight="0" hasTextRef="0" hasNumRef="0">{inner}</hp:subList>'
            f'<hp:cellAddr colAddr="{col}" rowAddr="{row}"/>'
            f'<hp:cellSpan colSpan="{colspan}" rowSpan="{rowspan}"/>'
            f'<hp:cellSz width="{w}" height="{h}"/>'
            f'<hp:cellMargin left="{ml}" right="{mr}" top="{mt}" bottom="{mb}"/>'
            "</hp:tc>"
        )

    def table(self, header, rows, widths=None, *, align=None, caption=None,
              dark_header=True, cp_head=None, cp_body=CP_TD, row_h=1100,
              head_h=1100, zebra=True, pp_body=None, total_w=TABLE_W,
              cell_margin=(510, 510, 200, 200)):
        ncol = len(header) if header else len(rows[0])
        if widths is None:
            widths = [total_w // ncol] * ncol
        else:
            s = sum(widths)
            widths = [int(w * total_w / s) for w in widths]
            widths[-1] += total_w - sum(widths)
        align = align or ["c"] * ncol
        pp_map = {"c": PP_TD_C, "l": PP_TD_L, "r": PP_TD_R}
        cp_head = cp_head or (CP_TH_D if dark_header else CP_TH)
        bf_head = BF_TBL_HEAD_D if dark_header else BF_TBL_HEAD

        trs = []
        r = 0
        if header:
            cells = "".join(
                self._cell(h, w=widths[c], h=head_h, col=c, row=0, cp=cp_head,
                           pp=PP_TD_C, bf=bf_head, margin=cell_margin)
                for c, h in enumerate(header)
            )
            trs.append(f"<hp:tr>{cells}</hp:tr>")
            r = 1
        for i, row in enumerate(rows):
            bf = BF_TBL_ALT if (zebra and i % 2 == 1) else BF_TBL_CELL
            cells = "".join(
                self._cell(v, w=widths[c], h=row_h, col=c, row=r, cp=cp_body,
                           pp=(pp_body[c] if pp_body else pp_map[align[c]]),
                           bf=bf, valign="CENTER", margin=cell_margin)
                for c, v in enumerate(row)
            )
            trs.append(f"<hp:tr>{cells}</hp:tr>")
            r += 1

        nrow = len(rows) + (1 if header else 0)
        total_h = head_h * (1 if header else 0) + row_h * len(rows)
        tbl = (
            f'<hp:tbl id="{self.idgen()}" zOrder="0" numberingType="TABLE" '
            f'textWrap="TOP_AND_BOTTOM" textFlow="BOTH_SIDES" lock="0" '
            f'dropcapstyle="None" pageBreak="CELL" repeatHeader="1" rowCnt="{nrow}" '
            f'colCnt="{ncol}" cellSpacing="0" borderFillIDRef="{BF_TBL_CELL}" noAdjust="0">'
            f'<hp:sz width="{total_w}" widthRelTo="ABSOLUTE" height="{total_h}" '
            f'heightRelTo="ABSOLUTE" protect="0"/>'
            '<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" '
            'holdAnchorAndSO="0" vertRelTo="PARA" horzRelTo="COLUMN" vertAlign="TOP" '
            'horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
            '<hp:outMargin left="0" right="0" top="0" bottom="0"/>'
            '<hp:inMargin left="0" right="0" top="0" bottom="0"/>'
            + "".join(trs)
            + "</hp:tbl>"
        )
        self.para(PP_FIG if caption else PP_TIGHT,
                  f'<hp:run charPrIDRef="{CP_TD}">{tbl}</hp:run>')
        if caption:
            self.text_para(PP_CAPTION, caption, cp=CP_CAPTION, cp_b=CP_CAPTION,
                           cp_a=CP_CAPTION)

    # ── 이미지 ────────────────────────────────────────────────
    def image(self, path, width_mm=150.0, caption=None):
        from PIL import Image  # 지연 임포트

        with Image.open(path) as im:
            px_w, px_h = im.size
        data = open(path, "rb").read()
        item_id = f"image{len(self.images) + 1}"
        ext = os.path.splitext(path)[1].lower().lstrip(".") or "png"
        fname = f"{item_id}.{ext}"
        self.images.append((item_id, fname, data, px_w, px_h))

        w = int(width_mm * HWPUNIT_PER_MM)
        w = min(w, TEXT_W)
        h = int(w * px_h / px_w)
        pic = (
            f'<hp:pic id="{self.idgen()}" zOrder="0" numberingType="PICTURE" '
            f'textWrap="TOP_AND_BOTTOM" textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" '
            f'href="" groupLevel="0" instid="{self.idgen()}" reverse="0">'
            '<hp:offset x="0" y="0"/>'
            f'<hp:orgSz width="{w}" height="{h}"/>'
            f'<hp:curSz width="{w}" height="{h}"/>'
            '<hp:flip horizontal="0" vertical="0"/>'
            '<hp:rotationInfo angle="0" centerX="0" centerY="0" rotateimage="1"/>'
            '<hp:renderingInfo>'
            '<hc:transMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>'
            '<hc:scaMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>'
            '<hc:rotMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>'
            "</hp:renderingInfo>"
            f'<hc:img binaryItemIDRef="{item_id}" bright="0" contrast="0" effect="REAL_PIC" alpha="0"/>'
            '<hp:imgRect>'
            '<hc:pt0 x="0" y="0"/>'
            f'<hc:pt1 x="{w}" y="0"/>'
            f'<hc:pt2 x="{w}" y="{h}"/>'
            f'<hc:pt3 x="0" y="{h}"/>'
            "</hp:imgRect>"
            '<hp:imgClip left="0" right="0" top="0" bottom="0"/>'
            '<hp:inMargin left="0" right="0" top="0" bottom="0"/>'
            f'<hp:imgDim dimwidth="{w}" dimheight="{h}"/>'
            f'<hp:sz width="{w}" widthRelTo="ABSOLUTE" height="{h}" heightRelTo="ABSOLUTE" protect="0"/>'
            '<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" '
            'holdAnchorAndSO="0" vertRelTo="PARA" horzRelTo="COLUMN" vertAlign="TOP" '
            'horzAlign="CENTER" vertOffset="0" horzOffset="0"/>'
            '<hp:outMargin left="0" right="0" top="0" bottom="0"/>'
            "</hp:pic>"
        )
        self.para(PP_FIG, f'<hp:run charPrIDRef="{CP_BODY}">{pic}</hp:run>')
        if caption:
            self.text_para(PP_CAPTION, caption, cp=CP_CAPTION, cp_b=CP_CAPTION,
                           cp_a=CP_CAPTION)
        return w, h

    # ── 고수준 블록 ───────────────────────────────────────────
    def h1(self, text, no=None):
        """섹션 제목: 남색 밴드 1행 표."""
        label = f"{no}  {text}" if no else text
        self.table(None, [[label]], widths=[1], align=["l"],
                   cp_body=CP_H1, row_h=1500, zebra=False,
                   pp_body=[PP_TD_L], cell_margin=(400, 300, 150, 150))
        # 밴드 셀 색을 남색으로: 마지막 표의 borderFill 교체
        self.paras[-1] = self.paras[-1].replace(
            f'borderFillIDRef="{BF_TBL_CELL}"', f'borderFillIDRef="{BF_BAND}"')

    def h2(self, text):
        self.text_para(PP_H2, "▌ " + text, cp=CP_H2, cp_b=CP_H2, cp_a=CP_H2)

    def h3(self, text):
        self.text_para(PP_H3, text, cp=CP_H3, cp_b=CP_H3, cp_a=CP_BODY_ACC)

    def p(self, text, tight=False):
        self.text_para(PP_BODY_TIGHT if tight else PP_BODY, text)

    def ul(self, items, level=1, tight=False):
        marks = {1: "· ", 2: "- "}
        pp = (PP_UL1 if level == 1 else PP_UL2)
        if tight:
            pp = PP_UL1_TIGHT if level == 1 else PP_UL2
        for it in items:
            self.text_para(pp, marks.get(level, "· ") + str(it))

    def callout(self, text, title=None):
        body = (f"**{title}**  " if title else "") + text
        self.table(None, [[body]], widths=[1], align=["l"], cp_body=CP_BODY,
                   row_h=900, zebra=False, pp_body=[PP_TD_L],
                   cell_margin=(500, 500, 300, 300))
        self.paras[-1] = self.paras[-1].replace(
            f'borderFillIDRef="{BF_TBL_CELL}"', f'borderFillIDRef="{BF_ACCENT}"')

    def spacer(self, h=200):
        self.empty()

    def pagebreak(self):
        self.para(PP_PAGEBREAK, f'<hp:run charPrIDRef="{CP_TINY}"><hp:t></hp:t></hp:run>')

    # ── 조립 ──────────────────────────────────────────────────
    def render_blocks(self, blocks):
        for b in blocks:
            t = b["type"]
            if t == "h1":
                self.h1(b["text"], b.get("no"))
            elif t == "h2":
                self.h2(b["text"])
            elif t == "h3":
                self.h3(b["text"])
            elif t == "p":
                self.p(b["text"], tight=b.get("tight", False))
            elif t == "fine":
                # 참고문헌·주석용 작은 서체. 본문 13pt 를 그대로 쓰면 지면 낭비다.
                self.text_para(PP_TIGHT, b["text"], cp=CP_CAPTION,
                               cp_b=CP_CAPTION, cp_a=CP_CAPTION)
            elif t == "ul":
                self.ul(b["items"], b.get("level", 1), tight=b.get("tight", False))
            elif t == "table":
                self.table(b.get("header"), b["rows"], b.get("widths"),
                           align=b.get("align"), caption=b.get("caption"),
                           dark_header=b.get("dark_header", True),
                           row_h=b.get("row_h", 1100),
                           head_h=b.get("head_h", 1100),
                           zebra=b.get("zebra", True))
            elif t == "img":
                self.image(b["path"], b.get("width_mm", 150.0), b.get("caption"))
            elif t == "callout":
                self.callout(b["text"], b.get("title"))
            elif t == "spacer":
                self.spacer(b.get("h", 200))
            elif t == "pagebreak":
                self.pagebreak()
            elif t == "raw_para":
                self.para(b["parapr"], b["inner"])
            else:
                raise ValueError(f"unknown block type: {t}")


# ── 패키지 생성 ───────────────────────────────────────────────
def _inject_header(header_xml: str) -> str:
    h = header_xml
    h = h.replace(
        f'<hh:borderFills itemCnt="{BASE_BORDERFILL_CNT}">',
        f'<hh:borderFills itemCnt="{BASE_BORDERFILL_CNT + len(EXTRA_BORDERFILLS)}">')
    h = h.replace("</hh:borderFills>", "".join(EXTRA_BORDERFILLS) + "</hh:borderFills>")
    h = h.replace(
        f'<hh:charProperties itemCnt="{BASE_CHARPR_CNT}">',
        f'<hh:charProperties itemCnt="{BASE_CHARPR_CNT + len(EXTRA_CHARPRS)}">')
    h = h.replace("</hh:charProperties>", "".join(EXTRA_CHARPRS) + "</hh:charProperties>")
    h = h.replace(
        f'<hh:paraProperties itemCnt="{BASE_PARAPR_CNT}">',
        f'<hh:paraProperties itemCnt="{BASE_PARAPR_CNT + len(EXTRA_PARAPRS)}">')
    h = h.replace("</hh:paraProperties>", "".join(EXTRA_PARAPRS) + "</hh:paraProperties>")
    return h


def _extract_secpr(section_xml: str) -> str:
    i = section_xml.index("<hp:secPr ")
    j = section_xml.index("</hp:secPr>") + len("</hp:secPr>")
    # secPr 뒤에 붙는 ctrl(머리말 등)까지는 가져오지 않는다.
    return section_xml[i:j]


SECTION_HEAD = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
    '<hs:sec xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app" '
    'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" '
    'xmlns:hp10="http://www.hancom.co.kr/hwpml/2016/paragraph" '
    'xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
    'xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core" '
    'xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head" '
    'xmlns:hhs="http://www.hancom.co.kr/hwpml/2011/history" '
    'xmlns:hm="http://www.hancom.co.kr/hwpml/2011/master-page" '
    'xmlns:hpf="http://www.hancom.co.kr/schema/2011/hpf" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/" '
    'xmlns:opf="http://www.idpf.org/2007/opf/" '
    'xmlns:ooxmlchart="http://www.hancom.co.kr/hwpml/2016/ooxmlchart" '
    'xmlns:hwpunitchar="http://www.hancom.co.kr/hwpml/2016/HwpUnitChar" '
    'xmlns:epub="http://www.idpf.org/2007/ops" '
    'xmlns:config="urn:oasis:names:tc:opendocument:xmlns:config:1.0">'
)

MEDIA = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
         "gif": "image/gif", "bmp": "image/bmp"}


def build(blocks, out_path, *, template=TEMPLATE, title="AI 신약개발 경진대회 제안서",
          preview_text=""):
    zin = zipfile.ZipFile(template, "r")
    names = zin.namelist()
    header_xml = zin.read("Contents/header.xml").decode("utf-8")
    section_xml = zin.read("Contents/section0.xml").decode("utf-8")
    content_hpf = zin.read("Contents/content.hpf").decode("utf-8")

    b = Builder()
    b.render_blocks(blocks)

    secpr = _extract_secpr(section_xml)
    # 첫 문단에 secPr 을 실어 보낸다 (템플릿과 동일한 구조)
    first = b.paras[0]
    m = re.match(r'(<hp:p [^>]*>)(.*)$', first, re.S)
    b.paras[0] = (
        m.group(1) + f'<hp:run charPrIDRef="{CP_BODY}">{secpr}</hp:run>' + m.group(2)
    )
    new_section = SECTION_HEAD + "".join(b.paras) + "</hs:sec>"
    new_header = _inject_header(header_xml)

    # content.hpf 에 이미지 매니페스트 추가
    if b.images:
        items = "".join(
            f'<opf:item id="{iid}" href="BinData/{fn}" '
            f'media-type="{MEDIA.get(fn.rsplit(".", 1)[-1], "image/png")}" isEmbeded="1"/>'
            for iid, fn, _d, _w, _h in b.images
        )
        content_hpf = content_hpf.replace("</opf:manifest>", items + "</opf:manifest>")

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zout:
        # mimetype 은 무압축 선두 엔트리
        zout.writestr(zipfile.ZipInfo("mimetype"), zin.read("mimetype"),
                      compress_type=zipfile.ZIP_STORED)
        for n in names:
            if n == "mimetype":
                continue
            if n == "Contents/header.xml":
                zout.writestr(n, new_header.encode("utf-8"))
            elif n == "Contents/section0.xml":
                zout.writestr(n, new_section.encode("utf-8"))
            elif n == "Contents/content.hpf":
                zout.writestr(n, content_hpf.encode("utf-8"))
            elif n == "Preview/PrvText.txt":
                zout.writestr(n, (preview_text or title).encode("utf-8"))
            else:
                zout.writestr(n, zin.read(n))
        for iid, fn, data, _w, _h in b.images:
            zout.writestr(f"BinData/{fn}", data)
    zin.close()
    return out_path, b


def validate(path):
    """생성된 hwpx 의 기본 무결성 점검."""
    import xml.etree.ElementTree as ET

    problems = []
    with zipfile.ZipFile(path) as z:
        bad = z.testzip()
        if bad:
            problems.append(f"손상된 엔트리: {bad}")
        need = ["mimetype", "version.xml", "META-INF/container.xml",
                "Contents/content.hpf", "Contents/header.xml", "Contents/section0.xml"]
        for n in need:
            if n not in z.namelist():
                problems.append(f"누락: {n}")
        if z.read("mimetype") != b"application/hwp+zip":
            problems.append("mimetype 불일치: %r" % z.read("mimetype")[:40])
        for n in z.namelist():
            if n.endswith(".xml") or n.endswith(".hpf"):
                try:
                    ET.fromstring(z.read(n))
                except ET.ParseError as e:
                    problems.append(f"XML 파싱 실패 {n}: {e}")
        hpf = z.read("Contents/content.hpf").decode("utf-8")
        for m in re.finditer(r'href="(BinData/[^"]+)"', hpf):
            if m.group(1) not in z.namelist():
                problems.append(f"매니페스트가 가리키는 파일 없음: {m.group(1)}")
        sec = z.read("Contents/section0.xml").decode("utf-8")
        for m in re.finditer(r'binaryItemIDRef="([^"]+)"', sec):
            if f'id="{m.group(1)}"' not in hpf:
                problems.append(f"미등록 이미지 참조: {m.group(1)}")
    return problems
