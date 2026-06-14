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
from src.orchestrator.decision import Decision, gate_action_for, verdict_to_label, defect_codes_for
from src.utils.part_map import to_korean
from src.orchestrator.recipe_mgr import RecipeManager
from src.orchestrator.tray_mgr import TrayManager
from src.devices.robot import Robot
from src.devices.serial_ctrl import SerialController
from src.core.agv_mqtt import get_manager as get_agv_manager
from src.core.db import save_inspection, save_recipe_session, complete_recipe_session
from src.core import frame_bus

logger = setup_logger("statemachine")

BROKER         = config["mqtt"]["broker"]
MQTT_PORT      = config["mqtt"]["port"]
DUMMY_MODE     = config["vision"]["dummy_mode"]
TOTAL_CYCLES   = config["system"]["demo_cycles"]
DUMMY_INTERVAL = config["vision"]["dummy_interval_sec"]
AGV_COUNT      = config["agv"]["count"]
AGV_START      = config["agv"]["nodes"]["start"]
# AGV 한 대에 트레이 몇 개가 적재되면 출발하는지 (1 = 트레이마다 즉시 출발)
# 신 키 trays_per_load 우선, 구 키 trays_per_dispatch 폴백 (양쪽 config 호환)
TRAYS_PER_DISPATCH = int(config["agv"].get("trays_per_load",
                         config["agv"].get("trays_per_dispatch", 3)))
RECIPE_PARTS   = config["recipe"]["parts"]
CONVEYOR_SPEED = config["conveyor"]["speed_cm_per_s"]

_conv_cfg    = config.get("conveyor", {})
_speed       = _conv_cfg.get("speed_cm_per_s", 1.5)
# 게이트 보정 오프셋(초) — 실측으로 게이트가 이르면 +, 늦으면 - 로 미세조정.
_gate_offset = _conv_cfg.get("gate_delay_offset_sec", 0.0)
GATE1_DELAY  = _conv_cfg.get("camera_to_gate1_cm", 30) / _speed + _gate_offset
GATE2_DELAY  = _conv_cfg.get("camera_to_gate2_cm", 45) / _speed + _gate_offset
# 부품별·게이트별 미세보정(초) — 부품마다 게이트 도달 타이밍이 달라(크기/마찰) 게이트
# 지연에 더한다. {부품한글명: {"1":불량G, "2":중복G}}. +는 더 늦게, -는 더 빨리.
GATE_PART_OFFSET = _conv_cfg.get("gate_part_offset_sec", {})
# 레시피 완성 후, 마지막(4번째) 양품이 카메라→컨1 끝단까지 가서 트레이에 낙하할
# 때까지 대기. 이 시간이 0이면 부품이 들어가기 전에 트레이가 이동해버린다.
# camera_to_tray_cm/speed 로 계산하거나, last_part_drop_sec 로 직접 실측 입력(우선).
LAST_DROP_WAIT = _conv_cfg.get(
    "last_part_drop_sec",
    _conv_cfg.get("camera_to_tray_cm", 0) / _speed,
)
DEBOUNCE_SEC = config.get("sensor", {}).get("debounce_sec", 0.5)
# IR 트리거 → 카메라 추론 사이 지연(초). IR 센서가 카메라보다 앞(상류)에 있을 때
# 부품이 카메라 시야에 들어올 때까지 기다린다. 0이면 즉시 추론(센서=카메라 위치).
# 실측 후 config.sensor.trigger_to_capture_sec 에 기입 (거리[cm] / 컨베이어속도[cm/s]).
CAPTURE_DELAY_SEC = config.get("sensor", {}).get("trigger_to_capture_sec", 0.0)
# 멀티프레임 보수 판정: 부품이 카메라 구간을 지나는 동안 N프레임 추론 →
# 하나라도 불량(DEFECT)이면 DEFECT. 각도에 따라 불량이 한 프레임에만 보여도 잡는다.
INSPECT_FRAMES = int(config["vision"].get("inspect_frames", 5))
INSPECT_WINDOW = float(config["vision"].get("inspect_window_sec", 1.0))
# 멀티프레임 불량 판정 최소 프레임 수: DEFECT 프레임이 이 수 '이상'일 때만 DEFECT.
# (1~2개는 각도/노이즈 오검출로 보고 무시 → 양품/중복 판정으로 진행)
DEFECT_MIN_FRAMES = int(config["vision"].get("defect_min_frames", 3))
# 측면 핀검사 대상 부품(영문 part). 상부가 이 목록의 부품으로 판정했을 때만 측면
# 핀휨 검사를 돌린다. 그 외(방열판·커패시터 등)는 측면검사 스킵 → 핀판정 UNKNOWN.
SIDE_INSPECT_PARTS = set(config["vision"].get("pin_inspector", {})
                         .get("inspect_parts", ["IC", "TerminalBlock"]))
