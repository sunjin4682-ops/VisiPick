import socket, json, threading, time
from collections.abc import Callable
from datetime import datetime
from src.utils.logger import setup_logger
from src.utils.config_loader import config

logger = setup_logger("serial_ctrl")

DUMMY_MODE  = config["serial"]["dummy_mode"]
SERIAL_PORT = config["serial"]["port"]
SERIAL_BAUD = config["serial"]["baudrate"]
ESP32_HOST  = config["mock"]["esp32"]["host"]
ESP32_PORT  = config["mock"]["esp32"]["port"]
# 컨3 트레이 1칸 구동 시간(ms). None 이면 펌웨어 기본값(2초) 사용.
TRAY_ADVANCE_MS = config.get("conveyor", {}).get("tray_advance_ms")


class SerialController:
    """
    ESP32 게이트 푸셔 + 컨베이어 제어.
    dummy_mode=True  → MockESP32 TCP (localhost:9001)
    dummy_mode=False → USB Serial COM8

    on_sensor: 투입단 센서({"type":"sensor_triggered"}) 수신 시 호출할 콜백.
               더미 모드에서는 state_machine의 _start_dummy_trigger가 대신하므로 무시.
    """

    def __init__(self, on_sensor: Callable | None = None,
                 on_estop: Callable | None = None,
                 on_estop_clear: Callable | None = None):
        self._on_sensor = on_sensor
        self._on_estop  = on_estop        # 물리 비상정지 버튼 눌림 콜백 (ESP32 → Python)
        self._on_estop_clear = on_estop_clear  # 물리 비상정지 버튼 해제 콜백
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
                    raw = None
                    # 락 안에서는 '읽기'만 — 콜백이 _send()로 같은 락을 재요청하면
                    # 데드락(비상정지 콜백 → emergency_stop()/set_conveyor_speed() 가 멈춤).
                    with self._send_lock:
                        if self._ser.in_waiting > 0:
                            raw = self._ser.readline()
                    if raw:
                        msg = json.loads(raw.decode("utf-8", errors="ignore").strip())
                        t = msg.get("type")
                        if t == "sensor_triggered":
                            if self._on_sensor:
                                self._on_sensor()
                        elif t == "emergency_stop" and msg.get("source") == "button":
                            logger.warning("물리 비상정지 버튼 눌림!")
                            if self._on_estop:
                                self._on_estop()
                        elif t == "emergency_clear" and msg.get("source") == "button":
                            logger.warning("물리 비상정지 버튼 해제됨")
                            if self._on_estop_clear:
                                self._on_estop_clear()
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
        """컨1(메인 컨베이어) 속도 설정 (cm/s). 0.0 이면 정지."""
        return self._send({"type": "conveyor_cmd", "action": "set_speed", "speed": speed_cm_per_s, "timestamp": _now()})

    def advance_tray(self) -> bool:
        """컨3(다음 빈 트레이 공급 컨베이어) 구동 — 트레이가 찰 때마다 다음 빈 트레이를 수집 위치로 이동.
        구동 시간은 config.conveyor.tray_advance_ms(ms)로 전달 → 펌웨어가 그 시간만큼 ON 후 자동 정지.
        (config 에 없으면 펌웨어 기본 2초)."""
        msg = {"type": "tray_cmd", "action": "advance", "timestamp": _now()}
        if TRAY_ADVANCE_MS is not None:
            msg["duration_ms"] = TRAY_ADVANCE_MS
        return self._send(msg)
    
    def start_return_conveyor(self) -> bool:
        """컨2(중복 반환 컨베이어, 상시 ON) 재가동. 펌웨어 텍스트 명령 'CONV2:START'.
        비상정지 시 펌웨어가 컨2를 멈추는데 컨베이어 시작이 컨1만 켜므로, 복귀 시
        컨2도 다시 켜기 위해 호출한다. (응답 ack 는 수신 루프가 소진)"""
        if DUMMY_MODE:
            return True
        try:
            with self._send_lock:
                self._ser.write(b"CONV2:START\n")
            return True
        except Exception as e:
            logger.error(f"컨2 시작 오류: {e}")
            return False

    def emergency_stop(self) -> bool:
        """비상정지 — 컨1·컨2·컨3·게이트 전체 정지 (펌웨어 emergencyStop())."""
        return self._send({"type": "emergency_stop", "timestamp": _now()})


    def _send(self, msg: dict) -> bool:
        try:
            if DUMMY_MODE:
                resp = _send_tcp(ESP32_HOST, ESP32_PORT, msg)
            else:
                with self._send_lock:
                    self._ser.reset_input_buffer()
                    self._ser.write((json.dumps(msg) + "\n").encode("utf-8"))
                    raw = self._ser.readline()
                    resp = json.loads(raw.decode("utf-8", errors="ignore").strip())
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
