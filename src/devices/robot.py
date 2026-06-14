"""
src/devices/robot.py  —  myCobot 280 트레이 이재 제어 (드롭인 교체본)

state_machine.py 인터페이스 100% 보존:
    from src.devices.robot import Robot
    self._robot = Robot()
    self._robot.transfer_tray()   # 레시피 완성 시 호출
    self._robot.home()

동작 방식 (visipick-server RobotCtrl 로직 이식):
    dummy_mode=True  → MockMyCobot TCP(localhost:9002) — 기존 헤드리스 테스트 그대로
    dummy_mode=False → pymycobot MyCobot280Socket 으로 myCobot Pi 공식 소켓 서버 직결.
                       커스텀 RPi4 서버(9002) 불필요. Pi에서 공식 소켓 서버만 실행하면 됨.

config.json 의 robot 섹션에 아래 키가 있어야 함 (없으면 기본값 사용):
    "robot": {
      "host": "192.168.0.17",      # myCobot Pi IP — DHCP라 바뀜, RealVNC/hostname -I 로 실측 후 갱신
      "port": 9000,                # 공식 소켓 서버 포트 (커스텀 9002 아님!)
      "speed": 80,
      "dummy_mode": false,
      "gripper_open": 100, "gripper_close": 30,
      "pickup_angles": [..6..],    # ← 티칭으로 채울 것 (현재 0)
      "lift_angles":   [..6..],
      "place_angles":  [..6..],
      "home_angles":   [..6..],
      "joint_limits": { "j2_min_deg": -120, "j3_min_deg": -120 }
    }

Pi 쪽 준비(1회): myCobot 280 Pi 에서 공식 소켓 서버 실행 → MyCobot280Socket 이 접속.
티칭: tools/robot_teach.py (Pi 에서 실행) 로 경유점 교시 → path.json 저장 →
      scp 로 config/robot_path.json 배치. 경로 파일이 있으면 4자세는 무시된다.
"""
import socket, json, time
from datetime import datetime
from pathlib import Path
from src.utils.logger import setup_logger
from src.utils.config_loader import config

logger = setup_logger("robot")

_R = config["robot"]
DUMMY_MODE = _R["dummy_mode"]

# ── 실로봇 파라미터 (dummy 면 사용 안 함) ──────────────────────────────
HOST  = _R.get("host", "192.168.0.17")
PORT  = int(_R.get("port", 9000))
SPEED = int(_R.get("speed", 80))
GRIPPER_OPEN  = int(_R.get("gripper_open", 100))
GRIPPER_CLOSE = int(_R.get("gripper_close", 30))
PICKUP = list(_R.get("pickup_angles", [0, 0, 0, 0, 0, 0]))
LIFT   = list(_R.get("lift_angles",   [0, 0, 0, 0, 0, 0]))
PLACE  = list(_R.get("place_angles",  [0, 0, 0, 0, 0, 0]))
HOME   = list(_R.get("home_angles",   [0, 0, 0, 0, 0, 0]))
_JL    = _R.get("joint_limits", {})
J2_MIN = float(_JL.get("j2_min_deg", -120.0))
J3_MIN = float(_JL.get("j3_min_deg", -120.0))
ARRIVE_TOL_DEG  = 3.0     # 웨이포인트 도달 허용 오차
ARRIVE_WAIT_SEC = 8.0     # 웨이포인트당 최대 대기

# ── 촘촘한 경로 교시 파일 ─────────────────────────────────────────────
# 4자세(home/pickup/lift/place)만 쓰면 이동 중 트레이가 뒤집힌다.
# tools/robot_teach.py 로 다관절 경유점을 촘촘히(10~15점) 찍어 path.json 저장 →
# scp 로 config/robot_path.json 에 두면 robot.py 가 그대로 재생한다(부하·뒤집힘 최소화).
# 형식: {"speed":25, "waypoints":[{"angles":[6], "grip":null|"close"|"open"}, ...]}
_PROJECT_ROOT = Path(__file__).resolve().parents[2]   # C:\VisiPick — config_loader 와 동일 기준
PATH_FILE = _R.get("path_file", "config/robot_path.json")


def _path_file(slot=None) -> Path:
    """slot=None → config/robot_path.json. slot=1~3 → config/robot_path_{slot}.json
    (AGV 트레이 자리별 경로 — 집기·이동은 공유, 놓기점만 다름)."""
    p = Path(PATH_FILE)
    if slot is not None:
        p = p.with_name(f"{p.stem}_{slot}{p.suffix}")
    return p if p.is_absolute() else _PROJECT_ROOT / p


