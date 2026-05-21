import socket, json, threading, time, sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.utils.logger import setup_logger

logger = setup_logger("agv")

HOST, PORT = "0.0.0.0", 9003
NODES = ["N1", "N2", "N3", "N4", "N5"]

def handle(conn, addr):
    logger.info(f"AGV Mock: {addr} 연결")
    while True:
        try:
            data = conn.recv(1024).decode()
            if not data:
                break
            msg = json.loads(data)
            logger.info(f"수신: {msg}")

            if msg.get("type") == "agv_cmd":
                # 노드 순서대로 이동 시뮬
                for node in NODES:
                    status = {
                        "type": "agv_status",
                        "agv_id": msg["agv_id"],
                        "state": "moving",
                        "node": node,
                        "timestamp": datetime.now().isoformat()
                    }
                    conn.send((json.dumps(status) + "\n").encode())
                    logger.info(f"이동 중: {node}")
                    time.sleep(1)

                # 도착
                arrived = {
                    "type": "agv_status",
                    "agv_id": msg["agv_id"],
                    "state": "arrived",
                    "node": msg["destination"],
                    "timestamp": datetime.now().isoformat()
                }
                conn.send((json.dumps(arrived) + "\n").encode())
                logger.info(f"도착: {msg['destination']}")
        except:
            break

server = socket.socket()
server.bind((HOST, PORT))
server.listen(5)
logger.info(f"Mock AGV 실행 중 — port {PORT}")

while True:
    conn, addr = server.accept()
    threading.Thread(target=handle, args=(conn, addr)).start()