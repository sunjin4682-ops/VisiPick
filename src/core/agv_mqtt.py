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
WAREHOUSE = config["agv"]["nodes"]["warehouse"]   # "WAREHOUSE"

# 진행 중인 미션: {agv_id(int): {"source","destination","recipe_session_id","phase"}}
#   phase: "outbound"(→창고) | "returning"(창고→홈 복귀)
_pending: dict[int, dict] = {}
# 현재 AGV 상태 캐시: {agv_id(int): {status, next_action, node, ...}}
_status: dict[int, dict] = {}
# 홈 도킹 슬롯 점유 현황(마스터 권위): {home_id(1/2/3): agv_id 점유 or None=비어있음}
_home_occupancy: dict[int, int | None] = {1: None, 2: None, 3: None}
_lock = threading.Lock()

# 전체 AGV ID 목록(브로드캐스트 대상)
ALL_AGV_IDS = list(range(1, config["agv"]["count"] + 1))


def _parse_agv_id(raw) -> int:
    """ESP32가 보내는 "AGV_1" 형식을 int 1로 변환."""
    try:
        if isinstance(raw, int):
            return raw
        # "AGV_1" → 1
        return int(str(raw).replace("AGV_", "").strip())
    except Exception:
        return 0


class AGVMqttManager:
    """
    AGV MQTT pub/sub 매니저.
    - 구독: visipick/agv/+/status
    - 발행: visipick/agv/{id}/command

    ESP32 펌웨어 동작 방식:
      1. GO_WAREHOUSE_1 or GO_WAREHOUSE_2 → 목적지 설정 (아직 출발 안 함)
      2. TRAYS_READY_3                    → 트레이 3개 적재 완료 → 출발 (출발점서 한바퀴 회전 후 이동)
      3. 창고 도착 → 5초 대기 → 자동 회전 → 자동 복귀 홈 (UNLOAD/GO_N1 불필요)
      4. 상태 JSON: {"agv_id":"AGV_1","status":"...","next_action":"...","node":"..."}
         arrived 감지: next_action == "ARRIVED_WAREHOUSE_1" / "ARRIVED_WAREHOUSE_2"
         홈 복귀 완료: next_action == "ARRIVED_HOME"
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

        agv_id      = _parse_agv_id(data.get("agv_id"))
        status      = data.get("status")        # ESP32: "status" 키
        next_action = data.get("next_action")
        node        = data.get("node")

        # ── AGV 펌웨어 형식 정규화 (AGV2 대응) ────────────────────────────────
        #   AGV1 은 node/next_action 을 직접 보내지만, AGV2 펌웨어는 위치를 status
        #   문자열("AT_START"/"HOME_1_DONE"/"ARRIVED_WH1"...)로만 보낸다. 공통 로직
        #   (get_agv_at_start=node, _on_home_arrived=next_action+selected_home)이
        #   동작하도록 변환한다. node 가 이미 있으면(AGV1) 그대로 둔다.
        #   node 는 sticky — 위치 이벤트가 없는 status(IDLE/STANDBY 하트비트)면 직전
        #   위치를 유지한다(AGV2 는 도착 순간만 1회 보고하므로).
        if node is None:
            sa = (status or "").upper()
            prev_node = _status.get(agv_id, {}).get("node")
            if sa == "AT_START":
                node = "START"
            elif sa.startswith("HOME_") and sa.endswith("_DONE"):
                node = "HOME_JUNCTION"
                next_action = "ARRIVED_HOME"
                try:
                    data["selected_home"] = int(sa.split("_")[1])
                except Exception:
                    pass
            elif sa.startswith("ARRIVED_WH"):
                next_action = "ARRIVED_WAREHOUSE_" + sa[-1]
                node = None
            elif sa in ("MISSION_WH1", "MISSION_WH2", "GOING_START", "U_TURN",
                        "RETURNING", "TRAYS_READY", "LEAVE_HOME1", "LEAVE_HOME2",
                        "LEAVE_HOME3", "STOPPED", "PENDING_WH1", "PENDING_WH2"):
                node = None              # 출발점/홈을 떠남 → 위치 해제
            else:
                node = prev_node          # IDLE/STANDBY/기타 → 직전 위치 유지(sticky)

        with _lock:
            prev_action = _status.get(agv_id, {}).get("next_action")
            _status[agv_id] = {
                "status":      status,
                "next_action": next_action,
                "node":        node,
                "timestamp":   data.get("timestamp", datetime.now().isoformat()),
                "raw":         data,
            }

        logger.debug(f"AGV {agv_id} 상태: {status} / next_action={next_action} @ {node}")

        # ── 도착 이벤트는 '엣지(상태 변화)' 에서만 처리 ──────────────────────
        #   AGV 가 홈/창고에 정지한 채 같은 next_action(예: ARRIVED_HOME)을 계속
        #   발행한다. 매 메시지마다 도착 처리하면 HOME_BUSY 브로드캐스트가 무한 반복
        #   → 브로커·AGV 폭주. next_action 이 직전과 '바뀌었을 때만' 1회 처리한다.
        if next_action == prev_action:
            return

        # 창고 도착 감지
        if next_action in ("ARRIVED_WAREHOUSE_1", "ARRIVED_WAREHOUSE_2"):
            warehouse_num = 1 if next_action == "ARRIVED_WAREHOUSE_1" else 2
            self._on_warehouse_arrived(agv_id, warehouse_num)

        # 홈 복귀 완료 감지
        elif next_action == "ARRIVED_HOME":
            self._on_home_arrived(agv_id)

        # START 도착 감지 (홈을 비우고 시작점 복귀 — 핸드오버 가이드 LEAVE_HOMEx_TO_START 흐름)
        elif next_action == "ARRIVED_START":
            self._on_start_arrived(agv_id)

    def _on_start_arrived(self, agv_id: int):
        """AGV가 홈을 비우고 START 위치에 도착 → 점유 중이던 홈을 FREE 로 해제.

        문서(WPF 핸드오버 가이드)의 `LEAVE_HOME{n}_TO_START` → `ARRIVED_START` 흐름 대응.
        홈 슬롯 권한은 Python 유지이므로, AGV가 홈을 떠나 START 에 닿으면 그 홈을 비운다.
        """
        with _lock:
            freed = next((h for h, owner in _home_occupancy.items()
                          if owner == agv_id), None)
        if freed is not None:
            self._mark_home_free(freed)
            save_system_event("AGV", "INFO", f"AGV {agv_id} START 도착 — 홈{freed} FREE")
            logger.info(f"AGV {agv_id} START 도착 — 홈{freed} 슬롯 해제")
        else:
            save_system_event("AGV", "INFO", f"AGV {agv_id} START 도착 (점유 홈 없음)")
            logger.info(f"AGV {agv_id} START 도착 (점유 홈 없음)")

    def _on_warehouse_arrived(self, agv_id: int, warehouse_num: int):
        """창고 도착 처리. ESP32가 5초 후 자동 복귀하므로 UNLOAD/GO 명령 불필요."""
        with _lock:
            mission = _pending.get(agv_id)

        destination = f"WAREHOUSE_{warehouse_num}"

        if not mission:
            save_system_event("AGV", "INFO", f"AGV {agv_id} 창고{warehouse_num} 도착 (미등록 미션)")
            logger.info(f"AGV {agv_id} 창고{warehouse_num} 도착 (미등록 미션)")
            return

        # 미션 DB 기록
        save_agv_mission(agv_id, mission["source"], destination,
                         mission.get("recipe_session_id"))
        save_system_event("AGV", "INFO",
                          f"AGV {agv_id} 창고{warehouse_num} 도착 — 자동 복귀 대기 중")
        logger.info(f"AGV {agv_id} 창고{warehouse_num} 도착 — ESP32 자동 복귀(5초 대기 후)")

        with _lock:
            if agv_id in _pending:
                _pending[agv_id]["phase"] = "returning"

    def _on_home_arrived(self, agv_id: int):
        """홈 복귀 완료 처리.

        AGV가 점유한 홈(status.selected_home)을 마스터 점유표에 BUSY로 기록하고
        전체 AGV에 HOME{n}_BUSY 브로드캐스트(다른 AGV의 동일 홈 선택 차단).
        """
        with _lock:
            _pending.pop(agv_id, None)
            home_id = _status.get(agv_id, {}).get("raw", {}).get("selected_home", 0)

        if home_id in (1, 2, 3):
            self._mark_home_busy(home_id, agv_id)
            save_system_event("AGV", "INFO",
                              f"AGV {agv_id} 홈{home_id} 도킹 — 슬롯 BUSY")
            logger.info(f"AGV {agv_id} 홈{home_id} 복귀 완료 — 슬롯 점유")
        else:
            save_system_event("AGV", "INFO", f"AGV {agv_id} 홈 복귀 완료 — 대기")
            logger.info(f"AGV {agv_id} 홈 복귀 완료 (홈 번호 미보고) — 다음 미션 대기")

    # ── 홈 슬롯 점유표(마스터 권위) ───────────────────────────────────────
    def _mark_home_busy(self, home_id: int, agv_id: int):
        """홈 슬롯을 점유 처리하고 전체 AGV에 BUSY 브로드캐스트."""
        with _lock:
            _home_occupancy[home_id] = agv_id
        for aid in ALL_AGV_IDS:
            self._command(aid, f"HOME{home_id}_BUSY")
        logger.info(f"홈{home_id} BUSY (점유: AGV {agv_id}) — 전체 브로드캐스트")

    def _mark_home_free(self, home_id: int):
        """홈 슬롯을 비움 처리하고 전체 AGV에 FREE 브로드캐스트.
        대기 중(RETURN_NO_FREE_HOME_WAIT)인 AGV가 있으면 그 홈으로 자동 출발한다."""
        with _lock:
            _home_occupancy[home_id] = None
        for aid in ALL_AGV_IDS:
            self._command(aid, f"HOME{home_id}_FREE")
        logger.info(f"홈{home_id} FREE — 전체 브로드캐스트")

    # ── 공개 API ────────────────────────────────────────────────────────────

    def _command(self, agv_id: int, payload: str):
        """AGV 명령 1건 발행 (visipick/agv/{id}/command). payload는 plain string."""
        self._client.publish(f"visipick/agv/{agv_id}/command", payload)
        logger.info(f"AGV {agv_id} 명령 발행: {payload}")

    def dispatch(self, agv_id: int, source: str = None,
                 recipe_session_id: int = None):
        """완성 트레이 운반 명령 (트레이 3개 적재 완료 시점에 호출).
        1) GO_WAREHOUSE_1 or GO_WAREHOUSE_2 → 목적지 설정 (대기)
        2) TRAYS_READY_3                    → 3개 적재 완료 → 출발 허가
        ESP32가 창고 도착 후 5초 대기 → 자동 복귀하므로 추가 명령 불필요.
        """
        source = source or START
        # AGV 1 → WAREHOUSE_1, AGV 2 → WAREHOUSE_2
        destination = f"{WAREHOUSE}_{agv_id}"

        # 이 AGV가 점유 중이던 홈 슬롯을 비움 → 대기 중인 다른 AGV가 그 홈으로 출발 가능
        with _lock:
            freed_home = next((h for h, owner in _home_occupancy.items()
                               if owner == agv_id), None)
        if freed_home is not None:
            self._mark_home_free(freed_home)

        with _lock:
            _pending[agv_id] = {
                "source":            source,
                "destination":       destination,
                "recipe_session_id": recipe_session_id,
                "phase":             "outbound",
            }

        self._command(agv_id, f"GO_{destination}")   # 목적지 설정 (아직 출발 안 함)
        self._command(agv_id, "TRAYS_READY_3")        # 트레이 3개 적재 완료 → 출발 허가
        logger.info(f"AGV {agv_id} 출고 명령: {source} → {destination}")

        # 출발점 AGV 출발 직후 → 홈에 대기 중인 다른 AGV를 출발점으로 호출(다음 적재 준비).
        #   LEAVE_HOME{n}_TO_START — 홈 슬롯 번호별 경로. 출발 AGV를 제외한, 홈에 도킹
        #   중인 AGV(들)에게 전송. (둘 다 출발점 비면 다음 트레이 적재가 멈추는 것 방지)
        with _lock:
            home_agvs = [(h, a) for h, a in _home_occupancy.items()
                         if a is not None and a != agv_id]
        for home_id, home_agv in home_agvs:
            self.leave_home_to_start(home_agv, home_id)
            logger.info(f"AGV {home_agv} 홈{home_id} → 출발점 호출 (다음 적재 준비)")

    def emergency_stop(self, agv_id: int = None):
        """비상정지. agv_id=None 이면 전체(1·2) 발행."""
        ids = [agv_id] if agv_id else [1, 2]
        for aid in ids:
            self._command(aid, "EMERGENCY_STOP")

    def emergency_clear(self, agv_id: int = None):
        """비상정지 해제."""
        ids = [agv_id] if agv_id else [1, 2]
        for aid in ids:
            self._command(aid, "EMERGENCY_CLEAR")

    # ── START 복귀 / 홈 비우기 (핸드오버 가이드 명령) ──────────────────────
    def go_start(self, agv_id: int):
        """AGV 를 START 위치로 복귀. 펌웨어: GO_START / LEAVE_HOME_TO_START(기본 경로)."""
        self._command(agv_id, "GO_START")

    def leave_home_to_start(self, agv_id: int, home_id: int = None):
        """홈에서 START 로 비켜나는 핸드오버 명령. home_id 지정 시 홈별 경로(커브 타이밍) 적용.
        펌웨어: LEAVE_HOME1/2/3_TO_START (홈마다 회전·커브 다름), 미지정 시 LEAVE_HOME_TO_START.
        AGV가 START 도착하면 status next_action=ARRIVED_START → _on_start_arrived 가 홈 FREE 처리.
        """
        cmd = f"LEAVE_HOME{home_id}_TO_START" if home_id in (1, 2, 3) else "LEAVE_HOME_TO_START"
        self._command(agv_id, cmd)

    # ── 홈(도킹) 슬롯 관리 ─────────────────────────────────────────────────
    def go_home(self, agv_id: int, home_id: int):
        """특정 홈(1/2/3)으로 복귀 명령. 펌웨어: GO_HOME_1/2/3."""
        self._command(agv_id, f"GO_HOME_{home_id}")

    def set_home_free(self, home_id: int, free: bool = True, agv_id: int = None):
        """홈 슬롯 비움/점유를 마스터 점유표에 반영 + 전체 AGV 브로드캐스트.
        free=True  → 마스터에서 비움 처리, 전체에 HOME{n}_FREE (대기 AGV 자동 출발).
        free=False → agv_id 점유로 기록, 전체에 HOME{n}_BUSY.
        주로 로봇이 홈의 트레이를 비웠을 때 set_home_free(n, True) 로 호출한다.
        """
        if free:
            self._mark_home_free(home_id)
        else:
            self._mark_home_busy(home_id, agv_id or 0)

    def get_home_occupancy(self) -> dict:
        """마스터 권위 홈 점유표 반환 {home_id: agv_id or None}."""
        with _lock:
            return dict(_home_occupancy)

    def clear_mission(self, agv_id: int):
        """AGV 미션/상태 초기화. 펌웨어: CLEAR_MISSION."""
        self._command(agv_id, "CLEAR_MISSION")

    def request_status(self, agv_id: int):
        """AGV 상태 즉시 publish 요청. 펌웨어: STATUS."""
        self._command(agv_id, "STATUS")

    def get_status(self, agv_id: int = None) -> dict:
        """현재 AGV 상태 반환. agv_id=None 이면 전체 딕셔너리."""
        with _lock:
            if agv_id is None:
                return dict(_status)
            return dict(_status.get(agv_id, {}))

    def get_agv_at_start(self) -> int | None:
        """출발점(START)에 와있는 AGV id 반환 — 출발점 RFID로 인식된 '지금 적재받는'
        AGV. status 의 node 가 START 인 AGV. 없으면 None.
        (둘 다 START 면 가장 최근 보고한 AGV — 보통 한 대만 출발점에 있음)"""
        with _lock:
            cands = [(aid, st.get("timestamp", "")) for aid, st in _status.items()
                     if st.get("node") == START]
        if not cands:
            return None
        # 여러 대가 START 보고 시 가장 최근 타임스탬프 (정상 운영선 한 대뿐)
        return max(cands, key=lambda x: x[1])[0]

    def get_home_free(self, agv_id: int) -> dict:
        """AGV가 보고한 홈 슬롯 점유 현황 반환 {1:bool,2:bool,3:bool}.
        펌웨어 status JSON 의 home1_free/home2_free/home3_free 에서 읽는다.
        """
        with _lock:
            raw = _status.get(agv_id, {}).get("raw", {})
        return {
            1: bool(raw.get("home1_free", False)),
            2: bool(raw.get("home2_free", False)),
            3: bool(raw.get("home3_free", False)),
        }

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
