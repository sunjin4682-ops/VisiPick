# CLAUDE.md

## 프로젝트 개요

**VisiPick V6.3** — 비정지(Non-stop) 컨베이어 위를 이동하는 DIP IC 4종을 2대의 카메라(상부+측면)로 실시간 검사하고, 레시피 기반으로 3클래스 자동 분류(필요+양품/중복/불량)한 뒤, 양품을 트레이에 중력 수집하고, myCobot이 완성된 트레이를 통째로 AGV에 이재하여 창고까지 운반하는 미니 스마트팩토리 셀이다.

| 기술 | 역할 |
|------|------|
| Python Central Server | 단일 마스터 — 모든 상태의 Single Source of Truth |
| C# WPF | Pure Display Client (WebSocket 수신·표시만) |
| MQTT (Mosquitto) | AGV 통신 + 내부 이벤트 브로드캐스트 |
| FastAPI + WebSocket | HMI 통신 (:8000) |
| SQLite WAL | 데이터 영속성 (4 테이블) |
| USB Serial → ESP32 | 게이트 푸셔(Gate1·Gate2) + 컨1 스텝모터 |
| Ethernet TCP → RPi4 | myCobot 트레이 이재 제어 (pymycobot) |

## 시스템 전체 흐름

```
[DIP IC 15개, 4초 간격 투입]
        ↓
[컨1: 싸이피아 A2 800mm — Non-stop 1~2cm/s]
        ↓
Camera1(상부): 종류 식별 + 레시피 매칭 + 1차 불량
Camera2(측면): 핀 휘어짐/들뜨 정밀 검사
        ↓
┌─ DUPLICATE → Gate1 푸셔 → 반환 bin
├─ DEFECT    → Gate2 푸셔 → Reject bin
└─ NEEDED    → 통과 → 컨1 끝단 낙하
                      ↓
             [컨2 트레이 대기열]
             레시피 4종 충족?
                      ↓ YES
             [myCobot: 완성 트레이 → AGV]
                      ↓
             [AGV → 창고 → 지게(서보 25°) 쏟아내기]

[Python Central Server + C# WPF HMI + SQLite]
```

| Phase | 담당 모듈 | 통신 |
|-------|-----------|------|
| 1 — 검사·분류·게이트 | `vision/` + `orchestrator/` + `core/state_machine.py` | USB Serial → ESP32 |
| 2 — 트레이 이재 | `devices/robot.py` | Ethernet TCP → RPi4 → pymycobot |
| 3 — AGV 운반 | `devices/agv_mqtt.py` | MQTT → AGV ESP32-CAM |

## 3클래스 판정 로직

```python
# orchestrator/decision.py
def judge(part_type, defect_result, recipe_state) -> str:
    if defect_result.is_defect:           return "DEFECT"     # Gate2 푸셔
    if not recipe_state.needs(part_type): return "DUPLICATE"  # Gate1 푸셔
    return "NEEDED"                                            # 통과 → 트레이
```

## DIP IC 레시피(현재는 IC칩, 방열판, 터미널블록, 커패시터를 쓰고 부품 변경은 계획중)

| # | 부품 | 패키지 | 식별 방법 |
|---|------|--------|-----------|
| 1 | NE555P | DIP-8 | 면적 + 핀 수 (8개) |
| 2 | CD4017BE | DIP-16 | 면적 + 마킹 "4017" |
| 3 | ATmega328P | DIP-28 | 면적 + 핀 수 (28개) |
| 4 | 74HC595N | DIP-16 | 면적 + 마킹 "595" |

## 디렉토리 구조

```
C:\VisiPick\
├── config/                  # config.json, docker-compose.yml
├── data/                    # visipick.db (SQLite WAL)
├── docs/                    # 기술 문서
├── logs/                    # 날짜별 롤링 로그 (loguru)
├── mock/                    # MockESP32.py · MockMyCobot.py · MockAGV.py
├── mosquitto/               # Mosquitto 설정·데이터
├── scripts/                 # backup.ps1
├── src/
│   ├── core/                # state_machine.py · db.py · agv_mqtt.py
│   ├── vision/              # camera_top.py · camera_side.py · classifier.py · defect_detector.py
│   ├── orchestrator/        # decision.py · recipe_mgr.py · tray_mgr.py
│   ├── devices/             # robot.py · serial_ctrl.py
│   ├── api/                 # api_server.py (FastAPI + WebSocket)
│   └── utils/               # logger.py · config_loader.py · heartbeat.py · db_init.py
├── tests/                   # auto_test.py · testsets.py
└── .venv/
```

## 주요 파일

