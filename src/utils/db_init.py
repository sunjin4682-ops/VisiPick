import sqlite3
from pathlib import Path
from src.utils.config_loader import config

DB_PATH = config["database"]["path"]


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """테이블·인덱스 생성 + WAL 모드 활성화. 이미 존재하면 무시."""
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = get_conn()

    conn.executescript("""
        PRAGMA journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS RecipeSessions (
            Id          INTEGER PRIMARY KEY AUTOINCREMENT,
            StartTime   TEXT    NOT NULL,
            EndTime     TEXT,
            Parts       TEXT    NOT NULL DEFAULT '',
            TotalNeeded INTEGER NOT NULL DEFAULT 0,
            TotalFilled INTEGER NOT NULL DEFAULT 0,
            Status      TEXT    NOT NULL DEFAULT '진행중'
        );

        CREATE TABLE IF NOT EXISTS InspectionResults (
            Id               INTEGER PRIMARY KEY AUTOINCREMENT,
            Timestamp        TEXT    NOT NULL,
            RecipeSessionId  INTEGER,
            PartType         TEXT    NOT NULL DEFAULT '',
            Classification   TEXT    NOT NULL DEFAULT '',
            DefectCode       TEXT    NOT NULL DEFAULT '',
            Confidence       REAL    NOT NULL DEFAULT 0,
            GateAction       TEXT    NOT NULL DEFAULT '',
            CycleTimeMs      INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (RecipeSessionId) REFERENCES RecipeSessions(Id)
        );

        CREATE TABLE IF NOT EXISTS AgvMissions (
            Id              INTEGER PRIMARY KEY AUTOINCREMENT,
            AgvId           INTEGER NOT NULL,
            StartTime       TEXT    NOT NULL,
            EndTime         TEXT,
            Source          TEXT    NOT NULL DEFAULT '',
            Destination     TEXT    NOT NULL DEFAULT '',
            RecipeSessionId INTEGER,
            Status          TEXT    NOT NULL DEFAULT '대기',
            FOREIGN KEY (RecipeSessionId) REFERENCES RecipeSessions(Id)
        );

        CREATE TABLE IF NOT EXISTS SystemEvents (
            Id        INTEGER PRIMARY KEY AUTOINCREMENT,
            Timestamp TEXT NOT NULL,
            Source    TEXT NOT NULL DEFAULT '',
            EventType TEXT NOT NULL DEFAULT '',
            Message   TEXT NOT NULL DEFAULT ''
        );

        CREATE INDEX IF NOT EXISTS ix_inspection_timestamp      ON InspectionResults (Timestamp);
        CREATE INDEX IF NOT EXISTS ix_inspection_classification ON InspectionResults (Classification);
        CREATE INDEX IF NOT EXISTS ix_inspection_part_type      ON InspectionResults (PartType);
        CREATE INDEX IF NOT EXISTS ix_inspection_session        ON InspectionResults (RecipeSessionId);
        CREATE INDEX IF NOT EXISTS ix_agv_id                    ON AgvMissions (AgvId);
        CREATE INDEX IF NOT EXISTS ix_agv_session               ON AgvMissions (RecipeSessionId);
        CREATE INDEX IF NOT EXISTS ix_event_timestamp           ON SystemEvents (Timestamp);
        CREATE INDEX IF NOT EXISTS ix_event_type                ON SystemEvents (EventType);
    """)

    conn.commit()
    conn.close()


def cleanup_old_records():
    """보존 기간 초과 레코드 삭제 (설정 기준)."""
    days_inspection = config["database"]["retention_days_inspection"]
    days_events     = config["database"]["retention_days_events"]

    conn = get_conn()
    conn.execute(
        "DELETE FROM InspectionResults WHERE Timestamp < datetime('now', ?)",
        (f"-{days_inspection} days",)
    )
    conn.execute(
        "DELETE FROM SystemEvents WHERE Timestamp < datetime('now', ?)",
        (f"-{days_events} days",)
    )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print(f"DB 초기화 완료: {DB_PATH}")
