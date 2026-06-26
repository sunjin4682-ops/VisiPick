# AGENTS.md

## 프로젝트 개요

**VisiPick V6.5** — 비정지(Non-stop) 컨베이어 위를 이동하는 DIP IC 계열 부품 4종을 상부 YOLO와 측면 카메라로 검사하고, 레시피 기반으로 필요품/중복품/불량품을 분류한다. 양품은 트레이에 중력 수집하고, 완성된 트레이는 myCobot이 AGV에 적재한다. AGV는 MQTT로 창고 운반 및 복귀 상태를 보고한다.

현재 런타임 기준:

| 기술 | 역할 |
|------|------|
| Python Central Server | 단일 마스터, FSM/DB/API/MQTT의 기준 상태 |
| C# WPF | REST/MQTT/MJPEG/WebSocket 기반 표시 및 제어 클라이언트 |
| MQTT (Mosquitto) | AGV 통신, WPF 브로드캐스트, 수동 제어 명령 |
| FastAPI + WebSocket | HMI REST/WS, 영상 MJPEG 송출 (:8000) |
| SQLite WAL | 검사/세션/AGV/이벤트 영속화 |
| USB Serial -> ESP32 | 컨1/컨2/컨3, 게이트 푸셔, 센서 트리거 |
| Ethernet TCP -> RPi4 | myCobot 280 공식 소켓 서버 제어 |

## 핵심 흐름

```text
[부품 투입]
    ↓
[컨1: Non-stop 메인 검사 라인]
    ↓
IR 트리거 → trigger_to_capture_sec 대기
    ↓
Camera1(상부): YOLO best.pt, 7클래스 → 4종 부품 + 불량 클래스
Camera2(측면): 핀 검사 프레임 수집 및 로그/참고 판정
    ↓
NEEDED    → 통과 → 트레이 낙하
DUPLICATE → Gate2 → 반환 컨베이어
DEFECT    → Gate1 → 폐기
    ↓
레시피 4종 충족
    ↓
last_part_drop_sec 대기 → 컨3 1칸 전진 → myCobot이 AGV 슬롯에 적재
    ↓
trays_per_load 개 적재 시 AGV 출발
```

## 실제 물리 게이트 매핑

현재 `src/core/state_machine.py` 기준 실제 ESP32로 발사되는 물리 매핑은 다음이다.

| 판정 | 실제 물리 게이트 | 의미 |
|------|------------------|------|
| `NEEDED` | 없음 | 통과 후 트레이 수집 |
| `DEFECT` | `Gate1` | 불량 폐기 |
| `DUPLICATE` / 보류성 `UNCERTAIN` | `Gate2` | 반환 컨베이어 재투입 |

주의:
- `src/orchestrator/decision.py`의 `gate_action_for()`는 기존 WPF/DB 호환 문자열을 유지한다. 그래서 문자열상 `DUPLICATE -> GATE1_PUSH`, `DEFECT -> GATE2_PUSH`가 남아 있지만, 실제 발사는 `state_machine._inspect_one()`에서 위 물리 매핑으로 다시 예약된다.
- `src/devices/serial_ctrl.py`, `src/api/api_server.py`, 일부 테스트 주석에는 예전 게이트 설명이 남아 있다. 실제 하드웨어 동작을 판단할 때는 `state_machine.py`의 스케줄링을 기준으로 본다.
- `config.conveyor.gate_part_offset_sec` 주석도 현재 코드와 맞게 `{"1": 불량 게이트, "2": 중복/보류 게이트}`로 운용한다.

## 판정 로직

`src/orchestrator/decision.py`의 `Decision.evaluate()`가 기준이다.

```python
if part is None or confidence < min_conf:
    return UNCERTAIN
if top.verdict_hint == "REJECT":
    return REJECT
if side.verdict == "BENT":
    return REJECT
if is_duplicate(part):
    return DUPLICATE
return PASS
```

