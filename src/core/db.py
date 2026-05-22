import sqlite3
from datetime import datetime
from src.utils.config_loader import config
from src.utils.logger import setup_logger

logger = setup_logger("db")

DB_PATH = config["database"]["path"]


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL;")
    return c


# ── 저장 ─────────────────────────────────────────────────────────────────────

def save_inspection(payload: dict):
    """InspectionResults 1건 삽입."""
    try:
        c = _conn()
        c.execute("""
            INSERT INTO InspectionResults
            (Timestamp, RecipeSessionId, PartType, Classification, DefectCode, Confidence, GateAction, CycleTimeMs)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            payload.get("timestamp", datetime.now().isoformat()),
            payload.get("recipe_session_id"),
            payload["part_type"],
            payload["classification"],
            payload.get("defect_code", "NONE"),
            payload.get("confidence", 0.0),
            payload.get("gate_action", "PASS_THROUGH"),
            payload.get("cycle_time_ms", 0),
        ))
        c.commit()
        c.close()
        logger.info(f"[DB] 검사 저장 — {payload['part_type']} {payload['classification']} ({payload.get('defect_code','NONE')})")
    except Exception as e:
        logger.error(f"save_inspection 실패: {e}")


def save_recipe_session(parts: list[str]) -> int | None:
    """RecipeSessions 1건 삽입. 생성된 Id 반환."""
    try:
        c = _conn()
        cur = c.execute("""
            INSERT INTO RecipeSessions (StartTime, Parts, TotalNeeded, Status)
            VALUES (?, ?, ?, ?)
        """, (
            datetime.now().isoformat(),
            ",".join(parts),
            len(parts),
            "진행중",
        ))
        session_id = cur.lastrowid
        c.commit()
        c.close()
        logger.info(f"[DB] 레시피 세션 시작 — Id={session_id} parts={parts}")
        return session_id
    except Exception as e:
        logger.error(f"save_recipe_session 실패: {e}")
        return None


def complete_recipe_session(session_id: int, total_filled: int):
    """RecipeSessions 완료 처리."""
    try:
        c = _conn()
        c.execute("""
            UPDATE RecipeSessions
            SET EndTime=?, TotalFilled=?, Status='완료'
            WHERE Id=?
        """, (datetime.now().isoformat(), total_filled, session_id))
        c.commit()
        c.close()
        logger.info(f"[DB] 레시피 세션 완료 — Id={session_id} filled={total_filled}")
    except Exception as e:
        logger.error(f"complete_recipe_session 실패: {e}")


def save_agv_mission(agv_id: int, source: str, destination: str,
                     recipe_session_id: int = None):
    """AgvMissions 1건 삽입."""
    try:
        c = _conn()
        c.execute("""
            INSERT INTO AgvMissions
            (AgvId, StartTime, Source, Destination, RecipeSessionId, Status)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            agv_id,
            datetime.now().isoformat(),
            source,
            destination,
            recipe_session_id,
            "완료",
        ))
        c.commit()
        c.close()
        logger.info(f"[DB] AGV 미션 저장 — AGV{agv_id} {source}→{destination}")
    except Exception as e:
        logger.error(f"save_agv_mission 실패: {e}")


def save_system_event(source: str, event_type: str, message: str):
    """SystemEvents 1건 삽입."""
    try:
        c = _conn()
        c.execute(
            "INSERT INTO SystemEvents (Timestamp, Source, EventType, Message) VALUES (?, ?, ?, ?)",
            (datetime.now().isoformat(), source, event_type, message),
        )
        c.commit()
        c.close()
    except Exception as e:
        logger.error(f"save_system_event 실패: {e}")


# ── 조회 ─────────────────────────────────────────────────────────────────────

def get_inspections(limit: int = 100) -> list[dict]:
    """최근 검사 이력 N건."""
    c = _conn()
    rows = c.execute("""
        SELECT Id, Timestamp, RecipeSessionId, PartType, Classification,
               DefectCode, Confidence, GateAction, CycleTimeMs
        FROM InspectionResults ORDER BY Id DESC LIMIT ?
    """, (limit,)).fetchall()
    c.close()
    return [dict(r) for r in rows]


