> **다음 세션 시작 시:** 이 파일을 읽고, 현재 상태를 파악한 뒤 다음 할 일을 제안해줘

---

# VisiPick 작업 로그

- **프로젝트명:** VisiPick
- **작업 시작일:** 2026-05-12
- **목표:** 스마트팩토리 부품 검사·분류 시스템 백엔드/인프라 구축 (8주차 Tier 1)

---

## 2026-05-12

### 완료된 작업 ✅

#### 기술 스택 결정
- Oracle → SQLite 전환 (개발 편의성, WAL 모드로 동시 읽기/쓰기 안전)
- TPS 계산 결과 최대 1~2 TPS → PostgreSQL은 오버스펙으로 판단

#### Mosquitto MQTT Broker 설치
- Docker Compose로 설치 (`C:\VisiPick\docker-compose.yml`)
- 포트: 1883 (MQTT), 9001 (WebSocket)
- 설정: `allow_anonymous true`
- 방화벽: `netsh advfirewall` 1883 포트 개방

#### SQLite 스키마 + EF Core
- NuGet: `Microsoft.EntityFrameworkCore.Sqlite 10.0.0`
- 테이블 3개: InspectionResults(9컬럼), AgvMissions(9컬럼), SystemEvents(5컬럼)
- 인덱스: Timestamp, Class, GateUsed, AgvId
- 마이그레이션: `dotnet ef migrations add InitSqlite`
- DB 경로: `C:\VisiPick\VisiPickData\visipick.db`
- 백업: `backup.ps1` (Windows 작업 스케줄러 매일 자정 등록)

#### Flask 백엔드 초기 구축
- 구조: main.py, app/api/routes.py, app/vision/detector.py, app/mqtt/publisher.py
- 더미 모드: 3초마다 가짜 검사 결과 MQTT 발행
- API: /health, /api/vision/start, /api/vision/stop, /api/inspection/save

---

### 이슈 및 주의사항 ⚠️
- 네트워크 분리 문제: 김선진(유선 이더넷 192.168.0.46), 박은수(무선 WiFi) → ESP32 MQTT 연결 실패 → 시리얼 전환 검토 시작

---

## 2026-05-14

### 완료된 작업 ✅

#### Flask → 순수 Python 전환
- Flask 제거 결정: WPF가 HTTP API 미사용, MQTT만 사용 → 웹 서버 오버헤드 불필요
- `vision_service.py` 단일 파일로 대체
  - MQTT 발행: factory/visipick/inspection, agv/{id}/status, system/event
  - SQLite 직접 저장 (WAL 모드)
  - 백그라운드 스레드: inspection_loop(3초), agv_loop(AGV 2대 N1→N5)

#### Mock 시뮬레이터
- `mock/MockMyCobot.py` (port 9002) — TCP 소켓, robot_cmd 수신 → 2초 시뮬 → robot_ack
- `mock/MockAGV.py` (port 9003) — TCP 소켓, agv_cmd 수신 → N1→N5 순차 이동 → arrived
- `test_client.py` — 3개 Mock 통합 테스트, 정상 응답 확인

#### StateMachine (상태 머신)
- 상태: IDLE → RUNNING → PHASE1(검사·게이트) → PHASE2(로봇) → PHASE3(AGV) → COMPLETE
- ESP32 시리얼: COM8, 115200bps, JSON+\n 프로토콜
- Mock TCP: myCobot(9002), AGV(9003)
- 3회 사이클 테스트 성공

#### 부가 모듈
- `Heartbeat.py` — 2초마다 TCP 포트 체크(9002, 9003), 상태 변화 감지
- `Logger.py` — setup_logger(), 콘솔+파일 출력, 날짜별 롤링, 30일 보관
- `SpcAnalysis.py` — Confidence/CycleTime 기반 Cp/Cpk 계산 (USL=1.0, LSL=0.85)

#### myCobot 280 테스트
- 라즈베리파이 SSH 연결 (er@192.168.0.47), pymycobot 4.0.4
- get_angles/get_coords/send_angles/set_gripper_state 테스트 성공
- 집게 열기/닫기, 관절 이동 확인

---

### 이슈 및 주의사항 ⚠️
- `send_coords()`는 좌표 계산 실패 시 안 움직임 → `send_angles()`(관절 각도)가 안정적

---

## 2026-05-15

### 완료된 작업 ✅

#### ESP32 시리얼 통신
- Arduino IDE 설치, ESP32Servo + ArduinoJson 라이브러리
- 서보 핀: Gate A(13), B(27), C(14)
- JSON 수신 → gate_cmd 파싱 → 서보 동작 → gate_ack 응답
- 시리얼 모니터 테스트: `{"type":"gate_cmd","gate":"A","action":"open"}` → 서보 동작 확인
- StateMachine.py `_send_gate()` 시리얼 연동 (응답 대기 최대 10초)
- MockESP32 제거 결정 (실제 ESP32 시리얼 연결로 대체)

