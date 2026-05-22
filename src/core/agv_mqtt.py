import json, threading
import paho.mqtt.client as mqtt
from datetime import datetime
from src.utils.logger import setup_logger
from src.utils.config_loader import config
from src.core.db import save_agv_mission, save_system_event

logger = setup_logger("agv_mqtt")

BROKER    = config["mqtt"]["broker"]
PORT      = config["mqtt"]["port"]
WAREHOUSE = config["agv"]["nodes"]["warehouse"]

# 진행 중인 미션: {agv_id: {"source":..., "destination":..., "recipe_session_id":...}}
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
        """도착 이벤트: 미션 기록 DB 저장."""
        with _lock:
            mission = _pending.pop(agv_id, {})

        source           = mission.get("source", "N1")
        destination      = mission.get("destination", node)
        recipe_session_id = mission.get("recipe_session_id")

        save_agv_mission(agv_id, source, destination, recipe_session_id)
        save_system_event("AGV", "INFO", f"AGV {agv_id} 도착: {node}")
        logger.info(f"AGV {agv_id} 도착 완료 — {source}→{destination}")

    # ── 공개 API ────────────────────────────────────────────────────────────

    def dispatch(self, agv_id: int, source: str = "N1",
                 recipe_session_id: int = None):
        """
        AGV 이동 명령 발행. 목적지는 항상 WAREHOUSE.
        """
        with _lock:
            _pending[agv_id] = {
                "source":           source,
                "destination":      WAREHOUSE,
                "recipe_session_id": recipe_session_id,
            }

        payload = {
            "type":        "agv_cmd",
            "agv_id":      agv_id,
            "destination": WAREHOUSE,
            "timestamp":   datetime.now().isoformat(),
        }
        self._client.publish(
            f"visipick/agv/{agv_id}/command",
            json.dumps(payload, ensure_ascii=False),
        )
        logger.info(f"AGV {agv_id} 명령 발행: {source} → {WAREHOUSE}")

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
