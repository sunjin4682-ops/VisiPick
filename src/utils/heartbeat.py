import socket, time, threading
from datetime import datetime
from src.utils.logger import setup_logger
from src.utils.config_loader import config

logger = setup_logger("heartbeat")

DEVICES = {
    "myCobot": config["robot_mock"]["port"],
    "AGV":     config["agv_mock"]["port"],
}

# 상태 저장
status = {name: False for name in DEVICES}

def check(name, port):
    """포트 연결 가능 여부로 생존 확인"""
    try:
        with socket.create_connection(("localhost", port), timeout=1):
            return True
    except:
        return False

def heartbeat_loop():
    while True:
        print("\n" + "="*40)
        print(f"Heartbeat — {datetime.now().strftime('%H:%M:%S')}")
        print("="*40)
        for name, port in DEVICES.items():
            alive = check(name, port)
            prev  = status[name]
            status[name] = alive

            icon = "🟢" if alive else "🔴"
            state = "정상" if alive else "연결 끊김"
            print(f"{icon} {name:10} — {state}")

            # 상태 변화 감지
            if prev and not alive:
                logger.warning(f"{name} 연결 끊김!")
            elif not prev and alive:
                logger.info(f"{name} 연결 복구!")

        time.sleep(2)

if __name__ == "__main__":
    logger.add(
        "logs/heartbeat-{time:YYYY-MM-DD}.log",
        rotation="00:00",
        encoding="utf-8"
    )
    logger.info("Heartbeat 모니터 시작")
    heartbeat_loop()
