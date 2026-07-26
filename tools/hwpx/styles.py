"""HWPX 스타일 정의.

제출 양식이 요구하는 서식(함초롬돋움 13pt, 줄간격 130%)을 기준으로,
템플릿 header.xml에 추가로 주입할 borderFill / charPr / paraPr 를 정의한다.

단위
  - charPr height : 1/100 pt  (1300 = 13pt)
  - HWPUNIT       : 1/7200 inch (1 mm = 283.465)
"""

HWPUNIT_PER_MM = 7200.0 / 25.4  # 283.4646

# 템플릿이 이미 가진 개수 (header.xml itemCnt 기준)
BASE_BORDERFILL_CNT = 6
BASE_CHARPR_CNT = 18
BASE_PARAPR_CNT = 27

# 함초롬돋움 = fontface 내 font id 0, 함초롬바탕 = 1
FONT_DOTUM = 0
FONT_BATANG = 1

# ── 색상 팔레트 ────────────────────────────────────────────────
NAVY = "#0F2B46"      # 섹션 제목 밴드
BLUE = "#1F5C99"      # 강조
TEAL = "#0E7C7B"      # 보조 강조
INK = "#111111"       # 본문
GRAY = "#5A5A5A"      # 캡션
LIGHT = "#EEF3F8"     # 표 짝수행 / 콜아웃 배경
BAND = "#DCE7F1"      # 표 헤더 배경(옅은 버전)
LINE = "#9AB2C8"      # 표 테두리
GOLD = "#B8860B"


def _border(color=LINE, width="0.12 mm", type_="SOLID"):
    return f'type="{type_}" width="{width}" color="{color}"'


def borderfill(idx, *, left=None, right=None, top=None, bottom=None, fill=None):
    """borderFill 정의 XML 생성. left/right/top/bottom 은 (type,width,color) 또는 None."""

    def b(tag, spec):
        if spec is None:
            return f'<hh:{tag} type="NONE" width="0.1 mm" color="#000000"/>'
        t, w, c = spec
        return f'<hh:{tag} type="{t}" width="{w}" color="{c}"/>'

    fill_xml = ""
    if fill:
        fill_xml = (
            '<hh:fillBrush><hc:winBrush faceColor="%s" hatchColor="#333333" alpha="0"/>'
            "</hh:fillBrush>" % fill
        )
    return (
        f'<hh:borderFill id="{idx}" threeD="0" shadow="0" centerLine="NONE" '
        f'breakCellSeparateLine="0">'
        '<hh:slash type="NONE" Crooked="0" isCounter="0"/>'
        '<hh:backSlash type="NONE" Crooked="0" isCounter="0"/>'
        + b("leftBorder", left)
        + b("rightBorder", right)
        + b("topBorder", top)
        + b("bottomBorder", bottom)
        + '<hh:diagonal type="SOLID" width="0.1 mm" color="#000000"/>'
        + fill_xml
        + "</hh:borderFill>"
    )


THIN = ("SOLID", "0.12 mm", LINE)
THICK = ("SOLID", "0.4 mm", NAVY)

# borderFill id 7~ : 우리가 추가하는 것
BF_TBL_HEAD = 7      # 표 머리행: 옅은 남색 배경 + 실선
BF_TBL_CELL = 8      # 표 본문 셀
BF_TBL_ALT = 9       # 표 본문 셀(줄무늬)
BF_CALLOUT = 10      # 콜아웃 박스: 배경 + 테두리 없음
BF_NONE = 11         # 테두리/배경 없음
BF_BAND = 12         # 섹션 제목 밴드(남색 채움)
BF_TBL_HEAD_D = 13   # 표 머리행(진한 남색 채움, 흰 글씨용)
BF_ACCENT = 14       # 좌측 강조선만 있는 박스