#### 자동 테스트
- `AutoTest.py` — 50회 풀 사이클 자동 실행
- 결과: 성공률 100%, 평균 8.03초/사이클, 전체 401.29초
- `logs/autotest-YYYYMMDD-HHMMSS.txt` 저장

#### 기술 문서 정리
- `docs/MESSAGE_SPEC.md` — PC↔ESP32, PC↔myCobot, PC↔AGV JSON 규격
- `docs/DB_SCHEMA.md` — 3개 테이블 ER, 인덱스 전략, 보관 정책
- `docs/SYSTEM_OVERVIEW.md` — 팀 역할, 시스템 구성, 통신 흐름

---

### 이슈 및 주의사항 ⚠️
- 박은수 ESP32 MQTT 연결 시도: rc=-2 (MQTT_CONNECT_FAILED)
- 원인: 김선진(유선 192.168.0.46), ESP32(무선 192.168.0.38) 네트워크 분리
- 핫스팟·방화벽 개방 시도 후 **최종 USB 시리얼 통신으로 전환 결정** (안정성, 레이턴시 1~2ms)

---

## 2026-05-16

### 완료된 작업 ✅

#### config.json 외부 설정 적용
- `config_loader.py` 생성 (UTF-8-sig 인코딩 로드)
- vision_service.py, StateMachine.py에서 하드코딩 제거
- BROKER, PORT, DB_PATH, SERIAL_PORT 등 외부화

#### 코드 품질 개선
- StateMachine.py run() 오류 재시도 로직 (max_retry=3)
- DB 연결 최적화: 매번 connect/close → 시작 시 한 번만 연결 (check_same_thread=False, WAL)
- vision ↔ StateMachine 연동: factory/visipick/inspection 구독 → 분류 결과 기반 게이트 제어

#### vision_service.py defect_code 추가
- DUMMY_COMPONENTS에 defect_code 필드 추가
- payload + DB 저장에 defect_code 반영
- result 값을 PASS/DEFECT로 변경

---

### 설계 결정 사항 📌

#### 통신 프로토콜 선택 근거
- ESP32 게이트(고정, 레이턴시 중요) → USB 시리얼 (1~2ms)
- myCobot(고정, 양방향 전이중) → 이더넷 TCP (pymycobot 공식 지원)
- AGV(이동, 무선) → WiFi MQTT (자동 재연결, 다중 장치 관리)

#### Python + C# 이기종 구조
- Python: OpenCV(카메라), pymycobot(로봇), YOLOv8(AI) 전용 생태계
- C# WPF: Windows 데스크탑 UI 최적화, 터치스크린
- MQTT: 두 언어 간 중립적 통신 레이어

#### FastAPI 추가 방향 (취업 관점)
- Flask "교체"가 아닌 FastAPI "추가"로 결정
- Swagger UI 발표용 + 이력 조회 REST API + WebSocket

---

### 이슈 및 주의사항 ⚠️
- config.json은 UTF-8-sig로 읽어야 함 (CP949 디코딩 오류 방지)
- 게이트는 A/B/C 3개, 부품은 4종류(IC칩/터미널블록/방열판/커패시터) → 분류 매핑 필요

---

## 2026-05-21

> **이날 목표:** 루트에 흩어진 Python 파일들을 역할별 폴더로 구조화하고, 유지보수 가능한 패키지 구조 확립

### 완료된 작업 ✅

#### 폴더 구조 설계 및 생성
```
C:\VisiPick\
├── src/
│   ├── core/        StateMachine, VisionService, SpcAnalysis
│   ├── api/         FastAPI 서버 (REST + WebSocket)
│   └── utils/       Logger, ConfigLoader, Heartbeat
├── tests/           AutoTest, testsets, gate_loop
├── scripts/         backup.ps1
├── config/          config.json, docker-compose.yml
├── data/            visipick.db + EF Core 프로젝트 (구 VisiPickData)
└── .venv/           (구 VisiPickEnv)
```

#### 파일 이동
| 구 경로 (루트) | 신 경로 |
|---------------|---------|
| `StateMachine.py` | `src/core/state_machine.py` |
| `vision_service.py` | `src/core/vision_service.py` |
| `SpcAnalysis.py` | `src/core/spc_analysis.py` |
| `api_server.py` | `src/api/api_server.py` |
| `Logger.py` | `src/utils/logger.py` |
| `Heartbeat.py` | `src/utils/heartbeat.py` |
| `config_loader.py` | `src/utils/config_loader.py` |
| `AutoTest.py` | `tests/auto_test.py` |
| `testsets.py` | `tests/testsets.py` |
| `gate_loop.py` | `tests/gate_loop.py` |
| `backup.ps1` | `scripts/backup.ps1` |
| `config.json` | `config/config.json` |
| `docker-compose.yml` | `config/docker-compose.yml` |
| `VisiPickData/` | `data/` |
| `VisiPickEnv/` | `.venv/` |

