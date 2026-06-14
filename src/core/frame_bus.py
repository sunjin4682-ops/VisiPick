"""프레임 버스 — 프로세스 간 '최신 카메라 프레임' 공유 (MJPEG 송출용).

V6.4 통신 아키텍처: 영상=MJPEG(HTTP :8000). 그런데 카메라를 점유하는 프로세스
(state_machine / live_yolo)와 MJPEG 를 송출하는 프로세스(api_server)가 분리돼 있어
메모리를 직접 공유할 수 없다. 그래서 '최신 1프레임'만 파일로 주고받는다.

- publish(name, frame_bgr): BGR 프레임을 JPEG 인코딩 후 <dir>/<name>.jpg 에 원자적 기록
- read_jpeg(name) -> bytes|None: 최신 JPEG 바이트 (없으면 None)

설계 메모:
- '최신 프레임 덮어쓰기' 모델 — 큐잉/히스토리 없음. 라이브 모니터링엔 이걸로 충분.
- 원자적 기록(임시파일 → os.replace)으로 reader 가 반쪽 프레임을 읽지 않게 한다.
- 카메라 점유 충돌 방지: 생산자(state_machine 또는 live_yolo)는 한 번에 하나만 실행.
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import cv2

from src.utils.config_loader import config

_STREAM_DIR = Path(config.get("stream", {}).get("dir", "data/stream"))
_JPEG_QUALITY = int(config.get("stream", {}).get("jpeg_quality", 70))

_STREAM_DIR.mkdir(parents=True, exist_ok=True)


def _path(name: str) -> Path:
    return _STREAM_DIR / f"{name}.jpg"


def publish(name: str, frame_bgr, quality: int | None = None) -> bool:
    """BGR 프레임을 JPEG 로 인코딩해 <dir>/<name>.jpg 에 원자적으로 기록.
    frame 이 None 이면 무시(False)."""
    if frame_bgr is None:
        return False
    q = _JPEG_QUALITY if quality is None else int(quality)
    ok, buf = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, q])
    if not ok:
        return False
    dst = _path(name)
    # 임시파일 이름을 스레드마다 다르게 — 같은 'side'를 연속송출 스레드와 검사 스레드가
    # 동시에 쓰면 같은 .tmp 에서 PermissionError(쓰기 충돌). 스레드별 .tmp 로 분리.
    tmp = dst.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_bytes(buf.tobytes())
    except PermissionError:
        return False              # 일시적 충돌 — 이번 프레임만 버림(다음 프레임이 곧 옴)
    # 원자적 교체. Windows 는 reader(api_server)가 dst 를 읽는 순간 교체가
    # PermissionError(WinError 5) 로 실패할 수 있어 — 일시적이라 잠깐 후 재시도.
    for _ in range(5):
        try:
            os.replace(tmp, dst)
            return True
        except PermissionError:
            time.sleep(0.005)
    try:
        tmp.unlink()              # 끝내 실패 시 임시파일 정리(이번 프레임만 버림)
    except OSError:
        pass
    return False


def read_jpeg(name: str) -> bytes | None:
    """최신 JPEG 바이트 반환 (없으면 None)."""
    p = _path(name)
    try:
        return p.read_bytes()
    except (FileNotFoundError, OSError):
        return None
