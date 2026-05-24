
import time, random, threading, json
import paho.mqtt.client as mqtt
from src.utils.logger import setup_logger
from src.utils.config_loader import config
from src.core.db import save_inspection

logger = setup_logger("vision")

BROKER   = config["mqtt"]["broker"]
PORT     = config["mqtt"]["port"]
INTERVAL = config["vision"]["dummy_interval_sec"]

DUMMY_COMPONENTS = [
    # IC칩
    {"part_type": "IC칩",     "classification": "NEEDED",    "defect_code": "NONE",     "gate_action": "PASS_THROUGH"},
    {"part_type": "IC칩",     "classification": "DEFECT",    "defect_code": "BENT_PIN", "gate_action": "GATE2_PUSH"},
    {"part_type": "IC칩",     "classification": "DEFECT",    "defect_code": "BROKEN", "gate_action": "GATE2_PUSH"},
    {"part_type": "IC칩",     "classification": "DUPLICATE", "defect_code": "NONE",     "gate_action": "GATE1_PUSH"},
    # 터미널블록
    {"part_type": "터미널블록",   "classification": "NEEDED",    "defect_code": "NONE",     "gate_action": "PASS_THROUGH"},
    {"part_type": "터미널블록",   "classification": "DEFECT",    "defect_code": "BROKEN",   "gate_action": "GATE2_PUSH"},
    {"part_type": "터미널블록",   "classification": "DEFECT",    "defect_code": "BROKEN",   "gate_action": "GATE2_PUSH"},
    {"part_type": "터미널블록",   "classification": "DUPLICATE", "defect_code": "NONE",     "gate_action": "GATE1_PUSH"},
    # 방열판
    {"part_type": "방열판", "classification": "NEEDED",    "defect_code": "NONE",     "gate_action": "PASS_THROUGH"},
    {"part_type": "방열판", "classification": "DEFECT",    "defect_code": "BENT_PIN", "gate_action": "GATE2_PUSH"},
    {"part_type": "방열판", "classification": "DEFECT",    "defect_code": "BROKEN", "gate_action": "GATE2_PUSH"},
    {"part_type": "방열판", "classification": "DUPLICATE", "defect_code": "NONE",     "gate_action": "GATE1_PUSH"},
    # 커패시터
    {"part_type": "커패시터",   "classification": "NEEDED",    "defect_code": "NONE",     "gate_action": "PASS_THROUGH"},
    {"part_type": "커패시터",   "classification": "DEFECT",    "defect_code": "BENT_PIN",   "gate_action": "GATE2_PUSH"},
    {"part_type": "커패시터",   "classification": "DEFECT",    "defect_code": "BROKEN",   "gate_action": "GATE2_PUSH"},
    {"part_type": "커패시터",   "classification": "DUPLICATE", "defect_code": "NONE",     "gate_action": "GATE1_PUSH"},
]

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.connect(BROKER, PORT)
client.loop_start()
logger.info(f"MQTT 연결: {BROKER}:{PORT}")

def publish_inspection(payload: dict):
    client.publish(
        "visipick/inspection",
        json.dumps(payload, ensure_ascii=False)
    )

def publish_system_event(source: str, event_type: str, message: str):
    client.publish(
        "visipick/system/event",
        json.dumps({
            "type":       "system_event",
            "source":     source,
            "event_type": event_type,
            "message":    message,
            "timestamp":  time.strftime("%Y-%m-%dT%H:%M:%S")
        }, ensure_ascii=False)
    )

def publish_agv_status(agv_id: int, state: str, node: str):
    client.publish(
        f"visipick/agv/{agv_id}/status",
        json.dumps({
            "agv_id":    agv_id,
            "state":     state,
            "node":      node,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")
        }, ensure_ascii=False)
    )

def inspection_loop():
    logger.info("검사 더미 모드 시작")
    while True:
        item = random.choice(DUMMY_COMPONENTS)
        payload = {
            "timestamp":      time.strftime("%Y-%m-%dT%H:%M:%S"),
            "part_type":      item["part_type"],
            "classification": item["classification"],
            "defect_code":    item["defect_code"],
            "confidence":     round(random.uniform(0.85, 0.99), 2),
            "gate_action":    item["gate_action"],
        }
        publish_inspection(payload)
        save_inspection(payload)
        publish_system_event(
            "Camera",
            "INFO",
            f"{item['part_type']} 검출 — {item['classification']} ({item['defect_code']})"
        )
        logger.info(f"[더미] {payload}")
        time.sleep(INTERVAL)

def agv_loop():
    logger.info("AGV 더미 모드 시작")
    nodes = ["N1", "N2", "N3", "N4", "WAREHOUSE"]
    while True:
        for agv_id in [1, 2]:
            for node in nodes[:-1]:
                publish_agv_status(agv_id, "moving", node)
                time.sleep(1)
            publish_agv_status(agv_id, "arrived", nodes[-1])
            publish_system_event("AGV", "INFO", f"AGV {agv_id} 창고 도착")
            time.sleep(2)

if __name__ == "__main__":
    logger.info("VisiPick Vision Service 시작")

    threading.Thread(target=inspection_loop, daemon=True).start()
    threading.Thread(target=agv_loop,        daemon=True).start()

    logger.info("Ctrl+C로 종료")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Vision Service 종료")
        client.loop_stop()
