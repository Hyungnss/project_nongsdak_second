"""
17단계 — 발표용 PPT 만들기  (03 · 04 · 06-1 · 06-2)

실행:
    python 17_slides.py

입력  docs/dashboard.html          (10_dashboard.py 결과 — 수치를 여기서 읽는다)
출력  docs/presentations/2026-08-19-농스닥-발표자료-03-04-06-분석파트.pptx


무엇에 쓰는가

    발표 자료 중 분석이 담당하는 03장 · 04장 · 06-1 · 06-2 를 슬라이드로 만든다.
    글은 여기 박아 두고, 숫자는 dashboard.html 에서 읽는다.
    분석을 다시 돌려 대시보드가 바뀌면 이 스크립트만 다시 실행하면 수치가 따라온다.

    dashboard.html 은 발표에서 직접 시연한다.
    그래서 슬라이드에 차트 그림을 욕심껏 넣지 않고,
    각 장 끝에 '무슨 화면을 열어 무엇을 보여줄지' 만 적어 뒀다.

주의

    슬라이드 번호는 이 파일 기준이다.
    팀 초안에 끼워 넣을 자리는 docs/presentations/*.md 의 [슬라이드 nn] 표기를 보면 된다.
"""

import json
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt
from lxml import etree


CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent

DASHBOARD = PROJECT_ROOT / "docs" / "dashboard.html"
OUT = (PROJECT_ROOT / "docs" / "presentations"
       / "2026-08-19-농스닥-발표자료-03-04-06-분석파트.pptx")

FONT = "Apple SD Gothic Neo"      # 발표 노트북(macOS) 기준. 윈도우면 맑은 고딕으로 바꾼다.

# 대시보드와 같은 색을 쓴다. 시연 화면과 슬라이드가 따로 놀지 않게.
INK = "16191D"
MUTED = "6B7280"
FAINT = "9AA3AB"
LINE = "E5E7EB"
BG = "F6F7F9"
WHITE = "FFFFFF"
TEAL = "0F766E"
TEAL_BG = "E7F1F0"
HOT = "C0392B"
HOT_SOFT = "D9776A"
COLD = "2563EB"
COLD_SOFT = "6E9BE8"
GRAY = "9AA3AB"
GRAY_SOFT = "C4CBD2"

SW, SH = 13.333, 7.5
MX = 0.62                 # 좌우 여백
CW = SW - MX * 2          # 본문 너비 12.09
BT = 1.55                 # 본문 시작
BB = 6.82                 # 본문 끝


# ----------------------------------------------------------------- 수치 읽기

def load_numbers():
    """dashboard.html 안에 박힌 const ALL 을 꺼내 일별 결과를 돌려준다."""

    if not DASHBOARD.exists():
        raise SystemExit(f"{DASHBOARD} 가 없습니다. 10_dashboard.py 를 먼저 돌리세요.")

    html = DASHBOARD.read_text(encoding="utf-8")
    head = "const ALL = "
    start = html.index(head) + len(head)

    depth = 0
    for i, ch in enumerate(html[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    return json.loads(html[start:end])["day"]


D = load_numbers()
Q1, Q2, Q3, Q4 = D["q1"], D["q2"], D["q3"], D["q4"]

q1_share = round(Q1["strongCount"] / Q1["totalCount"] * 100)
q2_share = round(Q2["counts"]["strong"] / Q2["counts"]["total"] * 100)
q4_total = sum(Q4["counts"].values())


# ----------------------------------------------------------------- 그리기 도구

prs = Presentation()
prs.slide_width = Inches(SW)
prs.slide_height = Inches(SH)
BLANK = prs.slide_layouts[6]


def rgb(hex6):
    return RGBColor.from_string(hex6)


def use_font(font, name=FONT):
    """한글은 latin 만 지정하면 안 먹는다. ea · cs 도 같이 박는다."""

    font.name = name
    rPr = font._rPr
    latin = rPr.get_or_add_latin()

    for tag in ("a:ea", "a:cs"):
        found = rPr.find(qn(tag))
        if found is None:
            found = etree.SubElement(latin.getparent(), qn(tag))
            latin.addnext(found)
        found.set("typeface", name)


def new_slide():
    slide = prs.slides.add_slide(BLANK)
    back = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0,
                                  Inches(SW), Inches(SH))
    back.fill.solid()
    back.fill.fore_color.rgb = rgb(BG)
    back.line.fill.background()
    back.shadow.inherit = False
    return slide


def text(slide, x, y, w, h, blocks, align=PP_ALIGN.LEFT,
         anchor=MSO_ANCHOR.TOP, wrap=True):
    """blocks = [(글, 크기, 굵기, 색, 줄간격, 문단앞여백), ...]"""

    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = wrap
    tf.margin_left = tf.margin_right = 0
    tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor

    for i, block in enumerate(blocks):
        body, size, bold, color = block[:4]
        spacing = block[4] if len(block) > 4 else 1.15
        before = block[5] if len(block) > 5 else 0

        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = spacing
        if before:
            p.space_before = Pt(before)

        run = p.add_run()
        run.text = body
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.color.rgb = rgb(color)
        use_font(run.font)

    return box


def box(slide, x, y, w, h, fill=WHITE, line=LINE, radius=0.05):
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x),
                                   Inches(y), Inches(w), Inches(h))
    shape.adjustments[0] = radius
    shape.fill.solid()
    shape.fill.fore_color.rgb = rgb(fill)
    if line:
        shape.line.color.rgb = rgb(line)
        shape.line.width = Pt(1)
    else:
        shape.line.fill.background()
    shape.shadow.inherit = False
    shape.text_frame.text = ""
    return shape


def head(slide, kicker, title, section, page):
    text(slide, MX, 0.40, CW, 0.28, [(kicker, 12.5, True, TEAL)])
    text(slide, MX, 0.66, CW, 0.62, [(title, 27, True, INK)])

    rule = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(MX),
                                  Inches(1.32), Inches(CW), Pt(1.4))
    rule.fill.solid()
    rule.fill.fore_color.rgb = rgb(LINE)
    rule.line.fill.background()
    rule.shadow.inherit = False

    text(slide, MX, 6.98, CW * 0.7, 0.26, [(section, 10, False, FAINT)])
    text(slide, MX + CW * 0.7, 6.98, CW * 0.3, 0.26,
         [(str(page), 10, False, FAINT)], align=PP_ALIGN.RIGHT)


def card(slide, x, y, w, h, label, value, note="", color=TEAL, size=23):
    box(slide, x, y, w, h)
    text(slide, x + 0.26, y + 0.12, w - 0.52, 0.24, [(label, 11.5, False, MUTED)])
    text(slide, x + 0.26, y + 0.36, w - 0.52, 0.42, [(value, size, True, color)])
    if note:
        text(slide, x + 0.26, y + 0.78, w - 0.52, h - 0.82,
             [(note, 10.5, False, MUTED, 1.1)])


