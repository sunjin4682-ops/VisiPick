# VisiPick JSON 메시지 규격서
> 설계: 김선진 | 모든 팀원은 이 규격으로 개발

## 1. PC → ESP32 (게이트 제어)
```json
{
  "type": "gate_cmd",
  "gate": "A",
  "action": "open",
  "timestamp": "2026-05-12T20:00:00"
}
```

## 2. ESP32 → PC (게이트 응답)
```json
{
  "type": "gate_ack",
  "gate": "A",
  "status": "ok",
  "timestamp": "2026-05-12T20:00:00"
}
```

## 3. PC → myCobot (로봇 명령)
```json
{
  "type": "robot_cmd",
  "action": "pick",
  "buffer": "A",
  "tray": "A",
  "timestamp": "2026-05-12T20:00:00"
}
```

## 4. myCobot → PC (로봇 응답)
```json
{
  "type": "robot_ack",
  "action": "pick",
  "status": "ok",
  "timestamp": "2026-05-12T20:00:00"
}
```

## 5. PC → AGV (이동 명령)
```json
{
  "type": "agv_cmd",
  "agv_id": 1,
  "destination": "N5",
  "timestamp": "2026-05-12T20:00:00"
}
```

## 6. AGV → PC (상태 보고)
```json
{
  "type": "agv_status",
  "agv_id": 1,
  "state": "moving",
  "node": "N3",
  "timestamp": "2026-05-12T20:00:00"
}
```

## 7. Flask → MQTT (검사 결과)
```json
{
  "type": "inspection",
  "component_type": "DIP-8",
  "class": "A",
  "result": "양품",
  "confidence": 0.95,
  "gate_used": 1,
  "timestamp": "2026-05-12T20:00:00"
}
```