EXTRA_BORDERFILLS = [
    borderfill(BF_TBL_HEAD, left=THIN, right=THIN, top=THIN, bottom=THIN, fill=BAND),
    borderfill(BF_TBL_CELL, left=THIN, right=THIN, top=THIN, bottom=THIN),
    borderfill(BF_TBL_ALT, left=THIN, right=THIN, top=THIN, bottom=THIN, fill="#F7FAFC"),
    borderfill(BF_CALLOUT, fill=LIGHT),
    borderfill(BF_NONE),
    borderfill(BF_BAND, fill=NAVY),
    borderfill(BF_TBL_HEAD_D, left=THIN, right=THIN, top=THIN, bottom=THIN, fill=NAVY),
    borderfill(BF_ACCENT, left=("SOLID", "0.5 mm", BLUE), fill=LIGHT),
]


def charpr(idx, height, color=INK, bold=False, font=FONT_DOTUM, underline=False,
           ratio=100, spacing=0):
    """charPr 정의 XML."""
    langs = "hangul latin hanja japanese other symbol user".split()
    fontref = " ".join(f'{l}="{font}"' for l in langs)
    ratios = " ".join(f'{l}="{ratio}"' for l in langs)
    spacings = " ".join(f'{l}="{spacing}"' for l in langs)
    hundred = " ".join(f'{l}="100"' for l in langs)
    zero = " ".join(f'{l}="0"' for l in langs)
    ul = (
        '<hh:underline type="BOTTOM" shape="SOLID" color="%s"/>' % color
        if underline
        else '<hh:underline type="NONE" shape="SOLID" color="#000000"/>'
    )
    return (
        f'<hh:charPr id="{idx}" height="{height}" textColor="{color}" shadeColor="none" '
        f'useFontSpace="0" useKerning="0" symMark="NONE" borderFillIDRef="3">'
        f"<hh:fontRef {fontref}/>"
        f"<hh:ratio {ratios}/>"
        f"<hh:spacing {spacings}/>"
        f"<hh:relSz {hundred}/>"
        f"<hh:offset {zero}/>"
        + ("<hh:bold/>" if bold else "")
        + ul
        + '<hh:strikeout shape="NONE" color="#000000"/>'
        '<hh:outline type="NONE"/>'
        '<hh:shadow type="NONE" color="#C0C0C0" offsetX="10" offsetY="10"/>'
        "</hh:charPr>"
    )


# charPr id 18~
CP_BODY = 18
CP_BODY_B = 19
CP_BODY_ACC = 20
CP_H1 = 21
CP_H2 = 22
CP_TH = 23
CP_TD = 24
CP_TD_B = 25
CP_CAPTION = 26
CP_TITLE = 27
CP_SUBTITLE = 28
CP_SMALL = 29
CP_SMALL_B = 30
CP_H3 = 31
CP_TH_D = 32
CP_META_K = 33
CP_META_V = 34
CP_TD_ACC = 35
CP_TINY = 36
CP_BODY_GRAY = 37

EXTRA_CHARPRS = [
    charpr(CP_BODY, 1300, INK),
    charpr(CP_BODY_B, 1300, INK, bold=True),
    charpr(CP_BODY_ACC, 1300, BLUE, bold=True),
    charpr(CP_H1, 1400, "#FFFFFF", bold=True),
    charpr(CP_H2, 1300, NAVY, bold=True),
    charpr(CP_TH, 1000, NAVY, bold=True),
    charpr(CP_TD, 1000, INK),
    charpr(CP_TD_B, 1000, INK, bold=True),
    charpr(CP_CAPTION, 900, GRAY),
    charpr(CP_TITLE, 2000, NAVY, bold=True),
    charpr(CP_SUBTITLE, 1100, GRAY),
    charpr(CP_SMALL, 1100, INK),
    charpr(CP_SMALL_B, 1100, INK, bold=True),
    charpr(CP_H3, 1300, INK, bold=True),
    charpr(CP_TH_D, 1000, "#FFFFFF", bold=True),
    charpr(CP_META_K, 1100, "#FFFFFF", bold=True),
    charpr(CP_META_V, 1100, INK),
    charpr(CP_TD_ACC, 1000, BLUE, bold=True),
    charpr(CP_TINY, 800, GRAY),
    charpr(CP_BODY_GRAY, 1300, GRAY),
]


