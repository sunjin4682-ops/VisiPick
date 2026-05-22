import time, json, random
from datetime import datetime
from enum import Enum
import paho.mqtt.client as mqtt

from src.utils.logger import setup_logger
from src.utils.config_loader import config
from src.vision.camera_top import CameraTop
from src.vision.camera_side import CameraSide
from src.vision.classifier import Classifier
from src.vision.defect_detector import DefectDetector
from src.orchestrator.decision import judge, gate_action_for
from src.orchestrator.recipe_mgr import RecipeManager
from src.orchestrator.tray_mgr import TrayManager
from src.devices.robot import Robot
from src.devices.serial_ctrl import SerialController
from src.core.agv_mqtt import get_manager as get_agv_manager
from src.core.db import save_inspection, save_recipe_session, complete_recipe_session

logger = setup_logger("statemachine")

BROKER       = config["mqtt"]["broker"]
MQTT_PORT    = config["mqtt"]["port"]
DUMMY_MODE   = config["vision"]["dummy_mode"]
TOTAL_CYCLES = config["system"]["demo_cycles"]
INTERVAL     = config["vision"]["dummy_interval_sec"]
AGV_COUNT    = config["agv"]["count"]
AGV_START    = config["agv"]["nodes"]["start"]
RECIPE_PARTS = config["recipe"]["parts"]


class State(Enum):
    IDLE          = "IDLE"
    RUNNING       = "RUNNING"
    TRAY_TRANSFER = "TRAY_TRANSFER"
    COMPLETE      = "COMPLETE"
    ERROR         = "ERROR"


class VisiPickStateMachine:
    def __init__(self):
        self.state       = State.IDLE
        self.cycle       = 0
        self._session_id = None

        # 비전
        self._cam_top  = CameraTop()
        self._cam_side = CameraSide()
        self._clf      = Classifier()
        self._dd       = DefectDetector()

        # 오케스트레이터
        self._recipe = RecipeManager()
        self._tray   = TrayManager()

        # 디바이스
        self._serial = SerialController()
        self._robot  = Robot()
        self._agv    = get_agv_manager()

        # MQTT — WPF 브로드캐스트
        self._mqtt = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self._mqtt.connect(BROKER, MQTT_PORT)
        self._mqtt.loop_start()

        logger.info("VisiPickStateMachine 초기화 완료")

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

    # ── 부품 1개 검사 ──────────────────────────────────────────
    def _inspect_one(self):
        t0 = time.time()

        frame_top  = self._cam_top.capture()
        frame_side = self._cam_side.capture()

        part_type  = self._clf.classify(frame_top)
        defect     = self._dd.detect(frame_top, frame_side)
        cls        = judge(part_type, defect, self._recipe)
        action     = gate_action_for(cls)
        confidence = round(random.uniform(0.85, 0.99), 2) if DUMMY_MODE else 0.0
        cycle_ms   = int((time.time() - t0) * 1000)

        # 게이트 동작
        if cls == "DUPLICATE":
            self._serial.push_gate(1)
        elif cls == "DEFECT":
            self._serial.push_gate(2)

        # 레시피 / 트레이 업데이트
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

    # ── 트레이 이송 + AGV 출발 ────────────────────────────────
    def _tray_transfer(self):
        self._transition(State.TRAY_TRANSFER)
        self._publish_event("Robot", "INFO", "트레이 이송 시작")

        ok = self._robot.transfer_tray()
        if not ok:
            raise RuntimeError("로봇 트레이 이송 실패")

        agv_id = (self.cycle % AGV_COUNT) + 1
        self._agv.dispatch(agv_id, source=AGV_START,
                           recipe_session_id=self._session_id)
        self._publish_event("AGV", "INFO", f"AGV {agv_id} 창고 출발")

        complete_recipe_session(self._session_id, self._tray.get_count())
        logger.info(f"레시피 완료 — 수집 {self._tray.get_count()}개, AGV {agv_id} 출발")

        self._recipe.reset()
        self._tray.reset()

    # ── 메인 루프 ──────────────────────────────────────────────
    def run(self):
        logger.info("VisiPick 시스템 시작")
        self._transition(State.RUNNING)

        while self.cycle < TOTAL_CYCLES:
            self.cycle += 1
            logger.info(f"{'='*40}")
            logger.info(f"사이클 {self.cycle}/{TOTAL_CYCLES} — 레시피 세션 시작")

            self._session_id = save_recipe_session(RECIPE_PARTS)

            try:
                while not self._recipe.is_complete():
                    self._inspect_one()
                    time.sleep(INTERVAL)

                logger.info(f"레시피 완성: {self._recipe.status()}")
                self._tray_transfer()
                self._transition(State.COMPLETE)
                logger.info(f"사이클 {self.cycle} 완료!")
                time.sleep(1)
                self._transition(State.RUNNING)

            except Exception as e:
                self._transition(State.ERROR)
                logger.error(f"오류: {e}")
                break

        logger.info(f"전체 {self.cycle}회 사이클 종료")
        self._shutdown()

    def _shutdown(self):
        self._cam_top.release()
        self._cam_side.release()
        self._serial.close()
        self._agv.stop()
        self._mqtt.loop_stop()
        logger.info("시스템 종료")


if __name__ == "__main__":
    sm = VisiPickStateMachine()
    sm.run()
