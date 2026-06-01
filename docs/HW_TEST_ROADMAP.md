# VisiPick 하드웨어 동작 테스트 로드맵

> **목표:** 이 PC에 **ESP32(컨베이어 3개 + 게이트 2개) + 카메라**만 연결해서 동작을 확인한다.
> 로봇(myCobot)·AGV는 실물 없이 더미로 둔다.
> **누구나 위에서부터 순서대로 따라 하면 된다.**

---

## 준비물 체크
- [ ] ESP32 보드 (펌웨어 업로드 완료) + USB 케이블
- [ ] USB 카메라 1~2대
- [ ] 컨베이어(컨1 스텝모터 / 컨2 A모터 / 컨3 B모터) + 게이트 서보 2개 결선 완료
- [ ] 이 PC (Windows)

> ⚠️ **COM 포트는 한 프로그램만 점유**한다. Arduino IDE의 Serial Monitor가 열려 있으면 Python이 포트를 못 연다 → 테스트 전 **Serial Monitor 닫기**.

---

## STEP 0 — 1회성 환경 준비

### 0-1. Python 가상환경 + 패키지
PowerShell에서 프로젝트 폴더(`C:\VisiPick`)로 이동 후:
```powershell
cd C:\VisiPick
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install pyserial paho-mqtt loguru opencv-python fastapi uvicorn
```

### 0-2. 펌웨어 업로드 (Arduino IDE)
- 라이브러리: **ESP32Servo**, **AccelStepper**, **ArduinoJson(v7)** 설치
- `Hardware-Connect/esp32/esp32.ino` 열고 → 보드 `ESP32 Dev Module` → 포트 선택 → 업로드
- Serial Monitor(115200, Newline)에서 RST 누르면 `{"type":"status","status":"ok","message":"ESP32 READY"...}` 확인 → **확인 후 Serial Monitor 닫기**

### 0-3. COM 포트 번호 확인
- **장치 관리자 → 포트(COM & LPT)** 에서 ESP32의 `COM?` 확인 (예: COM5)

### 0-4. 카메라 인덱스 확인
- 보통 0번(노트북 내장캠 있으면 0=내장, 1·2=USB). STEP 1에서 자동 확인됨.

---

## STEP 1 — 카메라 캡처 확인 (독립)

`cam_test.py` 파일을 만들어 아래 저장 후 실행:
```python
import cv2
for idx in range(3):                       # 0,1,2번 인덱스 검사
    cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)   # Windows는 CAP_DSHOW 권장
    ok, frame = cap.read()
    if ok:
        print(f"카메라 {idx}: OK  해상도={frame.shape[1]}x{frame.shape[0]}  → cam{idx}.jpg 저장")
        cv2.imwrite(f"cam{idx}.jpg", frame)
    else:
        print(f"카메라 {idx}: 없음/열기 실패")
    cap.release()
```
```powershell
python cam_test.py
```
- 생성된 `cam0.jpg`·`cam1.jpg` 등을 열어 **상부/측면 카메라가 어느 인덱스인지** 확인하고 메모.
- (이 인덱스는 나중에 `config.json`의 `cameras.top.index` / `cameras.side.index`에 넣는다.)

---

## STEP 2 — ESP32 컨베이어 + 게이트 동작 확인 (핵심, 가장 확실)

FSM·MQTT 없이 ESP32에 직접 명령을 보내 모든 구동부를 확인한다. (config 설정 불필요)

`hw_test.py` 파일을 만들어 저장 (포트 번호만 본인 것으로 수정):
```python
import serial, json, time

PORT = "COM5"   # ← STEP 0-3에서 확인한 포트로 수정
s = serial.Serial(PORT, 115200, timeout=10)
time.sleep(2); s.reset_input_buffer()

def send(m):
    s.reset_input_buffer()
    s.write((json.dumps(m) + "\n").encode())
    print("→", m, "\n←", s.readline().decode().strip())

print("\n[1] 통신 확인")
send({"type": "ping"})                                           # status:ok 기대

print("\n[2] 컨1(메인 컨베이어) 3초 구동")
send({"type": "conveyor_cmd", "action": "set_speed", "speed": 1.5})
time.sleep(3)

print("\n[3] 컨2(중복반환)는 ESP32 부팅 시 자동 ON — 이미 돌고 있어야 함")
time.sleep(1)

print("\n[4] 게이트 1, 2 푸셔")
send({"type": "gate_cmd", "gate": "1", "action": "push"}); time.sleep(1)
send({"type": "gate_cmd", "gate": "2", "action": "push"}); time.sleep(1)

print("\n[5] 컨3(다음 빈 트레이 공급) 2초 구동")
send({"type": "tray_cmd", "action": "advance"}); time.sleep(2.5)

print("\n[6] 컨1 정지")
send({"type": "conveyor_cmd", "action": "set_speed", "speed": 0.0})

s.close()
print("\n테스트 완료")
```
```powershell
python hw_test.py
```