현재 `state_machine.py`에서는 측면 핀 투표를 수행하지만 최종 판정에는 반영하지 않는다. 백라이트/측면 신뢰도 문제로 `side_bent`는 로그 참고용이며, 최종 `cls`, 게이트, 불량코드는 상부 YOLO 판정을 따른다.

`UNCERTAIN`은 내부 의미상 보류/재투입이지만, WPF가 3분류만 처리하므로 `verdict_to_label()`에서 현재 `DUPLICATE`로 합쳐 발행한다.

## 부품 및 비전

상부 YOLO 모델:
- 경로: `models/best.pt`
- 설정: `config.vision.mode = "yolo"`
- 주요 파라미터: `yolo_conf`, `yolo_iou`, `yolo_imgsz`, `defect_min_conf`

YOLO 클래스 매핑:

| YOLO 클래스 | 의미 |
|-------------|------|
| `IC` | IC |
| `TB` | TerminalBlock |
| `HS` | Heatsink |
| `CAP` | Capacitor |
| `Broken` | 불량 |
| `Dented` | 불량 |
| `Pinbent` | 불량 |

레시피 표시명은 `src/utils/part_map.py`를 통해 한글명으로 변환한다.

측면 핀 검사:
- 파일: `src/vision/pin_inspector.py`
- 대상: `config.vision.pin_inspector.inspect_parts`
- 현재 최종 판정 반영 안 함. 로그/튜닝/참고용으로 유지.

## 주요 디렉토리

```text
C:\VisiPick\
├── config/                  # config.json, docker-compose.yml, robot_path_*.json
├── data/                    # visipick.db, stream/top.jpg, stream/side.jpg
├── docs/                    # 기술 문서
├── Hardware-Connect/esp32/  # ESP32 펌웨어
├── jetson/                  # Jetson 이관용 파일. 현재 PC 런타임의 핵심 경로는 아님
├── mock/                    # MockESP32, MockMyCobot, MockAGV, MockBroker
├── models/                  # YOLO best.pt
├── src/
│   ├── api/                 # FastAPI, REST, WebSocket, MJPEG
│   ├── core/                # state_machine, db, agv_mqtt, frame_bus
│   ├── devices/             # serial_ctrl, robot
│   ├── orchestrator/        # decision, recipe_mgr, tray_mgr
│   ├── utils/               # logger, config_loader, db_init, part_map
│   └── vision/              # camera_top, camera_side, classifier, pin_inspector
├── tests/                   # auto_test, testsets, gate_loop, vision integration
└── tools/                   # 카메라/IR/로봇/AGV 단독 테스트 도구
```

## 주요 파일

| 파일 | 실제 역할 |
|------|-----------|
| `src/core/state_machine.py` | 전체 FSM, 센서 트리거, 멀티프레임 검사, 물리 게이트 예약, 트레이/AGV 연동 |
| `src/orchestrator/decision.py` | PASS/REJECT/DUPLICATE/UNCERTAIN 판정 및 WPF/DB 어댑터 |
| `src/vision/classifier.py` | YOLO/classical/dummy 분류 파사드 |
| `src/vision/camera_top.py` | 상부 카메라, 최신 프레임 그래버, 검사 크롭/송출 원본 분리 |
| `src/vision/camera_side.py` | 측면 카메라, 최신 프레임 그래버 |
| `src/vision/pin_inspector.py` | 측면 핀 검사 알고리즘 |
| `src/devices/serial_ctrl.py` | ESP32 JSON Serial/TCP mock 통신 |
| `src/devices/robot.py` | myCobot 280 소켓 제어, robot_path 파일 재생 |
| `src/core/agv_mqtt.py` | AGV MQTT 상태 캐시, 홈 점유표, dispatch/복귀 처리 |
| `src/core/frame_bus.py` | MJPEG용 최신 JPEG 파일 버스 |
| `src/api/api_server.py` | REST, WebSocket, `/video/{top,side}`, `/snapshot/{name}` |
| `src/core/db.py` | SQLite 저장/조회/통계 |