def demo_pill(slide, x, y, w, body):
    shape = box(slide, x, y, w, 0.44, fill=TEAL_BG, line=TEAL, radius=0.5)
    shape.line.width = Pt(0.75)
    text(slide, x + 0.22, y + 0.10, w - 0.44, 0.26,
         [("▶  " + body, 11.5, True, TEAL)])


BORDER_ORDER = ("a:lnL", "a:lnR", "a:lnT", "a:lnB")


def borders(cell, spec):
    """spec = {'B': (색, 굵기pt)}  — 표는 밑줄만 그어 대시보드와 결을 맞춘다."""

    tcPr = cell._tc.get_or_add_tcPr()

    for tag in BORDER_ORDER:
        for old in tcPr.findall(qn(tag)):
            tcPr.remove(old)

    built = {}
    for edge, (color, width) in spec.items():
        tag = "a:ln" + edge
        ln = etree.Element(qn(tag))
        ln.set("w", str(int(Pt(width))))
        ln.set("cap", "flat")
        ln.set("cmpd", "sng")
        ln.set("algn", "ctr")
        fill = etree.SubElement(ln, qn("a:solidFill"))
        clr = etree.SubElement(fill, qn("a:srgbClr"))
        clr.set("val", color)
        built[tag] = ln

    for tag in reversed(BORDER_ORDER):
        if tag in built:
            tcPr.insert(0, built[tag])


def table(slide, x, y, w, cols, rows, widths, size=12, head_size=11,
          row_h=0.44, head_h=0.42, bolds=(), aligns=None):
    """cols = 머리글, rows = 줄들. widths 는 비율."""

    shape = slide.shapes.add_table(len(rows) + 1, len(cols), Inches(x),
                                   Inches(y), Inches(w),
                                   Inches(head_h + row_h * len(rows)))
    tbl = shape.table

    style = tbl._tbl.find(qn("a:tblPr"))
    style.set("firstRow", "1")
    style.set("bandRow", "0")
    for old in style.findall(qn("a:tableStyleId")):
        style.remove(old)
    sid = etree.SubElement(style, qn("a:tableStyleId"))
    sid.text = "{2D5ABB26-0587-4C30-8999-92F81FD0307C}"      # 테두리 없음

    total = sum(widths)
    for i, ratio in enumerate(widths):
        tbl.columns[i].width = Emu(int(Inches(w) * ratio / total))

    tbl.rows[0].height = Inches(head_h)
    for r in range(len(rows)):
        tbl.rows[r + 1].height = Inches(row_h)

    body = [list(cols)] + [list(r) for r in rows]

    for r, line in enumerate(body):
        for c, value in enumerate(line):
            cell = tbl.cell(r, c)
            cell.margin_left = cell.margin_right = Inches(0.11)
            cell.margin_top = cell.margin_bottom = Inches(0.04)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.fill.solid()
            cell.fill.fore_color.rgb = rgb(WHITE)

            borders(cell, {"B": ((MUTED if r == 0 else LINE), 1.0)})

            tf = cell.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            if aligns:
                p.alignment = aligns[c]
            elif c > 0 and r > 0:
                p.alignment = PP_ALIGN.LEFT

            run = p.add_run()
            run.text = str(value)
            run.font.size = Pt(head_size if r == 0 else size)
            run.font.bold = (r == 0) or (r > 0 and (r - 1, c) in bolds)
            run.font.color.rgb = rgb(MUTED if r == 0 else INK)
            use_font(run.font)

    return tbl


def bar(slide, x, y, w, h, color):
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y),
                                   Inches(max(w, 0.012)), Inches(h))
    shape.fill.solid()
    shape.fill.fore_color.rgb = rgb(color)
    shape.line.fill.background()
    shape.shadow.inherit = False
    shape.text_frame.text = ""
    return shape


def axis(slide, x, y, w, h):
    """0 이 어디인지 알려 주는 가는 선."""

    line = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y),
                                  Inches(w) if w else Pt(0.9),
                                  Inches(h) if h else Pt(0.9))
    line.fill.solid()
    line.fill.fore_color.rgb = rgb(LINE)
    line.line.fill.background()
    line.shadow.inherit = False
    line.text_frame.text = ""


def hbars(slide, x, y, w, h, items, fmt="{:.2f}", label_w=1.2, val_w=0.78,
          diverging=False, name_size=11, val_size=10.5):
    """가로 막대. items = [(이름, 값, 색), ...] — 위에서 아래로 그린다."""

    n = len(items)
    row = h / n
    bh = min(0.21, row * 0.56)
    bx = x + label_w + (val_w if diverging else 0)
    bw = w - label_w - val_w * (2 if diverging else 1)
    top = max(abs(v) for _, v, _ in items) * 1.02

    zero = bx + bw / 2 if diverging else bx
    scale = (bw / 2 if diverging else bw) / top

    axis(slide, zero, y, 0, h)

    for i, (name, value, color) in enumerate(items):
        cy = y + row * i
        text(slide, x, cy + (row - 0.24) / 2, label_w - 0.14, 0.24,
             [(name, name_size, False, INK)], align=PP_ALIGN.RIGHT)

        length = abs(value) * scale
        left = zero if value >= 0 else zero - length
        bar(slide, left, cy + (row - bh) / 2, length, bh, color)

        label = fmt.format(value)
        if value >= 0:
            text(slide, left + length + 0.07, cy + (row - 0.24) / 2, val_w, 0.24,
                 [(label, val_size, True, INK)])
        else:
            text(slide, left - val_w - 0.07, cy + (row - 0.24) / 2, val_w, 0.24,
                 [(label, val_size, True, INK)], align=PP_ALIGN.RIGHT)


def vbars(slide, x, y, w, h, items, fmt="{:.1f}", name_size=12, val_size=13):
    """세로 막대. items = [(이름, 값, 색), ...]"""

    n = len(items)
    col = w / n
    bw = min(1.35, col * 0.46)
    top_pad, foot = 0.36, 0.46
    plot = h - top_pad - foot
    top = max(v for _, v, _ in items) * 1.06
    base = y + h - foot

    axis(slide, x, base, w, 0)

    for i, (name, value, color) in enumerate(items):
        length = value / top * plot
        left = x + col * i + (col - bw) / 2
        bar(slide, left, base - length, bw, length, color)
        text(slide, x + col * i, base - length - 0.4, col, 0.34,
             [(fmt.format(value), val_size, True, INK)], align=PP_ALIGN.CENTER)
        text(slide, x + col * i, base + 0.1, col, 0.3,
             [(name, name_size, False, INK)], align=PP_ALIGN.CENTER)


