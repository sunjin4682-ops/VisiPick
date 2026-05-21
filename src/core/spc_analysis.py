import sqlite3
import numpy as np
import pandas as pd
from datetime import datetime
from src.utils.logger import setup_logger
from src.utils.config_loader import config

logger = setup_logger("spc")

DB_PATH = config["database"]["path"]

def load_data():
    """SQLite에서 검사 결과 로드"""
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("""
        SELECT Confidence, CycleTimeMs, Class, Result, Timestamp
        FROM InspectionResults
        ORDER BY Timestamp DESC
    """, conn)
    conn.close()
    return df

def calc_spc(data: pd.Series, usl: float, lsl: float):
    """
    평균, 표준편차, Cp, Cpk 계산
    usl: 상한 규격, lsl: 하한 규격
    """
    mean  = data.mean()
    std   = data.std()

    if std == 0:
        return {"mean": mean, "std": 0, "Cp": 0, "Cpk": 0}

    cp  = (usl - lsl) / (6 * std)
    cpu = (usl - mean) / (3 * std)
    cpl = (mean - lsl) / (3 * std)
    cpk = min(cpu, cpl)

    return {
        "mean": round(mean, 4),
        "std":  round(std, 4),
        "Cp":   round(cp, 4),
        "Cpk":  round(cpk, 4),
    }

def run():
    logger.info("SPC 분석 시작")

    df = load_data()

    if df.empty:
        logger.warning("데이터 없음 — Flask 더미 모드로 데이터 먼저 쌓아주세요")
        return

    logger.info(f"총 데이터: {len(df)}건")

    # ① 신뢰도 SPC (USL=1.0, LSL=0.85)
    print("\n=== 신뢰도 (Confidence) SPC ===")
    result = calc_spc(df["Confidence"], usl=1.0, lsl=0.85)
    for k, v in result.items():
        print(f"  {k:6}: {v}")

    # ② 사이클 타임 SPC (USL=1000ms, LSL=0ms)
    print("\n=== 사이클 타임 (CycleTimeMs) SPC ===")
    result = calc_spc(df["CycleTimeMs"], usl=1000, lsl=0)
    for k, v in result.items():
        print(f"  {k:6}: {v}")

    # ③ 클래스별 분포
    print("\n=== 클래스별 분포 ===")
    counts = df["Class"].value_counts()
    total  = len(df)
    for cls, cnt in counts.items():
        print(f"  클래스 {cls}: {cnt}건 ({cnt/total*100:.1f}%)")

    # ④ 양품률
    print("\n=== 양품률 ===")
    good  = len(df[df["Result"] == "양품"])
    total = len(df)
    print(f"  양품: {good}건 / 전체: {total}건 ({good/total*100:.1f}%)")

    # ⑤ Cp/Cpk 판정
    print("\n=== 공정 능력 판정 ===")
    cp = calc_spc(df["Confidence"], usl=1.0, lsl=0.85)["Cp"]
    if cp >= 1.67:
        print("  ✅ 매우 우수 (Cp ≥ 1.67)")
    elif cp >= 1.33:
        print("  ✅ 우수 (Cp ≥ 1.33)")
    elif cp >= 1.0:
        print("  ⚠️ 보통 (Cp ≥ 1.0)")
    else:
        print("  ❌ 불량 (Cp < 1.0) — 공정 개선 필요")

    logger.info("SPC 분석 완료")

if __name__ == "__main__":
    run()