| 파일 | 역할 | 핵심 함수/클래스 |
|------|------|-----------------|
| `src/core/state_machine.py` | 전체 공정 FSM | `IDLE→RUNNING→TRAY_TRANSFER→COMPLETE` |
| `src/core/db.py` | SQLite I/O 전담 | `save_inspection()`, `save_recipe_session()`, `get_*()` |
| `src/core/agv_mqtt.py` | AGV MQTT 매니저 | `AGVMqttManager.dispatch()`, `get_status()` |
| `src/vision/camera_top.py` | Camera1 상부 캡처·전처리 | 종류 식별 + 레시피 매칭 + 1차 불량 |
| `src/vision/camera_side.py` | Camera2 측면 캡처·전처리 | 핀 휘어짐/들뜨 정밀 검사 |
| `src/vision/classifier.py` | DIP IC 4종 분류기 | `classify(frame)` → PartType |
| `src/vision/defect_detector.py` | 불량 검출기 | `detect(frame)` → DefectCode |
| `src/orchestrator/decision.py` | 3클래스 판정 | `judge()` → NEEDED/DUPLICATE/DEFECT |
| `src/orchestrator/recipe_mgr.py` | 레시피 매칭 | `needs()`, `mark_collected()`, `is_complete()` |
| `src/orchestrator/tray_mgr.py` | 트레이 수집 카운트 | `on_part_passed()` |
| `src/devices/robot.py` | myCobot TCP 제어 | `transfer_tray()` |
| `src/devices/serial_ctrl.py` | ESP32 시리얼 | `push_gate(gate_id)`, `set_conveyor_speed()` |
| `src/api/api_server.py` | FastAPI + WebSocket | REST + WS `:8000/docs` |
| `src/utils/logger.py` | 로깅 추상화 | `setup_logger(name)` |
| `src/utils/config_loader.py` | 설정 로드 | `config` 딕셔너리 |

## 실행 명령

```bash
# 1. MQTT 브로커
docker-compose -f config/docker-compose.yml up -d

# 2. Mock 서버 3개 (Mock 환경)
python mock/MockESP32.py       # port 9001
python mock/MockMyCobot.py     # port 9002
python mock/MockAGV.py         # port 9003

# 3. 메인 실행
python src/core/state_machine.py

# 4. API 서버
python src/api/api_server.py   # http://localhost:8000/docs

# 5. WPF 독립 개발용 더미 발행
python mock_publisher.py

# 6. DB 초기화 (최초 1회)
python -m src.utils.db_init

# 7. DB 백업
powershell scripts/backup.ps1
```

## 통신 프로토콜

| 프로토콜 | 방향 | 엔드포인트 | 포맷 |
|----------|------|------------|------|
| USB Serial | PC ↔ ESP32 | COM8, 115200 baud | JSON + `\n` |
| Ethernet TCP | PC ↔ myCobot | RPi4 IP:9002 | pymycobot |
| MQTT | PC ↔ AGV 1·2 | localhost:1883 | JSON |
| WebSocket | Python ↔ WPF | localhost:8000/ws | JSON |
| HTTP/REST | Client ↔ API | localhost:8000 | JSON |

## MQTT 토픽

| 토픽 | 방향 | 페이로드 예시 |
|------|------|--------------|
| `visipick/inspection` | vision → all | `{"part_type":"NE555P","classification":"NEEDED","defect_code":"PASS","confidence":0.97}` |
| `visipick/agv/{id}/status` | AGV → all | `{"agv_id":1,"state":"moving","node":"N3","timestamp":"..."}` |
| `visipick/agv/{id}/command` | PC → AGV | `{"action":"GO","destination":"WAREHOUSE","timestamp":"..."}` |
| `visipick/system/event` | any → WPF | `{"source":"Camera1","event_type":"INFO","message":"NE555P 검출"}` |
| `visipick/system/state` | SM → WPF | `{"state":"TRAY_TRANSFER","timestamp":"..."}` |

## 설정 (config/config.json 주요 키)

```json
{
  "cameras": {
    "top":  { "index": 0, "width": 1920, "height": 1080, "fps": 90 },
    "side": { "index": 1, "width": 1920, "height": 1080 }
  },
  "conveyor": {
    "speed_cm_per_s": 1.5,
    "gate1_delay_ms": 0,
    "gate2_delay_ms": 0
  },
  "serial":   { "port": "COM8", "baudrate": 115200 },
  "robot":    { "host": "192.168.0.47", "port": 9002, "speed": 80 },
  "mqtt":     { "broker": "localhost", "port": 1883 },
  "recipe":   { "parts": ["IC칩", "터미널블록", "방열판", "커패시터"] },
  "database": { "path": "C:\\VisiPick\\data\\visipick.db",
                "retention_days_inspection": 30,
                "retention_days_events": 7 }
}
```

## 데이터베이스

- 위치: `data/visipick.db` (WAL 모드)
- 초기화: `python -m src.utils.db_init`
- 테이블 4개:

