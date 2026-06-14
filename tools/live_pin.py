"""
측면 카메라 라이브 핀검사 뷰어 — 전체 시스템 없이 Camera2 핀검사를 튜닝.

production 과 동일 경로(src.vision.pin_inspector._PinDetector)를 그대로 사용하므로,
여기서 보이는 핀 개수/간격CV/끝점편차/판정이 곧 state_machine 이 받는 side 값이다.

측면 핀검사는 백라이트(역광) 실루엣이 핵심:
  - 부품 뒤에서 LED 패널로 비춰 부품이 '검은 실루엣' 으로 나오게 한다.
  - 그래야 Canny 엣지가 배경 노이즈 없이 핀 윤곽만 깨끗하게 잡는다.
  - 촬영 거리·각도는 고정 — 핀 간격을 픽셀로 재므로 거리가 변하면 임계값이 깨진다.

실행:
    cd C:\\VisiPick
    python tools/live_pin.py                  # config.cameras.side.index 카메라 라이브
    python tools/live_pin.py --source 1        # 카메라 인덱스 직접 지정
    python tools/live_pin.py --source clip.mp4 # 녹화 영상으로 테스트
    python tools/live_pin.py --part IC         # 기대 핀수 비교용 부품 지정(IC/TerminalBlock/...)
    python tools/live_pin.py --edges           # Canny 엣지맵을 나란히 표시(임계값 튜닝)

키:
    [ / ]  Canny low  -10 / +10        ; / '  Canny high -10 / +10
    - / =  peak 최소거리 -2 / +2 px     (핀 과다카운트 잡는 핵심 — 핀피치의 ~60%)
    , / .  peak 임계값  -0.05 / +0.05
    e      오른쪽 패널: 엣지맵 토글
    s      오른쪽 패널: 실루엣(이진) 토글 — 핀 끝점은 이 실루엣 최하단에서 검출
    q/ESC  종료
값을 화면에서 맞춘 뒤, config.vision.pin_inspector(canny_low/high, peak_min_dist_px, peak_thresh)에 기입한다.
"""
from __future__ import annotations
import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from src.utils.config_loader import config  # noqa: E402
from src.vision.camera_util import open_camera, open_camera_auto  # noqa: E402
from src.vision.pin_inspector import _PinDetector  # noqa: E402


def _frame_source(source: str, nocontrols: bool = False):
    """프레임 제너레이터. frame 을 yield."""
    if source.isdigit():
        if nocontrols:
            # 자동 노출로 열기 (백라이트 없이 튜닝할 때 / 검은 화면 진단용).
            # config 의 수동 저노출(-6)이 장치에 박혀있을 수 있으므로 자동 노출을
            # 명시적으로 켜서 복구한다(단순히 set 을 건너뛰면 박힌 값이 남음).
            cap = cv2.VideoCapture(int(source), cv2.CAP_DSHOW)
            cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)   # DSHOW: 0.75=자동
            cap.set(cv2.CAP_PROP_AUTO_WB, 1)
            print(f"[camera] idx={source} --nocontrols (자동 노출 강제 ON)")
        else:
            # 실 카메라: config.cameras.side 설정 적용(DSHOW+노출).
            # --source 가 config 기본값이면 자동 탐지(상부 인덱스 제외)로 인덱스 변경에 대응.
            cam = config["cameras"]["side"]
            top_idx = config["cameras"]["top"]["index"]
            if int(source) == cam.get("index", -1):
                cap, used = open_camera_auto(cam, exclude=(top_idx,))
                if cap is None:
                    raise RuntimeError("측면 카메라 자동 탐지 실패 — 연결/점유 확인")
                if used != int(source):
                    print(f"[camera] 인덱스 자동 보정: config={source} → 실제={used}")
                source = str(used)
            else:
                cap = open_camera(cam, index=int(source))   # 사용자가 명시 지정 시 그대로
            print(f"[camera] side idx={source} {int(cap.get(3))}x{int(cap.get(4))}@"
                  f"{cap.get(cv2.CAP_PROP_FPS):.0f}fps exposure={cap.get(cv2.CAP_PROP_EXPOSURE):.1f} "
                  f"gain={cap.get(cv2.CAP_PROP_GAIN):.0f}")
    else:
        cap = cv2.VideoCapture(source)        # 영상 파일
    if not cap.isOpened():
        raise RuntimeError(f"소스 열기 실패: {source}")
    # DSHOW 초기화 직후 첫 몇 프레임은 ok=False 반환 → 워밍업으로 건너뜀
    for _ in range(30):
        cap.read()
    try:
        yielded = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                if yielded == 0:
                    raise RuntimeError(
                        f"카메라 인덱스 {source} 에서 프레임을 받지 못했습니다.\n"
                        f"  · 다른 인덱스 시도: python tools/live_pin.py --source 0\n"
                        f"  · 카메라가 다른 프로그램(state_machine 등)에 점유됐는지 확인\n"
                        f"  · config.cameras.side.index 값이 실제 카메라 번호와 맞는지 확인"
                    )
                break
            yielded += 1
            yield frame
    finally:
        cap.release()