def divider(slide, number, title, subtitle, note=""):
    back = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0,
                                  Inches(SW), Inches(SH))
    back.fill.solid()
    back.fill.fore_color.rgb = rgb(INK)
    back.line.fill.background()
    back.shadow.inherit = False

    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(1.1),
                                 Inches(2.55), Pt(4), Inches(2.4))
    bar.fill.solid()
    bar.fill.fore_color.rgb = rgb(TEAL)
    bar.line.fill.background()
    bar.shadow.inherit = False

    text(slide, 1.45, 2.45, 9.5, 0.9, [(number, 15, True, TEAL)])
    text(slide, 1.45, 2.85, 10.5, 1.0, [(title, 40, True, WHITE)])
    text(slide, 1.45, 3.95, 10.5, 0.6, [(subtitle, 15, False, "B7BEC6")])
    if note:
        text(slide, 1.45, 4.55, 10.5, 0.5, [("▶  " + note, 12.5, True, TEAL)])


# ============================================================ 03. 데이터 분석

S = "03. 데이터 분석 및 결과"

# --- 1 표지 ---------------------------------------------------------------
divider(new_slide(), "03", "데이터 분석 및 결과",
        f"네 가지 질문 · 상품 {Q1['totalCount']}개 · {D['meta']['period']} "
        f"KAMIS 소매가격 {D['meta']['rows']:,}행",
        "이 장은 분석 대시보드를 화면으로 함께 봅니다")

# --- 2  3-1 네 가지 질문 ---------------------------------------------------
slide = new_slide()
head(slide, "3-1  분석 질문 및 분석 방향", "무엇을 물었는가", S, 2)

questions = [
    ("Q1", "품목별 가격에\n계절 패턴이 있는가",
     "같은 주차끼리 10년치를 모아\n1년 모양을 그린다"),
    ("Q2", "기온과 강수량은\n가격 변동과 어떤 관계인가",
     "시차를 옮겨 가며 상관을 내고\n가장 잘 맞는 시점을 고른다"),
    ("Q3", "10년간의 가격 상승은\n물가로 얼마나 설명되는가",
     "소비자물가지수로 나눠\n명목과 실질을 갈라 본다"),
    ("Q4", "과거 분포로\n미래 가격을 예측할 수 있는가",
     "마지막 시점 가격이 과거 같은 시기\n분포의 어디인지 백분위로 낸다"),
]

cw = (CW - 0.24 * 3) / 4
for i, (tag, ask, how) in enumerate(questions):
    x = MX + (cw + 0.24) * i
    box(slide, x, BT, cw, 2.75)
    text(slide, x + 0.24, BT + 0.20, cw - 0.48, 0.3, [(tag, 15, True, TEAL)])
    text(slide, x + 0.24, BT + 0.62, cw - 0.48, 1.1,
         [(ask, 15, True, INK, 1.25)])
    text(slide, x + 0.24, BT + 1.85, cw - 0.48, 0.8,
         [(how, 11.5, False, MUTED, 1.3)])

box(slide, MX, 4.62, CW, 1.05, fill=WHITE)
text(slide, MX + 0.3, 4.78, CW - 0.6, 0.75,
     [("분석 단위 — 품목 · 품종 · 등급 · 단위 네 가지가 모두 같아야 한 상품으로 센다",
       14, True, INK),
      ("갈치 냉동과 갈치 생물, 상품과 중품은 가격대가 달라 묶으면 어느 쪽도 아닌 값이 된다.",
       12, False, MUTED, 1.2, 6)])

text(slide, MX, 5.95, CW, 0.8,
     [(f"분석 대상   {D['meta']['period']} KAMIS 소매가격 {D['meta']['rows']:,}행 · "
       f"품목 {D['meta']['items']}개 · 최소 관측 {D['meta']['minObs']}일을 채운 상품 "
       f"{Q1['totalCount']}개", 12.5, False, MUTED)])

# --- 3  3-1 왜 일별인가 ----------------------------------------------------
slide = new_slide()
head(slide, "3-1  분석 질문 및 분석 방향", "같은 분석을 세 주기로 세 번 했다", S, 3)

text(slide, MX, BT, CW, 0.34,
     [("결론이 자료를 자르는 방식에 따라 흔들리는지 확인하기 위해서다.", 14, False, INK)])

table(slide, MX, BT + 0.45, CW,
      ["", "일별  (대표)", "주별", "월별"],
      [["서비스와 주기가 같다  (KAMIS 일일 조사)", "일치", "불일치", "불일치"],
       ["분석에 살아남은 상품", "232개", "225개", "130개"],
       ["날씨 반응 시차를 며칠 단위로 볼 수 있는가", "0~28일", "0~8주", "0~3달"],
       ["짧은 급등(폭염 2주)이 평균에 지워지는가", "안 지워짐", "조금", "많이 지워짐"],
       ["뚜렷한 계절 패턴 비율", "29%", "26%", "22%"],
       ["계절 진폭 중앙값", "0.301", "0.273", "0.174"]],
      widths=[5.2, 2.0, 2.0, 2.0], size=12.5,
      bolds={(0, 1), (1, 1), (2, 1), (3, 1), (4, 1), (5, 1)})

box(slide, MX, 5.20, CW, 0.98, fill=TEAL_BG, line=TEAL)
text(slide, MX + 0.3, 5.36, CW - 0.6, 0.75,
     [("세 주기가 같은 결론을 냈다 — 29% · 26% · 22%", 14.5, True, TEAL),
      ("어느 주기를 골라도 결론이 달라지지 않으므로, 가장 잘게 볼 수 있고 서비스와 주기가 같은 "
       "일별을 대표로 삼았다.", 12, False, INK, 1.2, 6)])

text(slide, MX, 6.32, CW, 0.5,
     [("다만 일별은 하루짜리 이상치가 최고-최저에 그대로 들어가 진폭이 가장 크게 나온다. "
       "이 점은 6-3 한계에 적었다.", 11.5, False, MUTED)])

# --- 4  3-1 계산의 뼈대 ----------------------------------------------------
slide = new_slide()
head(slide, "3-1  분석 질문 및 분석 방향", "계산의 뼈대 — 가격지수", S, 4)

box(slide, MX, BT, 6.4, 2.9)
text(slide, MX + 0.32, BT + 0.22, 5.8, 0.9,
     [("단위가 제각각이라 원 단위로는 상품끼리 견줄 수 없다.", 13, False, MUTED),
      ("배추 1포기 4천원 · 쌀 20kg 5만원", 11.5, False, FAINT, 1.2, 4)])
text(slide, MX + 0.32, BT + 1.05, 5.8, 0.45,
     [("가격지수 =  그 시점 가격  ÷  그 상품의 전체 기간 중앙값", 14.5, True, TEAL)])
text(slide, MX + 0.32, BT + 1.62, 5.8, 0.8,
     [("1.30  →  평소보다 30% 비쌌던 시점", 13, False, INK, 1.35),
      ("0.80  →  평소보다 20% 쌌던 시점", 13, False, INK, 1.35)])

box(slide, MX, BT + 3.1, 6.4, 1.9, fill=TEAL_BG, line=TEAL)
text(slide, MX + 0.32, BT + 3.3, 5.8, 1.5,
     [("10년 내내 같은 수 하나로 나눈다", 14, True, TEAL),
      ("해마다 다른 수로 나누면 물가상승이 지워진다. 이번 분석은 물가를 걷어내지 않기로 했다. "
       "소비자가 실제로 지불하는 가격 그대로를 보기 위해서다.", 12, False, INK, 1.25, 6)])