#### import 경로 수정
| 파일 | 변경 내용 |
|------|-----------|
| `src/core/state_machine.py` | `from Logger import` → `from src.utils.logger import setup_logger` |
| `src/core/vision_service.py` | `from loguru import logger` → `setup_logger("vision")` / `logger.add()` 제거 |
| `src/core/spc_analysis.py` | `from src.utils.logger import setup_logger` + config_loader 사용 |
| `src/api/api_server.py` | config 경로 `config/config.json` 으로 수정 |
| `src/utils/heartbeat.py` | `from src.utils.logger import setup_logger` |
| `mock/MockESP32.py` | `sys.path.insert` + `from src.utils.logger import setup_logger` |
| `mock/MockMyCobot.py` | 동일 |
| `mock/MockAGV.py` | 동일 |
| `tests/gate_loop.py` | 하드코딩 IP 제거 → `config["mqtt"]["broker"]` 사용 |
| `tests/testsets.py` | `logger.add()` 중복 호출 제거 |

#### 기타 정리
- `__pycache__/` 삭제
- `CLAUDE.md` 재작성 — STATIC(80%) / DYNAMIC(20%) 캐시 구조로 분리

---

### 진행 중인 작업 🔄

- 없음

---

### 다음 할 일

- [x] 각 모듈 단독 실행 테스트 (`python src/utils/logger.py` 등)
- [x] Mock 서버 3개 실행 후 `python tests/auto_test.py` 전체 테스트
- [x] 오류 발생 시 import 경로 재확인 및 수정
- [x] CLAUDE.md DYNAMIC 블록 업데이트 (테스트 결과 반영)
- [x] Git 초기화 및 첫 커밋 (`git init` → `git add` → `git commit`)
- [x] GitHub 저장소 생성 및 push
- [x] SourceTree 연결 안내

---

### 테스트 결과 ✅

| 항목 | 결과 |
|------|------|
| 총 사이클 | 5회 |
| 성공률 | 100% |
| 평균 사이클 시간 | 8.02초 |
| 최단/최장 | 8.01 / 8.04초 |

### 발견 및 수정된 버그

| 파일 | 문제 | 수정 |
|------|------|------|
| `src/utils/logger.py` | Windows CP949 콘솔 인코딩 오류 (em dash `—`) | `sys.stdout`을 UTF-8 TextIOWrapper로 교체 |
| `src/utils/logger.py` | `setup_logger` 재호출 시 버퍼 닫힘 오류 | 모듈 레벨에서 한 번만 stdout 교체 |
| `src/core/state_machine.py` | Mock 환경에서 COM8 시리얼 연결 시도 | `dummy_mode` 플래그로 TCP 전환 |
| `mock/MockAGV.py` | 응답에 `\n` 없어 수신 파싱 타임아웃 | 모든 send에 `+ "\n"` 추가 |
| `mock/MockMyCobot.py` | 동일 | 동일 |
| `mock/MockESP32.py` | 동일 | 동일 |
| `config/config.json` | `esp32_mock` 항목 없음 | `"esp32_mock": {"host":"localhost","port":9001}` 추가 |

#### Git / GitHub 연동
- `.gitignore` 생성 (`.venv/`, `logs/`, `data/visipick.db*`, `data/.vs/`, `data/bin/`, `data/obj/`, `mosquitto/data/`, `.claude/` 제외)
- 첫 커밋: `f51ebda` — 42개 파일, 2600줄
- GitHub 저장소: https://github.com/sunjin4682-ops/VisiPick
- 원격 브랜치: `origin/main`
- SourceTree: `C:\VisiPick` 를 **Add** 탭으로 연결

---

### 진행 중인 작업 🔄

- 없음 (2026-05-21 전체 완료)

---

### 다음 세션 시작 시 할 일

- [ ] ESP32 실제 연결 후 `tests/testsets.py` 로 하드웨어 테스트
- [ ] `tests/auto_test.py` 50사이클 정식 실행 (현재까지 5사이클만 확인)
- [ ] `src/utils/heartbeat.py` 에 ESP32(9001) 모니터링 추가

---

### 이슈 및 주의사항 ⚠️
- `tests/testsets.py`는 실제 ESP32 IP(`192.168.0.38`)에 연결하는 파일 — Mock 환경에서는 `tests/auto_test.py` 사용
- `src/utils/heartbeat.py`는 현재 ESP32(9001)를 체크하지 않음 — 실제 하드웨어 연결 시 추가 필요
- GitHub 계정: `sunjin4682-ops` (이전 캐시 계정 `silverb530` 충돌 → Windows 자격증명 관리자에서 정리 완료)

---

## 2026-05-21 (2차)

### 완료된 작업 ✅

#### .claudeignore 생성
- `.venv/`(6,833개), `data/bin/`, `data/obj/`, `data/.vs/`, `logs/`, `mosquitto/data/` 등 차단
- 실수로 읽힐 경우 수십만 토큰 낭비 방지

#### DB 관리 Python 전환 (`src/utils/db_init.py`)
- .NET EF Core 의존성 제거 — `dotnet` 없이 DB 세팅 가능
- 3개 테이블(InspectionResults, AgvMissions, SystemEvents) + 인덱스 6개 + WAL 모드
- 보존 기간 초과 레코드 자동 삭제 (`cleanup_old_records()`)
- 실행: `python -m src.utils.db_init`

