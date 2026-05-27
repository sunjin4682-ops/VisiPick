import sys
import io
from loguru import logger

# Windows CP949 → UTF-8: reconfigure()로 기존 fd를 보존하며 인코딩만 교체
# (io.TextIOWrapper 재생성은 isatty() 정보를 잃어 colorize가 무시됨)
if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        if _stream is None:
            continue
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, io.UnsupportedOperation):
            # Python < 3.7 또는 reconfigure 미지원 스트림 → TextIOWrapper로 대체
            if hasattr(_stream, "buffer"):
                _name = "stdout" if _stream is sys.stdout else "stderr"
                setattr(sys, _name, io.TextIOWrapper(
                    _stream.buffer, encoding="utf-8", errors="replace", line_buffering=True
                ))


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
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:8} | {name} | {message}",
        rotation="00:00",
        retention="30 days",
        encoding="utf-8",
        colorize=False,
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
