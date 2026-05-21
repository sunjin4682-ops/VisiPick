import socket, json, threading, time, sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.utils.logger import setup_logger

logger = setup_logger("mycobot")

HOST, PORT = "0.0.0.0", 9002

def handle(conn, addr):
    logger.info(f"myCobot Mock: {addr} 연결")
    while True:
        try:
            data = conn.recv(1024).decode()
            if not data:
                break
            msg = json.loads(data)
            logger.info(f"수신: {msg}")

            if msg.get("type") == "robot_cmd":
                logger.info(f"[Mock] {msg['action']} 시뮬 중...")
                time.sleep(2)  # 동작 시간 시뮬
                ack = {
                    "type": "robot_ack",
                    "action": msg["action"],
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
logger.info(f"Mock myCobot 실행 중 — port {PORT}")

while True:
    conn, addr = server.accept()
    threading.Thread(target=handle, args=(conn, addr)).start()