### 다음 할 일
- [ ] `data/` 에서 .NET 프로젝트 파일 삭제 (`.cs`, `.csproj`, `.sln`, `Migrations/`, `Models/`, `bin/`, `obj/`, `.vs/`)
- [ ] `.gitignore`, `.claudeignore` 에서 .NET 관련 항목 정리
- [ ] ESP32 실제 연결 후 `tests/testsets.py` 하드웨어 테스트
- [ ] `tests/auto_test.py` 50사이클 정식 실행

### 이슈 및 주의사항 ⚠️
- 기존 DB(`data/visipick.db`)는 EF Core가 만든 `__EFMigrationsHistory` 테이블이 남아있음 — 동작에는 무관
- 새 환경에서는 `python -m src.utils.db_init` 으로 DB 초기화

---

---

## 2026-05-22

### 완료된 작업 ✅

#### FastAPI 서버 구축
- `src/api/api_server.py` — REST API + WebSocket + Swagger UI
- 패키지 설치: `pip install fastapi uvicorn`
- 실행: `python src/api/api_server.py` → `http://localhost:8000/docs`
- Swagger UI 정상 동작 확인 (시스템/검사/통계/제어/이벤트 그룹)

#### REST API 엔드포인트 (10개)
| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/health` | 서버 상태 확인 |
| GET | `/api/config` | 시스템 설정 조회 |
| GET | `/api/inspections` | 검사 이력 조회 (최근 N건) |
| GET | `/api/inspections/search` | 검사 이력 필터 검색 |
| GET | `/api/stats` | 양품률·클래스별·불량유형별 통계 |
| GET | `/api/stats/spc` | SPC 분석 (Cp/Cpk) |
| POST | `/api/vision/start` | 카메라 비전 시작 |
| POST | `/api/vision/stop` | 카메라 비전 중지 |
| POST | `/api/conveyor/start` | 컨베이어 시작 |
| POST | `/api/conveyor/stop` | 컨베이어 중지 |
| GET | `/api/events` | 시스템 이벤트 조회 |

#### WebSocket 구현
- `/ws` 엔드포인트 — MQTT 수신 → 모든 연결 클라이언트에 broadcast
- WPF에서 명령 수신 시 MQTT로 전달 (양방향)
- `factory/visipick/#` 전체 구독

#### 추가 모듈 생성
| 파일 | 역할 |
|------|------|
| `db.py` | SQLite 저장/조회 전용 (save_inspection, save_agv_mission, save_system_event, get_*) |
| `agv_mqtt.py` | AGV MQTT pub/sub 매니저 (dispatch, get_status, 도착 시 DB 저장) |
| `tools/mock_publisher.py` | 최지윤 WPF 독립 개발용 가짜 데이터 생성기 |

#### Mock Publisher (최지윤 전달용)
- 검사 결과(3초), AGV 상태(1~2초), 시스템 이벤트(5초), 공정 상태(4초) 발행
- Python 서버 없이 WPF 단독 테스트 가능
- 실행: `python tools/mock_publisher.py`

#### vision_service.py 부품/불량 종류 변경
- 부품: IC칩, 터미널블록, 방열판, 커패시터
- 불량: `BENT_PIN`(핀 휨), `BROKEN`(파손)
- `defect_code` 필드 payload + DB 저장 반영

#### 기술 문서 작성
- `docs/MQTT_TOPICS.md` — 토픽 명세 (Python ↔ WPF 통일), 페이로드 형식, 구독 목록

---

### 진행 중인 작업 🔄

- 없음

---

### 다음 할 일

- [ ] TRANSITIONS 딕셔너리 방식 상태 머신 적용 (`state_machine.py`)
- [ ] `config/config.json` 게이트 타이밍 실측값 입력 (박은수)
- [ ] vision_service ↔ state_machine MQTT 연동 강화 (random 분류 → MQTT 수신 결과 사용)
- [ ] WPF MQTT 구독 검증 (최지윤)
- [ ] 실제 하드웨어 연결 테스트

---

### 설계 결정 사항 📌

#### 통신 프로토콜 (용도별 분리)
- **실시간 데이터**(검사 결과, AGV 위치) → MQTT (Push)
- **제어 명령**(컨베이어/카메라 시작·중지) → REST API (요청-응답)
- **이력 조회**(검사 이력, 통계) → REST API

#### 장치별 통신 방식
- ESP32 게이트(고정, 레이턴시 중요) → USB 시리얼 (1~2ms)
- myCobot(고정, 전이중) → 이더넷 TCP (pymycobot 공식)
- AGV(이동, 무선) → WiFi MQTT (자동 재연결)

#### 외부 팀원 설계 근거서 11개 항목 검토
- ✅ 채용: 단일 마스터, MQTT 처음부터, 상태 머신, SQLite WAL, WPF Pure Display, MQTT 토픽 구조, ESP32 시리얼, myCobot 이더넷
- ⚠️ 부분 채용: FastAPI("교체"가 아닌 "추가"), 모듈 분리(10개 대신 3~4개)
- ⚠️ 불채용: Event Bus(MQTT가 이미 동일 역할 → 과설계)

