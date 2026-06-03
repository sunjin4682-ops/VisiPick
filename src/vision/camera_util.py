"""상부 카메라 공통 유틸 — 라이브뷰(tools/live_yolo.py)와 production(camera_top.py)이
같은 프레임 처리를 쓰도록 한곳에 모은다. (튜닝 화면 ≠ 실전 화면 도메인 갭 방지)

- open_top_camera(): config.cameras.top 의 백엔드/포맷/해상도/노출 설정을 적용해 VideoCapture 생성
- center_square(): 프레임 중앙을 정사각형 크롭 (학습셋 512x512 기하에 맞춤)
"""
from __future__ import annotations

import sys

import cv2

# config.cameras.top.controls 키 → OpenCV 속성 매핑.
# 자동(auto_*) 을 먼저 끈 뒤 수동값을 적용해야 노출/화벨이 고정된다.
_CTRL_PROPS = [
    ("auto_exposure",  cv2.CAP_PROP_AUTO_EXPOSURE),   # DSHOW: 0.25=수동, 0.75=자동
    ("auto_wb",        cv2.CAP_PROP_AUTO_WB),          # 0=수동, 1=자동
    ("exposure",       cv2.CAP_PROP_EXPOSURE),         # Windows 로그값: 시간=2^(-값) 초 (-5≈31ms)
    ("gain",           cv2.CAP_PROP_GAIN),
    ("wb_temperature", cv2.CAP_PROP_WB_TEMPERATURE),
    ("brightness",     cv2.CAP_PROP_BRIGHTNESS),
    ("contrast",       cv2.CAP_PROP_CONTRAST),
    ("gamma",          cv2.CAP_PROP_GAMMA),
    ("sharpness",      cv2.CAP_PROP_SHARPNESS),
]


def apply_camera_controls(cap, cam: dict):
    """config.cameras.top 의 포맷/해상도/노출 설정을 카메라에 적용.

    글로벌셔터 모션블러 제거는 '짧은 노출 + 충분한 조명' 이 핵심.
    형광등 기본값(config): exposure -5(~31ms) + gain 보정. LED 추가 후엔
    config 에서 exposure 를 -9~-10 으로 낮추고 gain 을 줄인다.
    """
    fourcc = cam.get("fourcc", "MJPG")       # 1200p 고프레임은 MJPEG 필수
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  cam.get("width", 1280))
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cam.get("height", 720))
    cap.set(cv2.CAP_PROP_FPS,          cam.get("fps", 30))

    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)      # 버퍼 최소화 — 오래된 프레임 누적(검사 밀림) 완화
    ctrl = cam.get("controls", {})
    for key, prop in _CTRL_PROPS:            # config 에 있는 키만 적용
        if key in ctrl:
            cap.set(prop, float(ctrl[key]))


def open_top_camera(cam: dict, index=None):
    """config.cameras.top(cam) 설정으로 VideoCapture 를 열어 반환.

    Windows 실 카메라는 DSHOW 백엔드라야 노출/화벨 수동 제어가 먹는다.
    index 를 주면 config 의 index 대신 사용 (라이브뷰 --source 대응).
    """
    idx = cam["index"] if index is None else index
    if sys.platform == "win32":
        cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
    else:
        cap = cv2.VideoCapture(idx)
    apply_camera_controls(cap, cam)
    return cap


def center_square(frame):
    """프레임 중앙을 정사각형으로 크롭. 학습셋(512x512 정사각)과 기하를 맞춰
    16:9 레터박스로 부품이 작아지는 도메인 갭을 줄인다."""
    h, w = frame.shape[:2]
    s = min(h, w)
    y0 = (h - s) // 2
    x0 = (w - s) // 2
    return frame[y0:y0 + s, x0:x0 + s]
