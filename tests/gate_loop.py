"""
tests/gate_loop.py — 게이트 단독 반복 테스트 (로드맵 Phase 2 Step 3)

visipick/gate/cmd 로 Gate1·Gate2 푸시 명령을 번갈아 발행한다. 실행 중인 FSM
(state_machine) 이 이 토픽을 받아 serial_ctrl.push_gate() 로 ESP32 에 전달한다.
→ Gate1(반환/DUPLICATE·UNCERTAIN), Gate2(불량/DEFECT) 서보 동작·타이밍 단독 점검용.

실행:  python -m tests.gate_loop      (Ctrl+C 중지)
전제:  브로커 + FSM(또는 api_server autorun) 기동.
"""
import paho.mqtt.client as mqtt
import json, time, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.utils.config_loader import config

BROKER = config["mqtt"]["broker"]
PORT   = config["mqtt"]["port"]

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.connect(BROKER, PORT)
client.loop_start()

print("게이트 연속 푸시 시작 (Ctrl+C 중지) — FSM 이 visipick/gate/cmd 를 ESP32 로 전달")
try:
    while True:
        for gate in (1, 2):
            client.publish("visipick/gate/cmd", json.dumps({
                "type": "gate_cmd", "gate": gate, "action": "push",
            }))
            print(f"Gate {gate} push")
            time.sleep(2)
except KeyboardInterrupt:
    client.loop_stop()
    print("게이트 테스트 종료")
