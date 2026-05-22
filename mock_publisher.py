import json, time, random, threading, sys, io
import paho.mqtt.client as mqtt
from datetime import datetime

# Windows CP949 콘솔에서 em dash 등 유니코드 문자 출력 오류 방지 (logger.py와 동일)
if hasattr(sys.stdout, "buffer") and sys.stdout.encoding.lower().replace("-", "") != "utf8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BROKER = "localhost"
PORT   = 1883

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.connect(BROKER, PORT)
client.loop_start()

print("="*50)
print("VisiPick Mock Publisher")
print("최지윤님 WPF 독립 개발용 가짜 데이터 생성기")
print("="*50)

COMPONENTS = [
    {"component_type": "IC칩",       "class": "A", "result": "PASS",   "defect_code": "NONE"},
    {"component_type": "IC칩",       "class": "A", "result": "DEFECT", "defect_code": "BENT_PIN"},
    {"component_type": "터미널블록",  "class": "B", "result": "PASS",   "defect_code": "NONE"},
    {"component_type": "터미널블록",  "class": "B", "result": "DEFECT", "defect_code": "BROKEN"},
    {"component_type": "방열판",     "class": "C", "result": "PASS",   "defect_code": "NONE"},
    {"component_type": "커패시터",   "class": "A", "result": "PASS",   "defect_code": "NONE"},
]

def publish_inspection():
    """3초마다 검사 결과 발행"""
    while True:
        item = random.choice(COMPONENTS)
        payload = {
            "timestamp":      datetime.now().isoformat(),
            "component_type": item["component_type"],
            "class":          item["class"],
            "result":         item["result"],
            "defect_code":    item["defect_code"],
            "confidence":     round(random.uniform(0.85, 0.99), 2),
            "gate_used":      {"A":1,"B":2,"C":3}[item["class"]],
        }
        client.publish("visipick/inspection", json.dumps(payload, ensure_ascii=False))
        print(f"[검사] {item['component_type']} — {item['result']}")
        time.sleep(3)

def publish_agv():
    """AGV 상태 발행"""
    nodes = ["N1", "N2", "N3", "N4", "N5"]
    while True:
        for agv_id in [1, 2]:
            for node in nodes:
                payload = {
                    "agv_id":    agv_id,
                    "state":     "moving",
                    "node":      node,
                    "timestamp": datetime.now().isoformat()
                }
                client.publish(f"visipick/agv/{agv_id}/status", json.dumps(payload))
                time.sleep(1)
            payload = {
                "agv_id":    agv_id,
                "state":     "arrived",
                "node":      nodes[-1],
                "timestamp": datetime.now().isoformat()
            }
            client.publish(f"visipick/agv/{agv_id}/status", json.dumps(payload))
            time.sleep(2)

def publish_system_event():
    """5초마다 시스템 이벤트 발행"""
    events = [
        {"source": "Camera",   "event_type": "INFO",    "message": "IC칩 검출 완료"},
        {"source": "Robot",    "event_type": "INFO",    "message": "Pick 완료"},
        {"source": "AGV",      "event_type": "INFO",    "message": "AGV 1 도착"},
        {"source": "Gate",     "event_type": "WARNING", "message": "Gate A 응답 지연"},
        {"source": "System",   "event_type": "INFO",    "message": "사이클 완료"},
    ]
    while True:
        evt = random.choice(events)
        payload = {
            "type":       "system_event",
            "source":     evt["source"],
            "event_type": evt["event_type"],
            "message":    evt["message"],
            "timestamp":  datetime.now().isoformat()
        }
        client.publish("visipick/system/event", json.dumps(payload, ensure_ascii=False))
        print(f"[이벤트] {evt['source']} — {evt['message']}")
        time.sleep(5)

def publish_state():
    """공정 상태 발행"""
    states = ["IDLE", "RUNNING", "PHASE1", "PHASE2", "PHASE3", "COMPLETE"]
    while True:
        for state in states:
            payload = {
                "state":     state,
                "timestamp": datetime.now().isoformat()
            }
            client.publish("visipick/system/state", json.dumps(payload))
            print(f"[상태] {state}")
            time.sleep(4)

if __name__ == "__main__":
    print("\n모든 더미 데이터 발행 시작... (Ctrl+C로 종료)\n")

    threading.Thread(target=publish_inspection,   daemon=True).start()
    threading.Thread(target=publish_agv,           daemon=True).start()
    threading.Thread(target=publish_system_event,  daemon=True).start()
    threading.Thread(target=publish_state,         daemon=True).start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nMock Publisher 종료")
