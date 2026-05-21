import socket, json, threading
from datetime import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.utils.logger import setup_logger

logger = setup_logger("esp32")

HOST, PORT = "0.0.0.0", 9001

def handle(conn, addr):
    logger.info(f"ESP32 Mock: {addr} 연결")
    while True:
        try:
            data = conn.recv(1024).decode()
            if not data:
                break
            msg = json.loads(data)
            logger.info(f"수신: {msg}")
            if msg.get("type") == "gate_cmd":
                ack = {
                    "type": "gate_ack",
                    "gate": msg["gate"],
                    "status": "ok",
                    "timestamp": datetime.now().isoformat()
                }
                conn.send((json.dumps(ack) + "\n").encode())
                logger.info(f"응답: {ack}")
        except:
            break

server = socket.socket()
server.bind((HOST, PORT))
server.listen(5)
logger.info(f"Mock ESP32 실행 중 — port {PORT}")

while True:
    conn, addr = server.accept()
    threading.Thread(target=handle, args=(conn, addr)).start()