## 실행 규칙

반드시 프로젝트 루트(`C:\VisiPick`)에서 `-m` 모듈 방식으로 실행한다.

```powershell
cd C:\VisiPick

# 최초 1회 또는 DB 재생성
python -m src.utils.db_init

# MQTT 브로커
docker-compose -f config/docker-compose.yml up -d

# API 서버
python -m src.api.api_server

# FSM
python -m src.core.state_machine
```

Mock 환경:

```powershell
python -m mock.MockBroker
python -m mock.MockESP32
python -m mock.MockMyCobot
python -m mock.MockAGV
python -m src.core.state_machine
```

WPF 독립 개발용 더미 발행:

```powershell
python -m mock.mock_publisher
```

단독 테스트 도구:

```powershell
python -m tests.testsets
python -m tests.auto_test
python -m tests.gate_loop
python tools/test_ir_trigger.py
python tools/test_robot.py
python tools/test_agv.py
```

## REST / 영상 / 제어

API 서버:
- Swagger: `http://localhost:8000/docs`
- WebSocket: `/ws`
- MJPEG: `/video/top`, `/video/side`
- Snapshot: `/snapshot/top`, `/snapshot/side`

주요 제어 REST:

| API | 동작 |
|-----|------|
| `POST /api/vision/start` | 검사 활성화 |
| `POST /api/vision/stop` | 검사 비활성화 |
| `POST /api/conveyor/start` | 컨1/컨2 재가동, 비상정지 래치 해제, AGV emergency clear |
| `POST /api/conveyor/stop` | 컨1 정지 |
| `POST /api/emergency_stop` | FSM 일시정지, 컨베이어/게이트/AGV 정지 |
| `POST /api/gate/{gate_no}/push` | 수동 게이트 푸시 |
| `POST /api/robot/transfer` | 로봇 수동 이재 |
| `POST /api/agv/dispatch?agv_id=1` | AGV 수동 출발 |
| `POST /api/reset` | 레시피/트레이/게이트 큐/카운트 초기화 후 RUNNING |

## MQTT

| 토픽 | 페이로드 |
|------|----------|
| `visipick/inspection` | 검사 결과 JSON |
| `visipick/system/event` | 시스템 이벤트 JSON |
| `visipick/system/state` | FSM 상태 JSON |
| `visipick/system/cmd` | `{"action":"stop"}` 또는 `{"action":"reset"}` |
| `visipick/vision/cmd` | `{"action":"start"}` / `{"action":"stop"}` |
| `visipick/conveyor/cmd` | `{"action":"start"}` / `{"action":"stop"}` |
| `visipick/gate/cmd` | `{"type":"gate_cmd","gate":1,"action":"push"}` |
| `visipick/robot/cmd` | `{"type":"robot_cmd","action":"transfer"}` |
| `visipick/agv/{id}/status` | AGV 상태 JSON |
| `visipick/agv/{id}/command` | AGV plain string 명령 |

AGV command는 JSON이 아니라 plain string이다. 예: `GO_WAREHOUSE_1`, `TRAYS_READY_3`, `HOME1_BUSY`, `HOME1_FREE`, `LEAVE_HOME1_TO_START`, `EMERGENCY_STOP`, `EMERGENCY_CLEAR`.

## 설정 기준

현재 `config/config.json` 주요 값:

```json
{
  "vision": {
    "dummy_mode": false,
    "mode": "yolo",
    "yolo_model_path": "models/best.pt",
    "yolo_imgsz": 416,
    "inspect_frames": 10,
    "inspect_window_sec": 1.0,
    "defect_min_frames": 3
  },
  "cameras": {
    "top":  { "index": 0, "width": 1280, "height": 720, "fps": 60 },
    "side": { "index": 2, "width": 1280, "height": 720, "fps": 30 }
  },
  "stream": {
    "dir": "data/stream",
    "fps": 10,
    "publish_fps": 10,
    "label_hold_sec": 2.0
  },
  "conveyor": {
    "speed_cm_per_s": 1.5,
    "gate_delay_offset_sec": -7.5,
    "last_part_drop_sec": 39.0,
    "tray_advance_ms": 2150
  },
  "serial": {
    "port": "COM5",
    "baudrate": 115200,
    "dummy_mode": false
  },
  "robot": {
    "host": "192.168.0.17",
    "port": 9000,
    "dummy_mode": false,
    "path_file": "config/robot_path.json"
  },
  "agv": {
    "count": 2,
    "dummy_mode": false,
    "trays_per_load": 3,
    "initial_home": { "2": 1 }
  },
  "mqtt": {
    "broker": "192.168.0.15",
    "port": 1883
  },
  "system": {
    "demo_cycles": 50,
    "autorun_fsm": false
  }
}
```

## 데이터베이스

DB 위치: `data/visipick.db`

초기화:

```powershell
python -m src.utils.db_init
```

테이블:
- `InspectionResults`
- `RecipeSessions`
- `AgvMissions`
- `SystemEvents`

`src/core/db.py`에는 `uncertain_count` 통계가 있다. 다만 현재 WPF 호환 때문에 `UNCERTAIN`이 `DUPLICATE` 라벨로 합쳐져 저장될 수 있다.

## 로봇/AGV 현재 구조

로봇:
- `src/devices/robot.py`
- real mode는 RPi4의 myCobot 280 공식 소켓 서버 `9000` 사용
- `config/robot_path_1.json`, `robot_path_2.json`, `robot_path_3.json` 슬롯별 경로 사용 가능
- 교시 도구: `tools/robot_teach.py`

AGV:
- `src/core/agv_mqtt.py`
- `trays_per_load=3`이면 트레이 3개 적재 후 `dispatch()`
- 창고 도착 후 ESP32 펌웨어가 자동 복귀하는 흐름을 기준으로 함
- 홈 슬롯 점유표는 Python이 마스터 권위로 관리

## 비상정지

현재 비상정지는 프로그램 종료가 아니라 **일시정지**다.

동작:
- `POST /api/emergency_stop` 또는 `visipick/system/cmd {"action":"stop"}`
- 컨1/컨2/컨3/게이트 정지
- AGV 전체 `EMERGENCY_STOP`
- 게이트 예약 큐 clear
- FSM 상태 `EMERGENCY_STOP`

재개:
- `POST /api/conveyor/start`
- 컨1 속도 복구
- 컨2 반환 컨베이어 재가동
- AGV `EMERGENCY_CLEAR`
- 비전 검사 활성화
- FSM `RUNNING`

물리 비상정지 버튼 콜백은 현재 `state_machine.py`에서 비활성화되어 있다. 주석상 이유는 모터 EMI 노이즈 오발화 방지다. 펌웨어 디바운스/RESET 안정화 후 다시 연결할 수 있다.

## 코딩 규칙

- 실행은 루트에서 `python -m ...` 사용
- 임포트는 `from src...` 패키지 기준 사용
- TCP/Serial JSON 전송은 `json.dumps(..., ensure_ascii=False) + "\n"` 사용
- 설정은 `src.utils.config_loader.config`에서 읽기
- 로깅은 `from src.utils.logger import setup_logger`
- `setup_logger()` 이후 임의 `logger.add()` 중복 호출 금지
- WPF/AGV/수동제어 이벤트는 MQTT 경유
- 실제 물리 게이트 판단은 `state_machine.py`를 기준으로 확인

## 디버깅