text(slide, MX + 6.9, BT - 0.02, 5.19, 0.3,
     [("분석 전제 — 해석할 때 함께 봐야 할 것", 13.5, True, INK)])

table(slide, MX + 6.9, BT + 0.38, 5.19,
      ["전제", "결과에 미치는 영향"],
      [["물가를 걷어내지 않았다", "계절 진폭에 10년치 물가상승이 섞여 실제보다 커진다"],
       ["계절을 걷어내지 않았다 (Q2)", "계절이 기온과 가격을 함께 움직인 몫이 상관에 들어 있다"],
       ["기상 자료가 전국 하나뿐이다", "같은 날 모든 시도에 같은 기온이 붙어 지역 차이를 못 본다"],
       ["상관은 인과가 아니다", "\"같이 움직였다\" 까지만 말할 수 있다"]],
      widths=[2.0, 3.2], size=11, head_size=10.5, row_h=1.0, head_h=0.36,
      bolds={(0, 0), (1, 0), (2, 0), (3, 0)})

# --- 5  3-2 Q1 -------------------------------------------------------------
slide = new_slide()
head(slide, "3-2  분석 결과 ①", "Q1. 품목별 가격에 계절 패턴이 있는가", S, 5)

cw = (CW - 0.24 * 2) / 3
card(slide, MX, BT, cw, 1.12, "뚜렷한 계절 패턴",
     f"{Q1['strongCount']}개  /  {Q1['totalCount']}개",
     f"전체 상품의 {q1_share}%")
card(slide, MX + cw + 0.24, BT, cw, 1.12, "계절 진폭 중앙값",
     f"{Q1['medianAmplitude']:.3f}", "1년 사이 평소 값의 30%p 만큼", color=INK)
card(slide, MX + (cw + 0.24) * 2, BT, cw, 1.12, "뚜렷 판정선",
     f"진폭 {Q1['strongLine']:.2f} 이상", "진폭 분포에서 정한 값", color=INK)

amp_items = [("시금치", 2.10, TEAL), ("상추", 1.18, TEAL), ("미나리", 1.02, TEAL),
             ("참외", 0.96, TEAL), ("호박", 0.86, TEAL), ("딸기", 0.84, TEAL),
             ("닭고기", 0.10, GRAY_SOFT), ("바나나", 0.06, GRAY_SOFT),
             ("쌀", 0.06, GRAY_SOFT), ("김", 0.05, GRAY_SOFT),
             ("두부", 0.04, GRAY_SOFT), ("우유", 0.02, GRAY_SOFT)]
text(slide, MX, BT + 1.32, 6.5, 0.3,
     [("품목별 계절 진폭 중앙값  (일별)", 12.5, True, INK)])
hbars(slide, MX, BT + 1.66, 6.5, 3.5, amp_items, fmt="{:.2f}")

box(slide, MX + 6.85, BT + 1.32, 5.24, 1.55)
text(slide, MX + 7.11, BT + 1.5, 4.72, 1.3,
     [("판정선 0.50의 근거", 13, True, INK),
      ("0.20에서는 상품의 3분의 2가 '뚜렷'이라 아무것도 가르지 못했고, 그 경계에 "
       "쇠고기·계란·건오징어가 놓였다. 0.50은 세 주기 모두 상위 22~29%가 걸린다.",
       11.5, False, MUTED, 1.25, 5)])

box(slide, MX + 6.85, BT + 3.02, 5.24, 1.75, fill=TEAL_BG, line=TEAL)
text(slide, MX + 7.11, BT + 3.2, 4.72, 1.5,
     [("계절을 타는 것은 노지 잎채소와 과채류다", 13, True, TEAL),
      ("시금치는 1년 사이 값이 2배 넘게 오르내린다. 반대로 우유·두부·쌀·바나나처럼 "
       "가공·저장·수입에 기대는 품목은 거의 평평하다. 파는 방식이 계절을 흡수한다.",
       11.5, False, INK, 1.25, 5),
      ("→ 품목을 뭉뚱그린 하나의 답을 줄 수 없다", 11.5, True, INK, 1.2, 5)])

demo_pill(slide, MX + 6.85, 6.38, 5.24, "시연 · 계절 달력(상위 10개) → 평년 밴드(상추)")

# --- 6  3-3 Q2 -------------------------------------------------------------
slide = new_slide()
head(slide, "3-3  분석 결과 ②", "Q2. 기온과 강수량은 가격 변동과 어떤 관계인가", S, 6)

cw = (CW - 0.24 * 2) / 3
card(slide, MX, BT, cw, 1.12, "뚜렷한 관계를 보인 상품",
     f"{Q2['counts']['strong']}개  /  {Q2['counts']['total']}개",
     f"약한 관계까지 {Q2['counts']['weak']}개 (23%)")
card(slide, MX + cw + 0.24, BT, cw, 1.12, "전체를 한 덩어리로 묶으면",
     f"기온 {Q2['overall']['temp']:+.2f} · 강수 {Q2['overall']['rain']:+.2f}",
     "방향이 갈려 서로 상쇄된다", color=INK, size=19)
card(slide, MX + (cw + 0.24) * 2, BT, cw, 1.12, "강수량만으로 뚜렷한 상품",
     "0개", "가장 센 것도 +0.38 (상추)", color=INK)

pair = [("시금치", 0.87), ("감귤 (시설)", 0.75), ("무 (봄)", 0.60),
        ("상추 (적)", 0.54), ("상추 (청)", 0.53), ("포도 (샤인)", 0.52),
        ("물오징어", -0.83), ("오렌지", -0.74), ("참외", -0.72),
        ("방울토마토", -0.69), ("오이", -0.64), ("딸기", -0.61)]
text(slide, MX, BT + 1.32, 6.5, 0.3,
     [("기온과 가격이 함께 움직인 정도  (상관계수 r · 가장 잘 맞는 시차 기준)",
       12.5, True, INK)])
hbars(slide, MX, BT + 1.66, 6.5, 3.5,
      [(n, v, HOT if v > 0 else COLD) for n, v in pair],
      fmt="{:+.2f}", diverging=True, label_w=1.45, val_w=0.7)

box(slide, MX + 6.85, BT + 1.32, 5.24, 1.15)
text(slide, MX + 7.11, BT + 1.5, 4.72, 0.9,
     [("22개 전부 기온이 판정을 이끌었다", 13, True, INK),
      ("빨강 = 기온이 높을 때 비싸진 품목 10개 · 파랑 = 싸진 품목 12개",
       11.5, False, MUTED, 1.25, 5)])

