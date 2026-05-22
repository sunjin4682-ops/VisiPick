from src.utils.logger import setup_logger

logger = setup_logger("decision")

_GATE_ACTION = {
    "NEEDED":    "PASS_THROUGH",
    "DUPLICATE": "GATE1_PUSH",
    "DEFECT":    "GATE2_PUSH",
}


def judge(part_type: str, defect_code: str, recipe_mgr) -> str:
    """
    3클래스 판정.
      DEFECT    — 불량 → Gate2 푸셔 → reject bin
      DUPLICATE — 레시피 불필요 또는 초과 → Gate1 푸셔 → 반환 bin
      NEEDED    — 통과 → 컨1 끝단 낙하 → 트레이
    """
    if defect_code != "NONE":
        logger.debug(f"{part_type} → DEFECT ({defect_code})")
        return "DEFECT"
    if not recipe_mgr.needs(part_type):
        logger.debug(f"{part_type} → DUPLICATE")
        return "DUPLICATE"
    logger.debug(f"{part_type} → NEEDED")
    return "NEEDED"


def gate_action_for(classification: str) -> str:
    """classification → gate_action 문자열."""
    return _GATE_ACTION.get(classification, "PASS_THROUGH")
