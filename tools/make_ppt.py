# -*- coding: utf-8 -*-
"""김선진 파트 발표 PPT 생성 (팀 템플릿 색/비율 매칭)."""
from pptx import Presentation
from pptx.util import Emu, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR

PX = lambda v: Emu(int(v * 9525))           # px → EMU (96dpi)
NAVY  = RGBColor(0x23, 0x41, 0x67)
SLATE = RGBColor(0x38, 0x4F, 0x67)
BLUE  = RGBColor(0x4D, 0x69, 0x87)
LIGHT = RGBColor(0xA4, 0xB9, 0xCE)
TINT  = RGBColor(0xEE, 0xF2, 0xF6)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
GRAY  = RGBColor(0x5A, 0x6B, 0x7D)
FONT  = "맑은 고딕"

prs = Presentation()
prs.slide_width  = PX(1440)
prs.slide_height = PX(810)
BLANK = prs.slide_layouts[6]


def slide():
    s = prs.slides.add_slide(BLANK)
    bg = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, PX(1440), PX(810))
    bg.fill.solid(); bg.fill.fore_color.rgb = WHITE; bg.line.fill.background()
    bg.shadow.inherit = False
    return s


def txt(s, x, y, w, h, lines, size=18, color=SLATE, bold=False, align=PP_ALIGN.LEFT,
        anchor=MSO_ANCHOR.TOP, sp=6):
    tb = s.shapes.add_textbox(PX(x), PX(y), PX(w), PX(h)); tf = tb.text_frame
    tf.word_wrap = True; tf.vertical_anchor = anchor
    if isinstance(lines, str): lines = [lines]
    for i, ln in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align; p.space_after = Pt(sp)
        if isinstance(ln, tuple):
            t, kw = ln
        else:
            t, kw = ln, {}
        r = p.add_run(); r.text = t
        r.font.size = Pt(kw.get("size", size)); r.font.bold = kw.get("bold", bold)
        r.font.color.rgb = kw.get("color", color); r.font.name = FONT
    return tb


def box(s, x, y, w, h, text="", fill=NAVY, fc=WHITE, size=15, bold=True,
        shape=MSO_SHAPE.ROUNDED_RECTANGLE, align=PP_ALIGN.CENTER):
    sp = s.shapes.add_shape(shape, PX(x), PX(y), PX(w), PX(h))
    if fill is None: sp.fill.background()
    else: sp.fill.solid(); sp.fill.fore_color.rgb = fill
    sp.line.color.rgb = fill if fill else BLUE; sp.line.width = Pt(1)
    sp.shadow.inherit = False
    tf = sp.text_frame; tf.word_wrap = True; tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]; p.alignment = align
    for j, part in enumerate(text.split("\n")):
        pp = p if j == 0 else tf.add_paragraph(); pp.alignment = align
        r = pp.add_run(); r.text = part; r.font.size = Pt(size)
        r.font.bold = bold; r.font.color.rgb = fc; r.font.name = FONT
    return sp


def line(s, x1, y1, x2, y2, color=BLUE, w=2.0):
    c = s.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, PX(x1), PX(y1), PX(x2), PX(y2))
    c.line.color.rgb = color; c.line.width = Pt(w); c.shadow.inherit = False
    return c


def header(s, title, num, kicker=""):
    box(s, 0, 0, 14, 86, "", fill=NAVY, shape=MSO_SHAPE.RECTANGLE)  # left accent
    txt(s, 80, 50, 1000, 70, title, size=34, color=NAVY, bold=True)
    if kicker:
        txt(s, 80, 30, 1000, 24, kicker, size=14, color=BLUE, bold=True)
    txt(s, 1230, 36, 130, 60, num, size=40, color=LIGHT, bold=True, align=PP_ALIGN.RIGHT)
    line(s, 80, 132, 1360, 132, color=LIGHT, w=1.5)


def footer(s, n):
    txt(s, 80, 770, 600, 24, "VisiPick · 중앙 서버 / 통신 통합", size=11, color=LIGHT)
    txt(s, 1260, 770, 100, 24, f"{n:02d}", size=11, color=LIGHT, align=PP_ALIGN.RIGHT)


# ── 0. 파트 표지 ──────────────────────────────────────────────
s = slide()
box(s, 0, 0, 1440, 810, "", fill=NAVY, shape=MSO_SHAPE.RECTANGLE)
box(s, 0, 470, 1440, 6, "", fill=BLUE, shape=MSO_SHAPE.RECTANGLE)
txt(s, 110, 300, 1200, 40, "PART", size=20, color=LIGHT, bold=True)
txt(s, 108, 330, 1240, 110, "중앙 서버 · 통신 통합", size=58, color=WHITE, bold=True)
txt(s, 110, 500, 1240, 120, [
    ("FastAPI 서버 구축 · API 연동", {"size": 22, "color": LIGHT}),
    ("MQTT 기반 실시간 데이터 통신 · 전체 공정 조율", {"size": 22, "color": LIGHT}),
], sp=10)
txt(s, 110, 700, 600, 40, "발표 : 김선진", size=20, color=WHITE, bold=True)

