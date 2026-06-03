"""적외선(IR) 투입단 센서 트리거 단독 검증 — 1단계 하드웨어 테스트.

전체 FSM/카메라/게이트 없이, ESP32가 부품 감지 시 보내는
{"type":"sensor_triggered"} 가 PC 까지 실제로 도달하는지만 확인한다.

사용:
    cd C:\\VisiPick
    python tools/test_ir_trigger.py
    → IR 센서 앞으로 부품을 통과시키면 트리거가 콘솔에 찍힌다.
    Ctrl+C 로 종료.

config.serial.port(COM8)/baudrate 를 사용. dummy_mode 와 무관하게 항상 실시리얼로 연다
(이 테스트의 목적이 실하드웨어 확인이므로).
"""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import serial  # noqa: E402
from src.utils.config_loader import config  # noqa: E402

PORT = config["serial"]["port"]
BAUD = config["serial"]["baudrate"]


def main():
    print(f"[IR test] {PORT} @ {BAUD}bps 연결 시도...")
    ser = serial.Serial(PORT, BAUD, timeout=1)
    time.sleep(2)                    # ESP32 리셋 대기
    ser.reset_input_buffer()
    print("[IR test] 연결됨. IR 센서 앞으로 부품을 통과시키세요. (Ctrl+C 종료)\n")

    count = 0
    last_t = None
    try:
        while True:
            raw = ser.readline()
            if not raw:
                continue
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            # JSON 이면 파싱, 아니면 원문 그대로 표시(펌웨어 디버그 로그 포함)
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                print(f"  [raw] {line}")
                continue

            if msg.get("type") == "sensor_triggered":
                count += 1
                now = time.time()
                gap = f"  (직전 대비 {now - last_t:.2f}s)" if last_t else ""
                last_t = now
                print(f"✅ [{count}] sensor_triggered 수신{gap}  payload={msg}")
            else:
                print(f"  [msg] {msg}")
    except KeyboardInterrupt:
        print(f"\n[IR test] 종료 — 총 {count}회 트리거 감지")
    finally:
        ser.close()


if __name__ == "__main__":
    main()
