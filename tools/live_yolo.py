"""
컨베이어 라이브 YOLO 뷰어 — 전체 시스템 없이 상부 카메라에서 검출만 확인.

production 과 동일한 경로(src.vision.Classifier.classify_top)를 그대로 사용하므로,
여기서 보이는 부품/신뢰도/판정힌트가 곧 state_machine 이 판단하는 값이다.

실행 (김선진 리그 PC — 컨베이어 상부 카메라):
    cd C:\\VisiPick
    python tools/live_yolo.py                 # config.cameras.top.index 카메라 라이브
    python tools/live_yolo.py --source 0       # 카메라 인덱스 직접 지정
    python tools/live_yolo.py --source belt.mp4   # 녹화 영상으로 테스트
    python tools/live_yolo.py --source frames  # 동봉 컨베이어 샘플(장비 없이 데모)
    python tools/live_yolo.py --no-display     # 창 없이 콘솔+주석프레임 저장(헤드리스)
    python tools/live_yolo.py --camera-settings # 시작 시 속성창 1회(PowerLine 60Hz 등 안티플리커)

노출/게인/화벨은 config.cameras.top.controls 에서 조정 (형광등 기본 exposure -6, LED 추가 후 -9~-10).
q 또는 ESC 로 종료.
"""
from __future__ import annotations
import argparse
import glob
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from src.utils.config_loader import config  # noqa: E402
from src.utils.part_map import to_korean  # noqa: E402
from src.vision.camera_util import center_square, open_top_camera  # noqa: E402
from src.vision.classifier import Classifier  # noqa: E402


def _frame_source(source: str, open_settings: bool = False):
    """프레임 제너레이터. (frame, tag) 를 yield."""
    if source == "frames":
        files = sorted(glob.glob(str(ROOT / "sample_frames" / "conveyor" / "*.jpg")))
        if not files:
            files = sorted(glob.glob(str(ROOT / "sample_frames" / "diag" / "*.jpg")))
        print(f"[source] 동봉 샘플 {len(files)}장 루프 (컨베이어 모사)")
        while True:                          # 움직이는 벨트처럼 반복 재생
            for f in files:
                img = cv2.imread(f)
                if img is not None:
                    yield img, Path(f).name
                    time.sleep(0.08)         # ~12fps 재생감
    else:
        if source.isdigit():                 # 실 카메라: config 설정 적용(DSHOW+노출/화벨) — production 과 동일 경로
            cam = config["cameras"]["top"]
            cap = open_top_camera(cam, index=int(source))
            print(f"[camera] {cam.get('fourcc', 'MJPG')} {int(cap.get(3))}x{int(cap.get(4))}@"
                  f"{cap.get(cv2.CAP_PROP_FPS):.0f}fps exposure={cap.get(cv2.CAP_PROP_EXPOSURE):.1f} "
                  f"gain={cap.get(cv2.CAP_PROP_GAIN):.0f} auto_exp={cap.get(cv2.CAP_PROP_AUTO_EXPOSURE):.2f}")
            if open_settings:                # 1회: DirectShow 속성창(PowerLine Frequency=60Hz 등)
                print("[camera] 속성창 열림 — PowerLine Frequency 를 60Hz 로 설정 후 닫으세요")
                cap.set(cv2.CAP_PROP_SETTINGS, 1)
        else:
            cap = cv2.VideoCapture(source)   # 영상 파일
        if not cap.isOpened():
            raise RuntimeError(f"소스 열기 실패: {source}")
        print(f"[source] {source} ({int(cap.get(3))}x{int(cap.get(4))})")
        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                yield frame, None
        finally:
            cap.release()


# 한글 폰트 후보 (cv2.putText 는 한글을 못 그려 ??? 로 나옴 → PIL 로 직접 렌더)
_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\malgun.ttf",                          # 맑은 고딕 (Windows 기본 한글)
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",       # Linux NanumGothic
]
_FONT_CACHE: dict[int, ImageFont.FreeTypeFont] = {}


def _font(size: int):
    f = _FONT_CACHE.get(size)
    if f is None:
        for path in _FONT_CANDIDATES:
            try:
                f = ImageFont.truetype(path, size)
                break
            except OSError:
                continue
        if f is None:                        # 한글 폰트 없으면 기본폰트(한글은 □)로 폴백
            f = ImageFont.load_default()
        _FONT_CACHE[size] = f
    return f


def _draw_labels(frame, items):
    """items: [(text, (x, y), (b, g, r), size), ...] 를 한 번의 PIL 변환으로 그린다.
    color 는 cv2 관례(BGR) 그대로 받아 PIL(RGB) 로 변환해 그린다. frame 을 제자리 수정."""
    if not items:
        return frame
    img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(img)
    for text, (x, y), (b, g, r), size in items:
        draw.text((x, y), text, font=_font(size), fill=(r, g, b))
    frame[:] = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)
    return frame