# ── 1. 전체 연결 (단일 마스터) ─────────────────────────────────
s = slide(); header(s, "흩어진 장치를 잇는 단일 마스터", "01", "SYSTEM ARCHITECTURE")
txt(s, 80, 150, 1280, 40,
    "장치마다 다른 통신을 하나의 공정으로 통합 — 모든 상태의 단일 진실원(Single Source of Truth)",
    size=18, color=SLATE, bold=True)
# 중앙
box(s, 600, 380, 240, 110, "Python\n중앙 서버", fill=NAVY, fc=WHITE, size=22)
# 주변 노드 (라벨, 프로토콜)
nodes = [
    (180, 230, "카메라\n(상부·측면)", "검사 데이터"),
    (1060, 230, "ESP32\n게이트·컨베이어", "USB Serial"),
    (1100, 470, "myCobot\n로봇팔", "Ethernet TCP"),
    (700, 640, "AGV ×2", "MQTT (무선)"),
    (180, 470, "WPF\nHMI", "WebSocket·MJPEG"),
]
cx, cy = 720, 435
for x, y, label, proto in nodes:
    box(s, x, y, 210, 86, label, fill=TINT, fc=NAVY, size=16)
    line(s, cx, cy, x + 105, y + 43, color=LIGHT, w=2.2)
    txt(s, x, y + 88, 210, 22, proto, size=12, color=BLUE, bold=True, align=PP_ALIGN.CENTER)
footer(s, 1)

# ── 2. 검사 → 3분류 → 정밀 게이트 ──────────────────────────────
s = slide(); header(s, "실시간 검사 → 3분류 → 정밀 게이트", "02", "INSPECTION & SORTING")
txt(s, 80, 150, 1280, 30,
    "2단계 검사 결과를 받아 부품을 3가지로 자동 분류하고, 정확한 순간에 게이트로 밀어냄",
    size=18, color=SLATE, bold=True)
box(s, 110, 240, 250, 120, "2단계 검사\n상부 + 측면", fill=NAVY, size=18)
txt(s, 110, 366, 250, 40, "멀티프레임 보수 판정", size=13, color=BLUE, bold=True, align=PP_ALIGN.CENTER)
line(s, 360, 300, 470, 300, color=LIGHT, w=2.5)
box(s, 470, 240, 230, 120, "3클래스\n자동 판정", fill=BLUE, size=18)
# 3갈래
outs = [(800, 200, "NEEDED · 양품", "→ 트레이 수집", RGBColor(0x2E,0x7D,0x4F)),
        (800, 300, "DUPLICATE · 중복", "→ 반환 게이트", RGBColor(0xC8,0x8A,0x2C)),
        (800, 400, "DEFECT · 불량", "→ 폐기 게이트", RGBColor(0xB0,0x3A,0x3A))]
for x, y, t, sub, col in outs:
    line(s, 700, 300, x, y + 32, color=LIGHT, w=2)
    box(s, x, y, 260, 64, t, fill=col, size=16)
    txt(s, x + 270, y + 14, 260, 36, sub, size=15, color=SLATE, bold=True)
# 어필 박스
box(s, 110, 470, 1220, 250, "", fill=TINT, fc=NAVY, shape=MSO_SHAPE.ROUNDED_RECTANGLE)
txt(s, 150, 495, 1150, 40, "어필 포인트 — 게이트 '정밀 타이밍' 제어", size=20, color=NAVY, bold=True)
txt(s, 150, 545, 1150, 170, [
    ("· 검사 시점부터 카메라→게이트 거리 ÷ 컨베이어 속도로 발사 순간을 계산", {"size": 17}),
    ("· 부품마다 크기·마찰이 달라 거동이 다름 → 부품별로 발사 시점을 따로 보정", {"size": 17}),
    ("   예) 터미널블록 1.5초 빨리 · 방열판 0.5초 늦게 · IC칩 기준값", {"size": 16, "color": BLUE, "bold": True}),
], color=SLATE, sp=10)
footer(s, 2)

# ── 3. 논스톱 연속 운전 ────────────────────────────────────────
s = slide(); header(s, "라인을 멈추지 않는 논스톱 연속 운전", "03", "NON-STOP OPERATION")
txt(s, 80, 150, 1280, 30,
    "트레이가 완성되고 로봇이 이재하는 동안에도 검사가 멈추지 않음 — 처리량 극대화",
    size=18, color=SLATE, bold=True)
# 순차 (전)
txt(s, 110, 230, 400, 30, "기존 순차 방식", size=18, color=GRAY, bold=True)
segs1 = [(110,"검사",BLUE,180),(300,"이재 대기·로봇",LIGHT,260),(570,"검사",BLUE,180)]
for x,t,c,w in segs1:
    box(s, x, 270, w, 60, t, fill=c, fc=NAVY if c==LIGHT else WHITE, size=14)
txt(s, 770, 282, 360, 40, "← 이재 동안 검사 빈틈(멈춤)", size=15, color=RGBColor(0xB0,0x3A,0x3A), bold=True)
# 연속 (후)
txt(s, 110, 380, 400, 30, "연속 운전 (적용)", size=18, color=NAVY, bold=True)
segs2 = [(110,"검사",BLUE,200),(320,"검사",BLUE,200),(530,"검사",BLUE,200),(740,"검사",BLUE,200)]
for x,t,c,w in segs2:
    box(s, x, 420, w, 60, t, fill=c, size=14)
