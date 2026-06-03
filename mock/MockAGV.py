"""
mock/MockAGV.py — AGV 시뮬레이터 (MQTT 버전, agv_mqtt.AGVMqttManager 짝)

기존 TCP(9003) 목은 현재 MQTT 기반 agv_mqtt 와 통신 불가라 폐기하고 MQTT 로 교체.

구독: visipick/agv/+/command   ({"action":"GO","destination":...} | {"action":"UNLOAD"})
발행: visipick/agv/{id}/status  ({"agv_id","state","node","timestamp"})

동작:
  - GO       → 중간 노드 몇 개 "moving" 발행 후 목적지에서 "arrived" 발행
  - UNLOAD   → "unloading" → "idle" (arrived 아님 → 매니저가 도착으로 오인 안 함)

C2 라운드트립: GO(창고) → arrived(창고) → [매니저] UNLOAD + GO(N1) → arrived(N1).

이동 속도는 환경변수 MOCK_AGV_STEP(초/스텝, 기본 0.3)로 조절 — 테스트는 짧게.
단독 실행:  python -m mock.MockAGV
"""
import json, os, threading, sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import paho.mqtt.client as mqtt

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.utils.logger import setup_logger
from src.utils.config_loader import config

logger = setup_logger("agv")

BROKER = config["mqtt"]["broker"]
PORT   = config["mqtt"]["port"]
STEP   = float(os.environ.get("MOCK_AGV_STEP", "0.3"))
MID_NODES = ["J1", "J2"]                 # 중간 분기 노드 (라벨은 무의미 — moving 표시용)


class MockAGV:
    def __init__(self):
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._locks: dict[int, threading.Lock] = defaultdict(threading.Lock)

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        client.subscribe("visipick/agv/+/command")
        logger.info("Mock AGV(MQTT) 명령 구독: visipick/agv/+/command")

    def _on_message(self, client, userdata, msg):
        try:
            data = json.loads(msg.payload.decode())
        except Exception:
            return
        agv_id = data.get("agv_id")
        action = (data.get("action") or "GO").upper()
        dest   = data.get("destination")
        # 명령마다 워커 스레드 — 네트워크 루프 비차단, AGV별 직렬화
        threading.Thread(target=self._handle, args=(agv_id, action, dest),
                         daemon=True).start()

    def _handle(self, agv_id, action, dest):
        with self._locks[agv_id]:
            if action == "UNLOAD":
                self._status(agv_id, "unloading", "WAREHOUSE")
                threading.Event().wait(STEP)
                self._status(agv_id, "idle", "WAREHOUSE")
                logger.info(f"AGV {agv_id} 하역 완료(지게 서보)")
                return
            # GO
            logger.info(f"AGV {agv_id} 이동 시작 → {dest}")
            for node in MID_NODES:
                self._status(agv_id, "moving", node)
                threading.Event().wait(STEP)
            self._status(agv_id, "arrived", dest)
            logger.info(f"AGV {agv_id} 도착: {dest}")

    def _status(self, agv_id, state, node):
        payload = {
            "agv_id":    agv_id,
            "state":     state,
            "node":      node,
            "timestamp": datetime.now().isoformat(),
        }
        self._client.publish(f"visipick/agv/{agv_id}/status",
                             json.dumps(payload, ensure_ascii=False))

    def run_forever(self):
        self._client.connect(BROKER, PORT)
        logger.info(f"Mock AGV(MQTT) 실행 중 — broker {BROKER}:{PORT}, step={STEP}s")
        self._client.loop_forever()


if __name__ == "__main__":
    MockAGV().run_forever()