### 합격 기준 (눈으로 확인)
| 단계 | 기대 동작 | 응답 |
|------|-----------|------|
| [1] | — | `{"type":"pong","status":"ok"}` |
| [2] | 컨1 스텝모터 3초간 회전 | `conveyor_ack ... "status":"ok"` |
| [3] | 컨2 A모터 계속 회전(부팅부터) | (자동, 명령 없음) |
| [4] | 게이트1·2 서보가 밀고 복귀 | `gate_ack ... "status":"ok"` ×2 |
| [5] | 컨3 B모터 약 2초 회전 후 정지 | `tray_ack ... "status":"ok"` |
| [6] | 컨1 정지 | `conveyor_ack ... "status":"ok"` |

> 모든 응답에 `"status": "ok"` 가 보이면 통신·구동 정상.

---

## STEP 3 — (선택) 통합 FSM 시연

실제 센서가 부품을 감지하면 → 분류(더미) → 게이트 자동 분류까지 전체 흐름을 본다.
(분류기는 아직 더미라 결과는 랜덤. 카메라 영상 기반 실제 분류는 별도 작업.)

### 3-1. config.json 설정 (4곳)
```json
"vision":  { "dummy_mode": true,  ... },     // 분류는 더미 유지 (실 YOLO 미구현)
"serial":  { "port": "COM5", "baudrate": 115200, "dummy_mode": false },  // ← 실 ESP32
"robot":   { ... "dummy_mode": true },        // 로봇 없음 → 더미
"agv":     { ... "dummy_mode": true }         // AGV 없음 → 더미
```
`cameras.top.index` / `cameras.side.index` 도 STEP 1에서 확인한 값으로.

### 3-2. MQTT 브로커 실행 (택1)
```powershell
# A) Docker Desktop이 있으면
docker compose -f config/docker-compose.yml up -d
# B) 없으면 mosquitto를 설치해 서비스로 실행
```

### 3-3. 더미 서버 실행 (로봇·AGV 대역) — 터미널 2개
> ⚠️ ESP32는 실물이므로 **MockESP32.py 는 실행하지 않는다.**
```powershell
python mock/MockMyCobot.py    # 9002
python mock/MockAGV.py        # 9003
```

### 3-4. 메인 실행 — 새 터미널
```powershell
$env:PYTHONPATH="C:\VisiPick"
python -m src.core.state_machine
```
- 센서 앞을 부품이 지나가면 → 검사 로그 출력 → DUPLICATE/DEFECT면 해당 게이트가 실제로 동작.

### 3-5. (선택) API + 비상정지
```powershell
$env:PYTHONPATH="C:\VisiPick"
python -m src.api.api_server          # http://localhost:8000/docs
# /docs 에서 POST /api/emergency_stop → 컨1·컨2·컨3·게이트 일괄 정지 확인
```

> ⚠️ **알려진 한계**: 현재 코드는 `vision.dummy_mode=true`이면 실제 센서 트리거와 **별개로** 더미 타이머(약 3초 간격)도 검사를 발생시킨다 → 실 ESP32 센서와 동시에 동작해 게이트가 주기적으로도 열릴 수 있다. 순수하게 "실 센서로만" 구동하려면 `state_machine.run()`의 더미 트리거 시작 조건을 "serial도 더미일 때만"으로 바꾸면 된다(코드 1줄 수정, 별도 작업).

---

## 빠른 트러블슈팅
| 증상 | 원인 / 해결 |
|------|------------|
| `PermissionError(13) ... COM5` | Arduino Serial Monitor가 포트 점유 중 → 닫기 |
| `{"error":"UNKNOWN CMD"}` | Serial Monitor 줄바꿈이 "Newline"인지 확인 (CR 섞이면 인식 실패) |
| 응답이 `pong`이 아니라 status JSON | 펌웨어 `ENABLE_PERIODIC_STATUS`가 1 → 0으로 두고 재업로드 |
| 카메라 열기 실패 | 인덱스 바꿔 재시도 / 다른 앱이 카메라 점유 / `CAP_DSHOW` 유지 |
| 컨2가 안 돔 | 컨2는 부팅 시 자동 ON. ESP32 RST 후에도 안 돌면 A모터(26/27) 결선·전원 확인 |
| `ModuleNotFoundError: src` | `$env:PYTHONPATH="C:\VisiPick"` 설정 후 `python -m ...` 로 실행 |
| 게이트는 되는데 컨1 안 돔 | 스텝모터 드라이버 EN(13)/전원, 속도 0.0 아닌지 확인 |

---

## 한눈 요약
1. **STEP 0** 환경 1회 준비 (venv·펌웨어·포트·deps)
2. **STEP 1** `cam_test.py` → 카메라 인덱스 확인
3. **STEP 2** `hw_test.py` → 컨1·컨2·컨3·게이트 직접 구동 확인 ← **핵심 동작 테스트**
4. **STEP 3** (선택) 실 ESP32 + 더미 로봇/AGV로 전체 FSM 시연
