"""
비전 이식 통합 자가검증 (염재니 비전 → 김선진 몸통).

실행:
    cd C:\\Final_Project\\VisiPick
    python tests/test_vision_integration.py

검증 항목 (프롬프트 체크리스트 + 염재니 4 체크포인트):
  1. part_map 단일 소스 변환 (EN/KO/DB enum)
  2. PASS/REJECT/DUPLICATE → NEEDED/DEFECT/DUPLICATE 라벨 매핑
  3. is_duplicate 부호가 needs() 와 반대 (영문→한글 변환 포함)
  4. 저신뢰(conf<0.40)·핀휨(BENT) → DEFECT (judge 폐기 효과)
  5. dummy_mode=True 시연 안전판 (장비 없이 무한 동작, import 에러 0)
  6. config.vision 에 yolo/pin_inspector 키 존재 (KeyError 방지)
  7. 실제 YOLO(best.pt) 가 돌아 NEEDED/DEFECT 를 산출 (욜로 실동작 증명)
"""
import sys
import copy
import glob
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402

from src.utils.config_loader import config  # noqa: E402
from src.utils.part_map import to_korean, to_db_enum, to_english, PARTS_EN  # noqa: E402
from src.orchestrator.decision import (  # noqa: E402
    Decision, Verdict, verdict_to_label, defect_code_for, gate_action_for,
)
from src.orchestrator.recipe_mgr import RecipeManager  # noqa: E402
from src.vision.classifier import Classifier  # noqa: E402
from src.vision.pin_inspector import PinInspector  # noqa: E402

# 백엔드 내부 loguru 로그를 줄여 테스트 리포트만 깔끔히 출력 (운영 로거에는 영향 없음)
from loguru import logger as _loguru  # noqa: E402
_loguru.remove()

_OK, _FAIL = [], []


def check(name, cond):
    (_OK if cond else _FAIL).append(name)
    print(("  [ OK ] " if cond else "  [FAIL] ") + name)


def section(t):
    print("\n" + "=" * 64 + "\n" + t + "\n" + "=" * 64)


# ── 1. part_map 단일 소스 ─────────────────────────────────────────────────────
section("1) part_map — 부품명 단일 변환 지점")
check("to_korean('IC') == 'IC칩'", to_korean("IC") == "IC칩")
check("to_korean('TerminalBlock') == '터미널블록'", to_korean("TerminalBlock") == "터미널블록")
check("to_db_enum('Capacitor') == 'CAP_220UF'", to_db_enum("Capacitor") == "CAP_220UF")
check("to_english('방열판') == 'Heatsink'", to_english("방열판") == "Heatsink")
check("to_korean(None) is None (미검출 통과)", to_korean(None) is None)
check("recipe.parts 와 KO 매핑 일치",
      set(to_korean(p) for p in PARTS_EN) == set(config["recipe"]["parts"]))

# ── 2. 라벨/게이트 매핑 ──────────────────────────────────────────────────────
section("2) Verdict → 김선진 3클래스 / 게이트 매핑")
check("PASS → NEEDED", verdict_to_label(Verdict.PASS) == "NEEDED")
check("REJECT → DEFECT", verdict_to_label(Verdict.REJECT) == "DEFECT")
check("DUPLICATE → DUPLICATE", verdict_to_label(Verdict.DUPLICATE) == "DUPLICATE")
check("NEEDED → PASS_THROUGH", gate_action_for("NEEDED") == "PASS_THROUGH")
check("DUPLICATE → GATE1_PUSH", gate_action_for("DUPLICATE") == "GATE1_PUSH")
check("DEFECT → GATE2_PUSH", gate_action_for("DEFECT") == "GATE2_PUSH")

# ── 3. is_duplicate 부호 (가장 위험한 함정) + 4. judge 폐기 효과 ──────────────
section("3) is_duplicate 부호 (needs 의 반대) + 4) 저신뢰/핀휨 → DEFECT")

# state_machine 과 동일한 람다를 그대로 재현
recipe = RecipeManager()
is_dup = lambda p: (p is not None) and (not recipe.needs(to_korean(p)))  # noqa: E731
check("신선한 레시피: 'IC' 는 중복 아님 (is_dup==False)", is_dup("IC") is False)
recipe.mark_collected("IC칩")
check("수집 후: 'IC' 는 중복 (is_dup==True)", is_dup("IC") is True)

MIN_CONF = config["vision"]["min_conf"]


def decide(top, side, collected_ko=()):
    r = RecipeManager()
    for c in collected_ko:
        r.mark_collected(c)
    dup = lambda p: (p is not None) and (not r.needs(to_korean(p)))  # noqa: E731
    res = Decision(is_duplicate=dup, min_conf=MIN_CONF).evaluate(top, side)
    return verdict_to_label(res.verdict), defect_code_for(res, top, side)