box(slide, MX + 6.85, BT + 2.62, 5.24, 2.05, fill=TEAL_BG, line=TEAL)
text(slide, MX + 7.11, BT + 2.8, 4.72, 1.9,
     [("부호는 그 품목의 제철을 비추고 있다", 13, True, TEAL),
      ("시금치·상추처럼 여름에 값이 뛰는 잎채소는 양(+), 딸기·참외·오렌지처럼 "
       "겨울·봄이 제철인 품목은 음(−)으로 잡힌다. \"더우면 오른다/내린다\"가 아니다.",
       11.5, False, INK, 1.25, 5),
      ("→ 전체를 묶으면 관계가 사라진다. 날씨의 영향은 품목별로 봐야 보인다.",
       11.5, True, INK, 1.2, 5)])

demo_pill(slide, MX + 6.85, 6.38, 5.24, "시연 · 상품별 시차 곡선(시금치) 열기")

# --- 7  3-3 Q2 극단 날씨 ---------------------------------------------------
slide = new_slide()
head(slide, "3-3  분석 결과 ②", "극단 날씨 이후 28일 — 잎채소에 몰려 있다", S, 7)

text(slide, MX, BT, 5.85, 0.3,
     [(f"폭염  기온 상위 5% ({Q2['thresholds']['hot']}도 이상) 이후 28일",
       13, True, HOT)])
table(slide, MX, BT + 0.38, 5.85,
      ["품목", "그 해 평균 대비"],
      [["시금치", "+202.6%"], ["상추", "+69.9%"],
       ["미나리", "+43.0%"], ["얼갈이배추", "+42.1%"]],
      widths=[3.2, 2.0], size=13, row_h=0.46, head_h=0.4,
      bolds={(0, 0), (0, 1)})

text(slide, MX + 6.24, BT, 5.85, 0.3,
     [(f"호우  강수량 상위 5% ({Q2['thresholds']['wet']}mm 이상) 이후 28일",
       13, True, COLD)])
table(slide, MX + 6.24, BT + 0.38, 5.85,
      ["품목", "그 해 평균 대비"],
      [["시금치", "+112.9%"], ["상추", "+57.4%"],
       ["포도", "+37.3%"], ["생강", "+25.1%"]],
      widths=[3.2, 2.0], size=13, row_h=0.46, head_h=0.4,
      bolds={(0, 0), (0, 1)})

box(slide, MX, 4.18, CW, 0.98, fill=WHITE)
text(slide, MX + 0.3, 4.36, CW - 0.6, 0.7,
     [("반응은 즉시가 아니라 시차를 두고 나타났다", 14, True, INK),
      ("뚜렷한 22개 중 12개가 12일 이후에, 그중 8개는 20일 이후에 가장 강했다. "
       "시금치는 25일 뒤가 가장 강하다.", 12, False, MUTED, 1.2, 5)])

box(slide, MX, 5.32, CW, 1.36, fill=TEAL_BG, line=TEAL)
text(slide, MX + 0.3, 5.5, CW - 0.6, 1.1,
     [("저장이 안 되고 생육 기간이 짧은 품목일수록 날씨가 곧장 물량으로 이어진다.  "
       "폭염 뒤 28일 동안 시금치는 그 해 평균보다 세 배 가까이 비쌌다.",
       12.5, False, INK, 1.3),
      ("다만 계절을 걷어내지 않았으므로 여름이라는 공통 원인이 기온과 가격을 함께 움직였을 "
       "가능성이 결과에 들어 있다. 여기서 말할 수 있는 것은 \"함께 움직였다\" 까지다.",
       11.5, False, MUTED, 1.25, 6)])

# --- 8  3-4 Q3 -------------------------------------------------------------
slide = new_slide()
head(slide, "3-4  분석 결과 ③", "Q3. 10년간의 가격 상승은 물가로 얼마나 설명되는가", S, 8)

box(slide, MX, BT, CW, 0.92, fill=TEAL_BG, line=TEAL)
text(slide, MX + 0.3, BT + 0.2, CW - 0.6, 0.6,
     [("같은 가격을 놓고 \"40% 올랐다\" 와 \"15% 올랐다\" 가 둘 다 맞다",
       17, True, TEAL)])

text(slide, MX, BT + 1.18, 6.3, 0.3,
     [(f"{Q3['y0']}년 → {Q3['y1']}년 상승률 중앙값", 12.5, True, INK)])
vbars(slide, MX + 0.1, BT + 1.5, 6.1, 3.5,
      [("소비자물가", Q3["cpiGrowth"], GRAY),
       ("명목 상승률", Q3["medianNominal"], HOT),
       ("실질 상승률", Q3["medianReal"], TEAL)],
      fmt="+{:.1f}%", name_size=13, val_size=17)

card(slide, MX + 6.75, BT + 1.18, 5.34, 1.15, "물가보다 더 오른 품목",
     f"{Q3['fasterCount']}개  /  {Q3['totalItems']}개",
     f"{round(Q3['fasterCount'] / Q3['totalItems'] * 100)}% · 물가보다 빠르게 오른 것은 사실",
     color=HOT)

box(slide, MX + 6.75, 4.03, 5.34, 2.25)
text(slide, MX + 7.01, 4.23, 4.82, 1.95,
     [("결과 해석", 13, True, INK),
      (f"물가가 {Q3['cpiGrowth']}% 오르는 동안 농산물은 {Q3['medianNominal']}% 올랐다. "
       f"오른 것의 절반 이상이 물가로 설명된다. 뒤집으면 명목 숫자만 보면 실제보다 훨씬 "
       f"많이 오른 것처럼 보인다는 뜻이다.", 12, False, MUTED, 1.3, 6),
      ("소비자가 마트에서 보는 숫자는 명목이다. 기준선 없이 그 숫자만으로는 비싼 것인지 "
       "원래 그런 것인지 알 수 없다.", 12, False, MUTED, 1.3, 6),
      ("→ 이 결과가 서비스 방향을 정한 근거가 됐다", 12, True, TEAL, 1.2, 6)])

demo_pill(slide, MX + 6.75, 6.38, 5.34, "시연 · 품목별 명목 vs 실질 상승률 표")

# --- 9  3-5 Q4 -------------------------------------------------------------
slide = new_slide()
head(slide, "3-5  분석 결과 ④", "Q4. 과거 분포로 미래 가격을 예측할 수 있는가", S, 9)

cw = (CW - 0.24 * 2) / 3
card(slide, MX, BT, cw, 1.12, "기준 시점", Q4["asOf"]["label"],
     f"마지막 조사일 · {Q4['asOf']['compare']}와 견줌", color=INK)
card(slide, MX + cw + 0.24, BT, cw, 1.12, "판정 가능 상품", f"{q4_total}개",
     "3개 연도 미만이면 판정하지 않음")
card(slide, MX + (cw + 0.24) * 2, BT, cw, 1.12, "위치 70 이상",
     f"{Q4['dearShare']}%", "위치 중앙값 76.7 · 견준 9년", color=HOT)

order = ["매우 비쌈", "비쌈", "보통", "쌈", "매우 쌈"]
text(slide, MX, BT + 1.32, 6.3, 0.3,
     [("판정 분포  (과거 같은 시기 분포에서의 백분위)", 12.5, True, INK)])
