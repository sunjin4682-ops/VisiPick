
import time, random, threading, sqlite3, json
import paho.mqtt.client as mqtt
from datetime import datetime
from src.utils.logger import setup_logger
from src.utils.config_loader import config

logger = setup_logger("vision")

BROKER   = config["mqtt"]["broker"]
PORT     = config["mqtt"]["port"]
DB_PATH  = config["database"]["path"]
INTERVAL = config["vision"]["dummy_interval_sec"]

# 불량 종류 : 핀 휨, 파손
# 부품 종류 : IC칩, 터미널블록, 방열판, 커패시터
DUMMY_COMPONENTS = [
    # IC칩 — A클래스
    {"component_type": "IC칩",       "class": "A", "result": "PASS",   "defect_code": "NONE"},
    {"component_type": "IC칩",       "class": "A", "result": "DEFECT", "defect_code": "BENT_PIN"},
    {"component_type": "IC칩",       "class": "A", "result": "DEFECT", "defect_code": "BROKEN"},
    # 터미널블록 — B클래스
    {"component_type": "터미널블록",  "class": "B", "result": "PASS",   "defect_code": "NONE"},
    {"component_type": "터미널블록",  "class": "B", "result": "DEFECT", "defect_code": "BENT_PIN"},
    {"component_type": "터미널블록",  "class": "B", "result": "DEFECT", "defect_code": "BROKEN"},
    # 방열판 — C클래스
    {"component_type": "방열판",     "class": "C", "result": "PASS",   "defect_code": "NONE"},
    {"component_type": "방열판",     "class": "C", "result": "DEFECT", "defect_code": "BENT_PIN"},
    {"component_type": "방열판",     "class": "C", "result": "DEFECT", "defect_code": "BROKEN"},
    # 커패시터 — D클래스 (또는 A~C 중 분배)
    {"component_type": "커패시터",   "class": "A", "result": "PASS",   "defect_code": "NONE"},
    {"component_type": "커패시터",   "class": "A", "result": "DEFECT", "defect_code": "BENT_PIN"},
    {"component_type": "커패시터",   "class": "A", "result": "DEFECT", "defect_code": "BROKEN"},
]

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.connect(BROKER, PORT)
client.loop_start()
logger.info(f"MQTT 연결: {BROKER}:{PORT}")

# 시작 시 한 번만 연결
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
conn.execute("PRAGMA journal_mode=WAL;")
logger.info(f"DB 연결: {DB_PATH}")

def save_to_db(payload: dict):
    try:
        conn.execute("""
            INSERT INTO InspectionResults
            (Timestamp, ComponentType, Class, DefectCode, Result, Confidence, CycleTimeMs, GateUsed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            payload["timestamp"],
            payload["component_type"],
            payload["class"],
            payload["defect_code"],
            payload["result"],
            payload["confidence"],
            0,
            payload["gate_used"]
        ))
        conn.commit()
        logger.info(f"[DB 저장] {payload['class']}클래스 — {payload['result']} — {payload['defect_code']}")
    except Exception as e:
        logger.error(f"DB 저장 실패: {e}")

def publish_inspection(payload: dict):
    client.publish(
        "factory/visipick/inspection",
        json.dumps(payload, ensure_ascii=False)
    )

def publish_system_event(source: str, event_type: str, message: str):
    client.publish(
        "factory/visipick/system/event",
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
        f"factory/visipick/agv/{agv_id}/status",
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
            "component_type": item["component_type"],
            "class":          item["class"],
            "result":         item["result"],
            "defect_code":    item["defect_code"],
            "confidence":     round(random.uniform(0.85, 0.99), 2),
            "gate_used":      {"A":1,"B":2,"C":3}[item["class"]],
        }
        publish_inspection(payload)
        save_to_db(payload)
        publish_system_event(
            "Camera",
            "INFO",
            f"{item['component_type']} 검출 — {item['class']}클래스 {item['result']} ({item['defect_code']})"
        )
        logger.info(f"[더미] {payload}")
        time.sleep(INTERVAL)

def agv_loop():
    logger.info("AGV 더미 모드 시작")
    nodes = ["N1", "N2", "N3", "N4", "N5"]
    while True:
        for agv_id in [1, 2]:
            for node in nodes:
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