def parapr(idx, *, align="JUSTIFY", line=130, left=0, right=0, intent=0,
           prev=0, next_=250, border=None, keep_next=False, page_break_before=False):
    """paraPr 정의 XML. 여백 단위는 HWPUNIT."""
    margin = (
        "<hh:margin>"
        f'<hc:intent value="{intent}" unit="HWPUNIT"/>'
        f'<hc:left value="{left}" unit="HWPUNIT"/>'
        f'<hc:right value="{right}" unit="HWPUNIT"/>'
        f'<hc:prev value="{prev}" unit="HWPUNIT"/>'
        f'<hc:next value="{next_}" unit="HWPUNIT"/>'
        "</hh:margin>"
        f'<hh:lineSpacing type="PERCENT" value="{line}" unit="HWPUNIT"/>'
    )
    bf = border if border is not None else 3
    return (
        f'<hh:paraPr id="{idx}" tabPrIDRef="0" condense="0" fontLineHeight="0" '
        f'snapToGrid="1" suppressLineNumbers="0" checked="0">'
        f'<hh:align horizontal="{align}" vertical="BASELINE"/>'
        '<hh:heading type="NONE" idRef="0" level="0"/>'
        '<hh:breakSetting breakLatinWord="KEEP_WORD" breakNonLatinWord="BREAK_WORD" '
        f'widowOrphan="0" keepWithNext="{1 if keep_next else 0}" keepLines="0" '
        f'pageBreakBefore="{1 if page_break_before else 0}" lineWrap="BREAK"/>'
        '<hh:autoSpacing eAsianEng="0" eAsianNum="0"/>'
        "<hp:switch>"
        '<hp:case hp:required-namespace="http://www.hancom.co.kr/hwpml/2016/HwpUnitChar">'
        + margin
        + "</hp:case><hp:default>"
        + margin
        + "</hp:default></hp:switch>"
        f'<hh:border borderFillIDRef="{bf}" offsetLeft="0" offsetRight="0" '
        'offsetTop="0" offsetBottom="0" connect="0" ignoreMargin="0"/>'
        "</hh:paraPr>"
    )


# paraPr id 27~
PP_BODY = 27
PP_H1 = 28
PP_H2 = 29
PP_UL1 = 30
PP_UL2 = 31
PP_TD_C = 32
PP_TD_L = 33
PP_CAPTION = 34
PP_CENTER = 35
PP_TIGHT = 36
PP_FIG = 37
PP_H3 = 38
PP_TITLE = 39
PP_UL1_TIGHT = 40
PP_TD_R = 41
PP_BODY_TIGHT = 42
PP_PAGEBREAK = 43

EXTRA_PARAPRS = [
    parapr(PP_BODY, align="JUSTIFY", line=130, next_=230),
    parapr(PP_H1, align="LEFT", line=130, prev=0, next_=0, keep_next=True),
    parapr(PP_H2, align="LEFT", line=130, prev=330, next_=140, keep_next=True),
    parapr(PP_UL1, align="JUSTIFY", line=130, left=800, intent=-800, next_=110),
    parapr(PP_UL2, align="JUSTIFY", line=130, left=1600, intent=-800, next_=110),
    parapr(PP_TD_C, align="CENTER", line=125, next_=0),
    parapr(PP_TD_L, align="LEFT", line=125, next_=0),
    parapr(PP_CAPTION, align="CENTER", line=120, prev=60, next_=300),
    parapr(PP_CENTER, align="CENTER", line=130, next_=230),
    parapr(PP_TIGHT, align="JUSTIFY", line=130, next_=0),
    parapr(PP_FIG, align="CENTER", line=100, prev=140, next_=0),
    parapr(PP_H3, align="LEFT", line=130, prev=230, next_=100, keep_next=True),
    parapr(PP_TITLE, align="CENTER", line=130, next_=120),
    parapr(PP_UL1_TIGHT, align="JUSTIFY", line=130, left=800, intent=-800, next_=0),
    parapr(PP_TD_R, align="RIGHT", line=125, next_=0),
    parapr(PP_BODY_TIGHT, align="JUSTIFY", line=130, next_=90),
    parapr(PP_PAGEBREAK, align="LEFT", line=130, next_=0, page_break_before=True),
]
