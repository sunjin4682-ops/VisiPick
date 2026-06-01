"""
3-class decision logic  (염재니 비전 이식 — 통합방향 A)

Merges Camera1 (classification + orientation hint) and Camera2 (pin
inspection) results into one of:
  - PASS      : 양품   -> no gate (lets the part drop into tray)
  - REJECT    : 불량   -> Gate2  (orientation wrong, broken, pinbent, low-conf...)
  - DUPLICATE : 중복   -> Gate1  (this part type already collected)

염재니 Decision.evaluate(top, side) 를 채택하고 김선진 judge() 는 폐기한다.
김선진 인프라(gate_action_for, 3클래스 라벨, DB defect_code)와의 경계는
아래 어댑터로 단일화:
  - verdict_to_label : PASS/REJECT/DUPLICATE -> NEEDED/DEFECT/DUPLICATE
  - defect_code_for  : top/side -> NONE/BENT_PIN/BROKEN/UNKNOWN (DB DefectCode)
  - gate_action_for  : 김선진 것 그대로 유지 (NEEDED->PASS_THROUGH ...)

Inputs
------
top  = {"part": str|None, "verdict_hint": "PASS|REJECT|UNKNOWN", "confidence": float, "raw_class": str}
side = {"verdict": "NORMAL|BENT|UNKNOWN", "pin_count": int, "gap_cv": float, "tip_y_range_px": int}
is_duplicate(part) -> bool   (caller injects; 부호 주의 — 김선진 needs() 와 반대)
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional

from src.utils.logger import setup_logger

logger = setup_logger("decision")


class Verdict(str, Enum):
    PASS = "PASS"
    REJECT = "REJECT"
    DUPLICATE = "DUPLICATE"


@dataclass
class DecisionResult:
    verdict: Verdict
    part: Optional[str]
    reasons: List[str] = field(default_factory=list)
    confidence: float = 0.0
    debug: Dict[str, str] = field(default_factory=dict)


class Decision:
    """Stateless evaluator. Caller injects a `is_duplicate` predicate.

    주의: is_duplicate(part)=True 면 '중복'. 김선진 RecipeManager.needs(part)=True 는
    '아직 필요(안 모음)' 로 부호가 반대다. 따라서 호출부에서 반드시
        is_duplicate = lambda p: (p is not None) and (not recipe.needs(to_korean(p)))
    로 감싸야 한다 (영문 part → 한글 변환 포함).
    """

    def __init__(self, is_duplicate: Callable[[str], bool], min_conf: float = 0.40) -> None:
        self.is_duplicate = is_duplicate
        self.min_conf = min_conf

    def evaluate(self, top: dict, side: dict) -> DecisionResult:
        part = top.get("part")
        conf = float(top.get("confidence", 0.0))
        hint = (top.get("verdict_hint") or "UNKNOWN").upper()
        pin_verdict = (side.get("verdict") or "UNKNOWN").upper()
        reasons: List[str] = []

        # 1) Low-confidence or no detection -> REJECT (route to reject bin)
        if part is None or conf < self.min_conf:
            reasons.append(f"low_conf={conf:.2f}")
            return DecisionResult(Verdict.REJECT, part, reasons, conf,
                                  debug={"hint": hint, "pin": pin_verdict})

        # 2) Orientation / classifier said reject
        if hint == "REJECT":
            reasons.append(f"classifier_hint=REJECT (cls={top.get('raw_class')})")
            return DecisionResult(Verdict.REJECT, part, reasons, conf,
                                  debug={"hint": hint, "pin": pin_verdict})

        # 3) Side-view pin defect
        if pin_verdict == "BENT":
            reasons.append("pin_bent")
            return DecisionResult(Verdict.REJECT, part, reasons, conf,
                                  debug={"hint": hint, "pin": pin_verdict})

        # 4) Already collected for this recipe -> DUPLICATE
        if self.is_duplicate(part):
            reasons.append("already_collected")
            return DecisionResult(Verdict.DUPLICATE, part, reasons, conf,
                                  debug={"hint": hint, "pin": pin_verdict})

        # 5) Default: PASS
        reasons.append("clean")
        return DecisionResult(Verdict.PASS, part, reasons, conf,
                              debug={"hint": hint, "pin": pin_verdict})


# ── 김선진 경계 어댑터 ────────────────────────────────────────────────────────

# 염재니 Verdict -> 김선진 3클래스 라벨
_VERDICT_TO_LABEL = {
    "PASS":      "NEEDED",
    "REJECT":    "DEFECT",
    "DUPLICATE": "DUPLICATE",
}

# 김선진 3클래스 라벨 -> 게이트 동작 (김선진 것 그대로 유지)
_GATE_ACTION = {
    "NEEDED":    "PASS_THROUGH",
    "DUPLICATE": "GATE1_PUSH",
    "DEFECT":    "GATE2_PUSH",
}


def verdict_to_label(verdict) -> str:
    """염재니 Verdict(enum/str) → 김선진 NEEDED/DUPLICATE/DEFECT.

    매핑 외 값은 안전하게 DEFECT(reject bin) 로 보낸다.
    """
    v = verdict.value if isinstance(verdict, Verdict) else str(verdict)
    return _VERDICT_TO_LABEL.get(v.upper(), "DEFECT")


def defect_code_for(result: DecisionResult, top: dict, side: dict) -> str:
    """DecisionResult + top/side → 김선진 DB DefectCode 문자열.

    반환: "NONE" | "BENT_PIN" | "BROKEN" | "UNKNOWN"
    REJECT 가 아닌 경우(NEEDED/DUPLICATE)는 항상 "NONE".
    """
    if result.verdict != Verdict.REJECT:
        return "NONE"
    if (side.get("verdict") or "").upper() == "BENT":
        return "BENT_PIN"
    raw = top.get("raw_class") or ""
    if raw == "Pinbent":
        return "BENT_PIN"
    if raw in ("Broken", "Dented"):
        return "BROKEN"
    if top.get("part") is None:
        return "UNKNOWN"  # 저신뢰/미검출
    return "BROKEN"


def gate_action_for(classification: str) -> str:
    """classification → gate_action 문자열 (김선진 인프라 그대로)."""
    return _GATE_ACTION.get(classification, "PASS_THROUGH")
