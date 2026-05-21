# CLAUDE.md

<!-- ═══════════════════════════════════════════════════════════════
     STATIC  (80–90%) — 자주 바뀌지 않음 · 캐시 히트 대상
     절대 이 블록 안에 날짜·카운터·버전 번호를 넣지 말 것
     ═══════════════════════════════════════════════════════════════ -->

## 프로젝트 개요

VisiPick은 비전 검사 → 로봇 픽앤플레이스 → AGV 운반을 통합한 스마트팩토리 자동화 시스템이다.

- Python — 전체 오케스트레이션 로직
- .NET / EF Core — SQLite 데이터 영속성
- MQTT — 컴포넌트 간 이벤트 버스
- JSON + newline — 디바이스 TCP 통신 포맷
- Mock 서버 3종 — 하드웨어 없이 전체 시스템 개발/테스트 가능

## 시스템 흐름 (3-Phase)

```
[Vision Inspection] → [Gate Control] → [Robot Pick&Place] → [AGV Transport]
      Phase 1               Phase 1           Phase 2             Phase 3
```

| Phase | 담당 모듈 | 통신 |
|-------|-----------|------|
| 1 — 검사·게이트 | `src/core/state_machine.py` | Serial COM8 → ESP32 |
| 2 — 로봇 | `src/core/state_machine.py` | TCP localhost:9002 |
| 3 — AGV | `src/core/state_machine.py` | TCP localhost:9003 |

## 디렉토리 구조

```
C:\VisiPick\
├── config/                  # config.json, docker-compose.yml
├── data/                    # visipick.db + EF Core 프로젝트 (Migrations, Models)
├── docs/
├── logs/                    # 날짜별 롤링 로그 (loguru)
├── mock/                    # MockESP32.py · MockMyCobot.py · MockAGV.py
├── mosquitto/
├── scripts/                 # backup.ps1
├── src/
│   ├── api/                 # api_server.py  (FastAPI + WebSocket)
│   ├── core/                # state_machine.py · vision_service.py · spc_analysis.py
│   └── utils/               # logger.py · config_loader.py · heartbeat.py
├── tests/                   # auto_test.py · testsets.py · gate_loop.py
└── .venv/
```

## 주요 파일

| 파일 | 역할 | 핵심 함수/클래스 |
|------|------|-----------------|
| `src/core/state_machine.py` | 메인 오케스트레이터 | `VisiPickStateMachine`, `phase1/2/3`, `run()` |
| `src/core/vision_service.py` | 검사 더미 서비스 | `inspection_loop()`, `save_to_db()` |
| `src/core/spc_analysis.py` | 품질 지표 (Cp/Cpk) | `load_data()`, `calc_spc()` |
| `src/api/api_server.py` | REST API + WebSocket | FastAPI app, `/api/inspections`, `/ws` |
| `src/utils/logger.py` | 로깅 추상화 | `setup_logger(name)` |
| `src/utils/config_loader.py` | 설정 로드 | `config` 딕셔너리 |
| `src/utils/heartbeat.py` | 디바이스 연결 감시 | `heartbeat_loop()` |
| `tests/auto_test.py` | 자동 테스트 하네스 | `AutoTest.run()` |
| `tests/testsets.py` | ESP32 TCP 직접 테스트 | `VisiPickStateMachine.run()` |
| `data/AppDbContext.cs` | EF Core 컨텍스트 | WAL 모드, 3 테이블 |

## 실행 명령

```bash
# 1. Mock 서버 3개 (별도 터미널)
python mock/MockESP32.py       # port 9001
python mock/MockMyCobot.py     # port 9002
python mock/MockAGV.py         # port 9003

# 2. MQTT 브로커
docker-compose -f config/docker-compose.yml up -d

# 3. 메인 실행
python src/core/state_machine.py    # 3사이클
python tests/auto_test.py           # 50사이클 자동 테스트

# 4. 모니터링
python src/utils/heartbeat.py       # 디바이스 연결 상태
python src/core/vision_service.py   # 검사 더미 데이터 생성
python src/core/spc_analysis.py     # Cp/Cpk 분석

# 5. API 서버
python src/api/api_server.py        # http://localhost:8000

# 6. DB 백업
powershell scripts/backup.ps1
```

## 통신 프로토콜

| 프로토콜 | 방향 | 엔드포인트 | 포맷 |
|----------|------|------------|------|
| Serial | PC ↔ ESP32 | COM8, 115200 baud | JSON + `\n` |
| TCP | PC ↔ Mock | localhost:9001/9002/9003 | JSON + `\n` |
| MQTT | Pub/Sub | localhost:1883 | JSON |
| HTTP/WS | Client ↔ API | localhost:8000 | JSON |

