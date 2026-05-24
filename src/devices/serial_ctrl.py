import socket, json, threading, time
from collections.abc import Callable
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

    on_sensor: 투입단 센서({"type":"sensor_triggered"}) 수신 시 호출할 콜백.
               더미 모드에서는 state_machine의 _start_dummy_trigger가 대신하므로 무시.
    """

    def __init__(self, on_sensor: Callable | None = None):
        self._on_sensor = on_sensor
        self._ser       = None
        self._send_lock = threading.Lock()   # 송신-수신 충돌 방지

        if DUMMY_MODE:
            logger.info(f"ESP32 더미 모드: {ESP32_HOST}:{ESP32_PORT}")
            return

        import serial
        self._ser = serial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=10)
        time.sleep(2)
        self._ser.reset_input_buffer()
        logger.info(f"ESP32 시리얼 연결: {SERIAL_PORT} {SERIAL_BAUD}bps")

        if on_sensor:
            self._start_recv_loop()

    # ── 비동기 수신 루프 ──────────────────────────────────────
    def _start_recv_loop(self):
        """ESP32 → PC 방향 메시지 감시 (sensor_triggered 전용)."""
        def _loop():
            while self._ser and self._ser.is_open:
                try:
                    with self._send_lock:
                        # 데이터가 있을 때만 readline — _send()와 readline() 충돌 방지
                        if self._ser.in_waiting > 0:
                            raw = self._ser.readline()
                            if raw:
                                msg = json.loads(raw.decode("utf-8").strip())
                                if msg.get("type") == "sensor_triggered":
                                    self._on_sensor()
                except Exception as e:
                    logger.warning(f"시리얼 수신 오류: {e}")
                time.sleep(0.01)   # 10ms 폴링

        threading.Thread(target=_loop, daemon=True).start()
        logger.info("ESP32 시리얼 수신 루프 시작")

    # ── 송신 API ──────────────────────────────────────────────
    def push_gate(self, gate_id: int) -> bool:
        """
        게이트 푸셔 동작.
        gate_id=1 → Gate1 (반환 bin, DUPLICATE)
        gate_id=2 → Gate2 (불량 bin, DEFECT)
        """
        return self._send({"type": "gate_cmd", "gate": str(gate_id), "action": "push", "timestamp": _now()})

    def set_conveyor_speed(self, speed_cm_per_s: float) -> bool:
        """컨베이어 속도 설정 (cm/s). 0.0 이면 정지."""
        return self._send({"type": "conveyor_cmd", "action": "set_speed", "speed": speed_cm_per_s, "timestamp": _now()})

    def _send(self, msg: dict) -> bool:
        try:
            if DUMMY_MODE:
                resp = _send_tcp(ESP32_HOST, ESP32_PORT, msg)
            else:
                with self._send_lock:
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
