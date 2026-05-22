import threading
from src.utils.logger import setup_logger

logger = setup_logger("tray_mgr")


class TrayManager:
    """트레이 수집 카운트 관리."""

    def __init__(self):
        self._count = 0
        self._lock  = threading.Lock()

    def on_part_passed(self, part_type: str):
        """NEEDED 부품이 컨베이어 끝단에서 트레이로 낙하할 때 호출."""
        with self._lock:
            self._count += 1
            logger.info(f"트레이 수집: {part_type} (누계 {self._count}개)")

    def get_count(self) -> int:
        with self._lock:
            return self._count

    def reset(self):
        with self._lock:
            self._count = 0
        logger.info("트레이 카운트 초기화")