vbars(slide, MX + 0.1, BT + 1.6, 6.1, 3.4,
      [(k, Q4["counts"][k], c) for k, c in
       zip(order, [HOT, HOT_SOFT, GRAY, COLD_SOFT, COLD])],
      fmt="{:.0f}개", name_size=12, val_size=15)

box(slide, MX + 6.75, BT + 1.32, 5.34, 1.5, fill=TEAL_BG, line=TEAL)
text(slide, MX + 7.01, BT + 1.5, 4.82, 1.25,
     [("앞날의 값은 맞히지 못한다", 13.5, True, TEAL),
      ("이 분석이 답할 수 있는 것은 \"해마다 같은 시기에 같은 자리로 돌아오는가\" 까지다. "
       "계절 패턴이 뚜렷한 품목은 과거 분포가 다음 시즌의 대략적인 눈금이 된다.",
       11.5, False, INK, 1.25, 5)])

box(slide, MX + 6.75, BT + 2.97, 5.34, 1.8)
text(slide, MX + 7.01, BT + 3.15, 4.82, 1.55,
     [("이 위치에는 물가상승이 그대로 들어 있다", 13, True, INK),
      (f"절반이 넘는 {Q4['dearShare']}%가 위치 70 이상인 것은 2025년이 유난히 비싼 해여서가 "
       f"아니라, 10년 사이 화폐 가치가 달라진 만큼 최근 값이 위쪽에 몰리기 때문이다.",
       11.5, False, MUTED, 1.25, 5),
      ("→ 소비자에게는 위치 하나가 아니라 비교 기준선을 함께 줘야 한다",
       11.5, True, TEAL, 1.2, 5)])

demo_pill(slide, MX + 6.75, 6.38, 5.34, "시연 · 상품별 위치 게이지와 판정 근거")

# --- 10  3-6 시연 ----------------------------------------------------------
slide = new_slide()
head(slide, "3-6  분석 결과 확인", "대시보드 시연 — 화면에서 직접 확인", S, 10)

steps = [
    ("1", "Q1  계절 달력", "상위 10개 품목. 시금치·상추가 여름에 붉게 물드는 것을 한눈에"),
    ("2", "Q1  평년 밴드", "상추의 1년 모양. 10~90% 띠 안에서 실제 가격이 어디를 지나는가"),
    ("3", "Q2  시차 곡선", "시금치. 기온 곡선이 25일에서 가장 높아지는 지점"),
    ("4", "Q3  명목 vs 실질", "같은 품목에 숫자가 둘. 어느 쪽을 보느냐로 해석이 갈린다"),
    ("5", "Q4  위치 게이지", "판정 근거 — 위치 백분율과 비교한 과거 연수를 함께 표시"),
    ("6", "주기 전환", "일 · 주 · 월 버튼. 결론이 흔들리지 않는 것을 즉석에서 확인"),
]

cw = (CW - 0.26) / 2
for i, (no, title, note) in enumerate(steps):
    col, row = i % 2, i // 2
    x = MX + (cw + 0.26) * col
    y = BT + 1.32 * row
    box(slide, x, y, cw, 1.14)
    text(slide, x + 0.24, y + 0.22, 0.5, 0.5, [(no, 17, True, TEAL)])
    text(slide, x + 0.78, y + 0.22, cw - 1.0, 0.32, [(title, 14, True, INK)])
    text(slide, x + 0.78, y + 0.58, cw - 1.0, 0.5, [(note, 11.5, False, MUTED, 1.25)])

box(slide, MX, BT + 4.05, CW, 0.95, fill=TEAL_BG, line=TEAL)
text(slide, MX + 0.3, BT + 4.22, CW - 0.6, 0.7,
     [("보여 줄 것은 숫자가 아니라 \"기준선이 있으면 판단이 달라진다\" 는 장면이다.",
       13.5, True, TEAL),
      ("이 장면이 그대로 4장의 서비스 도출로 이어진다.", 12, False, INK, 1.2, 5)])

# ============================================================ 04. 서비스 도출

S = "04. 분석 결과 종합 및 서비스 도출"

# --- 11 표지 --------------------------------------------------------------
divider(new_slide(), "04", "분석 결과 종합 및 서비스 도출",
        "네 개의 분석 결과가 하나의 문제로 모이고, 그 문제가 서비스가 된다")

# --- 12  4-1 종합 ----------------------------------------------------------
slide = new_slide()
head(slide, "4-1", "핵심 분석 결과 종합", S, 12)

table(slide, MX, BT, CW,
      ["분석", "핵심 결과"],
      [["계절 패턴 (Q1)",
        f"상품의 {q1_share}%가 1년 사이 50%p 넘게 오르내린다. "
        f"시금치 2.10 · 상추 1.18인 반면 쌀 0.06 · 우유 0.02"],
       ["기온 · 강수 (Q2)",
        f"{Q2['counts']['total']}개 중 {Q2['counts']['strong']}개가 날씨와 뚜렷하게 함께 "
        f"움직였고, 절반 이상이 12일 이후에 반응했다. 폭염 뒤 28일 시금치 +202.6%"],
       ["물가 (Q3)",
        f"물가가 {Q3['cpiGrowth']}% 오르는 동안 명목 +{Q3['medianNominal']}%, 실질은 "
        f"+{Q3['medianReal']}%. 절반 이상이 물가로 설명된다"],
       ["가격 위치 (Q4)",
        f"{Q4['asOf']['label']} 기준 {q4_total}개를 판정. 위치 70 이상이 "
        f"{Q4['dearShare']}%인데, 이는 물가를 걷어내지 않은 결과다"]],
      widths=[2.4, 9.69], size=12.5, row_h=0.66,
      bolds={(0, 0), (1, 0), (2, 0), (3, 0)})

box(slide, MX, 4.72, CW, 1.68, fill=TEAL_BG, line=TEAL)
text(slide, MX + 0.3, 4.92, CW - 0.6, 1.6,
     [("계절에 따라 크게 움직이고   +   날씨에 시차를 두고 반응하고   +   "
       "명목 숫자만으로는 수준을 판단할 수 없다", 14, False, INK, 1.3),
      ("↓", 14, True, TEAL, 1.1, 6),
      ("가격은 \"얼마인가\" 보다 \"지금 어느 수준인가\" 가 중요하다",
       19, True, TEAL, 1.2, 4)], align=PP_ALIGN.CENTER)

# --- 13  4-2 문제 ----------------------------------------------------------
slide = new_slide()
head(slide, "4-2", "분석 결과 기반 문제 및 필요성 도출", S, 13)

box(slide, MX, BT, CW, 0.95, fill=WHITE, line=HOT)
text(slide, MX + 0.32, BT + 0.24, CW - 0.64, 0.5,
     [("소비자는 오늘 가격이 얼마인지는 알 수 있지만, 그 가격이 비싼 것인지 싼 것인지 "
       "판단할 기준이 없다.", 16, True, INK)])

