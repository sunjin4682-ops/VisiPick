#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VisiPick — myCobot 280 Pi 경로 교시(Path Teaching) 도구
==========================================================================
트레이를 수평으로 유지하며 옮기려면 4자세(home/pickup/lift/place)로는 부족하다
(이동 중 관절 급변 → 트레이 뒤집힘). 이 도구는 다관절 경유점을 촘촘히(10~15점)
찍어 하나의 경로로 저장하고, 집는 지점/놓는 지점만 표시한다.

저장 결과(path.json)를 PC 의 config/robot_path.json 으로 복사하면
robot.py 가 그대로 재생한다. → config 값을 하나하나 넣을 필요 없음(파일 1개 scp).

⚠️ 실행 위치: 반드시 **Pi 위에서** (SSH: er@192.168.0.46 / 비번 Elephant).
⚠️ 포트 충돌: 공식 소켓 서버(9000)·다른 pymycobot 프로세스 끄고 실행(/dev/ttyAMA0 단일 점유).

복사·실행:
    scp tools/robot_teach.py er@192.168.0.46:~/visipick/
    ssh er@192.168.0.46
    cd ~/visipick && python3 robot_teach.py            # heredoc(<<) 금지, 파일로 실행

AGV 트레이 3칸 — 칸마다 따로 교시(놓는 위치만 다름):
    python3 robot_teach.py --slot 1                    # → path1.json
    python3 robot_teach.py --slot 2                    # → path2.json
    python3 robot_teach.py --slot 3                    # → path3.json

교시 후 PC 에서 (슬롯별):
    scp er@192.168.0.46:~/visipick/path1.json config/robot_path_1.json
    scp er@192.168.0.46:~/visipick/path2.json config/robot_path_2.json
    scp er@192.168.0.46:~/visipick/path3.json config/robot_path_3.json
    # (단일 운용이면) scp .../path.json config/robot_path.json

