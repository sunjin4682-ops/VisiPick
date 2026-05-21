import socket, json
from datetime import datetime

def send(port, msg):
    with socket.socket() as s:
        s.connect(("localhost", port))
        s.send(json.dumps(msg).encode())
        resp = s.recv(4096).decode()
        print(f"응답: {json.loads(resp)}")

def send_agv(port, msg):
    with socket.socket() as s:
        s.connect(("localhost", port))
        s.send(json.dumps(msg).encode())
        # AGV는 도착할 때까지 계속 응답 수신
        while True:
            resp = s.recv(4096).decode()
            if not resp:
                break
            data = json.loads(resp)
            print(f"AGV 상태: {data['state']} — 노드: {data['node']}")
            if data["state"] == "arrived":
                print("AGV 도착 완료!")
                break

print("\n=== ESP32 게이트 A 열기 ===")
send(9001, {
    "type": "gate_cmd",
    "gate": "A",
    "action": "open",
    "timestamp": datetime.now().isoformat()
})

print("\n=== myCobot Pick 명령 ===")
send(9002, {
    "type": "robot_cmd",
    "action": "pick",
    "buffer": "A",
    "tray": "A",
    "timestamp": datetime.now().isoformat()
})

print("\n=== AGV 이동 명령 ===")
send_agv(9003, {
    "type": "agv_cmd",
    "agv_id": 1,
    "destination": "N5",
    "timestamp": datetime.now().isoformat()
})

print("\n=== 전체 테스트 완료 ===")