import sys
from src.utils.logger import setup_logger
from src.utils.config_loader import config

logger = setup_logger("camera_top")

DUMMY_MODE = config["vision"]["dummy_mode"]
CAM_INDEX  = config["cameras"]["top"]["index"]
WIDTH      = config["cameras"]["top"]["width"]
HEIGHT     = config["cameras"]["top"]["height"]
FPS        = config["cameras"]["top"]["fps"]


class CameraTop:
    """Camera1 — 상부 카메라 (종류 식별 + 1차 불량)."""

    def __init__(self):
        self._cap = None
        if DUMMY_MODE:
            logger.info("Camera1(상부) 더미 모드")
            return
        import cv2
        # Linux(Jetson)는 V4L2 백엔드 명시 — 인덱스 오인식/지연 방지. 그 외 OS는 기본 백엔드.
        backend = cv2.CAP_V4L2 if sys.platform.startswith("linux") else cv2.CAP_ANY
        self._cap = cv2.VideoCapture(CAM_INDEX, backend)
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
        self._cap.set(cv2.CAP_PROP_FPS, FPS)
        if not self._cap.isOpened():
            raise RuntimeError(f"Camera1(상부) 열기 실패: index={CAM_INDEX}")
        logger.info(f"Camera1(상부) 초기화 완료: {WIDTH}x{HEIGHT}@{FPS}fps")

    def capture(self):
        """프레임 캡처. 더미 모드: None 반환."""
        if DUMMY_MODE or self._cap is None:
            return None
        ret, frame = self._cap.read()
        if not ret:
            logger.warning("Camera1 프레임 캡처 실패")
            return None
        return frame

    def release(self):
        if self._cap:
            self._cap.release()
            logger.info("Camera1(상부) 해제")