#### 엣지 디바이스 비교 (향후 도입 검토)
- 1순위: NVIDIA Jetson Orin Nano Super (67 TOPS, 35만원, 생태계 최강)
- 2순위: RPi5 + Hailo-8 (26 TOPS, 25만원, 가성비)
- RPi5 단독은 YOLOv8n 200~500ms — 3초 간격 검사면 충분, 실시간 영상은 가속기 필요

---

### 이슈 및 주의사항 ⚠️
- `api_server.py`의 config 로드는 `encoding="utf-8-sig"` 필수 (CP949 디코딩 오류 방지)
- 게이트는 A/B/C 3개인데 부품은 4종류 — 커패시터를 A클래스로 분류 중 (변경 가능)
- WebSocket broadcast의 MQTT 콜백에서 매번 새 event loop 생성 — 부하 발생 시 단일 loop 재사용으로 개선 필요

---

## 2026-05-22 (2차)

### 완료된 작업 ✅

#### V6.3 설계서 반영 — MD 파일 전면 업데이트

| 파일 | 변경 내용 |
|------|-----------|
| `CLAUDE.md` | V6.3 전면 재작성 — DIP IC 4종, 3클래스 판정, 2카메라, 푸셔 게이트, 트레이 이재, 새 디렉토리 구조 |
| `docs/DB_SCHEMA.md` | V6.3 스키마 — InspectionResults(컬럼 재정의), RecipeSessions(신규), AgvMissions(FK 추가), SystemEvents(동일) |
| `docs/SYSTEM_OVERVIEW.md` | 팀 5인 역할 재정의, 새 SW 패키지 구조, HMI 화면 레이아웃 |
| `docs/MESSAGE_SPEC.md` | gate_cmd(푸셔 방식), robot_cmd(transfer_tray), AGV(MQTT), inspection 페이로드 전면 개정 |
| `docs/MQTT_Schema.md` | 토픽 prefix `factory/visipick/` → `visipick/`, 전체 페이로드 재정의 |
| `docs/API_SPEC.md` | Base URL :8000, V6.3 엔드포인트 목록, WPF 독립 개발 안내 |

#### V6.2 → V6.3 핵심 변경 요약
- **게이트**: 열림/닫힘 3개 → 푸셔 2개 (Gate1: 중복, Gate2: 불량)
- **분류**: A/B/C 클래스 → NEEDED / DUPLICATE / DEFECT
- **부품**: IC칩/터미널블록/방열판/커패시터 → NE555P / CD4017BE / ATmega328P / 74HC595N
- **Camera**: 1개 → 2개 (상부: 종류 식별, 측면: 핀 검사)
- **myCobot**: 개별 픽업 → 완성 트레이 단위 이재
- **AGV**: TCP → MQTT, 지게 모듈(서보 25°) 추가
- **SW 구조**: `vision/`, `orchestrator/`, `devices/` 패키지 추가 예정

---

### 다음 할 일

- [ ] `src/vision/`, `src/orchestrator/`, `src/devices/` 패키지 생성
- [ ] `src/core/event_bus.py` 구현
- [ ] `recipe_mgr.py`, `tray_mgr.py`, `decision.py` 구현
- [ ] Camera1·Camera2 OpenCV 파이프라인 구현
- [ ] `config/config.json` V6.3 키 구조 업데이트 (cameras, conveyor, recipe)
- [ ] `src/utils/db_init.py` — RecipeSessions 테이블 추가

### 설계 결정 사항 📌

#### V6.3 핵심 차별화 (설계서 기준)
- 레시피 기반 키팅 — 기판에 필요한 4종 DIP IC 자동 수집
- 2단계 검사 — Camera1(종류+1차불량) + Camera2(측면 핀 정밀)
- 푸셔 게이트 — 불량/중복만 밀어내고 양품은 직진 통과
- 중력 수집 — 부품이 컨1 끝단에서 트레이로 낙하
- 트레이 이재 — myCobot이 완성 트레이 통째로 AGV에 올림

#### MQTT 토픽 prefix 변경
- 구: `factory/visipick/...`
- 신: `visipick/...` (설계서 V6.3 기준)
- **영향 범위**: `mock_publisher.py`, `src/core/agv_mqtt.py`, `src/api/api_server.py`, WPF 코드 모두 업데이트 필요

---

## 2026-05-22 (3차)

### 완료된 작업 ✅

#### V6.3 코드 전면 구현

##### config/config.json — V6.3 구조 재작성
- `cameras` (top/side 2카메라), `conveyor`, `recipe` 섹션 신규 추가
- `recipe.parts`: IC칩/터미널블록/방열판/커패시터 → NE555P/CD4017BE/ATmega328P/74HC595N (DIP IC 모델명으로 변경)
- `gates`: A/B/C 3개 → `"1"/"2"` 푸셔 게이트 2개 (`open_angle/close_angle` → `push_angle/return_angle`)
- `robot`: port/baudrate/positions 전체 → `host: "192.168.0.47"`, `port`, `speed`로 단순화 (TCP 방식으로 전환)
- `agv.nodes`: `warehouse_A/B/C` → 단일 `warehouse: "WAREHOUSE"`
- Mock 호스트/포트 → `mock.esp32/robot/agv` 하위로 통합
- MQTT topics prefix: `factory/visipick/` → `visipick/`

