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
| USB Serial → ESP32 | 게이트 푸셔(Gate1·Gate2) + 컨1 스텝모터 + 컨2 중복반환 + 컨3 트레이공급 |
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
┌─ DUPLICATE → Gate1 푸셔 → 컨2(중복 부품 반환 컨베이어)
├─ DEFECT    → Gate2 푸셔 → Reject bin
└─ NEEDED    → 통과 → 컨1 끝단 낙하 → 트레이 수집
                      ↓
             레시피 4종 충족?
                      ↓ YES
             [myCobot: 완성 트레이 → AGV] + 컨3(다음 빈 트레이 공급)
                      ↓
             [AGV → 창고 → 지게(서보 25°) 쏟아내기]

[Python Central Server + C# WPF HMI + SQLite]
```

### 컨베이어 3종 역할
| # | 모터 | 역할 |
|---|------|------|
| 컨1 | 스텝모터(PUL14/DIR12) | 메인 검사 라인 — 부품이 카메라 밑을 Non-stop 통과, 게이트로 분류 (cm/s 제어) |
| 컨2 | A모터(L9110S 26/27) | 중복 부품 반환 — 채우는 트레이에 이미 있는 중복(DUPLICATE) 부품을 돌려보냄 (상시 ON) |
| 컨3 | B모터(L9110S 32/33) | 다음 빈 트레이 공급 — 트레이가 찰 때마다 다음 빈 트레이를 수집 위치로 이동 (`tray_cmd` → 2초) |

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

## 레시피 부품 (확정 — 4종)

상부 YOLO(`best.pt`, 7클래스)로 종류·불량 식별. 측면(OpenCV)은 핀 있는 부품만 핀휨 검사.

| # | 부품 | YOLO 클래스 | 측면 핀검사 |
|---|------|-------------|-------------|
| 1 | IC칩 | `IC` | O — down 모드(핀 아래) |
| 2 | 터미널블록 | `TB` | O — toward_camera 모드(핀이 카메라 향함) |
| 3 | 방열판 | `HS` | X |
| 4 | 커패시터 | `CAP` | X |

불량 클래스(3종): `Broken`(파손) · `Dented`(찌그러짐) · `Pinbent`(핀휨) → REJECT.
config: `recipe.parts = ["IC칩","터미널블록","방열판","커패시터"]`, `vision.pin_inspector.inspect_parts = ["IC","TerminalBlock"]`.

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

> ⚠️ **반드시 `-m` 모듈 방식으로 실행** (슬래시 경로 직접 실행 금지)
> `src/`가 정식 패키지(`__init__.py`)라 `from src.utils...` 임포트를 쓴다.
> `python src/api/api_server.py` 처럼 실행하면 **`ModuleNotFoundError: No module named 'src'`** 발생.
> 항상 루트(`C:\VisiPick`)에서 `python -m src.api.api_server` 형식(점 구분, `.py` 없음)으로 실행할 것.
> (불가피하게 슬래시로 실행해야 하면 `$env:PYTHONPATH="C:\VisiPick"` 먼저 설정)

```powershell
# 1. MQTT 브로커
docker-compose -f config/docker-compose.yml up -d

# 2. Mock 서버 3개 (Mock 환경)
python -m mock.MockESP32       # port 9001
python -m mock.MockMyCobot     # port 9002
python -m mock.MockAGV         # port 9003

# 3. 메인 실행 (FSM)
python -m src.core.state_machine

# 4. API 서버
python -m src.api.api_server   # http://localhost:8000/docs

# 5. WPF 독립 개발용 더미 발행
python -m mock.mock_publisher

# 6. DB 초기화 (최초 1회)
python -m src.utils.db_init

# 7. DB 백업
powershell scripts/backup.ps1
```

### 전체 가동 순서 (실하드웨어)
1. **브로커** — Docker Desktop 에서 `visipick-mqtt` Running 확인 (또는 위 1번 명령)
2. **API 서버** — `python -m src.api.api_server` (별도 터미널, 켜둠)
3. **FSM** — `python -m src.core.state_machine` (또 별도 터미널, 켜둠)
4. 부품 투입 → IR 트리거 → 검사 시작
* ESP32(COM5)·카메라 연결 + 아두이노 시리얼 모니터 닫기(포트 점유) 선행
* ESP32 없이 WPF 연동만 테스트: `config.serial.dummy_mode=true` (단 IR 트리거 없어 자동검사 X)

## 통신 프로토콜

| 프로토콜 | 방향 | 엔드포인트 | 포맷 |
|----------|------|------------|------|
| USB Serial | PC ↔ ESP32 | COM5, 115200 baud | JSON + `\n` |
| Ethernet TCP | PC ↔ myCobot | RPi4 IP:9000 (공식 소켓 서버) | pymycobot |
| MQTT | PC ↔ AGV 1·2 | 192.168.0.15:1883 | 문자열 명령 / JSON 상태 |
| WebSocket | Python ↔ WPF | :8000/ws (서버 IP) | JSON |
| HTTP/REST | Client ↔ API | :8000 (서버 IP) | JSON |

## WPF 원격 접속 / 네트워크 (Tailscale 필수)

> ⚠️ **WPF가 다른 PC면 교실 Wi-Fi(`moble_classroom`)에서 직접 접속 안 됨 → Tailscale 필요.**
> 교실/공용 Wi-Fi는 **클라이언트 격리(AP isolation)**가 켜져 있어 같은 SSID라도 PC↔PC 직접 통신을 막는다.
> 공유기 설정을 못 바꾸므로 **Tailscale VPN**으로 우회하는 게 표준 해법.

서버는 `0.0.0.0` 으로 바인딩(API `uvicorn ... host=0.0.0.0`, 브로커 Docker `0.0.0.0:1883`)되어 있어
**Python 코드 수정 없이** LAN IP·Tailscale IP 둘 다로 접속 가능하다. 막는 건 네트워크/방화벽뿐.

**진단 순서 (WPF PC에서):**
1. `ping 192.168.0.15` → 응답 없으면 교실 Wi-Fi가 PC끼리 막는 것 → **Tailscale**
2. `Test-NetConnection 192.168.0.15 -Port 8000` → False면 방화벽/네트워크
3. 서버 PC 방화벽 인바운드 8000·1883 개방 필요:
   ```powershell
   New-NetFirewallRule -DisplayName "VisiPick API 8000" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow
   New-NetFirewallRule -DisplayName "VisiPick MQTT 1883" -Direction Inbound -LocalPort 1883 -Protocol TCP -Action Allow
   ```

**Tailscale 설정:**
- 두 PC 모두 https://tailscale.com/download 설치 → **같은 계정**으로 로그인
- 서버 PC IP 확인: `tailscale ip -4` (예: `100.x.x.x`)
- **WPF 접속 주소를 서버의 Tailscale IP(`100.x.x.x`)로** — MQTT `:1883`, 영상/REST `:8000`
- AGV 는 계속 교실 LAN(`192.168.0.15:1883`)으로 붙어도 됨(같은 브로커, 무관)

## MQTT 토픽

| 토픽 | 방향 | 페이로드 예시 |
|------|------|--------------|
| `visipick/inspection` | vision → all | `{"part":"IC","classification":"NEEDED","verdict":"PASS","defect_codes":[],"confidence":0.97}` |
| `visipick/agv/{id}/status` | AGV → all | `{"agv_id":"AGV_1","status":"TRACKING","next_action":"ARRIVED_WAREHOUSE_1","node":"WAREHOUSE_1","selected_home":1,"home1_free":false}` |
| `visipick/agv/{id}/command` | PC → AGV | **문자열**: `GO_WAREHOUSE_1` · `TRAY_LOADED` · `GO_HOME_1` · `CLEAR_MISSION` · `EMERGENCY_STOP` |
| `visipick/system/event` | any → WPF | `{"source":"Camera1","event_type":"INFO","message":"IC 검출"}` |
| `visipick/system/state` | SM → WPF | `{"state":"RUNNING","timestamp":"..."}` |

> AGV `command` 는 **plain string**(JSON 아님). status 는 JSON. `next_action` 의 `ARRIVED_WAREHOUSE_1/2`·`ARRIVED_HOME` 가 도착 이벤트. 전체 필드는 `agv_mqtt.py` 주석 참고.

## 설정 (config/config.json 주요 키)

```json
{
  "cameras": {
    "top":  { "index": 0, "width": 1280, "height": 720, "fps": 60, "square_crop": true },
    "side": { "index": 1, "width": 1280, "height": 720, "fps": 30 }
  },
  "conveyor": {
    "speed_cm_per_s": 1.5,
    "gate_delay_offset_sec": -7.5,
    "last_part_drop_sec": 35.0,
    "tray_advance_ms": 2000
  },
  "serial":   { "port": "COM5", "baudrate": 115200, "dummy_mode": false },
  "robot":    { "host": "192.168.0.47", "port": 9000, "speed": 80, "dummy_mode": true },
  "mqtt":     { "broker": "192.168.0.15", "port": 1883 },
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

- 콘솔: 색상 코딩 (UTF-8 — `reconfigure(encoding='utf-8')` 적용, isatty 보존)
- 파일: 00:00 일별 롤링, 30일 보존, `colorize=False` 명시

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
| ESP32 응답 없음 / `could not open port 'COM5'` | COM5 연결·드라이버(CH340/CP210x) 확인, 아두이노 시리얼 모니터 닫기. `python -m serial.tools.list_ports -v` 로 실제 포트 확인 후 `config.serial.port` 수정 |
| MQTT connection refused | `docker-compose -f config/docker-compose.yml up -d` (Docker `visipick-mqtt` Running) |
| myCobot timeout | `config["robot"]` host/port(9000, 공식 소켓 서버) 확인. Pi 에서 소켓 서버 실행 필요 |
| AGV MQTT 미수신 | AGV Wi-Fi(`moble_classroom`) + 브로커 IP `192.168.0.15` 확인 |
| WPF 가 서버에 접속 안 됨 | 방화벽 8000·1883 개방 + 교실 Wi-Fi 격리 → **Tailscale**(위 "WPF 원격 접속" 섹션) |
| `ModuleNotFoundError: No module named 'src'` | 슬래시 실행 금지 → `python -m src.api.api_server` 형식으로 |
| 한글 깨짐 | `logger.py` — `sys.stdout/stderr.reconfigure(encoding='utf-8')` 호출 여부 확인 |
| ImportError: src.utils… | 실행 디렉토리가 `C:\VisiPick` 인지 확인 |
| 게이트 타이밍 오차 | `config["gates"]["1"]["delay_sec"]` 실측 후 조정 (카메라→게이트 거리 / 컨베이어 속도) |

## 현재 상태 (업데이트 시 이 섹션만 수정)

### GitHub
- 저장소: https://github.com/sunjin4682-ops/VisiPick
- 브랜치: `feat/jetson-migration`
- 마지막 커밋: `835a796` (feat(fsm,vision): 비상정지 일시정지화 + 복수 불량 전송)

### 설계 버전
- **V6.5** (2026-06-03 통합 로드맵 반영) — 헤드리스 우선 통합 래더
- **V6.3** (2026-05-22 반영)
- V6.2 대비: 푸셔 게이트 2개, 2단계 검사(상부+측면), 중력 수집, 트레이 단위 이재, MQTT AGV, Python 단일 마스터

### 구현 상태
- ✅ FastAPI + WebSocket (`src/api/api_server.py`) — `POST /api/emergency_stop` 포함
- ✅ SQLite DB 레이어 (`src/core/db.py`) — V6.3 스키마
- ✅ AGV MQTT 매니저 (`src/core/agv_mqtt.py`)
- ✅ Mock Publisher (`mock/mock_publisher.py` — WPF 독립 개발용)
- ✅ `config/config.json` V6.3 키 구조 + 게이트 타이밍 실측값 (Gate1: 20.0s, Gate2: 30.0s)
- ✅ `src/utils/db_init.py` — RecipeSessions 포함 4 테이블
- ✅ `src/vision/` — `classifier.py`, `defect_detector.py`, `camera_top.py`, `camera_side.py` (더미 모드)
- ✅ Camera1(상부) 실제 YOLO 파이프라인 — `best.pt` 7클래스(F1 0.97), `camera_util.py` 공통화로 라이브뷰·production 동일 처리(DSHOW+노출+정사각 크롭), fps 개선(imgsz 416) (2026-06-01)
- ✅ `src/orchestrator/` — `decision.py`, `recipe_mgr.py`, `tray_mgr.py`
- ✅ `src/devices/` — `robot.py`, `serial_ctrl.py` (센서 콜백 수신 루프 + `advance_tray()` 포함)
- ✅ `state_machine.py` — 센서 트리거 기반 FSM, 게이트 지연 큐, 비상정지(`State.EMERGENCY_STOP`), 컨1 비정지 운행
- ✅ `mock/MockESP32.py` — sensor_triggered 자동 발행 + conveyor_cmd / tray_cmd 응답
- ✅ 더미 모드 end-to-end 2사이클 테스트 PASS (2026-05-23)
- ✅ `src/utils/logger.py` — 파일 로그 포맷 버그(`{{...}}`) 수정 + `reconfigure()` 기반 UTF-8 인코딩 안정화 (2026-05-27)
- ✅ Mock 환경 전체 플로우 재검증 PASS — IDLE→RUNNING→TRAY_TRANSFER→COMPLETE 사이클 확인 (2026-05-27)
- 🔄 Camera1·Camera2 실제 OpenCV 파이프라인 — 더미 모드만 구현, 실제 하드웨어 미구현

#### V6.5 통합 로드맵 (2026-06-03)
- ✅ **C1** `decision.py` — `Verdict.UNCERTAIN` 추가: 저신뢰/미검출을 REJECT(Gate2 폐기)가 아닌 **Gate1 반환**(재투입)으로. `db.get_stats().uncertain_count` 추가. (`tests/testsets.py` 6/6 PASS)
- ✅ **C2** `agv_mqtt.py` — 창고 도착 → 하역(UNLOAD) → **N1 복귀 dispatch** 라운드트립. `_pending` 에 phase(outbound/returning) 추적.
- ✅ **로봇팔** `src/devices/robot.py` — pymycobot `MyCobot280Socket` 드롭인(실로봇 공식 소켓 서버 **9000**, 지연연결+웨이포인트 폴링+그리퍼). dummy=MockMyCobot(9002) 유지. config `robot` 에 그리퍼·자세각(티칭 대기 0)·joint_limits 키 추가.
- ✅ **REST 제어**(WPF W2) `api_server.py` — `POST /api/gate/{n}/push · /api/robot/transfer · /api/agv/{cmd} · /api/reset` + FSM MQTT 핸들러(gate/cmd·robot/cmd·system reset). `autorun_fsm` opt-in startup 훅.
- ✅ `mock/MockAGV.py` — TCP→**MQTT** 재작성(agv_mqtt 짝). `mock/MockBroker.py` — 순수 파이썬 MQTT 브로커(테스트용, docker/mosquitto 불필요).
- ✅ `tests/auto_test.py` — 신 FSM(`start()`/`run_cycle()`)용 자급식 헤드리스 드라이버. **50/50 PASS · DB 522행 · 예외 0** (2026-06-03).
- ✅ `state_machine.py` — `start()`/`run_cycle()` 분리, UNCERTAIN→Gate1, 수동제어 MQTT 핸들러, `_reset()`.

#### Phase 1 하드웨어 브링업 (2026-06-03)
실 ESP32(COM5)+ELP 카메라로 검사·분류·게이트 실가동. 주요 변경:
- ✅ **프레임 그래버** `camera_top.py` — 백그라운드 스레드로 최신 프레임만 유지 → 버퍼 누적으로 검사 결과 밀리던 문제 해결. `camera_util` BUFFERSIZE=1.
- ✅ **멀티프레임 보수 판정** `state_machine._inspect_one` — 1초/5프레임 추론 후 하나라도 불량이면 DEFECT(각도 의존 불량 누락 방지). `vision.inspect_frames`/`inspect_window_sec`.
- ✅ **불량 우선 판정** `classifier.classify()` — argmax 단일박스 → 모든 박스 검사, 불량 박스 있으면 REJECT 우선.
- ✅ **IR 트리거 지연** `sensor.trigger_to_capture_sec` — 센서가 카메라보다 앞일 때 부품 진입 대기 후 추론. `tools/test_ir_trigger.py` 단독 검증 도구.
- ✅ **게이트 타이밍** — 기준시점을 검사 시작(t0)으로(검사 1초와 무관), `conveyor.gate_delay_offset_sec` 실측 오프셋. **역할 스왑: Gate1=불량 폐기, Gate2=중복/보류 반환**.
- ✅ **연속 운전** — 로봇 이송 실패 비치명 처리 + 리셋 보장 → 한 트레이 후 종료 안 하고 다음 트레이로(demo_cycles까지).
- ✅ **마지막 부품 낙하 대기** `conveyor.last_part_drop_sec` — 레시피 완성 후 4번째 양품이 트레이에 떨어질 때까지 대기 후 이재.
- ✅ **트레이 이재 순서** — 컨3 1칸 전진 → 로봇 AGV 이재 → AGV 출발.
- ✅ **컨3 이동시간 config화** `conveyor.tray_advance_ms` — `tray_cmd.duration_ms`로 전송, `esp32.ino`/MockESP32가 그 시간만큼 구동(없으면 기본 2초). **펌웨어 1회 재업로드 필요**.
- 🔄 진단 중: 실가동 시 검사 로그 미출력 케이스 — `[진단]` INFO 로그로 트리거→검사 추적 중.

#### Phase 1 추가 (2026-06-04)
- ✅ **MJPEG 실시간 영상** — `frame_bus.py`(파일 기반 프레임 버스) + `api_server` `/video/{top,side}`·`/snapshot/{name}`. `state_machine` 연속 송출 스레드(`stream.publish_fps`, 검사 라벨 오버레이 `label_hold_sec`). 송출=원본 1280x720(`camera_top.capture_full`), 검사=정사각 크롭. Windows `os.replace` 충돌 재시도.
- ✅ **비상정지 = 일시정지(종료X)** — `run()`/`run_cycle` 대기 루프가 정지 시 종료 대신 해제 대기. 재개: **컨베이어 시작**(래치 해제+RUNNING) + **비전 시작**(검사 재활성화). 진행 중 레시피/트레이 유지.
- ✅ **복수 불량 전송** — IC 의 Pinbent+Broken 등 2종 이상 시 `payload.defect_codes`(리스트) 추가. `classifier.defect_classes` + `decision.defect_codes_for`. `defect_code`(단일)는 하위호환 유지.
- ✅ **WPF 인수인계** — MQTT(상태)/REST(제어)/MJPEG(영상) 정리. Tailscale 로 유선/무선 다른 망 PC 접속 가능.

### 다음 작업
- [ ] 실가동 검사 로그 미출력 원인 규명 (트리거 수신/락 점유/카메라 프레임 — `[진단]` 로그 확인)
- [ ] 게이트 딜레이·`last_part_drop_sec`·`tray_advance_ms` 실측 튜닝 완료
- [ ] `esp32.ino` 재업로드 (tray_cmd duration_ms 반영)
- [ ] **C3** AGV 펌웨어(신규) — IR 8ch PID + RC522 + MQTT(GO/UNLOAD/복귀) + 지게 서보 (박은수, 최대 리스크)
- [ ] **C4** `esp32.ino` — E-Stop attachInterrupt + volatile 플래그 + 명시적 RESET (박은수)
- [ ] 로봇 4자세 티칭 → `config.robot.{pickup,lift,place,home}_angles` 기입 + Pi 공식 소켓 서버 실행 + `pip install pymycobot`
- [ ] imgsz=416 에서 약한 클래스(부서진 칩/휜 핀) 검출 유지 확인 (저하 시 512 상향 또는 재학습)
- [ ] Camera2 측면 핀 검사 OpenCV 파이프라인 (실제 하드웨어) — `camera_util.py` 재활용
- [ ] Phase 2 래더: dummy_mode 한 칸씩 false 전환(serial→vision→robot→agv) 하드웨어 통합
- [ ] `config["gates"]["1/2"]["delay_sec"]` 정밀 실측 (현재 20.0/30.0은 이론값)
