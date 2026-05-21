import socket
import json
import time
from datetime import datetime
from enum import Enum
from src.utils.logger import setup_logger

logger = setup_logger("statemachine")

# =========================
# 실제 ESP32 TCP 주소
# =========================
ESP32_HOST = "192.168.0.38"   # 여기를 ESP32 시리얼 모니터에 뜬 IP로 바꾸기
ESP32_PORT = 9001

# 로봇 / AGV는 아직 Mock 서버 사용
ROBOT_HOST = "localhost"
ROBOT_PORT = 9002

AGV_HOST = "localhost"
AGV_PORT = 9003


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
        self.state = State.IDLE
        self.cycle = 0
        self.total_cycles = 3
        self.current_class = None

    def _send(self, host, port, msg, multi=False):
        """
        TCP 서버에 JSON 명령 전송.
        ESP32는 newline 기반으로 받으므로 마지막에 \\n을 붙인다.
        """
        logger.info(f"TCP 전송 시도: {host}:{port} / {msg}")

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(10)
            s.connect((host, port))

            payload = json.dumps(msg, ensure_ascii=False) + "\n"
            s.sendall(payload.encode("utf-8"))

            if multi:
                results = []

                while True:
                    resp = s.recv(4096).decode("utf-8").strip()

                    if not resp:
                        break

                    data = json.loads(resp)
                    results.append(data)

                    if data.get("state") == "arrived":
                        break

                return results

            else:
                resp = s.recv(4096).decode("utf-8").strip()

                if not resp:
                    raise RuntimeError(f"{host}:{port} 에서 응답이 없습니다.")

                return json.loads(resp)

    def _transition(self, new_state):
        logger.info(f"상태 전이: {self.state.value} → {new_state.value}")
        self.state = new_state

    def phase1_inspect(self):
        """PHASE1: 검사·분류·게이트 열기"""
        self._transition(State.PHASE1)

        import random
        self.current_class = random.choice(["A", "B", "C"])

        logger.info(f"분류 결과: {self.current_class} 클래스")

        resp = self._send(ESP32_HOST, ESP32_PORT, {
            "type": "gate_cmd",
            "gate": self.current_class,
            "action": "open",
            "timestamp": datetime.now().isoformat()
        })

        logger.info(f"게이트 {self.current_class} 열기 응답: {resp}")

        if resp.get("status") != "ok":
            raise RuntimeError(f"ESP32 게이트 동작 실패: {resp}")

        time.sleep(1)

    def phase2_robot(self):
        """PHASE2: 로봇 Pick&Place"""
        self._transition(State.PHASE2)

        resp = self._send(ROBOT_HOST, ROBOT_PORT, {
            "type": "robot_cmd",
            "action": "pick",
            "buffer": self.current_class,
            "tray": self.current_class,
            "timestamp": datetime.now().isoformat()
        })

        logger.info(f"로봇 동작 응답: {resp}")

        if resp.get("status") != "ok":
            raise RuntimeError(f"로봇 동작 실패: {resp}")

    def phase3_agv(self):
        """PHASE3: AGV 운반"""
        self._transition(State.PHASE3)

        dest = {
            "A": "N5",
            "B": "N6",
            "C": "N7"
        }[self.current_class]

        results = self._send(AGV_HOST, AGV_PORT, {
            "type": "agv_cmd",
            "agv_id": 1,
            "destination": dest,
            "timestamp": datetime.now().isoformat()
        }, multi=True)

        for r in results:
            logger.info(f"AGV: {r.get('state')} — {r.get('node')}")

    def run(self):
        logger.info("VisiPick 시스템 시작")
        self._transition(State.RUNNING)

        while self.cycle < self.total_cycles:
            self.cycle += 1

            logger.info("")
            logger.info("=" * 40)
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

        logger.info("")
        logger.info(f"전체 {self.cycle}회 사이클 종료")


if __name__ == "__main__":
    sm = VisiPickStateMachine()
    sm.run()
