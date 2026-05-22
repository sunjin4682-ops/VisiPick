# VisiPick JSON 메시지 규격서 (V6.3)
> 설계: 김선진 | 모든 팀원은 이 규격으로 개발

## 1. PC → ESP32 (Gate1 푸셔 — 중복 부품)

```json
{
  "type": "gate_cmd",
  "gate": 1,
  "action": "push",
  "timestamp": "2026-05-22T12:00:00"
}
```

## 2. PC → ESP32 (Gate2 푸셔 — 불량 부품)

```json
{
  "type": "gate_cmd",
  "gate": 2,
  "action": "push",
  "timestamp": "2026-05-22T12:00:00"
}
```

## 3. ESP32 → PC (푸셔 응답)

```json
{
  "type": "gate_ack",
  "gate": 1,
  "status": "ok",
  "timestamp": "2026-05-22T12:00:00"
}
```

## 4. PC → ESP32 (컨1 스텝모터 제어)

```json
{
  "type": "conveyor_cmd",
  "action": "start",
  "speed": 50,
  "timestamp": "2026-05-22T12:00:00"
}
```

## 5. PC → myCobot (트레이 이재 명령)

```json
{
  "type": "robot_cmd",
  "action": "transfer_tray",
  "source": "conveyor2",
  "target": "agv",
  "timestamp": "2026-05-22T12:00:00"
}
```

## 6. myCobot → PC (로봇 응답)

```json
{
  "type": "robot_ack",
  "action": "transfer_tray",
  "status": "ok",
  "timestamp": "2026-05-22T12:00:00"
}
```

## 7. MQTT: PC → AGV (이동 명령)

토픽: `visipick/agv/{id}/command`

```json
{
  "action": "GO",
  "destination": "WAREHOUSE",
  "timestamp": "2026-05-22T12:00:00"
}
```

## 8. MQTT: AGV → PC (상태 보고)

토픽: `visipick/agv/{id}/status`

```json
{
  "agv_id": 1,
  "state": "moving",
  "node": "N3",
  "timestamp": "2026-05-22T12:00:00"
}
```

AGV `state` 값:
| state | 의미 |
|-------|------|
| `idle` | 대기 중 |
| `moving` | 이동 중 |
| `arrived` | 목적지 도착 |
| `dumping` | 지게 쏟아내기 중 |
| `returning` | 복귀 중 |

## 9. MQTT: vision → all (검사 결과)

토픽: `visipick/inspection`

```json
{
  "part_type": "NE555P",
  "classification": "NEEDED",
  "defect_code": "PASS",
  "confidence": 0.97,
  "gate_action": "PASS_THROUGH",
  "timestamp": "2026-05-22T12:00:00"
}
```

`classification` 값:
| 값 | 의미 | 게이트 동작 |
|----|------|------------|
| `NEEDED` | 레시피에 필요한 양품 | PASS_THROUGH (통과) |
| `DUPLICATE` | 이미 수집된 부품 | GATE1_PUSH |
| `DEFECT` | 불량 (핀 휘어짐 등) | GATE2_PUSH |

`defect_code` 값:
| 값 | 의미 |
|----|------|
| `PASS` | 양품 |
| `BENT_PIN` | 핀 휘어짐 |
| `WRONG_SIZE` | 크기 이상 |
| `UNKNOWN` | 식별 불가 |

## 10. MQTT: any → WPF (시스템 이벤트)

토픽: `visipick/system/event`

```json
{
  "source": "Camera1",
  "event_type": "INFO",
  "message": "NE555P 검출 — NEEDED 판정",
  "timestamp": "2026-05-22T12:00:00"
}
```

## 11. MQTT: state_machine → WPF (공정 상태)

토픽: `visipick/system/state`

```json
{
  "state": "TRAY_TRANSFER",
  "timestamp": "2026-05-22T12:00:00"
}
```

`state` 값: `IDLE` / `RUNNING` / `TRAY_TRANSFER` / `AGV_DISPATCH` / `COMPLETE` / `ERROR`
