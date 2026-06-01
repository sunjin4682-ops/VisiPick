from src.utils.logger import setup_logger
from src.utils.config_loader import config
from src.vision.camera_util import center_square, open_top_camera

logger = setup_logger("camera_top")

DUMMY_MODE = config["vision"]["dummy_mode"]
CAM_TOP    = config["cameras"]["top"]
CAM_INDEX  = CAM_TOP["index"]
WIDTH      = CAM_TOP["width"]
HEIGHT     = CAM_TOP["height"]
FPS        = CAM_TOP["fps"]
SQUARE     = CAM_TOP.get("square_crop", False)   # 학습셋(정사각) 기하에 맞춤 — 라이브뷰 --square 와 동일


class CameraTop:
    """Camera1 — 상부 카메라 (종류 식별 + 1차 불량)."""

    def __init__(self):
        self._cap = None
        if DUMMY_MODE:
            logger.info("Camera1(상부) 더미 모드")
            return
        # DSHOW 백엔드 + config.controls(노출/게인/화벨) 적용 — 라이브뷰와 동일 경로
        self._cap = open_top_camera(CAM_TOP)
        if not self._cap.isOpened():
            raise RuntimeError(f"Camera1(상부) 열기 실패: index={CAM_INDEX}")
        logger.info(f"Camera1(상부) 초기화 완료: {WIDTH}x{HEIGHT}@{FPS}fps"
                    f"{' (정사각 크롭)' if SQUARE else ''}")

    def capture(self):
        """프레임 캡처. 더미 모드: None 반환."""
        if DUMMY_MODE or self._cap is None:
            return None
        ret, frame = self._cap.read()
        if not ret:
            logger.warning("Camera1 프레임 캡처 실패")
            return None
        if SQUARE:                       # 학습셋(512x512 정사각) 기하에 맞춤
            frame = center_square(frame)
        return frame

    def release(self):
        if self._cap:
            self._cap.release()
            logger.info("Camera1(상부) 해제")
