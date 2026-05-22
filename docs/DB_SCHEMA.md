# VisiPick DB 스키마 명세 (V6.3)
> 작성: 김선진 | DB: SQLite WAL | 경로: `C:\VisiPick\data\visipick.db`

## ER 다이어그램

```
InspectionResults          RecipeSessions            AgvMissions
+------------------+       +------------------+       +------------------+
| Id (PK)          |       | Id (PK, UUID)    |◄──FK─┤ RecipeSessionId  |
| Timestamp        |       | StartedAt        |       | Id (PK)          |
| PartType         |       | CompletedAt      |       | AgvId            |
| Classification   |       | Slot1Part        |       | StartTime        |
| DefectCode       |       | Slot2Part        |       | EndTime          |
| Confidence       |       | Slot3Part        |       | Source           |
| GateAction       |       | Slot4Part        |       | Destination      |
| CycleTimeMs      |       | AgvId            |       | Status           |
+------------------+       +------------------+       +------------------+

SystemEvents
+------------------+
| Id (PK)          |
| Timestamp        |
| Source           |
| EventType        |
| Message          |
+------------------+
```

## 테이블 상세

### InspectionResults (검사 결과)
| 컬럼 | 타입 | 설명 | 예시 |
|------|------|------|------|
| Id | INTEGER PK | 자동증가 | 1 |
| Timestamp | TEXT (ISO8601) | 검사 시각 | 2026-05-22T12:00:00 |
| PartType | TEXT | DIP IC 종류 | NE555P / CD4017BE / ATmega328P / 74HC595N / UNKNOWN |
| Classification | TEXT | 3클래스 판정 | NEEDED / DUPLICATE / DEFECT |
| DefectCode | TEXT | 불량 코드 | PASS / BENT_PIN / WRONG_SIZE / UNKNOWN |
| Confidence | REAL | 분류 신뢰도 | 0.97 |
| GateAction | TEXT | 게이트 동작 | PASS_THROUGH / GATE1_PUSH / GATE2_PUSH |
| CycleTimeMs | INTEGER | 검출~판정 소요 시간 | 320 |

### RecipeSessions (레시피 세션)
| 컬럼 | 타입 | 설명 | 예시 |
|------|------|------|------|
| Id | TEXT PK | 세션 UUID | "a1b2-c3d4-..." |
| StartedAt | TEXT (ISO8601) | 세션 시작 시각 | 2026-05-22T12:00:00 |
| CompletedAt | TEXT (nullable) | 완성 시각 | 2026-05-22T12:02:30 |
| Slot1Part | TEXT | NE555P 수집 기록 | "NE555P" |
| Slot2Part | TEXT | CD4017BE 수집 기록 | "CD4017BE" |
| Slot3Part | TEXT | ATmega328P 수집 기록 | "ATmega328P" |
| Slot4Part | TEXT | 74HC595N 수집 기록 | "74HC595N" |
| AgvId | INTEGER (nullable) | 이재된 AGV 번호 | 1 / 2 |

### AgvMissions (AGV 운반 기록)
| 컬럼 | 타입 | 설명 | 예시 |
|------|------|------|------|
| Id | INTEGER PK | 자동증가 | 1 |
| AgvId | INTEGER | AGV 번호 | 1 / 2 |
| StartTime | TEXT | 출발 시각 | 2026-05-22T12:02:30 |
| EndTime | TEXT (nullable) | 도착 시각 | 2026-05-22T12:03:10 |
| Source | TEXT | 출발지 노드 | N1 |
| Destination | TEXT | 목적지 노드 | WAREHOUSE |
| RecipeSessionId | TEXT (FK) | 연결된 레시피 세션 | "a1b2-c3d4-..." |
| Status | TEXT | 상태 | 대기 / 운반중 / 완료 / 오류 |

### SystemEvents (시스템 이벤트)
| 컬럼 | 타입 | 설명 | 예시 |
|------|------|------|------|
| Id | INTEGER PK | 자동증가 | 1 |
| Timestamp | TEXT | 이벤트 시각 | 2026-05-22T12:00:00 |
| Source | TEXT | 발생 장치 | Camera1 / Camera2 / Robot / AGV / Gate |
| EventType | TEXT | 이벤트 종류 | INFO / WARNING / ERROR |
| Message | TEXT | 상세 내용 | "NE555P 검출 완료" |

## 인덱스 전략

| 테이블 | 인덱스 컬럼 | 이유 |
|--------|------------|------|
| InspectionResults | Timestamp | 시간 범위 조회 |
| InspectionResults | PartType | 부품별 통계 |
| InspectionResults | Classification | 분류별 집계 |
| RecipeSessions | StartedAt | 최근 세션 조회 |
| AgvMissions | AgvId | AGV별 이력 |
| SystemEvents | Timestamp | 최근 이벤트 조회 |
| SystemEvents | EventType | 경고/오류 필터 |

## 데이터 보관 정책

| 테이블 | 보관 기간 | 비고 |
|--------|----------|------|
| InspectionResults | 30일 | `db_init.cleanup_old_records()` 자동 삭제 |
| RecipeSessions | 무제한 | 영구 보관 |
| AgvMissions | 무제한 | 영구 보관 |
| SystemEvents | 7일 | 자동 삭제 |

## 초기화

```bash
python -m src.utils.db_init   # 테이블·인덱스 생성 + WAL 모드 활성화
```