clean_ic = {"part": "IC", "verdict_hint": "PASS", "confidence": 0.92, "raw_class": "IC"}
normal_side = {"verdict": "NORMAL", "pin_count": 14, "gap_cv": 0.05, "tip_y_range_px": 2}

lbl, dc = decide(clean_ic, normal_side)
check("깨끗한 신규 부품 → NEEDED", lbl == "NEEDED" and dc == "NONE")

lbl, dc = decide(clean_ic, normal_side, collected_ko=["IC칩"])
check("이미 수집된 부품 → DUPLICATE", lbl == "DUPLICATE" and dc == "NONE")

low_conf = {"part": "IC", "verdict_hint": "PASS", "confidence": 0.30, "raw_class": "IC"}
lbl, dc = decide(low_conf, normal_side)
check("저신뢰(conf<0.40) → DEFECT", lbl == "DEFECT")

bent_side = {"verdict": "BENT", "pin_count": 11, "gap_cv": 0.5, "tip_y_range_px": 20}
lbl, dc = decide(clean_ic, bent_side)
check("핀휨(BENT) → DEFECT + defect_code=BENT_PIN", lbl == "DEFECT" and dc == "BENT_PIN")

reject_top = {"part": None, "verdict_hint": "REJECT", "confidence": 0.8, "raw_class": "Broken"}
lbl, dc = decide(reject_top, normal_side)
check("상부 결함(Broken) → DEFECT + defect_code=BROKEN", lbl == "DEFECT" and dc == "BROKEN")

# ── 5. dummy_mode 시연 안전판 ────────────────────────────────────────────────
section("5) dummy_mode=True — 장비 없는 50회 시연 안전판")
dummy_cfg = copy.deepcopy(config["vision"])
dummy_cfg["dummy_mode"] = True
clf_d = Classifier(dummy_cfg)
pin_d = PinInspector(dummy_cfg)
check("Classifier 더미 모드 (모델 미로드)", clf_d.mode == "dummy")

labels = {"NEEDED": 0, "DUPLICATE": 0, "DEFECT": 0}
crashed = False
try:
    rcp = RecipeManager()
    dup = lambda p: (p is not None) and (not rcp.needs(to_korean(p)))  # noqa: E731
    dec = Decision(is_duplicate=dup, min_conf=MIN_CONF)
    for i in range(300):  # 50회 시연을 충분히 상회
        top = clf_d.classify_top(None)      # frame=None (장비 없음)
        side = pin_d.inspect_side(None, top.get("part"))
        res = dec.evaluate(top, side)
        lbl = verdict_to_label(res.verdict)
        labels[lbl] = labels.get(lbl, 0) + 1
        if top["part"] not in PARTS_EN:
            crashed = True
        # NEEDED 면 수집 → DUPLICATE 도 발생하도록 (실제 흐름 모사)
        if lbl == "NEEDED":
            rcp.mark_collected(to_korean(top["part"]))
        if rcp.is_complete():
            rcp.reset()
except Exception as e:  # noqa: BLE001
    crashed = True
    print("   예외:", e)
check("300회 더미 검사 무중단 (frame=None 안전)", not crashed)
check("더미가 NEEDED 산출", labels.get("NEEDED", 0) > 0)
check("더미가 DEFECT 산출 (상부REJECT/측면BENT)", labels.get("DEFECT", 0) > 0)
check("더미가 DUPLICATE 산출", labels.get("DUPLICATE", 0) > 0)
print("   더미 분포:", labels)

# ── 6. config 키 존재 (KeyError 방지) ────────────────────────────────────────
section("6) config.vision yolo/pin_inspector 키 (실장 전환 KeyError 방지)")
v = config["vision"]
for k in ("mode", "yolo_model_path", "yolo_conf", "yolo_iou", "yolo_imgsz",
          "yolo_class_map", "defect_iou_threshold", "yolo_class_index",
          "defect_min_conf", "min_conf", "pin_inspector"):
    check(f"vision['{k}'] 존재", k in v)
for k in ("canny_low", "canny_high", "blur_ksize", "expected_pin_count",
          "pin_gap_tolerance_pct", "tip_y_tolerance_px"):
    check(f"pin_inspector['{k}'] 존재", k in v["pin_inspector"])