##### DB 스키마 V6.3 (`src/utils/db_init.py`, `src/core/db.py`)
- `InspectionResults`: ComponentType/Class/Result/GateUsed → PartType/Classification/GateAction/RecipeSessionId
- `RecipeSessions` 테이블 신규 (StartTime, EndTime, Parts, TotalNeeded, TotalFilled, Status)
- `AgvMissions`: TrayClass/ItemCount → RecipeSessionId FK
- 신규 함수: `save_recipe_session()`, `complete_recipe_session()`, `get_sessions()`, `get_current_session()`
- `get_stats()`: NEEDED/DUPLICATE/DEFECT 집계로 변경
- DB 재초기화 완료 (`data/visipick.db`)

##### src/vision/ 패키지 신규 구현
| 파일 | 내용 |
|------|------|
| `classifier.py` | 부품 4종 분류 — `config["recipe"]["parts"]` 참조, 더미: 랜덤 선택 |
| `defect_detector.py` | 불량 검출 (Camera1+2) — 더미: 15% 확률 BENT_PIN/BROKEN |
| `camera_top.py` | Camera1 상부 캡처 — 더미: None 반환, 실제: cv2.VideoCapture |
| `camera_side.py` | Camera2 측면 캡처 — 더미: None 반환, 실제: cv2.VideoCapture |

##### src/orchestrator/ 패키지 신규 구현
| 파일 | 내용 |
|------|------|
| `decision.py` | `judge(part_type, defect_code, recipe_mgr)` → NEEDED/DUPLICATE/DEFECT, `gate_action_for()` |
| `recipe_mgr.py` | 레시피 충족 추적: `needs()`, `mark_collected()`, `is_complete()`, `reset()`, `status()` |
| `tray_mgr.py` | 트레이 낙하 카운트: `on_part_passed()`, `get_count()`, `reset()` |

##### src/devices/ 패키지 신규 구현
| 파일 | 내용 |
|------|------|
| `robot.py` | myCobot 트레이 이송 TCP (더미: MockMyCobot, 실제: RPi4 192.168.0.47) |
| `serial_ctrl.py` | ESP32 게이트 푸셔 + 컨베이어 (더미: MockESP32 TCP, 실제: COM8) |

##### src/core/state_machine.py — orchestrator 통합
- 기존 직접 TCP 호출 코드(phase1/2/3) 전면 제거
- 신규 의존: `CameraTop`, `CameraSide`, `Classifier`, `DefectDetector`, `judge()`, `RecipeManager`, `TrayManager`, `Robot`, `SerialController`, `AGVMqttManager`
- 주요 흐름:
  - RUNNING 루프: 카메라 캡처 → 분류 → 불량 검출 → 3클래스 판정 → 게이트 → DB/MQTT 저장
  - 레시피 완성 시 TRAY_TRANSFER: 로봇 트레이 이송 → AGV 출발 → 세션 완료 처리 → 초기화
- 상태 전이 시 `visipick/system/state` MQTT 발행 (WPF 연동)

##### src/api/api_server.py — V6.3 엔드포인트 추가
- 검색 파라미터: `component_type/class_/result` → `part_type/classification`
- 신규: `/api/sessions`, `/api/sessions/current`, `/api/agv/status`, `/api/agv/missions`

##### src/core/vision_service.py — 더미 데이터 V6.3
- DUMMY_COMPONENTS: 부품명 IC칩/터미널블록/방열판/커패시터 → NE555P/CD4017BE/ATmega328P/74HC595N으로 교체
- 분류 조합: NEEDED/DUPLICATE/DEFECT × PASS_THROUGH/GATE1_PUSH/GATE2_PUSH

---

### 진행 중인 작업 🔄

- 없음 (2026-05-22 3차 전체 완료)

---

### 다음 할 일

- [ ] Camera1 상부 OpenCV 분류 파이프라인 (실제 하드웨어 연결 후)
- [ ] Camera2 측면 핀 검사 OpenCV 파이프라인 (실제 하드웨어 연결 후)
- [ ] ESP32 실제 연결 후 `tests/testsets.py` 하드웨어 테스트
- [ ] `tests/auto_test.py` 50사이클 정식 실행

---

### 설계 결정 사항 📌

#### state_machine.py 통합 방식
- 기존 state_machine.py가 TCP 직접 호출하던 방식을 모두 devices/orchestrator 모듈로 위임
- state_machine은 FSM 흐름 제어 + MQTT 브로드캐스트만 담당
- 더미 모드: config.json의 `vision.dummy_mode: true` 하나로 전체 제어

---

## 2026-05-22 (4차)

### 완료된 작업 ✅

#### state_machine.py 센서 트리거 기반 리팩터링

