# VisiPick MQTT 토픽 명세 (V6.3)
> Broker: Mosquitto localhost:1883 | 모든 페이로드: UTF-8 JSON

## 토픽 목록

| 토픽 | 발행자 | 구독자 | QoS |
|------|--------|--------|-----|
| `visipick/inspection` | vision (Python) | WPF, API | 0 |
| `visipick/agv/1/status` | AGV 1 (ESP32-CAM) | Python, WPF | 0 |
| `visipick/agv/2/status` | AGV 2 (ESP32-CAM) | Python, WPF | 0 |
| `visipick/agv/1/command` | Python | AGV 1 | 1 |
| `visipick/agv/2/command` | Python | AGV 2 | 1 |
| `visipick/system/event` | Python (any module) | WPF | 0 |
| `visipick/system/state` | state_machine (Python) | WPF | 0 |

---

## visipick/inspection

검사·분류 결과. Camera1+Camera2 판정 직후 발행.

```json
{
  "part_type":      "NE555P",
  "classification": "NEEDED",
  "defect_code":    "PASS",
  "confidence":     0.97,
  "gate_action":    "PASS_THROUGH",
  "timestamp":      "2026-05-22T12:00:00"
}
```

| 필드 | 타입 | 값 |
|------|------|-----|
| `part_type` | string | `NE555P` / `CD4017BE` / `ATmega328P` / `74HC595N` / `UNKNOWN` |
| `classification` | string | `NEEDED` / `DUPLICATE` / `DEFECT` |
| `defect_code` | string | `PASS` / `BENT_PIN` / `WRONG_SIZE` / `UNKNOWN` |
| `confidence` | float | 0.0 ~ 1.0 |
| `gate_action` | string | `PASS_THROUGH` / `GATE1_PUSH` / `GATE2_PUSH` |

---

## visipick/agv/{id}/status

AGV가 1초마다 발행하는 위치·상태 보고.

```json
{
  "agv_id":    1,
  "state":     "moving",
  "node":      "N3",
  "timestamp": "2026-05-22T12:00:00"
}
```

| `state` 값 | 의미 |
|------------|------|
| `idle` | 대기 중 |
| `moving` | 이동 중 |
| `arrived` | 목적지 도착 |
| `dumping` | 지게 쏟아내기 중 |
| `returning` | 출발지 복귀 중 |

---

## visipick/agv/{id}/command

Python Central Server → AGV 이동 명령.

```json
{
  "action":      "GO",
  "destination": "WAREHOUSE",
  "timestamp":   "2026-05-22T12:00:00"
}
```

| `action` 값 | 의미 |
|-------------|------|
| `GO` | 목적지로 출발 |
| `STOP` | 긴급 정지 |
| `RETURN` | 출발지 복귀 |
| `DOCK` | 도킹 위치 정밀 정렬 |

---

## visipick/system/event

모든 모듈이 발행하는 이벤트 로그. WPF 이벤트 패널에 표시.

```json
{
  "source":     "Camera1",
  "event_type": "INFO",
  "message":    "NE555P 검출 — NEEDED 판정",
  "timestamp":  "2026-05-22T12:00:00"
}
```

| `source` 예시 | `event_type` |
|--------------|--------------|
| `Camera1`, `Camera2` | `INFO` / `WARNING` / `ERROR` |
| `Gate1`, `Gate2` | `INFO` / `WARNING` |
| `Robot`, `AGV`, `System` | `INFO` / `WARNING` / `ERROR` |

---

## visipick/system/state

state_machine이 상태 전이 시마다 발행. WPF 상태바 갱신용.

```json
{
  "state":     "TRAY_TRANSFER",
  "timestamp": "2026-05-22T12:00:00"
}
```

| `state` 값 | 의미 |
|------------|------|
| `IDLE` | 대기 |
| `RUNNING` | 검사·분류 진행 중 |
| `TRAY_TRANSFER` | myCobot 트레이 이재 중 |
| `AGV_DISPATCH` | AGV 출발·운반 중 |
| `COMPLETE` | 사이클 완료 |
| `ERROR` | 오류 발생 |

---

## WPF 구독 목록 (최지윤 참고)

```csharp
// 구독해야 할 토픽 목록
client.Subscribe("visipick/inspection");
client.Subscribe("visipick/agv/1/status");
client.Subscribe("visipick/agv/2/status");
client.Subscribe("visipick/system/event");
client.Subscribe("visipick/system/state");
// command 토픽은 발행만, 구독 불필요
```
