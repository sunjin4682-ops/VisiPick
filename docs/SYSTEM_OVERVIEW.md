# VisiPick 시스템 구조 요약서
> 작성: 김선진 | 버전: 1.0 | 날짜: 2026-05-15

## 팀 역할 분담

| 담당 | 역할 | 주요 산출물 |
|------|------|-------------|
| 김선진 | 백엔드·인프라 | Flask, Mosquitto, SQLite, Blazor |
| 최지윤 | 현장 HMI | WPF, EF Core |
| 염재니 | 비전·로봇 | OpenCV, myCobot |

## 시스템 구성

| 컴포넌트 | 기술 | 포트 |
|----------|------|------|
| MQTT Broker | Mosquitto (Docker) | 1883 |
| Flask 백엔드 | Python 3.14 | 5001 |
| Blazor 관리자 | .NET 8 | 5000 |
| WPF HMI | .NET 8 | - |
| SQLite DB | EF Core 10.0 | - |

## 통신 흐름
카메라/로봇/ESP32/AGV
↓
Flask 백엔드 (비전·제어·발행)
↓ MQTT
Mosquitto Broker
↙         ↘
WPF          Blazor
(현장화면)   (관리자화면)
↕              ↕
SQLite ←────── SQLite
(쓰기)         (읽기)

## 자동 테스트 결과
- 50회 풀 사이클 성공률: 100%
- 평균 사이클 시간: 8.03초
- 전체 소요 시간: 401.29초

## 파일 구조
C:\VisiPick
├── config.json              # 전체 설정
├── StateMachine.py          # 상태 머신
├── Heartbeat.py             # 연결 모니터
├── Logger.py                # 로깅
├── SpcAnalysis.py           # SPC 분석
├── AutoTest.py              # 자동 테스트
├── docker-compose.yml       # Mosquitto
├── mock\                    # Mock 서버 3개
├── docs\                    # 기술 문서
├── logs\                    # 로그 파일
├── VisiPickData\            # SQLite + EF Core
└── VisiPickFlaskBackend\    # Flask 백엔드
