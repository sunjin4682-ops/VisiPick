import json, threading
import paho.mqtt.client as mqtt
from datetime import datetime
from src.utils.logger import setup_logger
from src.utils.config_loader import config
from src.core.db import save_agv_mission, save_system_event

logger = setup_logger("agv_mqtt")

BROKER    = config["mqtt"]["broker"]
PORT      = config["mqtt"]["port"]
START     = config["agv"]["nodes"]["start"]       # 기본 대기/출발 노드 (N1)
WAREHOUSE = config["agv"]["nodes"]["warehouse"]

# 진행 중인 미션: {agv_id: {"source","destination","recipe_session_id","phase"}}
#   phase: "outbound"(→창고) | "returning"(창고→N1 복귀)
_pending: dict[int, dict] = {}
# 현재 AGV 상태 캐시: {agv_id: {"state":..., "node":..., "timestamp":...}}
_status: dict[int, dict] = {}
_lock = threading.Lock()


class AGVMqttManager:
    """
    AGV MQTT pub/sub 매니저.
    - 구독: visipick/agv/+/status
    - 발행: visipick/agv/{id}/command
    - 도착 감지 → DB 저장 (save_agv_mission, save_system_event)
    """

    def __init__(self):
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.connect(BROKER, PORT)
        self._client.loop_start()
        logger.info(f"AGV MQTT 매니저 시작: {BROKER}:{PORT}")

    # ── MQTT 콜백 ──────────────────────────────────────────────────────────

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        client.subscribe("visipick/agv/+/status")
        logger.info("AGV 상태 구독: visipick/agv/+/status")

    def _on_message(self, client, userdata, msg):
        try:
            data = json.loads(msg.payload.decode())
        except Exception:
            return

        agv_id = data.get("agv_id")
        state  = data.get("state")
        node   = data.get("node")

        with _lock:
            _status[agv_id] = {
                "state":     state,
                "node":      node,
                "timestamp": data.get("timestamp", datetime.now().isoformat()),
            }

        logger.debug(f"AGV {agv_id} 상태: {state} @ {node}")

        if state == "arrived":
            self._on_arrived(agv_id, node)

    def _on_arrived(self, agv_id: int, node: str):
        """도착 이벤트 처리.

        창고 도착(outbound) → 하역 명령 + N1 복귀 dispatch (C2).
        N1 복귀 도착(returning) → 미션 종료(대기 상태).
        미등록 도착(수동 명령 등)은 이벤트만 남긴다.
        """
        with _lock:
            mission = _pending.get(agv_id)

        if not mission:
            save_system_event("AGV", "INFO", f"AGV {agv_id} 도착: {node}")
            logger.info(f"AGV {agv_id} 도착(미등록 미션): {node}")
            return

        if mission.get("phase") == "outbound":
            # 창고 도착 = 트레이 배달 완료 → 미션 기록 + 하역 + 복귀 dispatch
            save_agv_mission(agv_id, mission["source"], mission["destination"],
                             mission.get("recipe_session_id"))
            save_system_event("AGV", "INFO",
                              f"AGV {agv_id} 창고 도착 — 하역 후 {START} 복귀")
            logger.info(f"AGV {agv_id} 창고 도착 — 하역 명령 + {START} 복귀 dispatch")
            self._command(agv_id, action="UNLOAD")              # 지게 서보 쏟아내기
            self._command(agv_id, action="GO", destination=START)
            with _lock:
                mission["phase"]       = "returning"
                mission["source"]      = mission["destination"]
                mission["destination"] = START
        else:  # "returning"
            with _lock:
                _pending.pop(agv_id, None)
            save_system_event("AGV", "INFO", f"AGV {agv_id} {node} 복귀 완료 — 대기")
            logger.info(f"AGV {agv_id} {START} 복귀 완료 — 다음 미션 대기")

    # ── 공개 API ────────────────────────────────────────────────────────────

    def _command(self, agv_id: int, action: str, destination: str | None = None):
        """AGV 명령 1건 발행 (visipick/agv/{id}/command)."""
        payload = {
            "type":      "agv_cmd",
            "agv_id":    agv_id,
            "action":    action,
            "timestamp": datetime.now().isoformat(),
        }
        if destination is not None:
            payload["destination"] = destination
        self._client.publish(
            f"visipick/agv/{agv_id}/command",
            json.dumps(payload, ensure_ascii=False),
        )

    def dispatch(self, agv_id: int, source: str = None,
                 recipe_session_id: int = None):
        """완성 트레이 운반 명령. 목적지=창고, 도착 후 자동으로 하역+N1 복귀까지 진행."""
        source = source or START
        with _lock:
            _pending[agv_id] = {
                "source":            source,
                "destination":       WAREHOUSE,
                "recipe_session_id": recipe_session_id,
                "phase":             "outbound",
            }
        self._command(agv_id, action="GO", destination=WAREHOUSE)
        logger.info(f"AGV {agv_id} 출고 명령: {source} → {WAREHOUSE}")

    def get_status(self, agv_id: int = None) -> dict:
        """
        현재 AGV 상태 반환.
        agv_id 지정 시 해당 AGV만, None 이면 전체 딕셔너리 반환.
        """
        with _lock:
            if agv_id is None:
                return dict(_status)
            return dict(_status.get(agv_id, {}))

    def stop(self):
        self._client.loop_stop()
        logger.info("AGV MQTT 매니저 종료")


# ── 모듈 레벨 싱글톤 ──────────────────────────────────────────────────────────

_manager: AGVMqttManager | None = None


def get_manager() -> AGVMqttManager:
    """모듈 전체에서 공유하는 AGVMqttManager 인스턴스 반환."""
    global _manager
    if _manager is None:
        _manager = AGVMqttManager()
    return _manager