def _annotate(frame, r):
    """ClassifyResult 를 프레임에 오버레이 (라벨은 한글 PIL 렌더)."""
    part_ko = to_korean(r.part)
    if r.verdict_hint == "REJECT":
        color, label = (0, 0, 255), f"REJECT {r.raw_class} {r.confidence:.2f}"
    elif r.part is not None:
        color, label = (0, 200, 0), f"{part_ko or r.part} {r.confidence:.2f} PASS"
    else:
        color, label = (160, 160, 160), "no detection"
    texts = []
    if r.bbox:
        x, y, w, h = r.bbox
        cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)   # 박스는 ASCII-free, cv2 로
        texts.append((label, (x, max(0, y - 26)), color, 22))    # 박스 위 라벨
    texts.append((label, (10, 8), color, 26))                    # 좌상단 상태 라벨
    _draw_labels(frame, texts)
    return label


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=str(config["cameras"]["top"]["index"]),
                    help="카메라 인덱스 / 영상경로 / 'frames'")
    ap.add_argument("--no-display", action="store_true", help="창 없이 콘솔+저장")
    ap.add_argument("--save", default="", help="주석 영상 저장 경로(.mp4)")
    ap.add_argument("--camera-settings", action="store_true",
                    help="시작 시 DirectShow 속성창 1회 열기 (PowerLine Frequency=60Hz 등 안티플리커 설정)")
    ap.add_argument("--debug", action="store_true",
                    help="모델이 뱉는 '모든' 박스를 콘솔 출력+화면 표시 (불량 클래스 가려짐 확인용)")
    ap.add_argument("--square", action="store_true",
                    help="프레임 중앙을 정사각형 크롭 후 추론 (학습셋 512x512 기하에 맞춤)")
    ap.add_argument("--publish", metavar="NAME", default="",
                    help="주석 프레임을 frame_bus 에 연속 발행 (NAME=top/side). api_server MJPEG 송출용")
    args = ap.parse_args()

    clf = Classifier()  # config.vision (dummy_mode=false → YOLO best.pt 로드)
    print(f"[classifier] mode = {clf.mode}")
    if clf.mode != "yolo":
        print("  ⚠ YOLO 모드가 아님 — config.vision.dummy_mode=false / mode='yolo' 확인")

    headless = args.no_display
    writer = None
    out_dir = ROOT / "tools" / "live_out"
    n, t0, last = 0, time.time(), time.time()
    saved = 0
    try:
        square = args.square or bool(config["cameras"]["top"].get("square_crop", False))
        for frame, tag in _frame_source(args.source, open_settings=args.camera_settings):
            if square:                       # 학습셋(정사각)과 기하 맞춤
                frame = center_square(frame)
            r = clf.classify(frame)          # 추론 1회 (production 과 동일)
            top = {"part": r.part, "verdict_hint": r.verdict_hint,
                   "confidence": r.confidence, "raw_class": r.raw_class}
            label = _annotate(frame, r)
            if args.debug:                   # 모델의 '모든' 박스 표시 (불량 가려짐 확인)
                dets = clf.raw_detections(frame)
                if dets:
                    print("   raw:", ", ".join(f"{d['name']}={d['conf']:.2f}" for d in dets))
                for d in dets:
                    x, y, w, h = d["bbox"]   # 클래스명은 ASCII라 cv2 로 충분
                    cv2.rectangle(frame, (x, y), (x + w, y + h), (255, 200, 0), 1)
                    cv2.putText(frame, f"{d['name']} {d['conf']:.2f}", (x, y + h + 16),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 200, 0), 1)
            n += 1
            now = time.time()
            fps = 1.0 / max(now - last, 1e-3)
            last = now
            line = f"[{n:5d}] {tag or '':24s} part={str(top['part']):14s} " \
                   f"hint={top['verdict_hint']:7s} conf={top['confidence']:.2f}  ({fps:4.1f} fps)"
            print(line)

            if args.publish:                 # frame_bus 연속 발행 → api_server MJPEG
                from src.core import frame_bus
                frame_bus.publish(args.publish, frame)

            if args.save:
                if writer is None:
                    h, w = frame.shape[:2]
                    writer = cv2.VideoWriter(args.save, cv2.VideoWriter_fourcc(*"mp4v"), 15, (w, h))
                writer.write(frame)
            if headless:
                out_dir.mkdir(parents=True, exist_ok=True)
                if n <= 30:                  # 헤드리스: 앞 30프레임만 주석 저장
                    cv2.imwrite(str(out_dir / f"frame_{n:04d}.jpg"), frame)
                    saved += 1
            else:
                cv2.imshow("VisiPick — Conveyor YOLO (q/ESC 종료)", frame)
                if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                    break
    except KeyboardInterrupt:
        pass
    finally:
        if writer:
            writer.release()
        if not headless:
            cv2.destroyAllWindows()
    dt = time.time() - t0
    print(f"\n총 {n} 프레임, 평균 {n/max(dt,1e-3):.1f} fps"
          + (f", 주석 {saved}장 저장 → {out_dir}" if headless else "")
          + (f", 영상 → {args.save}" if args.save else ""))


if __name__ == "__main__":
    main()
