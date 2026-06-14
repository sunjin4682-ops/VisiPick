"""
AGV MQTT 연결 테스트 — 전체 시스템 없이 AGV 1대씩 독립 검증.

브로커: config.mqtt.broker (192.168.0.15:1883)
구독:   visipick/agv/+/status   (AGV → PC)
발행:   visipick/agv/{id}/command (PC → AGV)

실행:
    cd C:\\VisiPick
    python tools/test_agv.py            # 대기 모드 (상태 수신만)
    python tools/test_agv.py --id 1     # AGV 1번 지정
    python tools/test_agv.py --cmd STATUS          # 상태 즉시 요청
    python tools/test_agv.py --cmd GO_WAREHOUSE_1  # 목적지 설정
    python tools/test_agv.py --cmd TRAYS_READY_3   # 트레이 3개 적재 완료 → 출발
    python tools/test_agv.py --cmd EMERGENCY_STOP  # 비상정지
    python tools/test_agv.py --cmd EMERGENCY_CLEAR # 비상정지 해제
    python tools/test_agv.py --cmd LEAVE_HOME1_TO_START  # 홈1 → START 복귀(우커브)
    python tools/test_agv.py --cmd LEAVE_HOME2_TO_START  # 홈2 → START 복귀(직진)
    python tools/test_agv.py --cmd LEAVE_HOME3_TO_START  # 홈3 → START 복귀(좌커브)

키 (대기 중):
    1  AGV 1번에 STATUS 요청
    2  AGV 2번에 STATUS 요청
    g  GO_WAREHOUSE_1 발행 (--id 기준)
    h  GO_WAREHOUSE_2 발행 (--id 기준)
    t  TRAYS_READY_3 발행 (트레이 3개 적재 완료 → 출발)
    m  CLEAR_MISSION 발행 (미션/상태 초기화)
    7  GO_HOME_1 발행
    8  GO_HOME_2 발행
    9  GO_HOME_3 발행
    4  LEAVE_HOME1_TO_START 발행 (홈1 → 제자리회전·0.9s 라인트레이싱·우커브 → START 복귀)
    5  LEAVE_HOME2_TO_START 발행 (홈2 → 제자리회전 → 바로 START 복귀)
    6  LEAVE_HOME3_TO_START 발행 (홈3 → 제자리회전·0.9s 라인트레이싱·좌커브 → START 복귀)
    e  EMERGENCY_STOP 전체
    c  EMERGENCY_CLEAR 전체
    q  종료

복귀 테스트 순서: AGV를 HOME 라인 위에 두고 → g → t (창고 가서 자동 복귀)
끼임 복구:        손으로 HOME 라인 위로 옮기고 → m (CLEAR_MISSION) → 다시 g/t
"""
from __future__ import annotations
import argparse
import sys
import time
import json
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import paho.mqtt.client as mqtt
from src.utils.config_loader import config

BROKER = config["mqtt"]["broker"]
PORT   = config["mqtt"]["port"]
AGV_COUNT = config["agv"]["count"]

received: list[dict] = []
_lock = threading.Lock()


def on_connect(client, userdata, flags, rc, props=None):
    client.subscribe("visipick/agv/+/status")
    print(f"[브로커] 연결 OK ({BROKER}:{PORT}) — visipick/agv/+/status 구독 중")


def on_message(client, userdata, msg):
    raw = msg.payload.decode(errors="ignore")
    ts  = time.strftime("%H:%M:%S")
    try:
        data = json.loads(raw)
        agv_id      = data.get("agv_id", "?")
        status      = data.get("status", "?")
        next_action = data.get("next_action", "")
        node        = data.get("node", "")
        print(f"[{ts}] AGV {agv_id} | status={status} | next={next_action} | node={node}")
        with _lock:
            received.append({"ts": ts, "topic": msg.topic, **data})
    except Exception:
        print(f"[{ts}] RAW: {raw}")


def send(client, agv_id: int, cmd: str):
    topic = f"visipick/agv/{agv_id}/command"
    client.publish(topic, cmd)
    print(f"[발행] → {topic} : {cmd}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id",  type=int, default=1, help="대상 AGV ID (기본 1)")
    ap.add_argument("--cmd", default="",          help="즉시 발행할 명령 후 종료")
    args = ap.parse_args()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message

    print(f"브로커 연결 중 {BROKER}:{PORT} ...")
    try:
        client.connect(BROKER, PORT, keepalive=10)
    except Exception as e:
        print(f"[오류] 브로커 연결 실패: {e}")
        print("  → docker-compose -f config/docker-compose.yml up -d  실행 확인")
        sys.exit(1)

    client.loop_start()
    time.sleep(0.5)   # 연결 안정화

    # 즉시 명령 모드
    if args.cmd:
        send(client, args.id, args.cmd)
        time.sleep(2.0)   # 응답 수신 대기
        client.loop_stop()
        return

    # 대화형 대기 모드
    print("\n대기 중 — AGV 상태 수신 시 출력")
    print("키: 1/2=STATUS  g=GO_W1  h=GO_W2  t=TRAYS_READY_3  m=CLEAR_MISSION")
    print("    7/8/9=GO_HOME_1/2/3  4/5/6=LEAVE_HOME1/2/3_TO_START")
    print("    e=E-STOP  c=CLEAR  q=종료\n")
    try:
        import msvcrt   # Windows 전용 키 입력
        while True:
            if msvcrt.kbhit():
                k = msvcrt.getwch().lower()
                if k == "q":
                    break
                elif k == "1":
                    send(client, 1, "STATUS")
                elif k == "2":
                    send(client, 2, "STATUS")
                elif k == "g":
                    send(client, args.id, "GO_WAREHOUSE_1")
                elif k == "h":
                    send(client, args.id, "GO_WAREHOUSE_2")
                elif k == "t":
                    send(client, args.id, "TRAYS_READY_3")
                elif k == "m":
                    send(client, args.id, "CLEAR_MISSION")
                elif k == "7":
                    send(client, args.id, "GO_HOME_1")
                elif k == "8":
                    send(client, args.id, "GO_HOME_2")
                elif k == "9":
                    send(client, args.id, "GO_HOME_3")
                elif k == "4":
                    send(client, args.id, "LEAVE_HOME1_TO_START")
                elif k == "5":
                    send(client, args.id, "LEAVE_HOME2_TO_START")
                elif k == "6":
                    send(client, args.id, "LEAVE_HOME3_TO_START")
                elif k == "e":
                    for i in range(1, AGV_COUNT + 1):
                        send(client, i, "EMERGENCY_STOP")
                elif k == "c":
                    for i in range(1, AGV_COUNT + 1):
                        send(client, i, "EMERGENCY_CLEAR")
            time.sleep(0.05)
    except ImportError:
        input("엔터로 종료...\n")

    client.loop_stop()
    print(f"\n총 수신 {len(received)}건")


if __name__ == "__main__":
    main()
