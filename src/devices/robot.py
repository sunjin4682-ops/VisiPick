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
      "host": "192.168.0.47",      # myCobot Pi IP (확인)
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
티칭: robot.dummy_mode=false 로 두고 get_angles() 로 4개 자세 각도를 기록해 config 에 기입.
"""
import socket, json, time
from datetime import datetime
from src.utils.logger import setup_logger
from src.utils.config_loader import config

logger = setup_logger("robot")

_R = config["robot"]
DUMMY_MODE = _R["dummy_mode"]

# ── 실로봇 파라미터 (dummy 면 사용 안 함) ──────────────────────────────
HOST  = _R.get("host", "192.168.0.47")
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

# ── mock 파라미터 (dummy 경로) ────────────────────────────────────────
MOCK_HOST = config["mock"]["robot"]["host"]
MOCK_PORT = config["mock"]["robot"]["port"]


class Robot:
    def __init__(self):
        self._mc = None       # 지연 연결 (부팅 시 Pi 미기동이어도 서버 부팅 OK)

    # ── 공개 인터페이스 (FSM 호출) ───────────────────────────────────
    def transfer_tray(self) -> bool:
        """완성 트레이를 AGV 적재 위치로 이재."""
        if DUMMY_MODE:
            return self._mock_cmd("tray_transfer")
        if not self._ensure():
            return False
        return self._transfer_cycle()

    def home(self) -> bool:
        if DUMMY_MODE:
            return self._mock_cmd("home")
        if not self._ensure():
            return False
        return self._send_angles(HOME)

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
            self._mc = mc
            logger.info(f"myCobot 연결: {HOST}:{PORT}")
            return True
        except Exception as e:
            logger.error(f"myCobot 연결 실패: {e}")
            self._mc = None
            return False

    # ── 이재 시퀀스: home→pickup→그립닫기→lift→place→그립열기→home ──
    def _transfer_cycle(self) -> bool:
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

    def _send_angles(self, angles, wait: float = ARRIVE_WAIT_SEC) -> bool:
        """관절각 전송 후 도달까지 폴링. send_coords 는 홈 특이점에서 실패하므로 사용 안 함."""
        a = self._clip(angles)
        self._mc.send_angles(a, SPEED)
        deadline = time.time() + wait
        while time.time() < deadline:
            cur = self._mc.get_angles()           # int 반환 가능 → isinstance 가드
            if isinstance(cur, list) and len(cur) == 6 \
               and all(abs(c - t) < ARRIVE_TOL_DEG for c, t in zip(cur, a)):
                return True
            time.sleep(0.1)
        logger.warning(f"도달 타임아웃: target={a}")
        return False

    def _grip(self, value: int) -> bool:
        try:
            self._mc.set_gripper_value(int(value), 50)
            time.sleep(0.8)
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
