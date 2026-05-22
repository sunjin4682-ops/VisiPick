import socket, json
from datetime import datetime
from src.utils.logger import setup_logger
from src.utils.config_loader import config

logger = setup_logger("robot")

DUMMY_MODE = config["robot"]["dummy_mode"]
HOST       = config["mock"]["robot"]["host"] if DUMMY_MODE else config["robot"]["host"]
PORT       = config["mock"]["robot"]["port"] if DUMMY_MODE else config["robot"]["port"]
SPEED      = config["robot"]["speed"]


class Robot:
    """
    myCobot 트레이 이송 제어.
    dummy_mode=True  → MockMyCobot TCP (localhost:9002)
    dummy_mode=False → RPi4 Ethernet TCP (192.168.0.47:9002)
    """

    def transfer_tray(self) -> bool:
        """완성된 트레이를 AGV 적재 위치로 이송."""
        msg = {
            "type":      "robot_cmd",
            "action":    "tray_transfer",
            "speed":     SPEED,
            "timestamp": _now(),
        }
        try:
            resp = _send_tcp(HOST, PORT, msg)
            ok = resp.get("status") == "ok"
            if ok:
                logger.info("트레이 이송 완료")
            else:
                logger.error(f"트레이 이송 실패: {resp}")
            return ok
        except Exception as e:
            logger.error(f"Robot TCP 오류: {e}")
            return False

    def home(self) -> bool:
        """홈 포지션 복귀."""
        try:
            resp = _send_tcp(HOST, PORT, {"type": "robot_cmd", "action": "home", "timestamp": _now()})
            return resp.get("status") == "ok"
        except Exception as e:
            logger.error(f"Robot home 오류: {e}")
            return False


def _send_tcp(host: str, port: int, msg: dict) -> dict:
    with socket.socket() as s:
        s.settimeout(10)
        s.connect((host, port))
        s.sendall((json.dumps(msg, ensure_ascii=False) + "\n").encode())
        return json.loads(s.recv(4096).decode().strip())


def _now() -> str:
    return datetime.now().isoformat()
