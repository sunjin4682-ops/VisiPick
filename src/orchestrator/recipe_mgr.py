import threading
from src.utils.logger import setup_logger
from src.utils.config_loader import config

logger = setup_logger("recipe_mgr")

PARTS = config["recipe"]["parts"]  # ["NE555P", "CD4017BE", "ATmega328P", "74HC595N"]


class RecipeManager:
    """
    레시피 충족 상태 관리.
    기본 레시피: 4종 DIP IC 각 1개.
    """

    def __init__(self, parts: list[str] = None):
        self._parts     = parts or list(PARTS)
        self._needed    = {p: 1 for p in self._parts}
        self._collected = {p: 0 for p in self._parts}
        self._lock      = threading.Lock()

    def needs(self, part_type: str) -> bool:
        """해당 부품이 아직 레시피에서 필요한지."""
        with self._lock:
            return self._collected.get(part_type, 0) < self._needed.get(part_type, 0)

    def mark_collected(self, part_type: str):
        """NEEDED 판정 후 수집 처리."""
        with self._lock:
            if part_type in self._collected:
                self._collected[part_type] += 1
                n = self._collected[part_type]
                t = self._needed[part_type]
                logger.info(f"수집: {part_type} ({n}/{t})")

    def is_complete(self) -> bool:
        """레시피 전체 충족 여부."""
        with self._lock:
            return all(
                self._collected[p] >= self._needed[p]
                for p in self._needed
            )

    def reset(self):
        """다음 레시피 사이클을 위해 카운트 초기화."""
        with self._lock:
            self._collected = {p: 0 for p in self._needed}
        logger.info("레시피 초기화")

    def status(self) -> dict:
        """현재 수집 상태 반환."""
        with self._lock:
            return {
                p: {"needed": self._needed[p], "collected": self._collected[p]}
                for p in self._parts
            }
