import random
from src.utils.logger import setup_logger
from src.utils.config_loader import config

logger = setup_logger("classifier")

PARTS      = config["recipe"]["parts"]
DUMMY_MODE = config["vision"]["dummy_mode"]
DEVICE     = config["vision"].get("device", "cuda")  # 실제 추론 시 GPU 지정 (Jetson: "cuda" / 0)


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
        # 실제 추론 (추후 구현): Ultralytics 모델을 DEVICE에 올려 사용
        #   예) self._model.predict(frame, device=DEVICE)  # DEVICE="cuda"
        raise NotImplementedError(f"실제 분류기 미구현 (target device={DEVICE})")
