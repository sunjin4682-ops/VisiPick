import time, json, threading
from collections import deque
from datetime import datetime
from enum import Enum
import paho.mqtt.client as mqtt

from src.utils.logger import setup_logger
from src.utils.config_loader import config
from src.vision.camera_top import CameraTop
from src.vision.camera_side import CameraSide
from src.vision.classifier import Classifier
from src.vision.pin_inspector import PinInspector
from src.orchestrator.decision import Decision, gate_action_for, verdict_to_label, defect_code_for
from src.utils.part_map import to_korean
from src.orchestrator.recipe_mgr import RecipeManager
from src.orchestrator.tray_mgr import TrayManager
from src.devices.robot import Robot
from src.devices.serial_ctrl import SerialController
from src.core.agv_mqtt import get_manager as get_agv_manager
from src.core.db import save_inspection, save_recipe_session, complete_recipe_session

logger = setup_logger("statemachine")

BROKER         = config["mqtt"]["broker"]
MQTT_PORT      = config["mqtt"]["port"]
DUMMY_MODE     = config["vision"]["dummy_mode"]
TOTAL_CYCLES   = config["system"]["demo_cycles"]
DUMMY_INTERVAL = config["vision"]["dummy_interval_sec"]
AGV_COUNT      = config["agv"]["count"]
AGV_START      = config["agv"]["nodes"]["start"]
RECIPE_PARTS   = config["recipe"]["parts"]
CONVEYOR_SPEED = config["conveyor"]["speed_cm_per_s"]

_conv_cfg    = config.get("conveyor", {})
_speed       = _conv_cfg.get("speed_cm_per_s", 1.5)
GATE1_DELAY  = _conv_cfg.get("camera_to_gate1_cm", 30) / _speed
GATE2_DELAY  = _conv_cfg.get("camera_to_gate2_cm", 45) / _speed
DEBOUNCE_SEC = config.get("sensor", {}).get("debounce_sec", 0.5)


class State(Enum):
    IDLE           = "IDLE"
    RUNNING        = "RUNNING"
    TRAY_TRANSFER  = "TRAY_TRANSFER"
    COMPLETE       = "COMPLETE"
    ERROR          = "ERROR"
    EMERGENCY_STOP = "EMERGENCY_STOP"