def _color(verdict: str):
    return {"NORMAL": (0, 200, 0), "BENT": (0, 0, 255)}.get(verdict, (160, 160, 160))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=str(config["cameras"]["side"]["index"]),
                    help="카메라 인덱스 / 영상경로")
    ap.add_argument("--part", default=None,
                    help="기대 핀수 비교용 부품명 (IC/TerminalBlock/Heatsink/Capacitor)")
    ap.add_argument("--edges", action="store_true", help="시작 시 Canny 엣지맵 표시")
    ap.add_argument("--sil", action="store_true", help="시작 시 실루엣(이진) 표시")
    ap.add_argument("--nocontrols", action="store_true",
                    help="카메라 노출/게인 설정 미적용 (자동 노출) — 백라이트 없이 튜닝할 때")
    args = ap.parse_args()

    det = _PinDetector(config["vision"])      # production 과 동일 알고리즘 본체
    show = "edges" if args.edges else ("sil" if args.sil else "off")  # 오른쪽 패널 모드
    n, last = 0, time.time()
    print(f"[pin_inspector] canny=({det.canny_low},{det.canny_high}) blur={det.blur} "
          f"gap_tol={det.gap_tol:.2f} tip_y_tol={det.tip_y_tol}px expected={det.expected}")

    try:
        for frame in _frame_source(args.source, nocontrols=args.nocontrols):
            result, edges, sil, tips = det.inspect_debug(frame, args.part)
            color = _color(result.verdict)

            # 실루엣 bbox + 핀 끝점 + 끝점 y기준선
            if result.bbox:
                x, y, w, h = result.bbox
                cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
            for (px, py) in tips:
                cv2.line(frame, (px, py - 14), (px, py), (0, 255, 255), 1)   # 핀 세로선
                cv2.circle(frame, (px, py), 3, (0, 255, 255), -1)            # 핀 끝점
            if tips:
                ys = [p[1] for p in tips]
                cv2.line(frame, (0, min(ys)), (frame.shape[1], min(ys)), (255, 120, 0), 1)
                cv2.line(frame, (0, max(ys)), (frame.shape[1], max(ys)), (255, 120, 0), 1)

            exp = result.expected_count
            # toward_camera 모드는 tip_y_range_px 가 '리드 휨(lean)' 값 → 라벨/허용치를 맞춰 표시
            metal_mode = det.pin_direction.get(args.part or "", "down") == "toward_camera"
            dev_label = "lean" if metal_mode else "tip_dev"
            dev_tol = det.metal_lean_tol if metal_mode else det.tip_y_tol
            txt = [
                f"{result.verdict}",
                f"pins={result.pin_count}" + (f"/{exp}" if exp else ""),
                f"gap_cv={result.gap_cv:.2f} (tol {det.gap_tol:.2f})",
                f"{dev_label}={result.tip_y_range_px}px (tol {dev_tol})",
                f"canny=({det.canny_low},{det.canny_high}) min_dist={det.peak_min_dist} thr={det.peak_thresh:.2f}",
            ]
            for i, t in enumerate(txt):
                cv2.putText(frame, t, (10, 24 + i * 22),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

            n += 1
            now = time.time()
            fps = 1.0 / max(now - last, 1e-3)
            last = now
            print(f"[{n:5d}] {result.verdict:7s} pins={result.pin_count:2d} "
                  f"gap_cv={result.gap_cv:.2f} tip_dev={result.tip_y_range_px:3d}px ({fps:4.1f} fps)")

            cv2.imshow("VisiPick — Side Pin Inspector ([ ] ; ' canny, -= dist, e/s pane, q quit)", frame)

            def _safe_destroy(name):
                try:
                    cv2.destroyWindow(name)
                except cv2.error:
                    pass

            if show == "edges":
                cv2.imshow("Pin Inspector — Edges", edges)
                _safe_destroy("Pin Inspector — Silhouette")
            elif show == "sil":
                cv2.imshow("Pin Inspector — Silhouette", sil)
                _safe_destroy("Pin Inspector — Edges")
            else:
                _safe_destroy("Pin Inspector — Edges")
                _safe_destroy("Pin Inspector — Silhouette")

            k = cv2.waitKey(1) & 0xFF
            if k in (ord("q"), 27):
                break
            elif k == ord("["):
                det.canny_low = max(0, det.canny_low - 10)
            elif k == ord("]"):
                det.canny_low += 10
            elif k == ord(";"):
                det.canny_high = max(0, det.canny_high - 10)
            elif k == ord("'"):
                det.canny_high += 10
            elif k == ord("-"):
                det.peak_min_dist = max(1, det.peak_min_dist - 2)
            elif k == ord("="):
                det.peak_min_dist += 2
            elif k == ord(","):
                det.peak_thresh = max(0.05, det.peak_thresh - 0.05)
            elif k == ord("."):
                det.peak_thresh = min(0.95, det.peak_thresh + 0.05)
            elif k == ord("e"):
                show = "off" if show == "edges" else "edges"
            elif k == ord("s"):
                show = "off" if show == "sil" else "sil"
    except KeyboardInterrupt:
        pass
    finally:
        cv2.destroyAllWindows()

    print(f"\n총 {n} 프레임. 최종 canny=({det.canny_low},{det.canny_high}) — "
          f"이 값을 config.vision.pin_inspector.canny_low/high 에 기입하세요.")


if __name__ == "__main__":
    main()
