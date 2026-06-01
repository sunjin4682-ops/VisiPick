import json, threading, asyncio as _asyncio
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse, Response
from fastapi.middleware.cors import CORSMiddleware
import paho.mqtt.client as mqtt
import uvicorn
from src.utils.config_loader import config
from src.core import frame_bus
from src.core.db import (
    get_inspections, get_inspections_search,
    get_stats, get_events,
    get_sessions, get_current_session,
    get_agv_missions,
)
from src.core.agv_mqtt import get_manager as get_agv_manager
import asyncio

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

main_loop = None

@app.on_event("startup")
async def _capture_loop():
    global main_loop
    main_loop = asyncio.get_running_loop()

def on_mqtt_message(client, userdata, msg):
    try:
        data = json.loads(msg.payload.decode())
        data["_topic"] = msg.topic
        if main_loop is not None:
            asyncio.run_coroutine_threadsafe(broadcast(data), main_loop)
    except Exception:
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
            # 수신 전용 — 들어온 메시지는 무시(제어는 REST만 허용). 연결 유지/끊김 감지용.
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_clients.remove(websocket)

# =====================
# 영상 — MJPEG 스트림 (V6.4: 영상=MJPEG, 제어 채널과 분리)
# =====================
STREAM_FPS = config.get("stream", {}).get("fps", 10)
_BOUNDARY = "frame"

async def _mjpeg_generator(name: str):
    """프레임 버스의 최신 JPEG 를 multipart/x-mixed-replace 로 연속 송출."""
    interval = 1.0 / max(STREAM_FPS, 1)
    while True:
        jpeg = frame_bus.read_jpeg(name)
        if jpeg:
            yield (b"--" + _BOUNDARY.encode() + b"\r\n"
                   b"Content-Type: image/jpeg\r\n"
                   b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
                   + jpeg + b"\r\n")
        await _asyncio.sleep(interval)

@app.get("/video/{name}", tags=["영상"])
def video_stream(name: str):
    """카메라 MJPEG 스트림. name = top(상부) | side(측면).
    WPF/브라우저의 <Image>/<img> src 로 바로 사용."""
    return StreamingResponse(
        _mjpeg_generator(name),
        media_type=f"multipart/x-mixed-replace; boundary={_BOUNDARY}",
    )

@app.get("/snapshot/{name}", tags=["영상"])
def snapshot(name: str):
    """카메라 최신 1프레임(JPEG). 스냅샷/썸네일용."""
    jpeg = frame_bus.read_jpeg(name)
    if not jpeg:
        return Response(status_code=503, content=b"no frame")
    return Response(content=jpeg, media_type="image/jpeg")

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

@app.post("/api/emergency_stop", tags=["제어"])
def emergency_stop():
    """비상정지 — 컨베이어·게이트 큐 즉시 정지, state_machine EMERGENCY_STOP 전이"""
    mqtt_client.publish("visipick/system/cmd", json.dumps({
        "action":    "stop",
        "timestamp": datetime.now().isoformat(),
    }))
    return {"result": "emergency_stop_requested"}

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