def get_inspections_search(
    part_type: str = None,
    classification: str = None,
    limit: int = 100,
) -> list[dict]:
    """검사 이력 필터 검색."""
    query = "SELECT * FROM InspectionResults WHERE 1=1"
    params: list = []
    if part_type:
        query += " AND PartType = ?"
        params.append(part_type)
    if classification:
        query += " AND Classification = ?"
        params.append(classification)
    query += " ORDER BY Id DESC LIMIT ?"
    params.append(limit)
    c = _conn()
    rows = c.execute(query, params).fetchall()
    c.close()
    return [dict(r) for r in rows]


def get_stats() -> dict:
    """전체 검사 통계 (분류별, 불량유형별, 부품별)."""
    c = _conn()
    total         = c.execute("SELECT COUNT(*) FROM InspectionResults").fetchone()[0]
    needed_count  = c.execute("SELECT COUNT(*) FROM InspectionResults WHERE Classification='NEEDED'").fetchone()[0]
    dup_count     = c.execute("SELECT COUNT(*) FROM InspectionResults WHERE Classification='DUPLICATE'").fetchone()[0]
    defect_count  = c.execute("SELECT COUNT(*) FROM InspectionResults WHERE Classification='DEFECT'").fetchone()[0]
    classification_counts = {
        r[0]: r[1] for r in c.execute(
            "SELECT Classification, COUNT(*) FROM InspectionResults GROUP BY Classification"
        ).fetchall()
    }
    defect_type_counts = {
        r[0]: r[1] for r in c.execute(
            "SELECT DefectCode, COUNT(*) FROM InspectionResults WHERE Classification='DEFECT' GROUP BY DefectCode"
        ).fetchall()
    }
    part_counts = {
        r[0]: r[1] for r in c.execute(
            "SELECT PartType, COUNT(*) FROM InspectionResults GROUP BY PartType"
        ).fetchall()
    }
    c.close()
    return {
        "total":                total,
        "needed_count":         needed_count,
        "duplicate_count":      dup_count,
        "defect_count":         defect_count,
        "pass_rate":            round(needed_count / total * 100, 1) if total else 0,
        "classification_counts": classification_counts,
        "defect_type_counts":   defect_type_counts,
        "part_counts":          part_counts,
    }


def get_sessions(limit: int = 50) -> list[dict]:
    """레시피 세션 이력 최근 N건."""
    c = _conn()
    rows = c.execute("""
        SELECT Id, StartTime, EndTime, Parts, TotalNeeded, TotalFilled, Status
        FROM RecipeSessions ORDER BY Id DESC LIMIT ?
    """, (limit,)).fetchall()
    c.close()
    return [dict(r) for r in rows]


def get_current_session() -> dict | None:
    """진행 중인 레시피 세션 (없으면 None)."""
    c = _conn()
    row = c.execute(
        "SELECT * FROM RecipeSessions WHERE Status='진행중' ORDER BY Id DESC LIMIT 1"
    ).fetchone()
    c.close()
    return dict(row) if row else None


def get_events(limit: int = 100) -> list[dict]:
    """시스템 이벤트 최근 N건."""
    c = _conn()
    rows = c.execute("""
        SELECT Id, Timestamp, Source, EventType, Message
        FROM SystemEvents ORDER BY Id DESC LIMIT ?
    """, (limit,)).fetchall()
    c.close()
    return [dict(r) for r in rows]


def get_agv_missions(limit: int = 100) -> list[dict]:
    """AGV 미션 이력 최근 N건."""
    c = _conn()
    rows = c.execute("""
        SELECT Id, AgvId, StartTime, EndTime, Source, Destination,
               RecipeSessionId, Status
        FROM AgvMissions ORDER BY Id DESC LIMIT ?
    """, (limit,)).fetchall()
    c.close()
    return [dict(r) for r in rows]
