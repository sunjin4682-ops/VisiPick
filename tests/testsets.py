"""
tests/testsets.py — decision.py 판정 테스트셋 (C1 검증 포함)

염재니 Decision + 어댑터(verdict_to_label / gate_action_for / defect_code_for)의
3+1 클래스 분기를 케이스 테이블로 검증한다. 특히 C1:
    저신뢰(low-conf) / 미검출(no-detection) → UNCERTAIN → Gate1(반환 컨베이어)
    — 불량(Gate2 폐기)이 아니라 재투입을 위한 '보류'.

실행:  python -m tests.testsets    (전 케이스 통과 시 ALL PASS, 실패 시 AssertionError)
"""
from src.orchestrator.decision import (
    Decision, verdict_to_label, gate_action_for, defect_code_for,
)
from src.utils.logger import setup_logger

logger = setup_logger("testsets")

MIN_CONF = 0.40

# (이름, top, side, is_duplicate, expected_label, expected_gate)
CASES = [
    ("정상 신규(IC)",
     {"part": "IC", "confidence": 0.95, "verdict_hint": "PASS", "raw_class": "IC"},
     {"verdict": "NORMAL"}, False, "NEEDED", "PASS_THROUGH"),

    ("중복(이미 수집)",
     {"part": "IC", "confidence": 0.95, "verdict_hint": "PASS", "raw_class": "IC"},
     {"verdict": "NORMAL"}, True, "DUPLICATE", "GATE1_PUSH"),

    ("불량-상부 REJECT(Broken)",
     {"part": "IC", "confidence": 0.92, "verdict_hint": "REJECT", "raw_class": "Broken"},
     {"verdict": "NORMAL"}, False, "DEFECT", "GATE2_PUSH"),

    ("불량-측면 핀휨(BENT)",
     {"part": "IC", "confidence": 0.90, "verdict_hint": "PASS", "raw_class": "IC"},
     {"verdict": "BENT"}, False, "DEFECT", "GATE2_PUSH"),

    ("저신뢰 → UNCERTAIN(C1)",          # 저신뢰는 폐기(Gate2)가 아니라 반환(Gate1)
     {"part": "IC", "confidence": 0.20, "verdict_hint": "PASS", "raw_class": "IC"},
     {"verdict": "NORMAL"}, False, "UNCERTAIN", "GATE1_PUSH"),

    ("미검출 → UNCERTAIN(C1)",
     {"part": None, "confidence": 0.0, "verdict_hint": "UNKNOWN", "raw_class": None},
     {"verdict": "UNKNOWN"}, False, "UNCERTAIN", "GATE1_PUSH"),
]


def run():
    for name, top, side, dup, exp_label, exp_gate in CASES:
        decider = Decision(is_duplicate=lambda p, _d=dup: _d, min_conf=MIN_CONF)
        r = decider.evaluate(top, side)
        label = verdict_to_label(r.verdict)
        gate = gate_action_for(label)
        defect = defect_code_for(r, top, side)
        ok = (label == exp_label and gate == exp_gate)
        logger.info(f"[{'OK ' if ok else 'FAIL'}] {name:26} → "
                    f"{r.verdict.value:9} | {label:9} | {gate:12} | defect={defect}")
        assert ok, f"{name}: expected {exp_label}/{exp_gate}, got {label}/{gate}"
    logger.success(f"testsets ALL PASS — {len(CASES)}/{len(CASES)} 케이스")
    print(f"\n[OK] testsets ALL PASS — {len(CASES)}/{len(CASES)} 케이스")


if __name__ == "__main__":
    run()