────────────────────────────────────────────────────────────────────────
시드(2026-05-16) 검증 규칙 준수: MyCobot280 임포트 / J3·J5 비대칭 범위 /
get_angles int 가드 / release 후 power_on 필수 / send_angles+wait_arrive /
그리퍼 0~100 방향 테스트 / startswith 파싱 / heredoc EOF 안내.
==========================================================================
"""
import json
import sys
import time

try:
    from pymycobot import MyCobot280, PI_PORT, PI_BAUD
except Exception as e:                       # noqa: BLE001
    print(f"[!] pymycobot 임포트 실패: {e}")
    print("    Pi 위에서 실행하세요.  pip install pymycobot")
    sys.exit(1)

# ── 관절 소프트 제한 (시드 2.2 실측 — 비대칭 주의) ──────────────────────
JOINT_LIMITS = [
    (-165, 165),   # J1
    (-165, 165),   # J2
    (-150, 150),   # J3  ← ±165 아님
    (-165, 165),   # J4
    (-155, 160),   # J5  ← 비대칭
    (-175, 175),   # J6
]
RUNTIME_J2_MIN = -120.0    # config.robot.joint_limits — 이보다 낮으면 런타임에서 잘림
RUNTIME_J3_MIN = -120.0

TEACH_SPEED   = 25         # 경로 재생 속도(느리게)
GRIP_SPEED    = 80
GRIPPER_OPEN  = 100        # robot.py 기본값과 일치(테스트용)
GRIPPER_CLOSE = 15

OUT_PATH  = "path.json"                  # 저장 파일 (--slot 지정 시 path{N}.json)
DEST_PATH = "config/robot_path.json"     # scp 목적지 (--slot 지정 시 robot_path_{N}.json)


def clamp_angles(a):
    return [max(lo, min(hi, v)) for v, (lo, hi) in zip(a, JOINT_LIMITS)]


def read_angles(mc, retries=12):
    """get_angles() — int 반환 가능 → isinstance 가드 + 재시도."""
    for _ in range(retries):
        cur = mc.get_angles()
        if isinstance(cur, list) and len(cur) == 6:
            return [round(float(v), 2) for v in cur]
        time.sleep(0.2)
    return None


def wait_arrive(mc, target, tol=5.0, timeout=12.0):
    """도착까지 폴링(짧은 sleep 통과 금지)."""
    start = time.time()
    while time.time() - start < timeout:
        cur = mc.get_angles()
        if isinstance(cur, list) and len(cur) == 6 \
           and all(abs(cur[j] - target[j]) < tol for j in range(6)):
            return True
        time.sleep(0.3)
    return False


def lock_and_read(mc):
    """release 후 손으로 옮긴 자세를 잠그고(power_on) 실제 각도를 읽는다.
    시드 4 — power_on() 후 get_angles() 해야 실제 위치가 나온다."""
    mc.power_on()
    time.sleep(0.6)
    ang = read_angles(mc)
    if ang is None:
        print("    [!] 각도 읽기 실패 — 다시 시도")
        return None
    clamped = clamp_angles(ang)
    if clamped != ang:
        print(f"    (범위 제한: {ang} → {clamped})")
    if clamped[1] < RUNTIME_J2_MIN or clamped[2] < RUNTIME_J3_MIN:
        print(f"    ⚠ J2={clamped[1]} J3={clamped[2]} — 런타임 하한(-120) 미만, "
              "config.robot.joint_limits 조정 검토")
    return clamped


def gripper_test(mc, which):
    """그리퍼 방향 확인(캘리브레이션마다 바뀜)."""
    try:
        if which == "cal":
            mc.set_gripper_calibration()
            time.sleep(1.0)
            print("    그리퍼 캘리브레이션 완료")
            return
        val = GRIPPER_OPEN if which == "open" else GRIPPER_CLOSE
        mc.set_gripper_value(val, GRIP_SPEED)
        time.sleep(2.0)
        print(f"    set_gripper_value({val}) → 현재값 {mc.get_gripper_value()} "
              "(열림/닫힘 눈으로 확인)")
    except Exception as e:                     # noqa: BLE001
        print(f"    [!] 그리퍼 오류: {e}")


def save_path(waypoints):
    if not waypoints:
        print("    [!] 저장할 경유점 없음")
        return
    data = {"speed": TEACH_SPEED, "waypoints": waypoints}
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    n_close = sum(1 for w in waypoints if w.get("grip") == "close")
    n_open  = sum(1 for w in waypoints if w.get("grip") == "open")
    print(f"\n[저장] {OUT_PATH} — 경유점 {len(waypoints)}점 "
          f"(집기 {n_close}, 놓기 {n_open})")
    print(f"    PC 에서:  scp er@192.168.0.46:~/visipick/{OUT_PATH} {DEST_PATH}")
    if n_close == 0 or n_open == 0:
        print("    ⚠ 집기(pc) 또는 놓기(po) 지점이 없습니다 — 트레이를 못 집거나 못 놓습니다")


HELP = """
────────────────── 명령 ──────────────────
  f          : 힘빼기(release_all_servos) — ⚠ 팔을 손으로 잡고 있을 것!
  p          : 현재 위치를 경유점으로 추가(이동만)
  pc         : 현재 위치 경유점 추가 + 여기서 '집기'(그리퍼 닫기) 표시  ← pickup
  po         : 현재 위치 경유점 추가 + 여기서 '놓기'(그리퍼 열기) 표시  ← place
  del        : 마지막 경유점 삭제
  replay     : 전체 경로 재생(그리퍼 포함) — 트레이 수평·뒤집힘 검증
  grip open / grip close / grip cal : 그리퍼 방향·캘리브레이션 테스트
  list       : 경유점 목록(집기/놓기 표시 포함)
  w          : path.json 저장 + scp 안내
  h          : 도움말
  q          : 저장 후 종료
───────────────────────────────────────────
권장 흐름: 첫 점(home) → ... 집는 곳에서 pc → 들어올림 → 옮김(촘촘히 p) →
           놓는 곳에서 po → 복귀 점들 → 마지막 home → w
