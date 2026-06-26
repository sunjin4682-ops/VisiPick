"""
myCobot 트레이 이재 경로 테스트 — 전체 시스템(state_machine) 없이 robot.py 단독 검증.

robot_teach.py 로 교시해 둔 config/robot_path_{1,2,3}.json 을 production 코드(robot.py)가
그대로 재생하는지 확인한다. robot.py 의 transfer_tray(slot)/home() 을 호출하므로
여기서 되면 state_machine 에서도 동일하게 동작한다.

연결 모드 (config.robot.dummy_mode 로 결정):
    true  → MockMyCobot(9002)            — 장비 없이 흐름만 (경로 재생 X, mock 응답만)
    false → Pi 공식 소켓 서버(host:9000) — 실로봇
            ⚠️ Pi 에서 공식 소켓 서버 실행 + robot_teach.py 종료(/dev/ttyAMA0·포트 충돌)

실행:
    cd C:\\VisiPick
    python tools/test_robot.py                # 대화형
    python tools/test_robot.py --slot 1        # 슬롯1 경로 1회 재생 후 종료
    python tools/test_robot.py --cmd home      # home() 후 종료
    python tools/test_robot.py --all           # 슬롯 1→2→3 순차 재생 후 종료

대화형 명령:
    1 / 2 / 3   슬롯 경로 재생 (transfer_tray)
    h           home() — 홈/경로 첫 점 복귀
    p           슬롯별 경로 파일 상태 출력
    q           종료
"""
from __future__ import annotations
import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.utils.config_loader import config                                   # noqa: E402
from src.devices.robot import (                                              # noqa: E402
    Robot, _load_path, PATH_FILE_PATTERN, PATH_FILE, DUMMY_MODE,
)


def show_paths():
    """슬롯별 경로 파일이 있는지 + 경유점/집기·놓기 개수 출력."""
    print("\n[경로 파일 상태]")
    for slot in (1, 2, 3):
        data = _load_path(slot)
        fp = PATH_FILE_PATTERN.format(slot=slot)
        if data:
            wps = data.get("waypoints", [])
            n_close = sum(1 for w in wps if w.get("grip") == "close")
            n_open = sum(1 for w in wps if w.get("grip") == "open")
            warn = "" if (n_close and n_open) else "  ⚠ 집기/놓기 지점 누락"
            print(f"  슬롯{slot}: {len(wps):2d}점 (집기 {n_close}, 놓기 {n_open}){warn}")
        else:
            print(f"  슬롯{slot}: 경로 없음 → 4자세 폴백 사용 "
                  f"({fp} / {PATH_FILE} 둘 다 없음)")
    print()


def run_slot(robot, slot):
    print(f"\n→ 슬롯 {slot} 재생: transfer_tray({slot}) ...")
    t0 = time.time()
    ok = robot.transfer_tray(slot)
    print(f"← {'성공' if ok else '실패'}  ({time.time() - t0:.1f}s)\n")
    return ok


def main():
    ap = argparse.ArgumentParser(description="myCobot 트레이 이재 경로 테스트")
    ap.add_argument("--slot", type=int, default=0, help="해당 슬롯(1~3) 경로 1회 재생 후 종료")
    ap.add_argument("--cmd", default="", help="home : 홈 복귀 후 종료")
    ap.add_argument("--all", action="store_true", help="슬롯 1→2→3 순차 재생 후 종료")
    args = ap.parse_args()

    if DUMMY_MODE:
        mode = "더미(MockMyCobot 9002) — 경로 재생 안 함, mock 응답만"
    else:
        mode = f"실로봇 소켓서버({config['robot'].get('host')}:{config['robot'].get('port')})"
    print(f"[robot] 연결 모드: {mode}")
    if not DUMMY_MODE:
        print("  ⚠️ Pi 공식 소켓 서버(9000) 실행 + robot_teach.py 종료 필요(포트 충돌)")

    robot = Robot()
    show_paths()

    # ── 단발 모드 ──
    if args.slot:
        run_slot(robot, args.slot)
        return
    if args.cmd == "home":
        print("→ home() ...")
        print("←", "성공" if robot.home() else "실패")
        return
    if args.all:
        for s in (1, 2, 3):
            if not run_slot(robot, s):
                print("실패 — 중단")
                break
            time.sleep(1.0)
        return

    # ── 대화형 ──
    print("명령:  1/2/3=슬롯 경로 재생   h=home   p=경로파일 상태   q=종료")
    while True:
        try:
            cmd = input("robot> ").strip().lower()
        except EOFError:
            break
        if not cmd:
            continue
        if cmd.startswith("q"):
            break
        elif cmd in ("1", "2", "3"):
            run_slot(robot, int(cmd))
        elif cmd.startswith("h"):
            print("→ home() ...")
            print("←", "성공" if robot.home() else "실패")
        elif cmd.startswith("p"):
            show_paths()
        else:
            print("  [?] 1 / 2 / 3 / h / p / q")

    print("종료")


if __name__ == "__main__":
    main()
