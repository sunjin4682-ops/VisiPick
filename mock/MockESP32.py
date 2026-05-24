import socket, json, threading, time
from datetime import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.utils.logger import setup_logger
from src.utils.config_loader import config

logger = setup_logger("esp32")

HOST, PORT = "0.0.0.0", 9001
SENSOR_INTERVAL = config.get("vision", {}).get("dummy_interval_sec", 4)


def _sensor_trigger_loop(conn, stop_event):
    """연결된 클라이언트에 주기적으로 sensor_triggered 전송."""
    while not stop_event.is_set():
        time.sleep(SENSOR_INTERVAL)
        if stop_event.is_set():
            break
        try:
            msg = {"type": "sensor_triggered", "timestamp": datetime.now().isoformat()}
            conn.send((json.dumps(msg) + "\n").encode())
            logger.debug(f"sensor_triggered 발행")
        except OSError:
            break


def handle(conn, addr):
    logger.info(f"ESP32 Mock: {addr} 연결 — sensor_triggered {SENSOR_INTERVAL}s 주기 시작")
    stop_event = threading.Event()
    trigger_thread = threading.Thread(
        target=_sensor_trigger_loop, args=(conn, stop_event), daemon=True
    )
    trigger_thread.start()

    try:
        while True:
            data = conn.recv(1024).decode()
            if not data:
                break
            for line in data.strip().splitlines():
                try:
                    msg = json.loads(line)
                    logger.info(f"수신: {msg}")
                    msg_type = msg.get("type")
                    if msg_type == "gate_cmd":
                        ack = {
                            "type": "gate_ack",
                            "gate": msg["gate"],
                            "status": "ok",
                            "timestamp": datetime.now().isoformat(),
                        }
                        conn.send((json.dumps(ack) + "\n").encode())
                        logger.info(f"응답: {ack}")
                    elif msg_type == "conveyor_cmd":
                        ack = {
                            "type": "conveyor_ack",
                            "action": msg.get("action"),
                            "speed": msg.get("speed"),
                            "status": "ok",
                            "timestamp": datetime.now().isoformat(),
                        }
                        conn.send((json.dumps(ack) + "\n").encode())
                        logger.info(f"응답: {ack}")
                    elif msg_type == "tray_cmd":
                        ack = {
                            "type": "tray_ack",
                            "action": msg.get("action"),
                            "status": "ok",
                            "timestamp": datetime.now().isoformat(),
                        }
                        conn.send((json.dumps(ack) + "\n").encode())
                        logger.info(f"응답: {ack}")
                except json.JSONDecodeError:
                    pass
    except OSError:
        pass
    finally:
        stop_event.set()
        conn.close()
        logger.info(f"ESP32 Mock: {addr} 연결 종료")


server = socket.socket()
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind((HOST, PORT))
server.listen(5)
logger.info(f"Mock ESP32 실행 중 — port {PORT}, sensor_triggered 주기: {SENSOR_INTERVAL}s")

while True:
    conn, addr = server.accept()
    threading.Thread(target=handle, args=(conn, addr), daemon=True).start()