**문제 3가지 해결:**

| 문제 | 기존 | 변경 후 |
|------|------|---------|
| 루프 모델 | `sleep(4s)` 후 PC가 직접 검사 호출 — 부품 누락 가능 | 투입단 센서 트리거 → `on_sensor_triggered()` → 데몬 스레드 |
| 게이트 타이밍 | 판정 즉시 `push_gate()` — 엉뚱한 부품 밀어냄 | `_schedule_gate(delay_sec)` 지연 큐 → `_flush_gate_queue()` 50ms 주기 소진 |
| 컨베이어 미구동 | 제어 없음 | RUNNING 진입 시 `set_conveyor_speed(1.5)`, 이재 직전 `set_conveyor_speed(0.0)` |

**추가된 메서드/속성:**

| 항목 | 내용 |
|------|------|
| `on_sensor_triggered()` | public 콜백 (serial_ctrl에서 연결). 디바운스 0.5초, RUNNING 상태에서만 처리 |
| `_inspect_lock` | `threading.Lock()` — 이전 검사가 끝나기 전 새 트리거 무시 |
| `_gate_queue` | `deque[(fire_at, gate_no)]` — 지연 게이트 예약 목록 |
| `_schedule_gate(gate_no, delay_sec)` | `fire_at = now + delay_sec` 을 큐에 적재 |
| `_flush_gate_queue()` | `fire_at <= now` 항목만 소진하여 `push_gate()` 실행 |
| `_start_dummy_trigger()` | 더미 모드 전용 — 별도 스레드에서 `on_sensor_triggered()` 주기 호출 |

**더미 모드:** `config["vision"]["dummy_mode"]=true` 이면 `_start_dummy_trigger()` 가 실제 센서 없이 동작 유지

---

#### config/config.json — 게이트/센서 타이밍 파라미터 추가

```json
"gates": {
  "1": { ..., "delay_sec": 1.5 },
  "2": { ..., "delay_sec": 1.5 },
  "pusher_hold_sec": 0.3
},
"sensor": { "debounce_sec": 0.5 }
```

- `delay_sec`: 카메라 → 게이트 구간 이동 시간 (실측 후 조정, 기본 1.5s)
- `pusher_hold_sec`: 푸셔 동작 유지 시간 (ESP32 측에서 사용)
- `debounce_sec`: 동일 부품 중복 트리거 무시 기간

---

#### serial_ctrl.py — 센서 콜백 수신 루프 추가

| 항목 | 내용 |
|------|------|
| `__init__(on_sensor: Callable \| None = None)` | 콜백 파라미터 추가 — 더미 모드에서는 무시 |
| `_send_lock` | `threading.Lock()` — `_send()`와 수신 루프의 `readline()` 충돌 방지 |
| `_start_recv_loop()` | 10ms 폴링, `in_waiting > 0` 확인 후 readline, `{"type":"sensor_triggered"}` 수신 시 콜백 호출 |
| `_send()` | 실제 모드에서 `with self._send_lock:` 으로 감쌈 |

**연결 방식 (state_machine.py):**
```python
self._serial = SerialController(on_sensor=self.on_sensor_triggered)
```

ESP32 → `{"type":"sensor_triggered"}` 시리얼 전송 → 수신 루프 → `state_machine.on_sensor_triggered()` → 디바운스 → 검사 스레드 → 판정 → `_schedule_gate()` → `_flush_gate_queue()` → `push_gate()`

---

### 진행 중인 작업 🔄

- 없음 (2026-05-22 4차 전체 완료)

---

### 다음 할 일

- [ ] MockESP32.py에 `{"type":"sensor_triggered"}` 자동 발행 추가 (더미 → 실제 흐름 검증용)
- [ ] `config["gates"]["1"]["delay_sec"]` 실측값 입력 (박은수 — 카메라~게이트 거리/속도 측정)
- [ ] Camera1 상부 OpenCV 분류 파이프라인 (실제 하드웨어 연결 후)
- [ ] Camera2 측면 핀 검사 OpenCV 파이프라인 (실제 하드웨어 연결 후)
- [ ] ESP32 실제 연결 후 `tests/testsets.py` 하드웨어 테스트
- [ ] `tests/auto_test.py` 50사이클 정식 실행

---

### 설계 결정 사항 📌

#### 센서 트리거 동시성 설계
- `_inspect_lock.acquire(blocking=False)` — 이전 검사 진행 중에는 새 트리거 즉시 반환 (드롭)
- 드롭 이유: 컨베이어 속도 1.5cm/s, 부품 간격 최소 4초 → 실제로 동시 검사 상황 없음. lock 충돌은 센서 오작동 신호 차단용

#### 게이트 큐 lock 설계
- 큐 적재(`_schedule_gate`)와 소진(`_flush_gate_queue`)은 별도 스레드에서 실행 가능 → `_gate_lock` 으로 보호
- 소진은 메인 루프(50ms 주기)에서만 수행 → 단일 호출자이므로 `push_gate()` 는 lock 밖에서 실행

