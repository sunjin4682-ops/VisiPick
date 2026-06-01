"""사용 가능한 카메라 인덱스 스캔 — 어느 번호가 ELP인지 찾는 용도.

실행:
    cd C:\\VisiPick
    python tools/list_cameras.py            # 0~9 인덱스 스캔, 열리는 것 표시
    python tools/list_cameras.py --show 1   # 1번 카메라 미리보기 창 (q/ESC 종료)

각 인덱스의 해상도를 보고 ELP(1920x1200/1080) 를 골라
config.cameras.top.index 에 그 번호를 넣으면 된다. (내장캠은 보통 640x480/1280x720)
"""
from __future__ import annotations
import argparse
import sys

import cv2

_BACKEND = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY


def scan(max_index: int = 10) -> None:
    print("인덱스 스캔 중... (각 카메라에 MJPG 1920x1200 요청 후 실제 반영값 확인)\n")
    found = []
    for i in range(max_index):
        cap = cv2.VideoCapture(i, _BACKEND)
        if not cap.isOpened():
            cap.release()
            continue
        dflt_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))   # 열자마자 기본 해상도
        dflt_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        # ELP 판별: MJPG + 1920x1200 를 요청해 실제로 받아들이는지
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1200)
        ok, _ = cap.read()
        max_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        max_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()
        is_elp = max_w >= 1600                             # 내장캠은 보통 1280 이하
        tag = "★ ELP 후보 (고해상도)" if is_elp else "내장캠 추정(저해상도)"
        status = "" if ok else " [프레임 실패]"
        print(f"  [index {i}] 기본 {dflt_w}x{dflt_h} → 1920요청시 {max_w}x{max_h}  {tag}{status}")
        found.append((i, is_elp))
    print()
    if not found:
        print("열리는 카메라 없음 — USB 연결/권한 확인. 다른 앱이 카메라를 쓰고 있으면 닫으세요.")
        return
    elp = [i for i, e in found if e]
    if elp:
        print(f"→ ELP 후보 인덱스: {elp}  → config.cameras.top.index 에 입력")
    else:
        print("⚠ 1920 을 받는 카메라가 없음 = ELP 미인식 가능성.")
        print("  확인법: ELP USB 뽑고 다시 스캔 → 인덱스가 줄면 남은 건 내장캠.")
        print("          ELP 꽂고 다시 스캔 → 새로 생긴 번호가 ELP.")
    print("  화면으로 확인: python tools/list_cameras.py --show <번호>")


def show(index: int) -> None:
    cap = cv2.VideoCapture(index, _BACKEND)
    if not cap.isOpened():
        print(f"[index {index}] 열기 실패")
        return
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"[index {index}] {w}x{h} 미리보기 — q 또는 ESC 로 종료")
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                print("프레임 읽기 실패")
                break
            cv2.putText(frame, f"index {index}  {w}x{h}", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
            cv2.imshow(f"camera index {index}", frame)
            if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", type=int, default=None, help="해당 인덱스 미리보기 창")
    ap.add_argument("--max", type=int, default=10, help="스캔할 최대 인덱스(기본 10)")
    args = ap.parse_args()
    if args.show is not None:
        show(args.show)
    else:
        scan(args.max)


if __name__ == "__main__":
    main()