| 테이블 | 보존 | 주요 컬럼 |
|--------|------|-----------|
| `InspectionResults` | 30일 | PartType, Classification, DefectCode, Confidence, CycleTimeMs, GateAction |
| `RecipeSessions` | 무제한 | StartedAt, CompletedAt, Slot1~4Part, AgvId |
| `AgvMissions` | 무제한 | AgvId, Source, Destination, RecipeSessionId |
| `SystemEvents` | 7일 | Source, EventType, Message |

## 로깅 규칙

```python
from src.utils.logger import setup_logger
logger = setup_logger("module_name")   # → logs/module_name-YYYY-MM-DD.log
```

- 콘솔: 색상 코딩 (UTF-8 — Windows CP949 래핑 적용)
- 파일: 00:00 일별 롤링, 30일 보존

## 코딩 규칙

- `import`: `from src.utils.logger import setup_logger` 형식 (루트 상대 임포트 금지)
- TCP 전송: `json.dumps(msg, ensure_ascii=False) + "\n"` — 한글 지원
- 설정값: 반드시 `config_loader.config["키"]`에서 읽기 (하드코딩 금지)
- `setup_logger()` 호출 후 `logger.add()` 재호출 금지 (핸들러 중복)
- 모듈 간 통신: MQTT 경유 (WPF·AGV와 동일한 방식, event_bus 불필요)

## 디버깅

| 증상 | 원인 / 해결 |
|------|------------|
| Camera1/2 인식 안 됨 | `index` 번호 확인 — USB 연결 순서에 따라 0/1이 바뀜 |
| ESP32 응답 없음 | `python mock/MockESP32.py` 실행 또는 COM8 연결 확인 |
| MQTT connection refused | `docker-compose -f config/docker-compose.yml up -d` |
| myCobot timeout | `config["robot"]` host/port 확인 (RPi4 IP) |
| AGV MQTT 미수신 | AGV ESP32-CAM Wi-Fi + Mosquitto 브로커 연결 확인 |
| 한글 깨짐 | `logger.py` UTF-8 래핑 확인 |
| ImportError: src.utils… | 실행 디렉토리가 `C:\VisiPick` 인지 확인 |
| 게이트 타이밍 오차 | `config["gates"]["1"]["delay_sec"]` 실측 후 조정 (카메라→게이트 거리 / 컨베이어 속도) |

## 현재 상태 (업데이트 시 이 섹션만 수정)

### GitHub
- 저장소: https://github.com/sunjin4682-ops/VisiPick
- 브랜치: `main`
- 마지막 커밋: `ed39fe6` (feat: V6.3 전면 구현)

### 설계 버전
- **V6.3** (2026-05-22 반영)
- V6.2 대비: 푸셔 게이트 2개, 2단계 검사(상부+측면), 중력 수집, 트레이 단위 이재, MQTT AGV, Python 단일 마스터

### 구현 상태
- ✅ FastAPI + WebSocket (`src/api/api_server.py`)
- ✅ SQLite DB 레이어 (`src/core/db.py`) — V6.3 스키마
- ✅ AGV MQTT 매니저 (`src/core/agv_mqtt.py`)
- ✅ Mock Publisher (`mock_publisher.py` — WPF 독립 개발용)
- ✅ `config/config.json` V6.3 키 구조 + 게이트 타이밍 실측값 (Gate1: 20.0s, Gate2: 30.0s)
- ✅ `src/utils/db_init.py` — RecipeSessions 포함 4 테이블
- ✅ `src/vision/` — `classifier.py`, `defect_detector.py`, `camera_top.py`, `camera_side.py` (더미 모드)
- ✅ `src/orchestrator/` — `decision.py`, `recipe_mgr.py`, `tray_mgr.py`
- ✅ `src/devices/` — `robot.py`, `serial_ctrl.py` (센서 콜백 수신 루프 포함)
- ✅ `state_machine.py` — 센서 트리거 기반 FSM, 게이트 지연 큐, 컨베이어 제어
- ✅ `mock/MockESP32.py` — sensor_triggered 자동 발행 + conveyor_cmd 응답
- ✅ 더미 모드 end-to-end 2사이클 테스트 PASS (2026-05-23)
- 🔄 Camera1·Camera2 실제 OpenCV 파이프라인 — 더미 모드만 구현, 실제 하드웨어 미구현

### 다음 작업
- [ ] Camera1 상부 OpenCV 분류 파이프라인 (실제 하드웨어)
- [ ] Camera2 측면 핀 검사 OpenCV 파이프라인 (실제 하드웨어)
- [ ] ESP32 실제 연결 후 `tests/testsets.py` 하드웨어 테스트
- [ ] `tests/auto_test.py` 50사이클 정식 실행
- [ ] `config["gates"]["1/2"]["delay_sec"]` 정밀 실측 (현재 20.0/30.0은 이론값)