class VisiPickStateMachine:
    def __init__(self):
        self.state       = State.IDLE
        self.cycle       = 0
        self._session_id = None
        self._inspect_enabled = True
        self._running        = True
        self._stop_requested = threading.Event()

        # 센서 디바운스
        self._last_trigger = 0.0
        self._sensor_lock  = threading.Lock()

        # 게이트 지연 큐
        self._gate_queue = deque()
        self._gate_lock  = threading.Lock()

        # 검사 중복 방지 (이전 검사가 끝나기 전에 새 트리거 무시)
        self._inspect_lock = threading.Lock()

        # 비전 (염재니 이식: 상부 분류기 + 측면 핀검사)
        self._cam_top  = CameraTop()
        self._cam_side = CameraSide()
        self._clf      = Classifier()
        self._pin      = PinInspector()

        # 오케스트레이터
        self._recipe = RecipeManager()
        self._tray   = TrayManager()

        # 판정 (염재니 Decision 채택, judge 폐기)
        #  · 부호 함정: is_duplicate=True 가 '중복'. needs()=True 는 '아직 필요' 로 반대 →
        #    반드시 not 으로 감싼다.
        #  · 부품명: 비전은 영문, recipe.needs 는 한글 → to_korean 으로 변환 후 전달.
        self._decider = Decision(
            is_duplicate=lambda p: (p is not None) and (not self._recipe.needs(to_korean(p))),
            min_conf=config["vision"].get("min_conf", 0.40),
        )

        # 디바이스
        self._serial = SerialController(on_sensor=self.on_sensor_triggered)
        self._robot  = Robot()
        self._agv    = get_agv_manager()

        # MQTT — WPF 브로드캐스트 + 제어 명령 구독
        self._mqtt = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self._mqtt.on_message = self._on_mqtt_cmd
        self._mqtt.connect(BROKER, MQTT_PORT)
        for t in ("visipick/system/cmd", "visipick/vision/cmd", "visipick/conveyor/cmd"):
            self._mqtt.subscribe(t)
        self._mqtt.loop_start()

        logger.info("VisiPickStateMachine 초기화 완료")

    # ── MQTT 제어 명령 수신 ────────────────────────────────────
    def _on_mqtt_cmd(self, client, userdata, msg):
        try:
            data   = json.loads(msg.payload.decode())
            action = data.get("action")
            topic  = msg.topic
            if topic == "visipick/system/cmd" and action == "stop":
                self._emergency_stop()
            elif topic == "visipick/vision/cmd":
                self._inspect_enabled = (action == "start")
                logger.info(f"비전 {'시작' if action=='start' else '중지'}")
            elif topic == "visipick/conveyor/cmd":
                self._serial.set_conveyor_speed(CONVEYOR_SPEED if action == "start" else 0.0)
                logger.info(f"컨베이어 {'시작' if action=='start' else '중지'}")
        except Exception:
            pass

    def _emergency_stop(self):
        if self._stop_requested.is_set():
            return
        logger.warning("비상정지 요청")
        self._stop_requested.set()
        self._serial.emergency_stop()       # 컨1·컨2·컨3·게이트 전체 정지
        with self._gate_lock:
            self._gate_queue.clear()
        self._transition(State.EMERGENCY_STOP)
        self._publish_event("System", "WARN", "비상정지 실행")

    # ── 센서 트리거 (public — serial_ctrl 콜백으로 연결 예정) ────
    def on_sensor_triggered(self):
        """투입단 센서 신호 수신 시 호출. 디바운스 + 상태 보호."""
        now = time.time()
        with self._sensor_lock:
            if now - self._last_trigger < DEBOUNCE_SEC:
                return
            self._last_trigger = now

        if self.state != State.RUNNING:
            return

        threading.Thread(target=self._inspect_one, daemon=True).start()

    # ── 게이트 예약 큐 ──────────────────────────────────────────
    def _schedule_gate(self, gate_no: int, delay_sec: float):
        fire_at = time.time() + delay_sec
        with self._gate_lock:
            self._gate_queue.append((fire_at, gate_no))

    def _flush_gate_queue(self):
        """fire_at이 지난 항목만 꺼내 push_gate() 실행."""
        now = time.time()
        fired = []
        with self._gate_lock:
            remaining = deque()
            for fire_at, gate_no in self._gate_queue:
                if fire_at <= now:
                    fired.append(gate_no)
                else:
                    remaining.append((fire_at, gate_no))
            self._gate_queue = remaining
        for gate_no in fired:
            self._serial.push_gate(gate_no)

    # ── 상태 전이 ──────────────────────────────────────────────
    def _transition(self, new_state: State):
        logger.info(f"상태 전이: {self.state.value} → {new_state.value}")
        self.state = new_state
        self._publish("visipick/system/state", {
            "state":     new_state.value,
            "timestamp": datetime.now().isoformat(),
        })

    # ── MQTT 발행 ──────────────────────────────────────────────
    def _publish(self, topic: str, payload: dict):
        self._mqtt.publish(topic, json.dumps(payload, ensure_ascii=False))

    def _publish_event(self, source: str, event_type: str, message: str):
        self._publish("visipick/system/event", {
            "type":       "system_event",
            "source":     source,
            "event_type": event_type,
            "message":    message,
            "timestamp":  datetime.now().isoformat(),
        })

    # ── 부품 1개 검사 (센서 트리거 → 데몬 스레드에서 실행) ────
    def _inspect_one(self):
        if not self._inspect_enabled:
            return
        if not self._inspect_lock.acquire(blocking=False):
            logger.debug("이전 검사 진행 중 — 이번 트리거 무시")
            return
        try:
            t0 = time.time()

            frame_top  = self._cam_top.capture()
            frame_side = self._cam_side.capture()

            # 비전 → 두 딕셔너리 산출 (염재니)
            top  = self._clf.classify_top(frame_top)              # {part, verdict_hint, confidence, raw_class}
            side = self._pin.inspect_side(frame_side, top.get("part"))  # {verdict, pin_count, gap_cv, tip_y_range_px}

            # 판정 — 염재니 Decision 채택 (judge 폐기)
            result = self._decider.evaluate(top, side)
            cls    = verdict_to_label(result.verdict)             # NEEDED | DUPLICATE | DEFECT
            action = gate_action_for(cls)                          # 김선진 게이트 매핑 그대로
            defect = defect_code_for(result, top, side)            # NONE | BENT_PIN | BROKEN | UNKNOWN

            # 부품명: 영문(비전) → 한글(표시/레시피/DB). 단일 변환 지점 = part_map
            part_type  = to_korean(top.get("part")) or "UNKNOWN"
            confidence = round(float(result.confidence), 2)
            cycle_ms   = int((time.time() - t0) * 1000)

            # 게이트 예약 — 부품이 카메라→게이트 구간을 이동하는 시간만큼 지연
            if cls == "DUPLICATE":
                self._schedule_gate(1, GATE1_DELAY)
            elif cls == "DEFECT":
                self._schedule_gate(2, GATE2_DELAY)

            if cls == "NEEDED":
                self._recipe.mark_collected(part_type)
                self._tray.on_part_passed(part_type)

            payload = {
                "timestamp":         datetime.now().isoformat(),
                "recipe_session_id": self._session_id,
                "part_type":         part_type,
                "classification":    cls,
                "defect_code":       defect,
                "confidence":        confidence,
                "gate_action":       action,
                "cycle_time_ms":     cycle_ms,
            }

            save_inspection(payload)
            self._publish("visipick/inspection", payload)
            self._publish_event(
                "Camera", "INFO",
                f"{part_type} → {cls} ({defect})"
            )
            logger.info(f"[검사] {part_type} | {cls} | {defect} | {action} | {cycle_ms}ms")
        finally:
            self._inspect_lock.release()

    # ── 트레이 이송 + AGV 출발 ────────────────────────────────
    def _tray_transfer(self):
        self._transition(State.TRAY_TRANSFER)
        self._publish_event("Robot", "INFO", "트레이 이송 시작")

        ok = self._robot.transfer_tray()
        if not ok:
            raise RuntimeError("로봇 트레이 이송 실패")

        self._serial.advance_tray()
        self._publish_event("Conveyor", "INFO", "컨3 — 다음 빈 트레이 공급 (2초 구동)")

        agv_id = (self.cycle % AGV_COUNT) + 1
        self._agv.dispatch(agv_id, source=AGV_START,
                           recipe_session_id=self._session_id)
        self._publish_event("AGV", "INFO", f"AGV {agv_id} 창고 출발")

        complete_recipe_session(self._session_id, self._tray.get_count())
        logger.info(f"레시피 완료 — 수집 {self._tray.get_count()}개, AGV {agv_id} 출발")

        self._recipe.reset()
        self._tray.reset()

    # ── 더미 센서 트리거 루프 ─────────────────────────────────
    def _start_dummy_trigger(self):
        def _loop():
            while self._running:
                time.sleep(DUMMY_INTERVAL)
                if self._running:
                    self.on_sensor_triggered()
        threading.Thread(target=_loop, daemon=True).start()
        logger.info(f"더미 센서 트리거 루프 시작 ({DUMMY_INTERVAL}s 간격)")

    # ── 메인 루프 ──────────────────────────────────────────────
    def run(self):
        logger.info("VisiPick 시스템 시작")
        self._transition(State.RUNNING)
        self._serial.set_conveyor_speed(CONVEYOR_SPEED)

        if DUMMY_MODE:
            self._start_dummy_trigger()

        while self.cycle < TOTAL_CYCLES and not self._stop_requested.is_set():
            self.cycle += 1
            logger.info(f"{'='*40}")
            logger.info(f"사이클 {self.cycle}/{TOTAL_CYCLES} — 레시피 세션 시작")

            self._session_id = save_recipe_session(RECIPE_PARTS)

            try:
                # 레시피 완성까지 게이트 큐만 처리 — 검사는 센서 트리거가 구동
                while not self._recipe.is_complete() and not self._stop_requested.is_set():
                    self._flush_gate_queue()
                    time.sleep(0.05)

                if self._stop_requested.is_set():
                    break

                logger.info(f"레시피 완성: {self._recipe.status()}")
                self._tray_transfer()          # 컨1은 계속 운행, 컨3가 다음 빈 트레이 공급
                self._transition(State.COMPLETE)
                logger.info(f"사이클 {self.cycle} 완료!")
                time.sleep(1)

                if self.cycle < TOTAL_CYCLES and not self._stop_requested.is_set():
                    self._transition(State.RUNNING)

            except Exception as e:
                self._transition(State.ERROR)
                logger.error(f"오류: {e}")
                break

        logger.info(f"전체 {self.cycle}회 사이클 종료")
        self._shutdown()

    def _shutdown(self):
        self._running = False
        self._cam_top.release()
        self._cam_side.release()
        self._serial.close()
        self._agv.stop()
        self._mqtt.loop_stop()
        logger.info("시스템 종료")


if __name__ == "__main__":
    sm = VisiPickStateMachine()
    sm.run()