## MQTT 토픽

| 토픽 | 방향 | 페이로드 예시 |
|------|------|--------------|
| `factory/visipick/inspection` | vision → all | `{"class":"A","result":"PASS","confidence":0.95}` |
| `factory/visipick/gate/cmd` | SM → ESP32 | `{"type":"gate_cmd","gate":"A","action":"open"}` |
| `factory/visipick/robot/cmd` | SM → robot | `{"type":"robot_cmd","action":"pick","buffer":"A"}` |
| `factory/visipick/agv/{id}/status` | AGV → all | `{"agv_id":1,"state":"moving","node":"N3"}` |
| `factory/visipick/system/event` | any → UI | `{"source":"Camera","event_type":"INFO","message":"..."}` |

## 설정 (config/config.json 주요 키)

```json
{
  "serial":     { "port": "COM8", "baudrate": 115200 },
  "robot_mock": { "host": "localhost", "port": 9002 },
  "agv_mock":   { "host": "localhost", "port": 9003 },
  "mqtt":       { "broker": "localhost", "port": 1883 },
  "database":   { "path": "C:\\VisiPick\\data\\visipick.db" },
  "vision":     { "dummy_mode": true, "dummy_interval_sec": 3 }
}
```

## 데이터베이스

- 위치: `data/visipick.db` (WAL 모드 — 동시 읽기 안전)
- 관리: EF Core (`data/` 폴더, `dotnet ef database update`)
- 테이블 3개:

| 테이블 | 보존 | 주요 컬럼 |
|--------|------|-----------|
| `InspectionResults` | 30일 | Class, Result, DefectCode, Confidence, CycleTimeMs |
| `AgvMissions` | 무제한 | AgvId, Source, Destination, TrayClass |
| `SystemEvents` | 7일 | Source, EventType, Message |

## 로깅 규칙

```python
from src.utils.logger import setup_logger
logger = setup_logger("module_name")   # → logs/module_name-YYYY-MM-DD.log
```

- 콘솔: 색상 코딩 (초록=시각, 청록=모듈명)
- 파일: 00:00 일별 롤링, 30일 보존, UTF-8
- **mock/ 에서 import 시** `sys.path.insert(0, str(Path(__file__).parent.parent))` 필요

## 코딩 규칙

- 모든 `import`는 `from src.utils.logger import setup_logger` 형식 사용 (루트 상대 임포트 금지)
- TCP 전송: `json.dumps(msg, ensure_ascii=False) + "\n"` — 한글 로그 지원
- 설정값은 반드시 `config_loader.config["키"]` 에서 읽을 것 (하드코딩 금지)
- `setup_logger()` 호출 후 `logger.add()` 재호출 금지 (핸들러 중복)

## 디버깅

| 증상 | 원인 / 해결 |
|------|------------|
| ESP32 응답 없음 (타임아웃) | `python mock/MockESP32.py` 미실행 또는 COM8 미연결 |
| MQTT connection refused | `docker-compose -f config/docker-compose.yml up -d` |
| Database locked | WAL 미활성 — `data/AppDbContext.cs` 확인 |
| 한글 깨짐 | `logger.py` encoding="utf-8" 확인 |
| TCP timeout | `config/config.json` host/port vs Mock 실행 포트 확인 |
| ImportError: src.utils… | 실행 디렉토리가 `C:\VisiPick` 인지 확인 |

<!-- ═══════════════════════════════════════════════════════════════
     DYNAMIC (10–20%) — 자주 바뀌는 정보만 여기에
     날짜·카운터·진행 상태를 이 블록에만 기록할 것
     ═══════════════════════════════════════════════════════════════ -->

## 현재 상태 (업데이트 시 이 섹션만 수정)

### 마지막 알려진 성능
- 50사이클 성공률: 100%
- 평균 사이클 타임: 8.03초
- 총 소요: 401.29초

### 완료된 구조 변경
- 루트 평탄 구조 → `src/core`, `src/api`, `src/utils` 패키지 구조로 리팩터링
- `VisiPickData/` → `data/` 이름 변경 (EF Core 프로젝트 + DB 통합)
- `VisiPickEnv/` → `.venv/` 이름 변경
- `config.json` → `config/config.json` 이동
- `docker-compose.yml` → `config/docker-compose.yml` 이동
- 모든 mock 서버 `setup_logger()` 통일

### 진행 중 / 다음 작업
- 없음 (구조 리팩터링 완료)
