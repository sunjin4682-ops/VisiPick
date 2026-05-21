import sys
import io
from loguru import logger

# Windows CP949 콘솔 → UTF-8 (모듈 최초 로드 시 한 번만 교체)
if sys.platform == "win32" and hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
    )


def setup_logger(name: str):
    logger.remove()

    logger.add(
        sys.stdout,
        format="<green>{time:HH:mm:ss}</green> | <level>{level:8}</level> | <cyan>{name}</cyan> | {message}",
        level="DEBUG",
        colorize=True,
    )

    logger.add(
        f"logs/{name}-{{time:YYYY-MM-DD}}.log",
        format="{{time:YYYY-MM-DD HH:mm:ss.SSS}} | {{level:8}} | {{name}} | {{message}}",
        rotation="00:00",
        retention="30 days",
        encoding="utf-8",
        level="DEBUG",
    )

    logger.info(f"Logger 시작 [{name}]")
    return logger


if __name__ == "__main__":
    log = setup_logger("test")
    log.debug("디버그 메시지")
    log.info("정보 메시지")
    log.warning("경고 메시지")
    log.error("오류 메시지")
    log.success("성공 메시지")
