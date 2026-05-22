import json, threading
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import paho.mqtt.client as mqtt
import uvicorn
from src.utils.config_loader import config
from src.core.db import (
    get_inspections, get_inspections_search,
    get_stats, get_events,
    get_sessions, get_current_session,
    get_agv_missions,
)
from src.core.agv_mqtt import get_manager as get_agv_manager

BROKER = config["mqtt"]["broker"]
PORT   = config["mqtt"]["port"]

# =====================
# FastAPI 앱
# =====================
app = FastAPI(
    title="VisiPick API",
    description="스마트팩토리 VisiPick 시스템 REST API + WebSocket",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

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
mqtt_client.subscribe("visipick/#")
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
            msg = json.loads(data)
            topic = msg.get("topic", "visipick/system/event")
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
def api_get_inspections(limit: int = 100):
    """검사 이력 조회 (최근 N건)"""
    return get_inspections(limit)

@app.get("/api/inspections/search", tags=["검사"])
def api_search_inspections(
    part_type: str = None,
    classification: str = None,
    limit: int = 100,
):
    """검사 이력 검색 (필터): part_type, classification(NEEDED/DUPLICATE/DEFECT)"""
    return get_inspections_search(part_type, classification, limit)

# =====================
# REST API — 통계
# =====================
@app.get("/api/stats", tags=["통계"])
def api_get_stats():
    """전체 검사 통계"""
    return get_stats()

@app.get("/api/stats/spc", tags=["통계"])
def api_get_spc():
    """SPC 분석 (Cp/Cpk)"""
    from src.core.spc_analysis import load_data, calc_spc
    df = load_data()
    if df.empty:
        return {"error": "데이터 없음"}
    return {
        **calc_spc(df["Confidence"], usl=1.0, lsl=0.85),
        "count": len(df),
    }

# =====================
# REST API — 레시피 세션
# =====================
@app.get("/api/sessions", tags=["세션"])
def api_get_sessions(limit: int = 50):
    """레시피 세션 이력 조회"""
    return get_sessions(limit)

@app.get("/api/sessions/current", tags=["세션"])
def api_get_current_session():
    """현재 진행 중인 레시피 세션"""
    session = get_current_session()
    if session is None:
        return {"status": "없음"}
    return session

# =====================
# REST API — AGV
# =====================
@app.get("/api/agv/status", tags=["AGV"])
def api_agv_status():
    """전체 AGV 현재 상태"""
    return get_agv_manager().get_status()

@app.get("/api/agv/missions", tags=["AGV"])
def api_agv_missions(limit: int = 100):
    """AGV 미션 이력 조회"""
    return get_agv_missions(limit)

# =====================
# REST API — 제어
# =====================
@app.post("/api/vision/start", tags=["제어"])
def vision_start():
    """카메라 비전 시작 명령"""
    mqtt_client.publish("visipick/vision/cmd", json.dumps({"action": "start"}))
    return {"result": "started"}

@app.post("/api/vision/stop", tags=["제어"])
def vision_stop():
    """카메라 비전 중지 명령"""
    mqtt_client.publish("visipick/vision/cmd", json.dumps({"action": "stop"}))
    return {"result": "stopped"}

@app.post("/api/conveyor/start", tags=["제어"])
def conveyor_start():
    """컨베이어 시작 명령"""
    mqtt_client.publish("visipick/conveyor/cmd", json.dumps({"action": "start"}))
    return {"result": "started"}

@app.post("/api/conveyor/stop", tags=["제어"])
def conveyor_stop():
    """컨베이어 중지 명령"""
    mqtt_client.publish("visipick/conveyor/cmd", json.dumps({"action": "stop"}))
    return {"result": "stopped"}

# =====================
# REST API — 시스템 이벤트
# =====================
@app.get("/api/events", tags=["이벤트"])
def api_get_events(limit: int = 100):
    """시스템 이벤트 조회"""
    return get_events(limit)

# =====================
# 실행
# =====================
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
