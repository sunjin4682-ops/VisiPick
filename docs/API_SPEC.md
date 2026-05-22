# VisiPick REST API 명세서 (V6.3)
> 작성: 김선진 | 버전: 2.0 | Swagger UI: http://localhost:8000/docs

## Base URL

```
http://localhost:8000
```

## 엔드포인트 목록

### 시스템

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/health` | 서버 상태 확인 |
| GET | `/api/config` | 현재 시스템 설정 조회 |

**GET /api/health 응답:**
```json
{ "status": "ok", "service": "VisiPick API", "timestamp": "2026-05-22T12:00:00" }
```

---

### 검사 이력

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/inspections` | 검사 이력 조회 (최근 N건) |
| GET | `/api/inspections/search` | 검사 이력 필터 검색 |

**GET /api/inspections 파라미터:**
| 파라미터 | 타입 | 기본값 | 설명 |
|----------|------|--------|------|
| `limit` | int | 100 | 최대 조회 건수 |

**GET /api/inspections/search 파라미터:**
| 파라미터 | 타입 | 설명 |
|----------|------|------|
| `part_type` | string | 부품 종류 필터 (NE555P 등) |
| `classification` | string | 분류 필터 (NEEDED/DUPLICATE/DEFECT) |
| `limit` | int | 최대 조회 건수 |

---

### 통계

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/stats` | 전체 검사 통계 |
| GET | `/api/stats/spc` | SPC 분석 (Cp/Cpk) |

**GET /api/stats 응답:**
```json
{
  "total": 150,
  "needed_count": 60,
  "duplicate_count": 50,
  "defect_count": 40,
  "pass_rate": 40.0,
  "part_counts": { "NE555P": 40, "CD4017BE": 38, "ATmega328P": 37, "74HC595N": 35 },
  "defect_counts": { "BENT_PIN": 30, "WRONG_SIZE": 10 }
}
```

---

### 레시피 세션

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/sessions` | 레시피 세션 이력 조회 |
| GET | `/api/sessions/current` | 현재 진행 중인 세션 |

---

### 제어

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/api/vision/start` | 비전 검사 시작 |
| POST | `/api/vision/stop` | 비전 검사 중지 |
| POST | `/api/conveyor/start` | 컨베이어 시작 |
| POST | `/api/conveyor/stop` | 컨베이어 정지 |

---

### 이벤트

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/events` | 시스템 이벤트 조회 |

---

### AGV

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/agv/status` | AGV 1·2 현재 상태 조회 |
| GET | `/api/agv/missions` | AGV 미션 이력 조회 |

---

## WebSocket

```
ws://localhost:8000/ws
```

- Python Central Server가 MQTT 수신 메시지를 모든 WPF 클라이언트에 브로드캐스트
- WPF → Python: 제어 명령을 JSON으로 전송하면 MQTT로 전달

**수신 메시지 형식:**
```json
{
  "_topic": "visipick/inspection",
  "part_type": "NE555P",
  "classification": "NEEDED",
  ...
}
```

---

## Mock 서버 포트 (개발용)

| 서버 | 포트 | 파일 |
|------|------|------|
| Mock ESP32 | 9001 | `mock/MockESP32.py` |
| Mock myCobot | 9002 | `mock/MockMyCobot.py` |
| Mock AGV | 9003 | `mock/MockAGV.py` |
| API + WebSocket | 8000 | `src/api/api_server.py` |
| Mosquitto | 1883 | `config/docker-compose.yml` |

## WPF 독립 개발용

```bash
# Python 서버 없이 Mock 데이터 발행
python mock_publisher.py
```

발행 토픽: `visipick/inspection` (3초), `visipick/agv/+/status` (1~2초),
`visipick/system/event` (5초), `visipick/system/state` (4초)