#### serial_ctrl lock 설계
- `_send()` 와 수신 루프가 동일 시리얼 포트 `readline()` 을 공유 → lock 없으면 ACK 응답을 수신 루프가 탈취
- `in_waiting > 0` 체크 후 `readline()` → lock 보유 시간 최소화 (블로킹 없음)
- `reset_input_buffer()` 가 큐에 쌓인 센서 이벤트를 삭제할 수 있으나, gate_cmd 레이턴시(수ms) 동안 부품이 도달할 확률 극히 낮음

---

## 2026-05-23

### 완료된 작업 ✅

#### 게이트 타이밍 실측값 적용 (`config/config.json`)
- 컨베이어 속도 1.5cm/s, 카메라~Gate1 30cm, 카메라~Gate2 45cm 실측
- Gate1 `delay_sec`: 1.5 → **20.0s** (30 ÷ 1.5)
- Gate2 `delay_sec`: 1.5 → **30.0s** (45 ÷ 1.5)
- 근거 수치(`camera_to_gate1_cm: 30`, `camera_to_gate2_cm: 45`) conveyor 섹션에 함께 기록

#### MockESP32.py 개선 (`mock/MockESP32.py`)
| 항목 | 내용 |
|------|------|
| `_sensor_trigger_loop()` | 연결마다 데몬 스레드 실행 — `SENSOR_INTERVAL`(=`vision.dummy_interval_sec`)초 주기로 `sensor_triggered` 발행 |
| `stop_event` | 클라이언트 연결 종료 시 루프 정상 중단 |
| `conveyor_cmd` 핸들러 추가 | 기존에 없어 `set_conveyor_speed()` 호출마다 10초 타임아웃 발생 → `conveyor_ack` 응답 추가 |
| `SO_REUSEADDR` | 프로세스 재시작 시 "Address already in use" 방지 |
| 수신 파싱 | `splitlines()` 루프로 변경 (멀티 메시지 안전 처리) |

#### 더미 모드 end-to-end 테스트 (2사이클 PASS)
- 실행: `python -m src.core.state_machine` (루트에서 모듈 실행 필수 — 아래 이슈 참고)
- 전체 흐름 확인: IDLE → RUNNING → (센서 트리거 → 검사 → 3클래스 판정 → 게이트 큐 예약) → TRAY_TRANSFER → COMPLETE × 2사이클
- AGV 교번 정상 확인: 사이클1 → AGV 2, 사이클2 → AGV 1
- DB 저장 확인: RecipeSessions Id=1,2 생성·완료, InspectionResults 전 검사 결과 저장

#### 부품 종류 원복 (V6.3 구현 시 변경됐던 이름 → 원래 이름으로 복원)
- `NE555P / CD4017BE / ATmega328P / 74HC595N` → `IC칩 / 터미널블록 / 방열판 / 커패시터`
- 수정 파일: `config/config.json`, `src/vision/classifier.py`, `src/core/vision_service.py`, `src/orchestrator/recipe_mgr.py`
- `config["recipe"]["parts"]`만 바꾸면 classifier·recipe_mgr·state_machine 자동 반영 (vision_service.py만 별도 수정)

---

### 설계 확인 사항 📌

#### 게이트 큐 사이클 간 유지 — 의도된 동작
- 사이클 전환 시 게이트 큐를 비우지 않는 것이 맞음
- 논스톱 컨베이어이므로 레시피 완성 시점에 이미 카메라를 통과한 DUPLICATE/DEFECT 부품이 컨베이어 위에 존재
- `fire_at` = 카메라 통과 시각 + delay_sec → 사이클이 바뀌어도 해당 절대 시각에 게이트 작동해야 함

---

### 다음 할 일

- [ ] Camera1 상부 OpenCV 분류 파이프라인 (실제 하드웨어 연결 후)
- [ ] Camera2 측면 핀 검사 OpenCV 파이프라인 (실제 하드웨어 연결 후)
- [ ] ESP32 실제 연결 후 `tests/testsets.py` 하드웨어 테스트
- [ ] `tests/auto_test.py` 50사이클 정식 실행
- [ ] `config["gates"]["1/2"]["delay_sec"]` 값 정밀 실측 (현재 20.0/30.0은 이론값)

---

### 이슈 및 주의사항 ⚠️

- **실행 명령 수정**: `python src/core/state_machine.py` 직접 실행 시 `ModuleNotFoundError: No module named 'src'` 발생 — 스크립트 실행 시 `src/core`가 sys.path에 추가되어 루트 패키지를 찾지 못함. **반드시 `python -m src.core.state_machine`으로 실행**
- `gate1_delay_ms`, `gate2_delay_ms` (conveyor 섹션) 는 현재 미사용 — `gates["1"]["delay_sec"]`이 실제 사용 값

---

<!-- 새 날짜 작업 시 아래 템플릿 복사해서 추가 -->
<!--
## YYYY-MM-DD

### 완료된 작업 ✅
-

### 진행 중인 작업 🔄
-

### 다음 할 일
- [ ]

### 이슈 및 주의사항 ⚠️
-
-->
