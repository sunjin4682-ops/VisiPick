# VisiPick API 명세서
> 작성: 김선진 | 버전: 1.0 | 날짜: 2026-05-15

## Base URL
http://192.168.0.46:5001

## 엔드포인트 목록

---

##
{ "result": "started" }
`

---


## MQTT 토픽 명세

| 토픽 | 방향 | 설명 |
|------|------|------|
| factory/visipick/inspection | Flask → WPF·Blazor | 검사 결과 |
| factory/visipick/robot/cmd | WPF → Flask | 로봇 명령 |
| factory/visipick/agv/{id}/status | WPF → Blazor | AGV 상태 |
| factory/visipick/system/event | 전체 → Blazor | 시스템 이벤트 |

---

## Mock 서버 포트

| 서버 | 포트 | 파일 |
|------|------|------|
| Mock ESP32 | 9001 | mock/MockESP32.py |
| Mock myCobot | 9002 | mock/MockMyCobot.py |
| Mock AGV | 9003 | mock/MockAGV.py |
| Flask API | 5001 | main.py |
| Mosquitto | 1883 | docker-compose.yml |