box(slide, MX, BT + 1.18, 5.85, 1.75)
text(slide, MX + 0.3, BT + 1.38, 5.25, 1.45,
     [("Q3 — 숫자는 하나인데 해석이 둘로 갈린다", 13.5, True, INK),
      (f"10년간 명목으로 {Q3['medianNominal']}% 오른 가격이, 물가를 걷어내면 "
       f"{Q3['medianReal']}% 상승이다. 마트에서 보는 것은 명목 숫자뿐이다.",
       12, False, MUTED, 1.3, 6)])

box(slide, MX + 6.24, BT + 1.18, 5.85, 1.75)
text(slide, MX + 6.54, BT + 1.38, 5.25, 1.45,
     [("Q1 — 같은 가격도 시기에 따라 뜻이 달라진다", 13.5, True, INK),
      ("상추처럼 1년 사이 값이 2배 넘게 오르내리는 품목은 같은 가격이 비싼 값이 되기도 하고 "
       "싼 값이 되기도 한다.", 12, False, MUTED, 1.3, 6)])

box(slide, MX, BT + 3.15, 5.4, 1.5, fill=WHITE)
text(slide, MX + 0.3, BT + 3.35, 4.8, 1.2,
     [("지금 있는 것", 12, False, MUTED),
      ("\"오늘 배추 4,921원\"", 18, True, FAINT, 1.2, 8)])

text(slide, MX + 5.5, BT + 3.6, 1.1, 0.6, [("→", 26, True, TEAL)],
     align=PP_ALIGN.CENTER)

box(slide, MX + 6.69, BT + 3.15, 5.4, 1.5, fill=TEAL_BG, line=TEAL)
text(slide, MX + 6.99, BT + 3.35, 4.8, 1.2,
     [("필요한 것", 12, False, TEAL),
      ("\"오늘 배추 4,921원,\n 평년보다 22.7% 싸다\"", 18, True, INK, 1.25, 8)])

text(slide, MX, 6.35, CW, 0.4,
     [("가격 하나만 던지는 것이 아니라 비교할 기준선과 함께 보여줘야 한다.",
       13.5, True, INK)], align=PP_ALIGN.CENTER)

# --- 14  4-3 서비스 방향 ---------------------------------------------------
slide = new_slide()
head(slide, "4-3", "분석 기반 서비스 방향 도출", S, 14)

flow = [("분석 결과", "가격은 계절·날씨에 따라 크게 움직이고\n명목 수치만으로는 수준 판단이 어렵다"),
        ("문제 및 필요성", "오늘 가격을 판단할 기준선이 필요하다"),
        ("서비스 방향", "오늘 가격을 여러 기준선과 나란히 보여주는\n장바구니 시세 서비스")]

for i, (tag, body) in enumerate(flow):
    y = BT + i * 1.62
    fill = TEAL_BG if i == 2 else WHITE
    edge = TEAL if i == 2 else LINE
    box(slide, MX, y, 5.5, 1.3, fill=fill, line=edge)
    text(slide, MX + 0.28, y + 0.16, 4.9, 0.26,
         [(tag, 11.5, True, TEAL if i == 2 else MUTED)])
    text(slide, MX + 0.28, y + 0.48, 4.9, 0.75,
         [(body, 13, True, INK, 1.25)])
    if i < 2:
        text(slide, MX, y + 1.3, 5.5, 0.3, [("↓", 15, True, TEAL)],
             align=PP_ALIGN.CENTER)

box(slide, MX + 6.1, BT, 5.99, 3.1, fill=WHITE, line=TEAL)
text(slide, MX + 6.42, BT + 0.24, 5.35, 0.28,
     [("핵심 연결 문장", 11.5, True, TEAL)])
text(slide, MX + 6.42, BT + 0.62, 5.35, 2.3,
     [("데이터 분석 결과 농산물 가격은 계절과 날씨에 따라 크게 움직이며 명목 수치만으로는 "
       "그 수준을 판단하기 어렵다는 것을 확인하였고, 소비자가 오늘 가격을 여러 기준과 비교해 "
       "판단할 수 있도록 '농스닥' 서비스를 기획하였다.", 15, True, INK, 1.35)])

box(slide, MX + 6.1, BT + 3.3, 5.99, 1.5)
text(slide, MX + 6.42, BT + 3.5, 5.35, 1.2,
     [("이름 — 농산물 + 코스닥", 13, True, INK),
      ("가격을 시세처럼 다루겠다는 뜻이다. 상승 빨강 / 하락 파랑, 하한가·상한가 같은 "
       "증권 화면의 표현을 그대로 가져왔다.", 12, False, MUTED, 1.3, 6)])

# --- 15  4-4 기능 설계 -----------------------------------------------------
slide = new_slide()
head(slide, "4-4", "분석 결과 기반 서비스 기능 설계", S, 15)

table(slide, MX, BT, CW,
      ["분석 결과", "도출된 문제 / 필요성", "서비스 기능"],
      [["명목 숫자만으로는 수준 판단 불가 (Q3·Q4)", "비교 기준선이 필요하다",
        "평년가 비교 + 차트에 평년선 겹쳐 그리기"],
       [f"상품의 {q1_share}%가 1년 사이 50%p 넘게 움직임 (Q1)", "시점에 따라 판단이 달라진다",
        "어제·1주·2주·1개월·1년전·평년 6개 시점 동시 비교"],
       ["계절에 따라 조사 품종이 바뀜 (Q1)", "철 지난 자료를 현재로 오인한다",
        "철 지난 품목 자동 제외 + 경고 표시"],
       ["품목별 진폭이 2.10에서 0.02까지 제각각 (Q1)", "어디에 주목할지 모른다",
        "하한가 · 상한가 (많이 내린 / 오른 품목)"],
       ["날씨 반응이 즉시가 아니라 시차를 두고 나타남 (Q2)", "지금 값만으로는 흐름을 못 본다",
        "90일 추이 차트"],
       ["—", "품목 93개를 훑기 번거롭다", "검색 (초성 지원)"],
       ["—", "매번 같은 품목만 보게 된다", "포춘쿠키 (무작위 추천)"]],
      widths=[4.3, 3.5, 4.29], size=11.5, head_size=11, row_h=0.55,
      bolds={(0, 2), (1, 2), (2, 2), (3, 2), (4, 2)})

box(slide, MX, 5.99, CW, 0.7, fill=TEAL_BG, line=TEAL)
text(slide, MX + 0.3, 6.17, CW - 0.6, 0.4,
     [("Q3 명목 ≠ 실질 → 평년선을 겹쳐 그린다     "
       "Q1 품목마다 진폭이 다름 → 품목별로 판단하게 한다     "
       "Q4 과거와 견줘야 안다 → 6개 시점과 동시 비교",
       11.5, True, INK)], align=PP_ALIGN.CENTER)

# ============================================================ 06. 결론

