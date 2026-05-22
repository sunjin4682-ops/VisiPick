# VisiPick 시스템 구조 요약서 (V6.3)
> 작성: 김선진 | 버전: 6.3 | 날짜: 2026-05-22

## 팀 역할 분담

| 담당 | 역할 | 주요 산출물 |
|------|------|-------------|
| 염재니 | Central Server 총괄 | `core/` + `vision/` + `orchestrator/` + `devices/robot.py` — Camera1·Camera2 OpenCV 파이프라인, 4종 분류기, 불량 검출기, 레시피 매칭, FSM, myCobot 트레이 이재 |
| 김선진 | Backend Infra + 통합 | `server/api.py` (FastAPI+WebSocket+Swagger) + `server/db.py` (SQLite) + `devices/agv_mqtt.py` + Mosquitto 셋업 + MockDataService + `config.json` + 통합 테스트 |
| 최지윤 | HMI 전담 | C# WPF Pure Display — 6분할 대시보드 (Camera1·Camera2 영상, 분류 현황, 레시피 체크리스트, AGV 맵, 이벤트 로그) + MockDataService로 독립 개발 |
| 박은수 | Embedded 전담 | ESP32 펌웨어 (푸셔 Gate1·Gate2 + 컨1 스텝모터 + 푸셔 타이밍), AGV ESP32-CAM (비전 라인팔로잉 + MQTT + 지게 서보) |
| 김동호 | HW + Ops | 3D프린팅 (트레이, 가이드 슘트, 게이트 마운트, 지게 모듈), AGV 조립, 시제품 제작, 시연 운영, 테스트 |

## 시스템 구성

| 컴포넌트 | 기술 | 포트/인터페이스 |
|----------|------|----------------|
| Python Central Server | Python 3.14 | 단일 프로세스 |
| FastAPI + WebSocket | uvicorn | :8000 |
| MQTT Broker | Mosquitto (Docker) | :1883 |
| C# WPF HMI | .NET 8 | WebSocket 수신 |
| SQLite DB | WAL 모드 | `data/visipick.db` |
| ESP32 (게이트+컨베이어) | Arduino / C++ | COM8, 115200bps |
| myCobot 280 Pi | pymycobot | RPi4 Ethernet TCP |
| AGV 1·2 (ESP32-CAM) | MicroPython | MQTT Wi-Fi |

## 통신 흐름

```
Camera1 (USB) ──┐
Camera2 (USB) ──┤
                ▼
        Python Central Server
        ├─ vision/ (분류·검출)
        ├─ orchestrator/ (판정·레시피)
        ├─ core/state_machine (FSM)
        │
        ├──Serial──► ESP32 (게이트 푸셔·컨1)
        ├──TCP/IP──► myCobot RPi4 (트레이 이재)
        ├──MQTT───► AGV 1·2 (ESP32-CAM)
        │
        └──FastAPI──► WebSocket
                         │
                    C# WPF HMI
                    (Pure Display)
```

## 소프트웨어 패키지 구조

```
src/
├── core/
│   ├── state_machine.py     전체 공정 FSM
│   ├── event_bus.py         내부 pub/sub 이벤트 버스
│   ├── db.py                SQLite I/O 전담
│   └── agv_mqtt.py          AGV MQTT 매니저
├── vision/
│   ├── camera_top.py        Camera1 상부 (종류 식별 + 1차 불량)
│   ├── camera_side.py       Camera2 측면 (핀 휘어짐 정밀 검사)
│   ├── classifier.py        DIP IC 4종 분류기
│   └── defect_detector.py   불량 검출기
├── orchestrator/
│   ├── decision.py          3클래스 판정 (NEEDED/DUPLICATE/DEFECT)
│   ├── recipe_mgr.py        레시피 매칭 + 완성 감지
│   └── tray_mgr.py          트레이 수집 카운트
├── devices/
│   ├── robot.py             myCobot TCP 트레이 이재
│   └── serial_ctrl.py       ESP32 시리얼 (푸셔·컨베이어)
├── api/
│   └── api_server.py        FastAPI REST + WebSocket
└── utils/
    ├── logger.py
    ├── config_loader.py
    ├── heartbeat.py
    └── db_init.py
```

## HMI 화면 구성 (최지윤)

```
┌─────────────────────────────────────────────────┐
│ [상태바] ● Cam1 ● Cam2 ● ESP32 ● myCobot ● AGV1·2│
├────────────────┬───────────────┬───────────────┤
│ ① Camera1 영상 │ ② 분류 현황   │ ③ 레시피       │
│ (상부, 바운딩  │ 수집: ███ 8개 │ 체크리스트     │
│  박스+라벨)    │ 중복: ██ 3개  │                │
│                │ 불량: █ 2개   │ ① NE555P   [☑] │
├────────────────┼───────────────┤ ② CD4017BE [☑] │
│ ④ Camera2 영상 │ ⑤ AGV 상태   │ ③ ATmega   [☐] │
│ (측면, 핀 검사)│ 2D맵 + 위치   │ ④ 74HC595N [☐] │
├────────────────┴───────────────┴───────────────┤
│ ⑥ 이벤트 로그 (DataGrid)                        │
├─────────────────────────────────────────────────┤
│ [▶ 시작] [⏹ 정지]   사이클: 0007   경과: 01:23  │
└─────────────────────────────────────────────────┘
```

## 시연 시나리오 (목표: 3분)

| Phase | 시간 | 내용 |
|-------|------|------|
| 1 — 검사·분류 | 0:00~1:30 | DIP IC 15개 투입 → Camera1+Camera2 동시 검사 → 중복/불량 푸셔 분리 → 트레이 수집 |
| 2 — 트레이 이재 | 1:30~2:30 | 레시피 4종 충족 → myCobot이 완성 트레이를 AGV 위에 올림 |
| 3 — 운반 완성 | 2:30~3:00 | AGV MQTT 출발 → 라인트레이싱 → 창고 → 지게(서보 25°) 쏟아내기 |