def _load_path(slot=None):
    """경로 교시 파일 로드 + 전체 검증. 유효하면 dict, 아니면 None(폴백).
    scp 도중 잘린 파일(JSONDecodeError)·waypoint 형식 오류면 파일 전체를 무시한다 —
    일부만 재생하면 트레이를 쥔 채 엉뚱한 곳에서 멈출 수 있기 때문."""
    fp = _path_file(slot)
    try:
        with open(fp, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"경로 파일 손상/읽기 실패({fp}): {e}")
        return None
    wps = data.get("waypoints") if isinstance(data, dict) else None
    if not isinstance(wps, list) or not wps:
        logger.error(f"경로 파일에 waypoints 없음({fp})")
        return None
    for i, wp in enumerate(wps):
        ang = wp.get("angles") if isinstance(wp, dict) else None
        if not (isinstance(ang, list) and len(ang) == 6
                and all(isinstance(v, (int, float)) for v in ang)):
            logger.error(f"경로 점 {i+1} angles 형식 오류 — 파일 전체 무시: {wp}")
            return None
    return data

# ── mock 파라미터 (dummy 경로) ────────────────────────────────────────
MOCK_HOST = config["mock"]["robot"]["host"]
MOCK_PORT = config["mock"]["robot"]["port"]


class Robot:
    def __init__(self):
        self._mc = None       # 지연 연결 (부팅 시 Pi 미기동이어도 서버 부팅 OK)

    # ── 공개 인터페이스 (FSM 호출) ───────────────────────────────────
    def transfer_tray(self, slot=None) -> bool:
        """완성 트레이를 AGV 적재 위치로 이재.
        slot=1~3 이면 그 자리 경로(robot_path_{slot}.json)로 — AGV 가 트레이 3개를
        서로 다른 자리에 싣는 경우. slot=None 이면 단일 경로(robot_path.json)."""
        if DUMMY_MODE:
            return self._mock_cmd("tray_transfer")
        if not self._ensure():
            return False
        return self._transfer_cycle(slot)

    def home(self) -> bool:
        if DUMMY_MODE:
            return self._mock_cmd("home")
        if not self._ensure():
            return False
        path = _load_path()                    # 경로 첫 점을 홈으로(파일 우선), 없으면 config HOME
        home_ang = path["waypoints"][0]["angles"] if path else HOME
        try:
            return self._send_angles(home_ang)
        except Exception as e:
            logger.error(f"홈 복귀 예외: {e}")
            self._mc = None
            return False

    # ── 실로봇 연결 (지연) ────────────────────────────────────────────
    def _ensure(self) -> bool:
        if self._mc is not None:
            return True
        try:
            try:
                from pymycobot import MyCobot280Socket as _Sock   # pymycobot 4.x 권장
            except Exception:
                from pymycobot.mycobot import MyCobotSocket as _Sock  # 구버전 폴백
            mc = _Sock(HOST, PORT)
            if hasattr(mc, "connect"):
                try:
                    mc.connect()
                except Exception:
                    pass
            try:
                # Nagle 비활성(TCP_NODELAY) — 스트리밍 미세 설정점(0.05s 간격 소형 패킷)을
                # TCP 가 모았다가 일괄 방출하면 '멈췄다가 훅' 증상이 난다. 즉시 전송 강제.
                mc.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except Exception:
                pass
            try:
                mc.set_fresh_mode(1)   # 새 명령이 진행 중 동작을 갈아탐 — 경로 블렌딩 전제
            except Exception:
                pass
            try:
                mc.power_on()          # 팔이 힘 빠진 상태(release)였어도 움직이게
                time.sleep(0.5)
            except Exception:
                pass
            self._mc = mc
            logger.info(f"myCobot 연결: {HOST}:{PORT}")
            return True
        except Exception as e:
            logger.error(f"myCobot 연결 실패: {e}")
            self._mc = None
            return False

    # ── 이재 시퀀스 ──────────────────────────────────────────────────
    def _transfer_cycle(self, slot=None) -> bool:
        """경로 파일이 있으면 촘촘한 경로 재생, 없으면 구버전 4자세 폴백.
        slot 경로가 없으면 단일 경로로 폴백(브링업 중 슬롯 미교시 대비)."""
        path = _load_path(slot) if slot is not None else None
        used = slot
        if path is None:
            if slot is not None:
                logger.warning(f"슬롯 {slot} 경로 파일({_path_file(slot)}) 없음/무효 — 단일 경로로 폴백")
            path = _load_path(None)
            used = None
        if path:
            logger.info(f"경로 재생 모드: {_path_file(used)} ({len(path['waypoints'])}점, 슬롯={slot})")
            return self._run_path(path)
        logger.warning("경로 파일 없음/무효 — 4자세 폴백 모드")
        return self._run_4pose()

    def _run_path(self, path) -> bool:
        """다관절 경로 재생: 각 경유점 send_angles+도착확인, grip 태그에서 그리퍼 동작.
        트레이 수평 유지를 위해 교시한 경유점을 그대로 따라간다(4자세 뒤집힘 회피).

        동작 방식 — 보간 스트리밍(슥슥 등속 이동):
          점 사이를 잘게 나눈 미세 설정점을 0.1s 주기로 연속 전송(set_fresh_mode(1) 전제).
          로봇이 항상 조금 앞의 설정점을 쫓아가므로 가속 튐 없이 미끄러지듯 움직인다.
          속도 2단: 빈 손(집기 전·놓은 후)은 speed_empty, 트레이 쥔 구간(close~open)은
          speed 로 — 둘 다 path.json 키(°/s). speed_empty 없으면 speed 와 동일.
        정밀 정지점(집기/놓기 + 그 바로 앞 접근점 + 마지막)에서만 tol 도달을 확인:
          · 집기/놓기 점 미도달, 그리퍼 실패: 중단 (잘못된 위치에서 집기 방지)
          · 접근점/마지막 점 미도달: 경고 후 계속 (트레이 쥔 채 공중 정지가 최악)"""
        carry = float(path.get("glide_deg_s", path.get("speed", 35)))
        empty = float(path.get("speed_empty", carry))
        tol   = float(path.get("arrive_tol_deg", 5.0))
        wait  = float(path.get("arrive_wait_sec", 12.0))
        wps   = path["waypoints"]
        try:
            if not self._grip(GRIPPER_OPEN):         # 시작: 그리퍼 열기
                return False
            cur0 = self._mc.get_angles()             # 보간 시작점(현재 자세)
            cur = cur0 if (isinstance(cur0, list) and len(cur0) == 6) else None
            holding = False                          # 트레이 쥐고 있는 구간만 신중 속도
            for i, wp in enumerate(wps):
                ang  = self._clip(wp["angles"])
                grip = (wp.get("grip") or "").lower()
                next_grip = (wps[i + 1].get("grip") or "").lower() if i + 1 < len(wps) else ""
                strict = grip in ("close", "open") \
                    or next_grip in ("close", "open") \
                    or i == len(wps) - 1
                spd = carry if holding else empty
                if cur is None:                      # 현재 각도 모름 → 구방식 1회(긴 대기)
                    arrived = self._send_angles(ang, wait=wait * 2)
                else:
                    self._stream_to(cur, ang, spd)
                    arrived = self._wait_arrive(ang, tol, wait) if strict else True
                cur = ang
                if not arrived:
                    if grip in ("close", "open"):
                        logger.error(f"집기/놓기 점 {i+1}/{len(wps)} 미도달 — 이재 중단")
                        return False
                    logger.warning(f"정지점 {i+1}/{len(wps)} 미도달 — 계속 진행")
                if grip == "close":
                    if not self._grip(GRIPPER_CLOSE):    # 집기 지점
                        return False
                    holding = True
                elif grip == "open":
                    if not self._grip(GRIPPER_OPEN):     # 놓기 지점
                        return False
                    holding = False
            logger.info(f"트레이 이재 완료 (경로 {len(wps)}점, 들고 {carry}°/s · 빈손 {empty}°/s)")
            return True
        except Exception as e:
            logger.error(f"트레이 이재 예외(경로): {e}")
            self._mc = None
            return False

    def _stream_to(self, start, target, deg_s, dt=0.05):
        """관절 보간 스트리밍 — start→target 미세 설정점을 dt 주기로 연속 전송(등속).
        추종 속도(cmd)는 설정점 진행 속도에 여유만 두고 맞춘다 — 100(최대)으로 하면
        각 스텝을 먼저 끝내고 쉬는 미세 가다서다가 고주파 떨림을 만든다."""
        cmd = min(100, max(10, int(deg_s * 1.5)))
        d = max(abs(a - b) for a, b in zip(start, target))
        n = max(1, int(d / (max(deg_s, 1.0) * dt)) + 1)
        # 스텝별 페이싱: 전송에 걸린 시간만 dt 에서 차감. 누적 시계(t_next += dt) 방식은
        # 전송이 dt 보다 느리면 밀린 설정점을 한꺼번에 쏟아부어 로봇이 중간점을 건너뛰고
        # 최대 추종속도로 돌진(멈췄다가 확 내려가는 증상) — 절대 빚을 다음 스텝에 안 넘긴다.
        for k in range(1, n + 1):
            t0 = time.time()
            pt = [round(a + (b - a) * k / n, 2) for a, b in zip(start, target)]
            self._mc.send_angles(pt, cmd)
            remain = dt - (time.time() - t0)
            if remain > 0:
                time.sleep(remain)

    def _wait_arrive(self, target, tol, timeout) -> bool:
        """정밀 정지점에서 도달 확인(명령 재전송 없이 폴링만)."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            cur = self._mc.get_angles()
            if isinstance(cur, list) and len(cur) == 6 \
               and all(abs(c - t) < tol for c, t in zip(cur, target)):
                return True
            time.sleep(0.1)
        logger.warning(f"도달 타임아웃: target={target}")
        return False

    def _run_4pose(self) -> bool:
        """구버전 호환: home→pickup→그립닫기→lift→place→그립열기→home (트레이 뒤집힘 주의)."""
        if all(v == 0 for pose in (HOME, PICKUP, LIFT, PLACE) for v in pose):
            logger.error("경로 파일 없음 + 4자세 미티칭(전부 0) — 이재 거부. "
                         "tools/robot_teach.py 교시 후 config/robot_path.json 배치 필요")
            return False
        try:
            ok = (self._send_angles(HOME)
                  and self._send_angles(PICKUP)
                  and self._grip(GRIPPER_CLOSE)
                  and self._send_angles(LIFT)
                  and self._send_angles(PLACE)
                  and self._grip(GRIPPER_OPEN)
                  and self._send_angles(HOME))
            logger.info("트레이 이재 완료" if ok else "트레이 이재 실패(웨이포인트 미도달)")
            return ok
        except Exception as e:
            logger.error(f"트레이 이재 예외: {e}")
            self._mc = None      # 다음 호출 시 재연결
            return False

    def _send_angles(self, angles, wait: float = ARRIVE_WAIT_SEC, speed: int = SPEED,
                     tol: float = ARRIVE_TOL_DEG) -> bool:
        """관절각 전송 후 도달까지 폴링. send_coords 는 홈 특이점에서 실패하므로 사용 안 함."""
        a = self._clip(angles)
        self._mc.send_angles(a, speed)
        deadline = time.time() + wait
        while time.time() < deadline:
            cur = self._mc.get_angles()           # int 반환 가능 → isinstance 가드
            if isinstance(cur, list) and len(cur) == 6 \
               and all(abs(c - t) < tol for c, t in zip(cur, a)):
                return True
            time.sleep(0.1)
        logger.warning(f"도달 타임아웃: target={a}")
        return False

    def _grip(self, value: int) -> bool:
        try:
            self._mc.set_gripper_value(int(value), 80)   # 교시 도구 replay 와 동일(속도 80, 1.5s 대기)
            time.sleep(1.5)
            return True
        except Exception as e:
            logger.error(f"그리퍼 오류: {e}")
            return False

    @staticmethod
    def _clip(angles):
        a = list(angles)
        if len(a) >= 3:
            a[1] = max(a[1], J2_MIN)   # j2 하한
            a[2] = max(a[2], J3_MIN)   # j3 하한
        return a

    # ── mock (dummy_mode) — 기존 MockMyCobot 그대로 사용 ──────────────
    def _mock_cmd(self, action: str) -> bool:
        msg = {"type": "robot_cmd", "action": action,
               "speed": SPEED, "timestamp": datetime.now().isoformat()}
        try:
            with socket.socket() as s:
                s.settimeout(10)
                s.connect((MOCK_HOST, MOCK_PORT))
                s.sendall((json.dumps(msg, ensure_ascii=False) + "\n").encode())
                resp = json.loads(s.recv(4096).decode().strip())
            return resp.get("status") == "ok"
        except Exception as e:
            logger.error(f"Mock robot 오류: {e}")
            return False
