import serial, json, time

s = serial.Serial("COM5", 115200, timeout=10)
time.sleep(2)
s.reset_input_buffer()

def send(m):
    s.reset_input_buffer()
    s.write((json.dumps(m) + "\n").encode())
    resp = s.readline().decode().strip()
    print("→", m)
    print("←", resp)
    return resp

send({"type": "ping"})

send({"type": "conveyor_cmd", "action": "set_speed", "speed": 1.5})
print("--- 컨베이어 3초 동작 확인 ---")
time.sleep(3)                                                        # ← 여기서 확인

send({"type": "gate_cmd", "gate": "1", "action": "push"})
time.sleep(0.5)

send({"type": "tray_cmd", "action": "advance"})
time.sleep(2)                                                        # B모터 2초 완료 대기

send({"type": "conveyor_cmd", "action": "set_speed", "speed": 0.0})
print("--- 정지 ---")

print("--- 센서 감지 대기 (Ctrl+C 로 종료) ---")
while True:
    line = s.readline().decode().strip()
    if line:
        print(line)