box(s, 110, 490, 830, 30, "", fill=NAVY, shape=MSO_SHAPE.RECTANGLE)
txt(s, 120, 492, 820, 26, "이재(로봇·AGV)는 백그라운드에서 동시 진행 — 검사 끊김 0", size=14, color=WHITE, bold=True, align=PP_ALIGN.CENTER)
# 효과
box(s, 110, 570, 1220, 150, "", fill=TINT)
txt(s, 150, 595, 1150, 40, "어필 포인트 — 완성 즉시 다음 트레이 수집 시작", size=20, color=NAVY, bold=True)
txt(s, 150, 645, 1150, 70, [
    ("· 레시피 완성 순간 트레이 정보를 넘기고 즉시 리셋 → 다음 부품을 새 트레이로 인식", {"size": 17}),
    ("· 이재(낙하 대기·로봇·AGV)는 별도 스레드 → 컨베이어를 한 번도 세우지 않음", {"size": 17}),
], color=SLATE, sp=10)
footer(s, 3)

# ── 4. AGV 2대 자율 교대 ──────────────────────────────────────
s = slide(); header(s, "AGV 2대 자율 교대 운반", "04", "AGV COORDINATION")
txt(s, 80, 150, 1280, 30,
    "RFID 위치 인식과 홈 슬롯 관리로, 사람 개입 없이 2대가 충돌 없이 번갈아 운반",
    size=18, color=SLATE, bold=True)
# 경로 맵
box(s, 130, 280, 220, 90, "출발점\n(적재)", fill=NAVY, size=17)
box(s, 600, 280, 220, 90, "창고", fill=BLUE, size=17)
box(s, 1080, 280, 220, 90, "홈\n(대기)", fill=SLATE, size=17)
line(s, 350, 325, 600, 325, color=LIGHT, w=2.5)
line(s, 820, 325, 1080, 325, color=LIGHT, w=2.5)
txt(s, 360, 300, 240, 26, "GO_WAREHOUSE →", size=13, color=BLUE, bold=True, align=PP_ALIGN.CENTER)
txt(s, 830, 300, 240, 26, "복귀 →", size=13, color=BLUE, bold=True, align=PP_ALIGN.CENTER)
box(s, 110, 440, 1220, 280, "", fill=TINT)
txt(s, 150, 465, 1150, 40, "어필 포인트 — 위치 기반 자동 교대 로직", size=20, color=NAVY, bold=True)
txt(s, 150, 515, 1150, 200, [
    ("· 출발점 RFID로 '지금 적재 위치에 와있는 AGV'를 인식 → 그 AGV를 운반 지시", {"size": 17}),
    ("· AGV1이 출발하면 홈 대기 중인 AGV2를 자동 호출 → 출발점으로 이동", {"size": 17}),
    ("· 홈 슬롯 점유표로 빈 홈만 배정 → 두 대가 충돌 없이 무한 교대", {"size": 17}),
    ("· 재시작·순서와 무관하게 실제 위치로 판단 → 견고한 운영", {"size": 16, "color": BLUE, "bold": True}),
], color=SLATE, sp=11)
footer(s, 4)

# ── 5. 마무리 ─────────────────────────────────────────────────
s = slide()
box(s, 0, 0, 1440, 810, "", fill=NAVY, shape=MSO_SHAPE.RECTANGLE)
txt(s, 110, 150, 1240, 40, "SUMMARY", size=20, color=LIGHT, bold=True)
txt(s, 108, 195, 1240, 120, "검사부터 운반까지, 하나의 자동화 셀로 통합", size=42, color=WHITE, bold=True)
txt(s, 110, 320, 1240, 50,
    "흩어진 하드웨어를 단일 마스터가 조율 — 검사 → 분류 → 수집 → 이재 → 운반 전 과정 무인화",
    size=20, color=LIGHT)
cards = [("4종", "실시간 분류"), ("2 대", "카메라 검사"),
         ("2 대", "AGV 자율 교대"), ("논스톱", "연속 운전")]
for i, (big, sub) in enumerate(cards):
    x = 110 + i * 305
    box(s, x, 440, 270, 180, "", fill=BLUE, shape=MSO_SHAPE.ROUNDED_RECTANGLE)
    txt(s, x, 480, 270, 70, big, size=40, color=WHITE, bold=True, align=PP_ALIGN.CENTER)
    txt(s, x, 560, 270, 40, sub, size=18, color=LIGHT, align=PP_ALIGN.CENTER)
txt(s, 110, 690, 1240, 40, "→ 통신 통합과 공정 조율로 셀 전체를 완성한 것이 제 역할이었습니다.",
    size=18, color=WHITE, bold=True)

out = r"C:\Users\moblle\Downloads\발표_중앙서버_김선진.pptx"
prs.save(out)
print("저장 완료:", out, "| 슬라이드", len(prs.slides.__iter__.__self__._sldIdLst))