# ── 7. 실제 YOLO(best.pt) 실동작 ─────────────────────────────────────────────
section("7) 실제 YOLO(best.pt) — 샘플 프레임 추론 → 3클래스 산출")
yolo_cfg = copy.deepcopy(config["vision"])
yolo_cfg["dummy_mode"] = False
yolo_cfg["mode"] = "yolo"
clf = Classifier(yolo_cfg)
check("Classifier mode == 'yolo' (best.pt 로드 성공)", clf.mode == "yolo")
pin = PinInspector(yolo_cfg)

# 7a) 결함 라벨 크롭(상부 진단 이미지) → 실제 결함 클래스 검출 → DEFECT
print("\n  [7a] 결함 진단 크롭 — YOLO 결함 클래스 검출 → DEFECT")
print(f"   {'file':30s} {'raw':9s} {'part(EN)':14s} {'hint':7s} {'conf':5s}")
print("   " + "-" * 70)
diag_files = sorted(glob.glob(str(ROOT / "sample_frames" / "diag" / "*.jpg")))
diag_detect = 0
diag_defect = 0
fresh_a = RecipeManager()
dup_a = lambda p: (p is not None) and (not fresh_a.needs(to_korean(p)))  # noqa: E731
dec_a = Decision(is_duplicate=dup_a, min_conf=yolo_cfg["min_conf"])
for f in diag_files:
    img = cv2.imread(f)
    if img is None:
        continue
    top = clf.classify_top(img)
    if top.get("part") is not None or top.get("verdict_hint") == "REJECT":
        diag_detect += 1
    # 측면 핀검사는 실제 측면 프레임이 없으므로 NORMAL 로 고정(상부 크롭에 적용 부적합)
    res = dec_a.evaluate(top, {"verdict": "NORMAL"})
    if verdict_to_label(res.verdict) == "DEFECT":
        diag_defect += 1
    print(f"   {Path(f).name[:28]:30s} {str(top.get('raw_class')):9s} "
          f"{str(top.get('part')):14s} {top.get('verdict_hint'):7s} {top.get('confidence'):.2f}")
print(f"   → 검출 {diag_detect}/{len(diag_files)} 프레임, DEFECT {diag_defect}건")
check("YOLO 가 결함 크롭에서 검출(>=6)", diag_detect >= 6)
check("YOLO 결함 검출 → DEFECT 산출", diag_defect > 0)

# 7b) 컨베이어 실촬영 프레임 → 실제 부품(Heatsink) 검출 → NEEDED, 재투입 시 DUPLICATE
print("\n  [7b] 컨베이어 실촬영 프레임 — YOLO 부품 검출 → NEEDED → (재수집)DUPLICATE")
conv_files = sorted(glob.glob(str(ROOT / "sample_frames" / "conveyor" / "*.jpg")))
fresh_b = RecipeManager()
dup_b = lambda p: (p is not None) and (not fresh_b.needs(to_korean(p)))  # noqa: E731
dec_b = Decision(is_duplicate=dup_b, min_conf=yolo_cfg["min_conf"])
conv_parts = 0
got_needed = False
got_duplicate = False
first_part_ko = None
NORMAL_SIDE = {"verdict": "NORMAL", "pin_count": 0, "gap_cv": 0.0, "tip_y_range_px": 0}
for f in conv_files:
    img = cv2.imread(f)
    if img is None:
        continue
    top = clf.classify_top(img)
    if top.get("part") is None:
        continue
    conv_parts += 1
    res = dec_b.evaluate(top, NORMAL_SIDE)   # 실측 측면 대신 NORMAL (부품 검출 격리)
    lbl = verdict_to_label(res.verdict)
    if lbl == "NEEDED":
        got_needed = True
        first_part_ko = to_korean(top["part"])
        fresh_b.mark_collected(first_part_ko)   # 트레이 수집 모사 → 다음엔 중복
    elif lbl == "DUPLICATE":
        got_duplicate = True
print(f"   부품 검출 프레임 {conv_parts}/{len(conv_files)} (예: {first_part_ko}) "
      f"| NEEDED={got_needed} DUPLICATE={got_duplicate}")
check("YOLO 가 컨베이어 프레임에서 부품 검출(>=5)", conv_parts >= 5)
check("실제 YOLO 부품 → NEEDED 산출", got_needed)
check("동일 부품 재검출 → DUPLICATE 산출 (부호 검증)", got_duplicate)

# ── 요약 ─────────────────────────────────────────────────────────────────────
section("요약")
print(f"  통과 {len(_OK)} / 실패 {len(_FAIL)}")
if _FAIL:
    print("  실패 항목:")
    for n in _FAIL:
        print("    -", n)
    sys.exit(1)
print("  ✅ 전체 통과 — 비전 이식 + YOLO 실동작 검증 완료")
sys.exit(0)
