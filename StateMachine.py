import socket, json, time, serial
from datetime import datetime
from enum import Enum
from Logger import setup_logger
import paho.mqtt.client as mqtt

logger = setup_logger("statemachine")

SERIAL_PORT = "COM8"
SERIAL_BAUD = 115200

ROBOT_HOST = "localhost"
ROBOT_PORT = 9002
AGV_HOST   = "localhost"
AGV_PORT   = 9003

class State(Enum):
    IDLE     = "IDLE"
    RUNNING  = "RUNNING"
    PHASE1   = "PHASE1"
    PHASE2   = "PHASE2"
    PHASE3   = "PHASE3"
    COMPLETE = "COMPLETE"
    ERROR    = "ERROR"

TRANSITIONS = {
    "IDLE":     {"start":       "RUNNING"},
    "RUNNING":  {"inspect":     "PHASE1",  "stop": "IDLE"},
    "PHASE1":   {"gate_done":   "PHASE2",  "error": "ERROR"},
    "PHASE2":   {"robot_done":  "PHASE3",  "error": "ERROR"},
    "PHASE3":   {"agv_done":    "COMPLETE","error": "ERROR"},
    "COMPLETE": {"next_cycle":  "RUNNING", "finish": "IDLE"},
    "ERROR":    {"retry":       "RUNNING", "stop":  "IDLE"},
}

class VisiPickStateMachine:
    def __init__(self):
        self.state         = State.IDLE
        self.cycle         = 0
        self.total_cycles  = 3
        self.current_class = None

        # 시리얼 연결
        self.ser = serial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=10)
        logger.info(f"시리얼 연결: {SERIAL_PORT} {SERIAL_BAUD}bps")

        # ESP32 부팅 완료까지 대기 (부팅 로그 전부 읽어서 버림)
        logger.info("ESP32 부팅 대기 중...")
        time.sleep(3)
        self.ser.reset_input_buffer()  # 버퍼 비우기

        # 준비완료 확인
        logger.info("ESP32 준비완료 확인 중...")
        self.ser.write(b'{"type":"ping"}\n')
        time.sleep(1)
        self.ser.reset_input_buffer()
        logger.info("ESP32 준비완료!")

        # MQTT 클라이언트 (vision 결과 수신)
        self._inspection_result = None
        self.mqttc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.mqttc.on_message = self._on_inspection
        self.mqttc.connect(config["mqtt"]["broker"], config["mqtt"]["port"])
        self.mqttc.subscribe(config["mqtt"]["topics"]["inspection"])
        self.mqttc.loop_start()
        logger.info("MQTT 구독 시작: 검사 결과 수신 대기")

    def _on_inspection(self, client, userdata, msg):
        """vision_service에서 검사 결과 수신"""
        data = json.loads(msg.payload.decode())
        self._inspection_result = data
        logger.info(f"검사 결과 수신: {data['class']}클래스 — {data['result']}")

    def _send_gate(self, gate, action):
        """시리얼로 ESP32에 게이트 명령"""
        # 버퍼 비우기
        self.ser.reset_input_buffer()

        msg = json.dumps({
            "type":   "gate_cmd",
            "gate":   gate,
            "action": action
        }) + "\n"

        self.ser.write(msg.encode("utf-8"))
        logger.info(f"시리얼 전송: {msg.strip()}")

        # 응답 수신 (최대 10초 대기)
        resp = ""
        for _ in range(100):
            if self.ser.in_waiting > 0:
                resp = self.ser.readline().decode("utf-8").strip()
                if resp.startswith("{"):
                    break
            time.sleep(0.1)

        if not resp:
            raise RuntimeError("ESP32 응답 없음 (타임아웃)")

        logger.info(f"ESP32 응답: {resp}")
        return json.loads(resp)

    def _send_tcp(self, host, port, msg, multi=False):
        with socket.socket() as s:
            s.settimeout(5)
            s.connect((host, port))
            s.sendall((json.dumps(msg, ensure_ascii=False) + "\n").encode())
            if multi:
                results = []
                while True:
                    resp = s.recv(4096).decode().strip()
                    if not resp:
                        break
                    data = json.loads(resp)
                    results.append(data)
                    if data.get("state") == "arrived":
                        break
                return results
            return json.loads(s.recv(4096).decode().strip())

    def _transition(self, event: str):
        allowed = TRANSITIONS.get(self.state.value, {})
        if event not in allowed:
            logger.warning(f"무시: {self.state.value}에서 '{event}' 이벤트는 불가")
            return False
        old = self.state.value
        self.state = State(allowed[event])
        logger.info(f"상태 전이: {old} → {self.state.value} (이벤트: {event})")
        return True

    def phase1_inspect(self):
        self._transition("inspect")  # RUNNING → PHASE1
        import random
        self.current_class = random.choice(["A", "B", "C"])
        logger.info(f"분류 결과: {self.current_class}클래스")

        resp = self._send_gate(self.current_class, "open")
        logger.info(f"게이트 응답: {resp}")

        if resp.get("status") != "ok":
            self._transition("error")  # → ERROR
            raise RuntimeError(f"게이트 동작 실패: {resp}")
        self._transition("gate_done")  # PHASE1 → PHASE2
        time.sleep(1)

    def phase2_robot(self):
        # 이미 PHASE2 상태
        resp = self._send_tcp(ROBOT_HOST, ROBOT_PORT, {
            "type":      "robot_cmd",
            "action":    "pick",
            "buffer":    self.current_class,
            "tray":      self.current_class,
            "timestamp": datetime.now().isoformat()
        })
        logger.info(f"로봇 동작: {resp['status']}")
        self._transition("robot_done")  # PHASE2 → PHASE3

    def phase3_agv(self):
        # 이미 PHASE3 상태
        dest = {"A": "N5", "B": "N6", "C": "N7"}[self.current_class]
        results = self._send_tcp(AGV_HOST, AGV_PORT, {
            "type":        "agv_cmd",
            "agv_id":      1,
            "destination": dest,
            "timestamp":   datetime.now().isoformat()
        }, multi=True)
        for r in results:
            logger.info(f"AGV: {r['state']} — {r['node']}")
        self._transition("agv_done")  # PHASE3 → COMPLETE

    def run(self):
        logger.info("VisiPick 시스템 시작")
        self._transition("start")  # IDLE → RUNNING

        while self.cycle < self.total_cycles:
            self.cycle += 1
            logger.info(f"\n{'='*40}")
            logger.info(f"사이클 {self.cycle}/{self.total_cycles} 시작")

            retry_count = 0
            max_retry = 3
            success = False

            while retry_count < max_retry and not success:
                try:
                    self.phase1_inspect()
                    self.phase2_robot()
                    self.phase3_agv()
                    logger.info(f"사이클 {self.cycle} 완료!")
                    success = True
                    self._transition("next_cycle")  # COMPLETE → RUNNING
                    time.sleep(1)
                except Exception as e:
                    retry_count += 1
                    self._transition("error")  # → ERROR
                    if retry_count < max_retry:
                        logger.warning(f"오류: {e} — 재시도 {retry_count}/{max_retry}")
                        self._transition("retry")  # ERROR → RUNNING
                        time.sleep(2)
                    else:
                        logger.error(f"오류: {e} — {max_retry}회 실패, 중단")

            if not success:
                self._transition("stop")  # ERROR → IDLE
                break

        self._transition("finish")  # COMPLETE → IDLE
        logger.info(f"\n전체 {self.cycle}회 사이클 완료!")
        self.ser.close()

if __name__ == "__main__":
    sm = VisiPickStateMachine()
    sm.run()
