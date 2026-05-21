> **다음 세션 시작 시:** 이 파일을 읽고, 현재 상태를 파악한 뒤 다음 할 일을 제안해줘

---

# VisiPick 작업 로그

- **프로젝트명:** VisiPick
- **작업 시작일:** 2026-05-21
- **목표:** 루트에 흩어진 Python 파일들을 역할별 폴더로 구조화하고, 유지보수 가능한 패키지 구조 확립

---

## 2026-05-21

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
