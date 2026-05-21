# VisiPick DB 스키마 명세
> 작성: 김선진 | DB: SQLite | 경로: C:\VisiPick\VisiPickData\visipick.db

## ER 다이어그램
InspectionResults          AgvMissions
+----------------+         +----------------+
| Id (PK)        |         | Id (PK)        |
| Timestamp      |         | AgvId          |
| ComponentType  |         | StartTime      |
| Class          |         | EndTime        |
| DefectCode     |         | Source         |
| Result         |         | Destination    |
| Confidence     |         | TrayClass      |
| CycleTimeMs    |         | ItemCount      |
| GateUsed       |         | Status         |
+----------------+         +----------------+
SystemEvents
+----------------+
| Id (PK)        |
| Timestamp      |
| Source         |
| EventType      |
| Message        |
+----------------+

## 테이블 상세

### InspectionResults (검사 결과)
| 컬럼 | 타입 | 설명 | 예시 |
|------|------|------|------|
| Id | INTEGER PK | 자동증가 | 1 |
| Timestamp | TEXT | 검사 시각 | 2026-05-15T12:00:00 |
| ComponentType | TEXT | 부품 종류 | DIP-8 |
| Class | TEXT | 분류 | A / B / C |
| DefectCode | TEXT | 불량 코드 | PASS / BENT_PIN |
| Result | TEXT | 판정 | 양품 / 불량 |
| Confidence | REAL | 신뢰도 | 0.95 |
| CycleTimeMs | INTEGER | 소요시간 | 320 |
| GateUsed | INTEGER | 게이트 번호 | 1 |

### AgvMissions (AGV 운반 기록)
| 컬럼 | 타입 | 설명 | 예시 |
|------|------|------|------|
| Id | INTEGER PK | 자동증가 | 1 |
| AgvId | INTEGER | AGV 번호 | 1 / 2 |
| StartTime | TEXT | 출발 시각 | 2026-05-15T12:00:00 |
| EndTime | TEXT | 도착 시각 | 2026-05-15T12:01:00 |
| Source | TEXT | 출발지 | N1 |
| Destination | TEXT | 목적지 | N5 |
| TrayClass | TEXT | 트레이 종류 | A / B / C |
| ItemCount | INTEGER | 적재 수량 | 5 |
| Status | TEXT | 상태 | 대기/운반중/완료/오류 |

### SystemEvents (시스템 이벤트)
| 컬럼 | 타입 | 설명 | 예시 |
|------|------|------|------|
| Id | INTEGER PK | 자동증가 | 1 |
| Timestamp | TEXT | 이벤트 시각 | 2026-05-15T12:00:00 |
| Source | TEXT | 발생 장치 | Camera/Robot/AGV |
| EventType | TEXT | 이벤트 종류 | INFO/WARNING/ERROR |
| Message | TEXT | 상세 내용 | DIP-8 검출 완료 |

## 인덱스 전략
- InspectionResults: Timestamp, Class, GateUsed
- AgvMissions: AgvId
- SystemEvents: Timestamp, EventType

## 데이터 보관 정책
- InspectionResults: 30일 후 삭제
- SystemEvents: 7일 후 삭제
- 백업: 매일 자정 backup/ 폴더 자동 복사