S = "06. 결론 및 기대효과"

# --- 16 표지 --------------------------------------------------------------
divider(new_slide(), "06", "결론 및 기대효과",
        "6-1 프로젝트 주요 결과 (분석)  ·  6-2 서비스 활용 방안 및 기대효과")

# --- 17  6-1 -------------------------------------------------------------
slide = new_slide()
head(slide, "6-1", "프로젝트 주요 결과 — 분석", S, 17)

results = [
    ("계절을 크게 타는 품목과 거의 타지 않는 품목이 뚜렷하게 갈렸다",
     f"상품의 {q1_share}%가 1년 사이 값이 50%p 넘게 오르내린다. "
     f"시금치 2.10 · 상추 1.18인 반면, 쌀 0.06 · 우유 0.02로 거의 평평하다."),
    ("같은 결론이 일별 · 주별 · 월별 세 주기에서 모두 나왔다",
     "뚜렷한 계절 패턴 비율이 29% · 26% · 22%로, 자료를 자르는 방식을 바꿔도 결론이 흔들리지 "
     "않는다. 그래서 가장 잘게 볼 수 있고 서비스와 주기가 같은 일별을 대표로 정할 수 있었다."),
    ("명목 가격만으로는 수준을 판단할 수 없다는 것을 수치로 확인했다",
     f"10년간 명목 상승률 중앙값 +{Q3['medianNominal']}%, 물가를 걷어낸 실질은 "
     f"+{Q3['medianReal']}%. 오른 것의 절반 이상이 물가로 설명된다."),
    ("날씨와 뚜렷하게 함께 움직인 상품은 소수이고, 그 소수는 크게 탄다",
     f"{Q2['counts']['total']}개 중 {Q2['counts']['strong']}개({q2_share}%)이며 반응은 "
     f"시차를 두고 나타났다. 22개 중 12개가 12일 이후에 가장 강했고, 폭염 뒤 28일 동안 "
     f"시금치는 그 해 평균보다 +202.6% 비쌌다."),
    ("판정 기준을 자료에서 정했다",
     "계절 진폭 0.50은 임의로 고른 값이 아니라 전 상품 진폭 분포를 뽑아 상위 22~29%가 "
     "걸리는 자리로 잡은 것이다."),
]

for i, (title, note) in enumerate(results):
    y = BT + i * 0.92
    text(slide, MX, y, 0.3, 0.3, [("•", 14, True, TEAL)])
    text(slide, MX + 0.3, y, CW - 0.3, 0.3, [(title, 14, True, INK)])
    text(slide, MX + 0.3, y + 0.32, CW - 0.3, 0.55,
         [(note, 12, False, MUTED, 1.25)])

box(slide, MX, 6.12, CW, 0.66, fill=TEAL_BG, line=TEAL)
text(slide, MX + 0.3, 6.28, CW - 0.6, 0.36,
     [("분석 결과를 보고서로 끝내지 않고, 소비자가 오늘 가격을 판단할 수 있는 화면으로 만들었다.",
       13.5, True, TEAL)], align=PP_ALIGN.CENTER)

# --- 18  6-2 -------------------------------------------------------------
slide = new_slide()
head(slide, "6-2", "서비스 활용 방안 및 기대효과", S, 18)

axes = [
    ("소비자 측면", "\"지금 이게 비싼 건가\" 를 장 보기 전에 확인한다", TEAL,
     ["평년 대비 수치는 KAMIS 원본에도 있지만 표 안에 묻혀 잘 보이지 않는다.",
      "농스닥은 그 값을 차트 위에 선으로 겹쳐 그려 한눈에 보이게 했다.",
      "Q1에서 확인했듯 판단 기준은 품목마다 다르다. 그래서 품목별로 따로 보여준다."]),
    ("데이터 활용 측면", "KAMIS 자료를 표가 아니라 판단할 수 있는 형태로 바꿨다", INK,
     ["등급 필드에 부위·원산지·제품형태가 20.5% 섞여 있어 일반인이 직접 고르기 어렵다.",
      "서비스가 대표 등급을 자동으로 정해 준다.",
      "철 지난 품목을 걸러내 오늘 조사된 값만 보이게 했다."]),
    ("프로젝트 측면", "분석에서 서비스까지 전체 과정을 하나로 이었다", INK,
     ["분석이 낸 결론(기준선이 필요하다)이 화면의 기능으로 그대로 남아 있다.",
      "분석 대시보드와 서비스가 같은 주기(일별)를 써서 결과를 그대로 얹을 수 있었다.",
      "판정 기준을 자료의 분포에서 정해, 어디서 정한 값인지 설명할 수 있다."]),
]

cw = (CW - 0.26 * 2) / 3
for i, (tag, lead, color, notes) in enumerate(axes):
    x = MX + (cw + 0.26) * i
    box(slide, x, BT, cw, 3.75, fill=(TEAL_BG if i == 0 else WHITE),
        line=(TEAL if i == 0 else LINE))
    text(slide, x + 0.26, BT + 0.22, cw - 0.52, 0.28, [(tag, 12, True, TEAL)])
    text(slide, x + 0.26, BT + 0.58, cw - 0.52, 0.9, [(lead, 14, True, color, 1.25)])
    text(slide, x + 0.26, BT + 1.62, cw - 0.52, 2.0,
         [(("· " + n, 11.5, False, MUTED, 1.3, 0 if j == 0 else 8))
          for j, n in enumerate(notes)])

box(slide, MX, 5.55, CW, 1.15, fill=WHITE)
text(slide, MX + 0.3, 5.72, CW - 0.6, 0.85,
     [("데이터 확보  →  분석  →  해석  →  문제 도출  →  서비스 기획  →  DB 구축  →  서비스 구현",
       14, True, INK),
      ("분석에서 확인한 한계 — 명목 숫자만으로는 수준을 알 수 없다 — 가 그대로 서비스의 "
       "기준선 설계로 이어졌다.", 12, False, MUTED, 1.2, 6)], align=PP_ALIGN.CENTER)


OUT.parent.mkdir(parents=True, exist_ok=True)
prs.save(OUT)

print(f"슬라이드 {len(prs.slides._sldIdLst)}장 저장")
print(f"  {OUT}")
print()
print("수치는 docs/dashboard.html 에서 읽었습니다 (일별 기준).")
print(f"  Q1 {Q1['strongCount']}/{Q1['totalCount']} ({q1_share}%) · 진폭 중앙값 "
      f"{Q1['medianAmplitude']}")
print(f"  Q2 뚜렷 {Q2['counts']['strong']} / 약함 {Q2['counts']['weak']} / 전체 "
      f"{Q2['counts']['total']}")
print(f"  Q3 물가 +{Q3['cpiGrowth']}% · 명목 +{Q3['medianNominal']}% · 실질 "
      f"+{Q3['medianReal']}%")
print(f"  Q4 {Q4['asOf']['label']} 기준 {q4_total}개 · 위치 70 이상 {Q4['dearShare']}%")