| 증상 | 확인 |
|------|------|
| `ModuleNotFoundError: No module named 'src'` | 루트에서 `python -m ...`로 실행 |
| ESP32 포트 오류 | `python -m serial.tools.list_ports -v`, `config.serial.port`, Arduino Serial Monitor 닫기 |
| MQTT connection refused | `docker-compose -f config/docker-compose.yml up -d`, 브로커 IP/방화벽 확인 |
| Camera1/2 열기 실패 | USB 인덱스 확인, `tools/list_cameras.py`, config camera index 수정 |
| 영상 안 나옴 | FSM 실행 여부, `data/stream/top.jpg`, `/snapshot/top` 확인 |
| 검사 로그 안 나옴 | `[진단]` 로그에서 트리거 수신, 디바운스, `state=RUNNING`, inspect lock 확인 |
| 게이트가 반대로 동작 | `state_machine.py` 물리 매핑 확인. 현재 Gate1=불량, Gate2=중복/보류 |
| 로봇 timeout | `config.robot.host`, Pi 공식 소켓 서버 9000, robot_path 파일 확인 |
| AGV 미수신 | AGV Wi-Fi, 브로커 `192.168.0.15:1883`, topic 문자열 확인 |
| WPF 원격 접속 실패 | 방화벽 8000/1883, 교실 Wi-Fi AP isolation, Tailscale 사용 |

## WPF 원격 접속

교실 Wi-Fi가 PC 간 직접 통신을 막으면 Tailscale을 사용한다.

서버 PC:

```powershell
New-NetFirewallRule -DisplayName "VisiPick API 8000" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow
New-NetFirewallRule -DisplayName "VisiPick MQTT 1883" -Direction Inbound -LocalPort 1883 -Protocol TCP -Action Allow
tailscale ip -4
```

WPF PC는 서버의 Tailscale IP로 접속한다.

## 현재 상태

### GitHub

- 저장소: https://github.com/sunjin4682-ops/VisiPick
- 현재 로컬 브랜치: `feat/jetson-migration`
- 참고: `jetson/` 폴더는 존재하지만 현재 주요 런타임은 Windows/PC 기준 `src/`, `mock/`, `Hardware-Connect/esp32/`이다. Jetson을 실제 운용하지 않는다면 브랜치명은 `main` 병합 후 정리해도 된다.

### 구현 상태

- FastAPI + WebSocket + REST 제어 + MJPEG 영상 송출 구현
- SQLite WAL DB 레이어 구현
- YOLO 상부 검사 구현 (`models/best.pt`)
- 측면 카메라/핀검사 구현, 현재 최종 판정 미반영
- 멀티프레임 검사 구현 (`inspect_frames=10`, `defect_min_frames=3`)
- 비상정지 일시정지/재개 흐름 구현
- 컨3 트레이 전진 `duration_ms` 전달 구현
- 트레이 3개 적재 후 AGV dispatch 구현
- AGV 홈 점유표 및 START 호출 흐름 구현
- MockBroker/MockESP32/MockMyCobot/MockAGV 보유

### 다음 작업

- 실제 코드 주석/테스트의 legacy 게이트 명칭 정리 (`serial_ctrl.py`, `api_server.py`, `tests/testsets.py`, `tests/test_vision_integration.py`)
- Gate1/Gate2 실물 배선과 `state_machine.py` 매핑 최종 확인
- `gate_delay_offset_sec`, `gate_part_offset_sec`, `last_part_drop_sec`, `tray_advance_ms` 실측 튜닝
- 물리 비상정지 버튼 콜백 재활성 여부 결정 및 ESP32 E-Stop 디바운스/RESET 안정화
- 측면 핀검사 백라이트 확보 후 최종 판정 반영 여부 결정
- 로봇 슬롯별 경로(`robot_path_1/2/3.json`) 최종 교시 및 Pi 소켓 서버 확인
- AGV 펌웨어 명령/상태 문자열과 `agv_mqtt.py` 정규화 로직 최종 동기화
- 브랜치명 정리: Jetson 미사용이면 `feat/jetson-migration`을 `main`에 병합하고 문서의 브랜치 표기도 `main`으로 변경
