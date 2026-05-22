import socket, json
from datetime import datetime
from src.utils.logger import setup_logger
from src.utils.config_loader import config

logger = setup_logger("serial_ctrl")

DUMMY_MODE  = config["vision"]["dummy_mode"]
SERIAL_PORT = config["serial"]["port"]
SERIAL_BAUD = config["serial"]["baudrate"]
ESP32_HOST  = config["mock"]["esp32"]["host"]
ESP32_PORT  = config["mock"]["esp32"]["port"]


class SerialController:
    """
    ESP32 게이트 푸셔 + 컨베이어 제어.
    dummy_mode=True  → MockESP32 TCP (localhost:9001)
    dummy_mode=False → USB Serial COM8
    """

    def __init__(self):
        self._ser = None
        if DUMMY_MODE:
            logger.info(f"ESP32 더미 모드: {ESP32_HOST}:{ESP32_PORT}")
            return
        import serial, time
        self._ser = serial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=10)
        time.sleep(2)
        self._ser.reset_input_buffer()
        logger.info(f"ESP32 시리얼 연결: {SERIAL_PORT} {SERIAL_BAUD}bps")

    def push_gate(self, gate_id: int) -> bool:
        """
        게이트 푸셔 동작.
        gate_id=1 → Gate1 (반환 bin, DUPLICATE)
        gate_id=2 → Gate2 (불량 bin, DEFECT)
        """
        return self._send({"type": "gate_cmd", "gate": str(gate_id), "action": "push", "timestamp": _now()})

    def set_conveyor_speed(self, speed_cm_per_s: float) -> bool:
        """컨베이어 속도 설정 (cm/s)."""
        return self._send({"type": "conveyor_cmd", "action": "set_speed", "speed": speed_cm_per_s, "timestamp": _now()})

    def _send(self, msg: dict) -> bool:
        try:
            if DUMMY_MODE:
                resp = _send_tcp(ESP32_HOST, ESP32_PORT, msg)
            else:
                self._ser.reset_input_buffer()
                self._ser.write((json.dumps(msg) + "\n").encode("utf-8"))
                resp = json.loads(self._ser.readline().decode("utf-8").strip())
            ok = resp.get("status") == "ok"
            if not ok:
                logger.warning(f"ESP32 응답 실패: {resp}")
            return ok
        except Exception as e:
            logger.error(f"ESP32 통신 오류: {e}")
            return False

    def close(self):
        if self._ser:
            self._ser.close()
            logger.info("ESP32 시리얼 종료")


def _send_tcp(host: str, port: int, msg: dict) -> dict:
    with socket.socket() as s:
        s.settimeout(10)
        s.connect((host, port))
        s.sendall((json.dumps(msg, ensure_ascii=False) + "\n").encode())
        return json.loads(s.recv(4096).decode().strip())


def _now() -> str:
    return datetime.now().isoformat()
