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

print("게이트 연속 동작 시작 (Ctrl+C로 중지)")

while True:
    for gate in ["A", "B", "C"]:
        # 열기
        client.publish("factory/visipick/gate/cmd", json.dumps({
            "type": "gate_cmd",
            "gate": gate,
            "action": "open"
        }))
        print(f"Gate {gate} 열기")
        time.sleep(1)

        # 닫기
        client.publish("factory/visipick/gate/cmd", json.dumps({
            "type": "gate_cmd",
            "gate": gate,
            "action": "close"
        }))
        print(f"Gate {gate} 닫기")
        time.sleep(1)
