import socket, json, time
from datetime import datetime
from enum import Enum
from src.utils.logger import setup_logger
from src.utils.config_loader import config

logger = setup_logger("statemachine")

DUMMY_MODE = config["vision"]["dummy_mode"]

# 실제 하드웨어
SERIAL_PORT = config["serial"]["port"]
SERIAL_BAUD = config["serial"]["baudrate"]

# Mock TCP 엔드포인트
ESP32_HOST = config["esp32_mock"]["host"]
ESP32_PORT = config["esp32_mock"]["port"]
ROBOT_HOST = config["robot_mock"]["host"]
ROBOT_PORT = config["robot_mock"]["port"]
AGV_HOST   = config["agv_mock"]["host"]
AGV_PORT   = config["agv_mock"]["port"]

DEST_MAP = {
    "A": config["agv"]["nodes"]["warehouse_A"],
    "B": config["agv"]["nodes"]["warehouse_B"],
    "C": config["agv"]["nodes"]["warehouse_C"],
}


class State(Enum):
    IDLE     = "IDLE"
    RUNNING  = "RUNNING"
    PHASE1   = "PHASE1"
    PHASE2   = "PHASE2"
    PHASE3   = "PHASE3"
    COMPLETE = "COMPLETE"
    ERROR    = "ERROR"


class VisiPickStateMachine:
    def __init__(self):
        self.state         = State.IDLE
        self.cycle         = 0
        self.total_cycles  = config["system"]["demo_cycles"]
        self.current_class = None
        self._ser          = None

        if DUMMY_MODE:
            logger.info(f"더미 모드 — ESP32 Mock TCP {ESP32_HOST}:{ESP32_PORT}")
        else:
            import serial
            self._ser = serial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=10)
            logger.info(f"시리얼 연결: {SERIAL_PORT} {SERIAL_BAUD}bps")
            logger.info("ESP32 부팅 대기 중...")
            time.sleep(3)
            self._ser.reset_input_buffer()
            self._ser.write(b'{"type":"ping"}\n')
            time.sleep(1)
            self._ser.reset_input_buffer()
            logger.info("ESP32 준비완료!")

    # ── 게이트 명령 ────────────────────────────────────────────
    def _send_gate(self, gate, action):
        msg = {"type": "gate_cmd", "gate": gate, "action": action,
               "timestamp": datetime.now().isoformat()}

        if DUMMY_MODE:
            return self._send_tcp(ESP32_HOST, ESP32_PORT, msg)

        # 실제 시리얼
        self._ser.reset_input_buffer()
        self._ser.write((json.dumps(msg) + "\n").encode("utf-8"))
        logger.info(f"시리얼 전송: {msg}")

        resp = ""
        for _ in range(100):
            if self._ser.in_waiting > 0:
                resp = self._ser.readline().decode("utf-8").strip()
                if resp.startswith("{"):
                    break
            time.sleep(0.1)

        if not resp:
            raise RuntimeError("ESP32 응답 없음 (타임아웃)")
        logger.info(f"ESP32 응답: {resp}")
        return json.loads(resp)

    # ── TCP 전송 ───────────────────────────────────────────────
    def _send_tcp(self, host, port, msg, multi=False):
        with socket.socket() as s:
            s.settimeout(10)
            s.connect((host, port))
            s.sendall((json.dumps(msg, ensure_ascii=False) + "\n").encode())

            if multi:
                results = []
                buf = ""
                while True:
                    chunk = s.recv(4096).decode()
                    if not chunk:
                        break
                    buf += chunk
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        line = line.strip()
                        if line:
                            data = json.loads(line)
                            results.append(data)
                            if data.get("state") == "arrived":
                                return results
                return results

            resp = s.recv(4096).decode().strip()
            return json.loads(resp)

    # ── 상태 전이 ──────────────────────────────────────────────
    def _transition(self, new_state):
        logger.info(f"상태 전이: {self.state.value} -> {new_state.value}")
        self.state = new_state

    # ── Phase 1: 검사 & 게이트 ─────────────────────────────────
    def phase1_inspect(self):
        self._transition(State.PHASE1)
        import random
        self.current_class = random.choice(["A", "B", "C"])
        logger.info(f"분류 결과: {self.current_class}클래스")

        resp = self._send_gate(self.current_class, "open")
        if resp.get("status") != "ok":
            raise RuntimeError(f"게이트 동작 실패: {resp}")
        logger.info(f"게이트 {self.current_class} 열기 완료")
        time.sleep(1)

    # ── Phase 2: 로봇 ──────────────────────────────────────────
    def phase2_robot(self):
        self._transition(State.PHASE2)
        resp = self._send_tcp(ROBOT_HOST, ROBOT_PORT, {
            "type":      "robot_cmd",
            "action":    "pick",
            "buffer":    self.current_class,
            "tray":      self.current_class,
            "timestamp": datetime.now().isoformat()
        })
        if resp.get("status") != "ok":
            raise RuntimeError(f"로봇 동작 실패: {resp}")
        logger.info(f"로봇 동작 완료: {resp['status']}")

    # ── Phase 3: AGV ───────────────────────────────────────────
    def phase3_agv(self):
        self._transition(State.PHASE3)
        dest = DEST_MAP[self.current_class]
        results = self._send_tcp(AGV_HOST, AGV_PORT, {
            "type":        "agv_cmd",
            "agv_id":      1,
            "destination": dest,
            "timestamp":   datetime.now().isoformat()
        }, multi=True)
        for r in results:
            logger.info(f"AGV: {r.get('state')} -> {r.get('node')}")

    # ── 전체 실행 ──────────────────────────────────────────────
    def run(self):
        logger.info("VisiPick 시스템 시작")
        self._transition(State.RUNNING)

        while self.cycle < self.total_cycles:
            self.cycle += 1
            logger.info(f"{'='*40}")
            logger.info(f"사이클 {self.cycle}/{self.total_cycles} 시작")

            try:
                self.phase1_inspect()
                self.phase2_robot()
                self.phase3_agv()
                self._transition(State.COMPLETE)
                logger.info(f"사이클 {self.cycle} 완료!")
                time.sleep(1)
            except Exception as e:
                self._transition(State.ERROR)
                logger.error(f"오류 발생: {e}")
                break

        logger.info(f"전체 {self.cycle}회 사이클 종료")
        if self._ser:
            self._ser.close()


if __name__ == "__main__":
    sm = VisiPickStateMachine()
    sm.run()
