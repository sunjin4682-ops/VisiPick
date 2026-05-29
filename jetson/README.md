# VisiPick — Jetson 이식 파일 모음 (overlay)

이 폴더는 **Windows 원본 소스를 건드리지 않고** Jetson에서 돌리기 위해 **달라지는 파일만** 저장소 구조 그대로 담아둔 것이다.
저장소 루트의 원본(`config/`, `src/`, `scripts/`)은 그대로 두고, Jetson에서 클론한 뒤 아래 파일들을 **원본 위에 덮어쓰기(overlay)** 하면 된다.

## 이 폴더에 든 것 (← 어느 원본을 대체하나)

| jetson/ 안의 파일 | 덮어쓸 원본 | 무엇이 다른가 |
|-------------------|-------------|---------------|
| `config/config.json` | `config/config.json` | `database.path` → `/home/jetson/...`, `serial.port` → `/dev/ttyUSB0`, `vision.device: "cuda"` 추가 |
| `src/vision/camera_top.py` | `src/vision/camera_top.py` | Linux는 `cv2.CAP_V4L2` 백엔드 명시 (그 외 OS는 `CAP_ANY`) |
| `src/vision/camera_side.py` | `src/vision/camera_side.py` | 동일 (V4L2 백엔드) |
| `src/vision/classifier.py` | `src/vision/classifier.py` | `vision.device` 읽어 CUDA 추론 인터페이스 준비 (더미 로직 불변) |
| `src/vision/defect_detector.py` | `src/vision/defect_detector.py` | 동일 (device 인터페이스) |
| `scripts/backup.sh` | `scripts/backup.ps1` 대체 | PowerShell → bash (WAL-safe `sqlite3 .backup`) |
| `requirements-jetson.txt` | `requirements.txt` 대체 | opencv 제거 + torch/ultralytics Jetson 설치법 주석 |

> ⚠️ 이 파일들은 원본의 **복사본**이라, 나중에 원본 `src/vision/*.py`가 바뀌면 여기도 손으로 맞춰줘야 한다(드리프트 주의).

## overlay 적용 (Jetson 클론 직후 1회)

```bash
cd /home/jetson/VisiPick
cp jetson/config/config.json   config/config.json
cp jetson/src/vision/*.py      src/vision/
cp jetson/scripts/backup.sh    scripts/
chmod +x scripts/backup.sh
# requirements는 복사 없이 jetson/ 경로에서 바로 설치 (아래 2번)
```

---

## Jetson 셋업 절차 (재설치 시 이대로)

> 보드: Jetson Orin Nano Super / JetPack 6.2.1 (Ubuntu 22.04, ARM64, CUDA)
> 계정: `jetson` / 경로: `/home/jetson/VisiPick`

### 1. 클론 & 가상환경
```bash
cd /home/jetson
git clone https://github.com/sunjin4682-ops/VisiPick.git
cd VisiPick
python3 -m venv .venv --system-site-packages   # JetPack 내장 cv2를 venv에서 쓰려면 필수
source .venv/bin/activate
python -V                                        # JetPack 기본 Python 3.10 확인
```

### 2. 의존성 설치
```bash
# (1) 순수 Python 패키지
pip install -r jetson/requirements-jetson.txt

# (2) OpenCV — 설치 금지! JetPack 내장본 확인만
python -c "import cv2; print('cv2', cv2.__version__)"

# (3) PyTorch/torchvision — NVIDIA Jetson 전용 휠(JetPack 6.x/cu12x)
#     https://developer.nvidia.com/embedded/downloads
python -c "import torch; print(torch.__version__, torch.cuda.is_available())"   # True 기대

# (4) ultralytics — torch 재설치 방지
pip install --no-deps ultralytics
```

### 3. overlay 적용
위 "overlay 적용" 블록 실행.

### 4. 시리얼 포트 (ESP32)
```bash
ls /dev/ttyUSB* /dev/ttyACM*          # 실제 포트 확인 (보통 /dev/ttyUSB0)
sudo usermod -aG dialout jetson       # 권한 부여 — 적용하려면 재로그인/재부팅 필요
# ttyUSB0이 아니면 config/config.json 의 serial.port 수정
```

### 5. 카메라 인덱스 확인
```bash
sudo apt install v4l-utils
v4l2-ctl --list-devices               # 상부/측면 카메라 인덱스 확인
# 결과에 맞춰 config.json 의 cameras.top.index / cameras.side.index 조정
```

### 6. MQTT 브로커 (둘 중 택일)
```bash
# A) Docker (eclipse-mosquitto:2.0은 ARM64 멀티아치)
docker compose -f config/docker-compose.yml up -d

# B) 네이티브
sudo apt install mosquitto mosquitto-clients
sudo systemctl enable --now mosquitto
```

### 7. DB 초기화
```bash
mkdir -p /home/jetson/VisiPick/data
PYTHONPATH=/home/jetson/VisiPick python -m src.utils.db_init
```

### 8. Mock 환경 2사이클 검증 (dummy_mode=true 유지)
```bash
# 터미널 3개 — Mock 서버
python mock/MockESP32.py      # 9001
python mock/MockMyCobot.py    # 9002
python mock/MockAGV.py        # 9003

# 메인
PYTHONPATH=/home/jetson/VisiPick python -m src.core.state_machine
# → IDLE→RUNNING→TRAY_TRANSFER→COMPLETE 사이클 PASS 확인

# API 서버
PYTHONPATH=/home/jetson/VisiPick python -m src.api.api_server   # http://<jetson-ip>:8000/docs
```

### 9. 백업
```bash
bash scripts/backup.sh        # → /home/jetson/VisiPick/backup/visipick-YYYY-MM-DD.db
```

### 10. (선택) 부팅 자동 시작 — systemd
`/etc/systemd/system/visipick.service`:
```ini
[Unit]
Description=VisiPick State Machine
After=network-online.target docker.service
Wants=network-online.target

[Service]
User=jetson
WorkingDirectory=/home/jetson/VisiPick
Environment=PYTHONPATH=/home/jetson/VisiPick
ExecStart=/home/jetson/VisiPick/.venv/bin/python -m src.core.state_machine
Restart=on-failure

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now visipick
```

## 유지/금지 (변경하지 않음)
- 모듈 간 통신은 MQTT 경유 / myCobot은 RPi4 경유 TCP (Jetson 직결 금지)
- MQTT 토픽·페이로드 / `decision.py`·`recipe_mgr.py`·`tray_mgr.py` 로직 불변
- 실제 YOLO 추론 구현은 범위 밖 — `dummy_mode` 분기 유지
