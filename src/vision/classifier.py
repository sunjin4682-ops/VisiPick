import random
from src.utils.logger import setup_logger
from src.utils.config_loader import config

logger = setup_logger("classifier")

PARTS      = config["recipe"]["parts"]
DUMMY_MODE = config["vision"]["dummy_mode"]


class Classifier:
    """DIP IC 4종 분류기. dummy_mode=True 이면 랜덤 선택."""

    def classify(self, frame=None) -> str:
        """
        frame: cv2 이미지 (더미 모드에서는 None 허용)
        반환: "IC칩" | "터미널블록" | "방열판" | "커패시터"
        """
        if DUMMY_MODE:
            result = random.choice(PARTS)
            logger.debug(f"[더미] 분류: {result}")
            return result
        # 실제 OpenCV 처리 (추후 구현)
        raise NotImplementedError("실제 분류기 미구현")