* 트레이 수평 유지: 옮기는 구간을 2~3cm 간격으로 p 를 촘촘히(총 10~15점)
"""


def main():
    import argparse
    ap = argparse.ArgumentParser(description="myCobot 280 경로 교시 (AGV 트레이 칸별)")
    ap.add_argument("--slot", type=int, default=0,
                    help="AGV 적재 칸 번호(1~3). 지정 시 path{N}.json → config/robot_path_{N}.json")
    args = ap.parse_args()
    if args.slot:
        global OUT_PATH, DEST_PATH
        OUT_PATH  = f"path{args.slot}.json"
        DEST_PATH = f"config/robot_path_{args.slot}.json"
        print(f"[슬롯 {args.slot}] 저장 파일: {OUT_PATH} → {DEST_PATH}")

    print("myCobot 280 연결 중 (PI_PORT, PI_BAUD)...")
    mc = MyCobot280(PI_PORT, PI_BAUD)
    time.sleep(1.0)

    a = read_angles(mc)
    if a is None:
        print("[!] 연결 실패 — 소켓 서버(9000)나 다른 프로세스의 /dev/ttyAMA0 점유 확인")
        return
    print(f"연결 OK. 현재 각도: {a}")
    print(HELP)

    wps = []   # [{"angles":[6], "grip": None|"close"|"open"}, ...]

    def add_point(grip):
        ang = lock_and_read(mc)
        if ang is None:
            return
        wps.append({"angles": ang, "grip": grip})
        tag = {"close": " [집기]", "open": " [놓기]"}.get(grip, "")
        print(f"    경유점 {len(wps)}{tag}: {ang}")

    try:
        while True:
            try:
                cmd = input("teach> ").strip()
            except EOFError:
                print("\n[!] stdin EOF — 파일로 직접 실행: python3 robot_teach.py")
                break
            if not cmd:
                continue

            if cmd.startswith("q"):
                break
            elif cmd.startswith("h"):
                print(HELP)
            elif cmd.startswith("f"):
                mc.release_all_servos()
                print("    힘빠짐 — 손으로 잡고 다음 자세로 옮긴 뒤 p / pc / po 입력")
            elif cmd.startswith("pc"):
                add_point("close")
            elif cmd.startswith("po"):
                add_point("open")
            elif cmd.startswith("p"):
                add_point(None)
            elif cmd.startswith("del"):
                if wps:
                    removed = wps.pop()
                    print(f"    삭제: {removed['angles']} (남은 {len(wps)}점)")
                else:
                    print("    [!] 경유점 없음")
            elif cmd.startswith("replay"):
                if not wps:
                    print("    [!] 경유점 없음")
                    continue
                print(f"    경로 {len(wps)}점 재생 — 트레이 수평 유지되는지 확인")
                mc.set_gripper_value(GRIPPER_OPEN, GRIP_SPEED)   # 시작 열기
                time.sleep(1.5)
                for i, wp in enumerate(wps):
                    tgt = clamp_angles(wp["angles"])
                    mc.send_angles(tgt, TEACH_SPEED)
                    ok = wait_arrive(mc, tgt)
                    grip = wp.get("grip")
                    if grip == "close":
                        mc.set_gripper_value(GRIPPER_CLOSE, GRIP_SPEED); time.sleep(1.5)
                    elif grip == "open":
                        mc.set_gripper_value(GRIPPER_OPEN, GRIP_SPEED); time.sleep(1.5)
                    tag = {"close": " [집기]", "open": " [놓기]"}.get(grip, "")
                    print(f"    [{i+1}/{len(wps)}] {'도착' if ok else '타임아웃'}{tag}")
            elif cmd.startswith("grip open"):
                gripper_test(mc, "open")
            elif cmd.startswith("grip close"):
                gripper_test(mc, "close")
            elif cmd.startswith("grip cal"):
                gripper_test(mc, "cal")
            elif cmd.startswith("list"):
                if not wps:
                    print("    경유점 없음")
                for i, wp in enumerate(wps):
                    tag = {"close": " [집기]", "open": " [놓기]"}.get(wp.get("grip"), "")
                    print(f"    {i+1:2d}{tag}: {wp['angles']}")
            elif cmd.startswith("w"):
                save_path(wps)
            else:
                print("    [?] 알 수 없는 명령 — 'h' 로 도움말")
    finally:
        if wps:
            save_path(wps)
        print("\n종료. 팔은 현재 자세에서 잠긴 상태입니다.")


if __name__ == "__main__":
    main()
