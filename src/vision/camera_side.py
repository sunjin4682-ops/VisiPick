from src.utils.logger import setup_logger
from src.utils.config_loader import config

logger = setup_logger("camera_side")

DUMMY_MODE = config["vision"]["dummy_mode"]
CAM_INDEX  = config["cameras"]["side"]["index"]


class CameraSide:
    """Camera2 — 측면 카메라 (핀 휘어짐/들뜨 정밀 검사)."""

    def __init__(self):
        self._cap = None
        if DUMMY_MODE:
            logger.info("Camera2(측면) 더미 모드")
            return
        import cv2
        self._cap = cv2.VideoCapture(CAM_INDEX)
        if not self._cap.isOpened():
            raise RuntimeError(f"Camera2(측면) 열기 실패: index={CAM_INDEX}")
        logger.info(f"Camera2(측면) 초기화 완료: index={CAM_INDEX}")

    def capture(self):
        """프레임 캡처. 더미 모드: None 반환."""
        if DUMMY_MODE or self._cap is None:
            return None
        ret, frame = self._cap.read()
        if not ret:
            logger.warning("Camera2 프레임 캡처 실패")
            return None
        return frame

    def release(self):
        if self._cap:
            self._cap.release()
            logger.info("Camera2(측면) 해제")