# 측면검사 스킵/중립 결과(BENT 아님 → 불량 유발 안 함). per-frame 판정은 top-only 로
# 두고, 측면은 10프레임 투표로 끝에서 한 번에 반영한다(아래 SIDE_NORMAL_MIN).
_SIDE_SKIP = {"verdict": "UNKNOWN", "pin_count": 0, "gap_cv": 0.0, "tip_y_range_px": 0}
# 측면 핀 투표: NORMAL 이 이 표 수 이상 '그리고' NORMAL>=BENT 면 정상, 아니면 핀휨.
SIDE_NORMAL_MIN = int(config["vision"].get("pin_inspector", {})
                      .get("side_normal_min_votes", 3))
# 핀휨(DEFECT) 판정 최소 BENT 표. 전부 UNKNOWN(핀 미검출, 백라이트 없음)이면 측면
# 판정 불가로 보고 상부 판정을 유지한다(정상 부품을 미검출만으로 폐기 방지).
SIDE_BENT_MIN = int(config["vision"].get("pin_inspector", {})
                    .get("side_bent_min_votes", 3))
# 영상 연속 송출: 카메라 최신 프레임을 이 fps 로 frame_bus 에 계속 발행(검사와 별개).
# 0 이면 연속 송출 끔(검사 시점에만 프레임 갱신).
STREAM_FPS    = float(config.get("stream", {}).get("publish_fps", 10))
STREAM_LABEL_HOLD = float(config.get("stream", {}).get("label_hold_sec", 2.0))


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
        self._trays_on_agv   = 0    # 현재 AGV에 쌓인 트레이 수 (TRAYS_PER_DISPATCH 도달 시 출발)
        self._dispatch_count = 0    # 출발 횟수 (AGV 1·2 번갈아 선택용)
        self._inspect_enabled = True
        self._running        = True
        self._stop_requested = threading.Event()
        # 영상 송출 라벨(검사 결과를 잠깐 화면에 얹기 위한 상태)
        self._stream_label       = None   # (text, (b,g,r))
        self._stream_label_until = 0.0

        # 센서 디바운스
        self._last_trigger = 0.0
        self._sensor_lock  = threading.Lock()

        # 게이트 지연 큐
        self._gate_queue = deque()
        self._gate_lock  = threading.Lock()

        # 검사 중복 방지 (이전 검사가 끝나기 전에 새 트리거 무시)
        self._inspect_lock = threading.Lock()

        # 트레이 이재 직렬화 — 이재를 백그라운드로 돌려 검사를 안 막되, 두 이재가
        # 겹치지 않도록(로봇·컨3·AGV 명령 충돌 방지) 한 번에 하나만 실행.
        self._transfer_lock = threading.Lock()

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
        # 물리 비상정지 버튼은 모터 EMI 노이즈로 오발화 → AGV/컨베이어가 EMERGENCY에
        # 갇히는 문제. 펌웨어 디바운스 재업로드 전까지 물리버튼 콜백을 비활성화한다.
        # (WPF 비상정지(MQTT)는 그대로 동작 — 아래 _on_mqtt_cmd 참고)
        # 재활성화: on_estop=self._emergency_stop, on_estop_clear=self._emergency_clear_button
        self._serial = SerialController(
            on_sensor=self.on_sensor_triggered,
            on_estop=None,          # 물리 버튼 비활성 (노이즈 오발화 차단)
            on_estop_clear=None,
        )
        self._robot  = Robot()
        self._agv    = get_agv_manager()

        # MQTT — WPF 브로드캐스트 + 제어 명령 구독
        self._mqtt = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self._mqtt.on_message = self._on_mqtt_cmd
        self._mqtt.connect(BROKER, MQTT_PORT)
        for t in ("visipick/system/cmd", "visipick/vision/cmd", "visipick/conveyor/cmd",
                  "visipick/gate/cmd", "visipick/robot/cmd"):
            self._mqtt.subscribe(t)
        self._mqtt.loop_start()

        logger.info("VisiPickStateMachine 초기화 완료")

    # ── MQTT 제어 명령 수신 ────────────────────────────────────
    def _on_mqtt_cmd(self, client, userdata, msg):
        try:
            data   = json.loads(msg.payload.decode())
            action = data.get("action")
            topic  = msg.topic
            if topic == "visipick/system/cmd":
                if action == "stop":
                    self._emergency_stop()
                elif action == "reset":
                    self._reset()
            elif topic == "visipick/vision/cmd":
                self._inspect_enabled = (action == "start")
                logger.info(f"비전 {'시작' if action=='start' else '중지'}")
            elif topic == "visipick/conveyor/cmd":
                if action == "start":
                    self._stop_requested.clear()         # 비상정지 래치 해제(재개)
                    self._serial.set_conveyor_speed(CONVEYOR_SPEED)
                    self._serial.start_return_conveyor() # 컨2(중복 반환) 재가동 (비상정지로 멈췄을 수 있음)
                    self._agv.emergency_clear()          # AGV 비상정지 해제
                    self._inspect_enabled = True         # 비전도 재개 (컨베이어 가동=검사 ON)
                    if self.state == State.EMERGENCY_STOP:
                        self._transition(State.RUNNING)
                    logger.info("컨베이어 시작 (비상정지 해제, AGV 재개, 비전 재개)")
                else:
                    self._serial.set_conveyor_speed(0.0)
                    logger.info("컨베이어 정지")
            elif topic == "visipick/gate/cmd":         # 수동 게이트 푸시 (/api/gate/{n}/push)
                gate = int(data.get("gate"))
                self._serial.push_gate(gate)
                logger.info(f"게이트 {gate} 수동 푸시")
            elif topic == "visipick/robot/cmd":        # 수동 트레이 이재 (/api/robot/transfer)
                if action == "transfer":
                    threading.Thread(target=self._robot.transfer_tray, daemon=True).start()
                    logger.info("로봇 트레이 이재 수동 트리거")
        except Exception:
            pass

    def _reset(self):
        """비상정지/오류 래치 해제 + 레시피·트레이·게이트 큐 초기화 → RUNNING (/api/reset).

        주의: run() 메인 루프는 1회성 배치라, 이미 _shutdown 된 뒤엔 상태만 RUNNING 으로
        표시될 뿐 새 사이클은 run() 재호출이 필요하다 (Phase4 'RESET 절차 점검' 확정 항목)."""
        logger.info("리셋 요청 — 상태/카운트 초기화")
        self._stop_requested.clear()
        with self._gate_lock:
            self._gate_queue.clear()
        self._recipe.reset()
        self._tray.reset()
        self._trays_on_agv = 0      # AGV 적재 카운트도 초기화 (반쯤 찬 AGV 가정 안 함)
        self._inspect_enabled = True
        self._serial.set_conveyor_speed(CONVEYOR_SPEED)
        self._transition(State.RUNNING)
        self._publish_event("System", "INFO", "리셋 완료 — RUNNING 복귀")

    def _emergency_stop(self):
        if self._stop_requested.is_set():
            return
        logger.warning("비상정지 요청 — 일시정지(프로그램 유지). 재개: 컨베이어 시작")
        self._stop_requested.set()
        self._serial.emergency_stop()       # 컨1·컨2·컨3·게이트 전체 정지
        self._agv.emergency_stop()          # AGV 전체 정지
        with self._gate_lock:
            self._gate_queue.clear()
        self._transition(State.EMERGENCY_STOP)
        self._publish_event("System", "WARN", "비상정지 실행")

    def _emergency_clear_button(self):
        """물리 비상정지 버튼 해제 — WPF/운영자에게 '재개 가능' 알림만.
        안전상 버튼 해제만으로 모터를 자동 재가동하지 않는다(재개는 '컨베이어 시작')."""
        logger.info("물리 비상정지 버튼 해제 — 재개 가능 (컨베이어 시작으로 재개)")
        self._publish_event("System", "INFO", "비상정지 버튼 해제 — 재개 가능")

    # ── 센서 트리거 (public — serial_ctrl 콜백으로 연결 예정) ────
    def on_sensor_triggered(self):
        """투입단 센서 신호 수신 시 호출. 디바운스 + 상태 보호."""
        now = time.time()
        with self._sensor_lock:
            if now - self._last_trigger < DEBOUNCE_SEC:
                logger.info("[진단] 트리거 수신 — 디바운스로 무시")
                return
            self._last_trigger = now

        logger.info(f"[진단] 트리거 수신 (state={self.state.value}, delay={CAPTURE_DELAY_SEC}s 후 검사)")
        if self.state != State.RUNNING:
            logger.info(f"[진단] state가 RUNNING 아님 → 검사 안 함")
            return

        # IR 센서가 카메라보다 앞이면 부품이 시야에 들어올 때까지 지연 후 추론.
        if CAPTURE_DELAY_SEC > 0:
            t = threading.Timer(CAPTURE_DELAY_SEC, self._inspect_one)
            t.daemon = True
            t.start()
        else:
            threading.Thread(target=self._inspect_one, daemon=True).start()

    # ── 게이트 예약 큐 ──────────────────────────────────────────
    def _schedule_gate(self, gate_no: int, delay_sec: float, ref_time: float | None = None):
        # 기준 시점(ref_time)에서 delay_sec 후 발사. ref_time 미지정 시 현재.
        # 검사 시작(부품이 카메라 진입한 때)을 기준으로 주면 멀티프레임 검사
        # 소요시간(~1초)과 무관하게 게이트 타이밍이 일정해진다.
        fire_at = (ref_time if ref_time is not None else time.time()) + delay_sec
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
            ok = self._serial.push_gate(gate_no)
            logger.info(f"[게이트 발사] Gate{gate_no} push → {'성공' if ok else '실패'}")

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
            logger.info("[진단] inspect_enabled=False → 검사 안 함")
            return
        if not self._inspect_lock.acquire(blocking=False):
            logger.info("[진단] 이전 검사 진행 중(락 점유) — 이번 트리거 무시")
            return
        try:
            logger.info("[진단] 검사 시작 (멀티프레임)")
            t0 = time.time()

            # 멀티프레임 판정: INSPECT_WINDOW 초 동안 INSPECT_FRAMES(10) 장 추론.
            #   - 상부(종류·파손): 보수적 — 하나라도 DEFECT면 DEFECT.
            #   - 측면(핀휨): per-frame 결정에 넣지 않고 verdict만 모았다가 끝에서 '투표'.
            #     (각도 의존 오검출 방지: NORMAL>=SIDE_NORMAL_MIN '그리고' NORMAL>=BENT 면 정상)
            frames = []
            side_verdicts = []          # 측면 핀 투표용 (IC/터미널블록일 때만 채워짐)
            last_side_frame = None       # 스트리밍용 마지막 측면 프레임
            interval = INSPECT_WINDOW / max(INSPECT_FRAMES, 1)
            for i in range(max(INSPECT_FRAMES, 1)):
                tf = time.time()
                frame_top  = self._cam_top.capture()
                top  = self._clf.classify_top(frame_top)
                # 측면 핀검사는 핀 있는 부품(IC·터미널블록)일 때만 수행하고 verdict 수집.
                if top.get("part") in SIDE_INSPECT_PARTS:
                    frame_side = self._cam_side.capture()
                    side = self._pin.inspect_side(frame_side, top.get("part"))
                    side_verdicts.append((side.get("verdict") or "UNKNOWN").upper())
                    if frame_side is not None:
                        last_side_frame = frame_side
                # per-frame 판정은 top-only (측면은 끝에서 투표로 반영)
                result = self._decider.evaluate(top, dict(_SIDE_SKIP))
                cls    = verdict_to_label(result.verdict)
                frames.append({"cls": cls, "result": result, "top": top,
                               "frame_top": frame_top})
                # 윈도우 간격 맞춰 페이싱 (추론이 빠르면 잠깐 대기)
                if i < INSPECT_FRAMES - 1:
                    time.sleep(max(0.0, interval - (time.time() - tf)))

            # 상부 집계: DEFECT 프레임이 DEFECT_MIN_FRAMES(기본 3) '이상'일 때만 DEFECT.
            #   1~2개는 각도/순간 오검출로 보고 무시 → 양품/중복(검출됨) 우선,
            #   그것도 없으면 UNCERTAIN(불량 프레임 제외). 표본이 전부 불량뿐이면 폴백.
            defects   = [f for f in frames if f["cls"] == "DEFECT"]
            valids    = [f for f in frames if f["cls"] in ("NEEDED", "DUPLICATE")]
            nondefect = [f for f in frames if f["cls"] != "DEFECT"]
            if len(defects) >= DEFECT_MIN_FRAMES:
                win = max(defects, key=lambda f: f["result"].confidence)
            elif valids:
                win = max(valids, key=lambda f: f["result"].confidence)
            elif nondefect:
                win = max(nondefect, key=lambda f: f["result"].confidence)
            else:
                win = max(defects, key=lambda f: f["result"].confidence)
            if 0 < len(defects) < DEFECT_MIN_FRAMES:
                logger.info(f"[상부] 불량 프레임 {len(defects)}개 < {DEFECT_MIN_FRAMES} "
                            f"→ 불량 무시(오검출 처리)")

            result     = win["result"]
            top        = win["top"]
            frame_top  = win["frame_top"]
            frame_side = last_side_frame
            cls        = win["cls"]

            # ── 측면 핀 투표 (IC·터미널블록만) — 참고/로그용, 최종 판정엔 영향 없음 ──
            #   백라이트 부재로 측면 핀검사 신뢰성이 낮아(정상 부품 오폐기) 최종 판정에서
            #   분리했다. 투표는 계속 수행·기록하되 cls/불량코드/게이트는 상부 판정만 따른다.
            #   (백라이트 확보 후 재활성화하려면 아래 side_bent 를 cls 덮어쓰기에 다시 연결)
            side_bent = False
            if top.get("part") in SIDE_INSPECT_PARTS:
                n_normal = side_verdicts.count("NORMAL")
                n_bent   = side_verdicts.count("BENT")
                n_unknown = len(side_verdicts) - n_normal - n_bent
                side_bent = (n_bent >= SIDE_BENT_MIN) and (n_bent >= n_normal)
                verdict_txt = "핀휨" if side_bent else \
                              ("측면판정불가(상부유지)" if n_bent + n_normal == 0 else "정상")
                logger.info(f"[측면] 투표 NORMAL={n_normal} BENT={n_bent} "
                            f"UNKNOWN={n_unknown} → {verdict_txt} (참고용, 판정 미반영)")

            action = gate_action_for(cls)                          # 김선진 게이트 매핑 그대로
            # 불량 코드: 상부 불량 클래스만 사용 (측면 핀투표는 최종 판정 미반영).
            if cls == "DEFECT":
                _all_defcls = []
                for f in frames:
                    for dc in f["top"].get("defect_classes", []):
                        if dc not in _all_defcls:
                            _all_defcls.append(dc)
                defect_codes = defect_codes_for(_all_defcls, {})
                defect = defect_codes[0] if defect_codes else "UNKNOWN"
            else:
                defect_codes = []
                defect = "NONE"

            # 부품명: 영문(비전) → 한글(표시/레시피/DB). 단일 변환 지점 = part_map
            part_type  = to_korean(top.get("part")) or "UNKNOWN"
            confidence = round(float(result.confidence), 2)
            cycle_ms   = int((time.time() - t0) * 1000)
            logger.debug(f"멀티프레임 판정: {[f['cls'] for f in frames]} → {cls}")

            # 게이트 예약 — 부품이 카메라→게이트 구간을 이동하는 시간만큼 지연.
            # 기준은 검사 시작(t0=부품이 카메라 진입한 때) → 검사 소요시간과 무관하게 일정.
            # Gate1=불량(DEFECT, 폐기), Gate2=중복/보류(DUPLICATE·UNCERTAIN, 반환 컨베이어).
            # 부품별 미세보정 적용 (config.conveyor.gate_part_offset_sec)
            _poff = GATE_PART_OFFSET.get(part_type, {})
            if cls == "DEFECT":
                _d = GATE1_DELAY + float(_poff.get("1", 0))
                logger.info(f"[게이트] {part_type} 불량 → Gate1 {_d:.2f}s 후 (보정 {_poff.get('1',0):+})")
                self._schedule_gate(1, _d, ref_time=t0)
            elif cls in ("DUPLICATE", "UNCERTAIN"):
                _d = GATE2_DELAY + float(_poff.get("2", 0))
                logger.info(f"[게이트] {part_type} 중복 → Gate2 {_d:.2f}s 후 (보정 {_poff.get('2',0):+})")
                self._schedule_gate(2, _d, ref_time=t0)

            if cls == "NEEDED":
                self._recipe.mark_collected(part_type)
                self._tray.on_part_passed(part_type)

            payload = {
                "timestamp":         datetime.now().isoformat(),
                "recipe_session_id": self._session_id,
                "part_type":         part_type,
                "classification":    cls,
                "defect_code":       defect,        # 주 불량 1개(DB·하위호환)
                "defect_codes":      defect_codes,  # 검출된 모든 불량(예: ["BENT_PIN","BROKEN"])
                "confidence":        confidence,
                "gate_action":       action,
                "cycle_time_ms":     cycle_ms,
            }

            # 프레임 버스에 최신 검사 프레임 발행 (api_server MJPEG 송출용)
            self._publish_frames(frame_top, frame_side, cls, top, confidence)

            save_inspection(payload)
            self._publish("visipick/inspection", payload)
            self._publish_event(
                "Camera", "INFO",
                f"{part_type} → {cls} ({defect})"
            )
            logger.info(f"[검사] {part_type} | {cls} | {defect} | {action} | {cycle_ms}ms")
        finally:
            self._inspect_lock.release()

    # ── 프레임 버스 발행 (MJPEG 송출용) ───────────────────────
    def _publish_frames(self, frame_top, frame_side, cls, top, conf):
        """검사 결과 라벨을 STREAM_LABEL_HOLD 초간 영상 송출 스레드가 얹도록 등록.
        (top 프레임 자체는 _start_stream_loop 가 연속 발행 — 여기선 라벨만 갱신)
        측면(side)은 연속 송출이 없으므로 검사 시점에 직접 발행."""
        color = (0, 0, 255) if cls == "DEFECT" else \
                (0, 165, 255) if cls == "DUPLICATE" else (0, 200, 0)
        label = f"{top.get('raw_class', '?')} {cls} {conf:.2f}"
        self._stream_label       = (label, color)
        self._stream_label_until = time.time() + STREAM_LABEL_HOLD
        if STREAM_FPS <= 0 and frame_top is not None:   # 연속 송출 꺼져있으면 검사 프레임이라도 발행
            import cv2
            cv2.putText(frame_top, label, (10, 28),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
            frame_bus.publish("top", frame_top)
        if frame_side is not None:
            frame_bus.publish("side", frame_side)

    # ── 트레이 이송 + AGV 출발 (백그라운드) ────────────────────
    def _tray_transfer_bg(self, session_id, tray_count):
        """완성 트레이 이재를 백그라운드로 수행 — 검사/다음 트레이 수집을 막지 않는다.
        run_cycle 에서 레시피/트레이는 이미 리셋됐으므로 여기선 리셋하지 않는다.
        두 이재가 겹치지 않도록 _transfer_lock 으로 직렬화한다.
        session_id/tray_count 는 '완성된' 트레이의 값(스냅샷) — self 의 현재 값과 다르다."""
        with self._transfer_lock:
            # 0) 마지막 양품이 트레이에 낙하할 때까지 대기 (컨3가 트레이를 빼기 전).
            #    이 동안에도 새 부품 검사는 별도 스레드에서 계속 진행된다.
            if LAST_DROP_WAIT > 0:
                logger.info(f"마지막 부품 낙하 대기 {LAST_DROP_WAIT:.1f}s (이재 백그라운드)")
                _until = time.time() + LAST_DROP_WAIT
                while time.time() < _until and self._running:
                    if self._stop_requested.is_set():
                        _until += 0.2     # 정지 동안엔 데드라인도 미뤄 낙하대기 보존
                        time.sleep(0.2)
                        continue
                    time.sleep(0.05)
                if not self._running:
                    return

            # 1) 컨3 1칸 전진 (완성 트레이 이재 위치로 / 다음 빈 트레이 공급)
            self._serial.advance_tray()
            self._publish_event("Conveyor", "INFO", "컨3 — 트레이 1칸 전진")

            # 2) 로봇이 완성 트레이를 AGV에 이재 (실패는 비치명)
            slot = self._trays_on_agv + 1
            self._publish_event("Robot", "INFO", f"트레이 이송 시작 (AGV {slot}칸)")
            try:
                if not self._robot.transfer_tray(slot):
                    logger.warning("로봇 트레이 이송 실패 — 건너뜀")
            except Exception as e:
                logger.warning(f"로봇 이송 예외 — 건너뜀: {e}")

            # 3) 트레이 적재 누계 — TRAYS_PER_DISPATCH 개 쌓이면 AGV 출발
            self._trays_on_agv += 1
            self._publish_event("AGV", "INFO",
                                f"AGV 트레이 적재 {self._trays_on_agv}/{TRAYS_PER_DISPATCH}")
            logger.info(f"트레이 적재 {self._trays_on_agv}/{TRAYS_PER_DISPATCH}")

            complete_recipe_session(session_id, tray_count)

            if self._trays_on_agv >= TRAYS_PER_DISPATCH:
                # 출발점(START) RFID로 인식된 '지금 적재받은' AGV를 출발. 못 찾으면 폴백.
                agv_id = self._agv.get_agv_at_start()
                if agv_id is None:
                    agv_id = (self._dispatch_count % AGV_COUNT) + 1
                    logger.warning(f"출발점 AGV 미확인(node=START 없음) — 폴백 교번 AGV {agv_id}")
                self._dispatch_count += 1
                self._agv.dispatch(agv_id, source=AGV_START,
                                   recipe_session_id=session_id)
                self._publish_event("AGV", "INFO",
                                    f"AGV {agv_id} 창고 출발 (출발점 적재 트레이 {self._trays_on_agv}개)")
                logger.info(f"AGV {agv_id} 출발 — 출발점 적재 트레이 {self._trays_on_agv}개 완료")
                self._trays_on_agv = 0
            else:
                logger.info(f"AGV 대기 — 트레이 {TRAYS_PER_DISPATCH - self._trays_on_agv}개 더 필요")

    # ── 더미 센서 트리거 루프 ─────────────────────────────────
    def _start_dummy_trigger(self):
        def _loop():
            while self._running:
                time.sleep(DUMMY_INTERVAL)
                if self._running:
                    self.on_sensor_triggered()
        threading.Thread(target=_loop, daemon=True).start()
        logger.info(f"더미 센서 트리거 루프 시작 ({DUMMY_INTERVAL}s 간격)")

    # ── 운행 시작 (컨1 ON + 더미 트리거) ───────────────────────
    def start(self):
        """RUNNING 진입 + 컨1 운행 + (더미 모드면) 센서 트리거 루프 기동.
        run() 과 auto_test 가 공유하는 1회성 셋업."""
        self._transition(State.RUNNING)
        self._register_initial_homes()     # 시작 시 수동 배치한 홈 AGV 등록
        self._serial.set_conveyor_speed(CONVEYOR_SPEED)
        self._serial.start_return_conveyor()   # 컨2(중복 반환 컨베이어, 상시 ON) 가동
        self._start_gate_flush_loop()      # 게이트 발사 전용 스레드 (run_cycle 상태와 무관하게 항상)
        self._start_stream_loop()          # 영상 연속 송출 (검사와 별개)
        if DUMMY_MODE:
            self._start_dummy_trigger()

    def _start_gate_flush_loop(self):
        """게이트 예약 큐를 항상 흘려보내는 전용 스레드. 연속 운전에서 run_cycle 이
        레시피 완성 후 바로 빠져나가 while 루프의 flush 가 끊겨도, 예약된 게이트가
        제때 발사되도록 보장한다. (_gate_lock 으로 큐 보호 — 중복 발사 없음)"""
        def _loop():
            while self._running:
                try:
                    self._flush_gate_queue()
                except Exception as e:
                    logger.warning(f"게이트 flush 오류(무시): {e}")
                time.sleep(0.05)
        threading.Thread(target=_loop, daemon=True).start()
        logger.info("게이트 발사 스레드 시작")

    def _register_initial_homes(self):
        """시작 시 수동으로 홈에 놓은 AGV를 점유표에 등록.
        홈 도착지점엔 RFID가 없어(교차로 전 RFID로만 홈번호 판단) 수동 배치 AGV는
        스스로 홈번호를 모른다. config.agv.initial_home {"agv_id": home_id} 로 알려준다.
        예: {"2": 1} = AGV2를 홈1에 배치. → set_home_free(False)로 점유 등록 + 방송."""
        for aid, hid in config.get("agv", {}).get("initial_home", {}).items():
            try:
                self._agv.set_home_free(int(hid), free=False, agv_id=int(aid))
                logger.info(f"시작 홈 배치 등록: AGV {aid} → 홈 {hid}")
            except Exception as e:
                logger.warning(f"시작 홈 배치 등록 실패(AGV {aid}, 홈 {hid}): {e}")

    # ── 영상 연속 송출 스레드 (MJPEG 소스) ─────────────────────
    def _start_stream_loop(self):
        """상부·측면 카메라 최신 프레임을 STREAM_FPS 로 frame_bus 에 계속 발행 →
        api_server /video/top·/video/side 가 부드러운 실시간 영상으로 송출.
        검사 결과 라벨은 STREAM_LABEL_HOLD 초 동안 상부 화면에 얹는다.
        (측면은 검사 때만 발행하면 부품 없을 때 WPF 측면 화면이 빈다 → 여기서 연속 발행)"""
        if DUMMY_MODE or STREAM_FPS <= 0:
            return
        import cv2
        interval = 1.0 / STREAM_FPS

        def _loop():
            while self._running:
                t = time.time()
                try:
                    frame = self._cam_top.capture_full()   # 원본 1280x720 (크롭 안 함)
                    if frame is not None:
                        if self._stream_label and time.time() < self._stream_label_until:
                            text, color = self._stream_label
                            cv2.putText(frame, text, (10, 28),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
                        frame_bus.publish("top", frame)
                    side = self._cam_side.capture()        # 측면 최신 프레임 연속 발행
                    if side is not None:
                        frame_bus.publish("side", side)
                except Exception as e:                 # 송출은 실패해도 검사에 영향 없게
                    logger.warning(f"영상 송출 오류(무시): {e}")
                time.sleep(max(0.0, interval - (time.time() - t)))

        threading.Thread(target=_loop, daemon=True).start()
        logger.info(f"영상 송출 스레드 시작 ({STREAM_FPS:.0f}fps)")

    # ── 레시피 1사이클: 수집 → 이재 → 완료 ─────────────────────
    def run_cycle(self) -> bool:
        """레시피 한 세션을 끝까지 수행 (4종 수집 → 트레이 이재 → COMPLETE).
        성공 True / 중단·예외 False. 검사는 센서 트리거가 비동기 구동, 여기선 게이트
        큐만 흘리며 레시피 완성을 대기한다. (auto_test 가 사이클별로 호출)"""
        if self.state != State.RUNNING:
            self._transition(State.RUNNING)
        self.cycle += 1
        logger.info(f"{'='*40}")
        logger.info(f"사이클 {self.cycle} — 레시피 세션 시작")
        self._session_id = save_recipe_session(RECIPE_PARTS)
        try:
            while not self._recipe.is_complete() and self._running:
                if self._stop_requested.is_set():
                    time.sleep(0.2)        # 비상정지 — 종료 않고 해제(재개) 대기
                    continue
                self._flush_gate_queue()
                time.sleep(0.05)
            if not self._running:          # 실제 프로그램 종료 시에만 빠져나감
                return False
            logger.info(f"레시피 완성: {self._recipe.status()}")
            # 연속 운전: 완성 즉시 트레이/레시피를 스냅샷 후 리셋한다. 그래야 검사가
            # 끊기지 않고, 완성 직후 들어오는 부품이 (중복이 아니라) 새 트레이용 NEEDED
            # 로 잡힌다. 실제 이재(낙하 대기 + 컨3 + 로봇 + AGV)는 백그라운드 스레드로
            # 돌려 검사/다음 수집을 막지 않는다.
            completed_session = self._session_id
            completed_count   = self._tray.get_count()
            self._recipe.reset()
            self._tray.reset()
            self._publish_event("System", "INFO", "트레이 완성 — 이재 시작(백그라운드), 다음 트레이 수집 계속")
            threading.Thread(
                target=self._tray_transfer_bg,
                args=(completed_session, completed_count),
                daemon=True,
            ).start()
            logger.info(f"사이클 {self.cycle} 완성 — 이재 백그라운드, 검사 계속")
            return True
        except Exception as e:
            self._transition(State.ERROR)
            logger.error(f"사이클 오류: {e}")
            return False

    # ── 메인 루프 ──────────────────────────────────────────────
    def run(self):
        logger.info("VisiPick 시스템 시작")
        self.start()
        try:
            while self.cycle < TOTAL_CYCLES and self._running:
                if self._stop_requested.is_set():
                    time.sleep(0.2)        # 비상정지 — 종료 않고 해제(재개) 대기
                    continue
                if not self.run_cycle():
                    break                  # 실제 종료(_running=False)/오류일 때만
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Ctrl+C — 종료")
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
