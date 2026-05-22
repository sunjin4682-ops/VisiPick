import random
from src.utils.logger import setup_logger
from src.utils.config_loader import config

logger = setup_logger("defect_detector")

DUMMY_MODE  = config["vision"]["dummy_mode"]
DEFECT_RATE = 0.15  # 더미 불량률 15%


class DefectDetector:
    """
    2단계 불량 검출기.
    - Camera1(상부): 1차 불량 감지
    - Camera2(측면): 핀 휨/들뜨 정밀 검사
    dummy_mode=True 이면 확률 기반 랜덤 반환.
    """

    def detect(self, frame_top=None, frame_side=None) -> str:
        """
        반환: "NONE" (양품) | "BENT_PIN" | "BROKEN"
        """
        if DUMMY_MODE:
            if random.random() < DEFECT_RATE:
                code = random.choice(["BENT_PIN", "BROKEN"])
                logger.debug(f"[더미] 불량 검출: {code}")
                return code
            return "NONE"
        raise NotImplementedError("실제 불량 검출기 미구현")
