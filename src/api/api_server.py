import json, sqlite3, threading
from pathlib import Path
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import paho.mqtt.client as mqtt
import uvicorn

# =====================
# 설정
# =====================
_root = Path(__file__).parent.parent.parent  # C:\VisiPick
with open(_root / "config" / "config.json", "r", encoding="utf-8-sig") as f:
    config = json.load(f)

DB_PATH = config["database"]["path"]
BROKER  = config["mqtt"]["broker"]
PORT    = config["mqtt"]["port"]

# =====================
# FastAPI 앱
# =====================
app = FastAPI(
    title="VisiPick API",
    description="스마트팩토리 VisiPick 시스템 REST API + WebSocket",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# =====================
# DB 연결
# =====================
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# =====================
# WebSocket 관리
# =====================
ws_clients: list[WebSocket] = []

async def broadcast(data: dict):
    """모든 WebSocket 클라이언트에 전송"""
    disconnected = []
    for ws in ws_clients:
        try:
            await ws.send_json(data)
        except:
            disconnected.append(ws)
    for ws in disconnected:
        ws_clients.remove(ws)

# =====================
# MQTT 구독 → WebSocket push
# =====================
mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

def on_mqtt_message(client, userdata, msg):
    """MQTT 수신 → WebSocket으로 push"""
    try:
        data = json.loads(msg.payload.decode())
        data["_topic"] = msg.topic
        import asyncio
        loop = asyncio.new_event_loop()
        loop.run_until_complete(broadcast(data))
        loop.close()
    except:
        pass

mqtt_client.on_message = on_mqtt_message
mqtt_client.connect(BROKER, PORT)
mqtt_client.subscribe("factory/visipick/#")
mqtt_client.loop_start()

# =====================
# WebSocket 엔드포인트
# =====================
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    ws_clients.append(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # WPF에서 명령 수신 시 MQTT로 전달
            msg = json.loads(data)
            topic = msg.get("topic", "factory/visipick/system/event")
            mqtt_client.publish(topic, json.dumps(msg))
    except WebSocketDisconnect:
        ws_clients.remove(websocket)

# =====================
# REST API — 시스템 상태
# =====================
@app.get("/api/health", tags=["시스템"])
def health():
    """서버 상태 확인"""
    return {"status": "ok", "service": "VisiPick API", "timestamp": datetime.now().isoformat()}

@app.get("/api/config", tags=["시스템"])
def get_config():
    """현재 시스템 설정 조회"""
    return config

# =====================
# REST API — 검사 이력
# =====================
@app.get("/api/inspections", tags=["검사"])
def get_inspections(limit: int = 100):
    """검사 이력 조회 (최근 N건)"""
    conn = get_db()
    rows = conn.execute("""
        SELECT Id, Timestamp, ComponentType, Class, DefectCode, Result, Confidence, CycleTimeMs, GateUsed
        FROM InspectionResults
        ORDER BY Id DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return [dict(row) for row in rows]

@app.get("/api/inspections/search", tags=["검사"])
def search_inspections(
    component_type: str = None,
    class_: str = None,
    result: str = None,
    limit: int = 100
):
    """검사 이력 검색 (필터)"""
    conn = get_db()
    query = "SELECT * FROM InspectionResults WHERE 1=1"
    params = []

    if component_type:
        query += " AND ComponentType = ?"
        params.append(component_type)
    if class_:
        query += " AND Class = ?"
        params.append(class_)
    if result:
        query += " AND Result = ?"
        params.append(result)

    query += " ORDER BY Id DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(row) for row in rows]

# =====================
# REST API — 통계
# =====================
@app.get("/api/stats", tags=["통계"])
def get_stats():
    """전체 검사 통계"""
    conn = get_db()

    total = conn.execute("SELECT COUNT(*) FROM InspectionResults").fetchone()[0]
    pass_count = conn.execute("SELECT COUNT(*) FROM InspectionResults WHERE Result = 'PASS'").fetchone()[0]
    defect_count = conn.execute("SELECT COUNT(*) FROM InspectionResults WHERE Result = 'DEFECT'").fetchone()[0]

    pass_rate = round(pass_count / total * 100, 1) if total > 0 else 0

    # 클래스별 카운트
    class_counts = {}
    for row in conn.execute("SELECT Class, COUNT(*) as cnt FROM InspectionResults GROUP BY Class").fetchall():
        class_counts[row[0]] = row[1]

    # 불량 유형별 카운트
    defect_counts = {}
    for row in conn.execute("""
        SELECT DefectCode, COUNT(*) as cnt
        FROM InspectionResults
        WHERE Result = 'DEFECT'
        GROUP BY DefectCode
    """).fetchall():
        defect_counts[row[0]] = row[1]

    # 부품별 카운트
    component_counts = {}
    for row in conn.execute("SELECT ComponentType, COUNT(*) as cnt FROM InspectionResults GROUP BY ComponentType").fetchall():
        component_counts[row[0]] = row[1]

    conn.close()

    return {
        "total": total,
        "pass_count": pass_count,
        "defect_count": defect_count,
        "pass_rate": pass_rate,
        "class_counts": class_counts,
        "defect_counts": defect_counts,
        "component_counts": component_counts
    }

@app.get("/api/stats/spc", tags=["통계"])
def get_spc():
    """SPC 분석 (Cp/Cpk)"""
    conn = get_db()
    rows = conn.execute("SELECT Confidence FROM InspectionResults").fetchall()
    conn.close()

    if not rows:
        return {"error": "데이터 없음"}

    import numpy as np
    data = np.array([r[0] for r in rows])
    mean = float(np.mean(data))
    std = float(np.std(data))
    usl, lsl = 1.0, 0.85

    if std == 0:
        return {"mean": mean, "std": 0, "Cp": 0, "Cpk": 0}

    cp = round((usl - lsl) / (6 * std), 4)
    cpu = (usl - mean) / (3 * std)
    cpl = (mean - lsl) / (3 * std)
    cpk = round(min(cpu, cpl), 4)

    return {
        "mean": round(mean, 4),
        "std": round(std, 4),
        "Cp": cp,
        "Cpk": cpk,
        "count": len(data)
    }

# =====================
# REST API — 제어
# =====================
@app.post("/api/vision/start", tags=["제어"])
def vision_start():
    """카메라 비전 시작 명령"""
    mqtt_client.publish("factory/visipick/vision/cmd", json.dumps({"action": "start"}))
    return {"result": "started"}

@app.post("/api/vision/stop", tags=["제어"])
def vision_stop():
    """카메라 비전 중지 명령"""
    mqtt_client.publish("factory/visipick/vision/cmd", json.dumps({"action": "stop"}))
    return {"result": "stopped"}

@app.post("/api/conveyor/start", tags=["제어"])
def conveyor_start():
    """컨베이어 시작 명령"""
    mqtt_client.publish("factory/visipick/conveyor/cmd", json.dumps({"action": "start"}))
    return {"result": "started"}

@app.post("/api/conveyor/stop", tags=["제어"])
def conveyor_stop():
    """컨베이어 중지 명령"""
    mqtt_client.publish("factory/visipick/conveyor/cmd", json.dumps({"action": "stop"}))
    return {"result": "stopped"}

# =====================
# REST API — 시스템 이벤트
# =====================
@app.get("/api/events", tags=["이벤트"])
def get_events(limit: int = 100):
    """시스템 이벤트 조회"""
    conn = get_db()
    rows = conn.execute("""
        SELECT Id, Timestamp, Source, EventType, Message
        FROM SystemEvents
        ORDER BY Id DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return [dict(row) for row in rows]

# =====================
# 실행
# =====================
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
