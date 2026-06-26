// ─────────────────────────────────────────────────────────────────────────────
//  VisiPick ESP32 펌웨어 (Hardware-Connect)
//
//  통신 상대: Python 마스터(src/devices/serial_ctrl.py) — USB Serial 115200, JSON+\n
//
//  [PC → ESP32]  (serial_ctrl.py가 보내는 명령)
//    {"type":"gate_cmd","gate":"1","action":"push"}      → Gate1/2 즉시 푸셔
//    {"type":"conveyor_cmd","action":"set_speed","speed":1.5}  → 컨1 속도(cm/s), 0.0=정지
//    {"type":"tray_cmd","action":"advance"}              → 컨3(B모터) 2초 — 다음 빈 트레이 공급
//    {"type":"ping"}                                     → pong
//  각 명령에 대해 정확히 1줄 JSON 응답을 보냄 (반드시 "status":"ok" 포함).
//
//  [ESP32 → PC]  (비동기)
//    {"type":"sensor_triggered","timestamp":...}         → 부품 감지 → PC가 촬영/검사 트리거
//
//  ※ 수동 시리얼 모니터 테스트용 텍스트 프로토콜(GATE1:PUSH 등)도 폴백으로 유지.
//  ※ 주기적 status 송신은 기본 OFF (ENABLE_PERIODIC_STATUS) — 켜면 PC의 1명령-1응답
//     readline 모델을 깨므로, 필요 시 "STATUS" 명령으로 1회성 조회 사용.
//
//  필요 라이브러리: ESP32Servo, AccelStepper, ArduinoJson(v7)
// ─────────────────────────────────────────────────────────────────────────────
#include <Arduino.h>
#include <ESP32Servo.h>
#include <AccelStepper.h>
#include <ArduinoJson.h>
#include <esp_task_wdt.h>

// ── 핀 config ─────────────────────────────
#define GATE1_PIN   15
#define GATE2_PIN   2
#define CONV_ENBL   13
#define CONV_DIR    12
#define CONV_PUL    14
#define END_SENSOR  34
#define ESTOP_PIN   25

// ── L9110S 컨베이어 config ────────────────
#define CONV2_A  26  // A모터 (중복 부품 반환 컨베이어 — 상시 ON)
#define CONV2_B  27
#define CONV3_A  32  // B모터 (다음 빈 트레이 공급 컨베이어 — 2초 동작)
#define CONV3_B  33

// ── 서보 객체 ─────────────────────────────
Servo gate1Servo;
Servo gate2Servo;

// ── 서보 config ───────────────────────────
const int SERVO_IDLE = 0;
const int SERVO_PUSH = 90;
const int HOLD_TIME  = 300;

// ── 서보 상태 ─────────────────────────────
bool gate1Busy = false;
bool gate2Busy = false;
unsigned long gate1Timer = 0;
unsigned long gate2Timer = 0;
int gate1Step = 0;
int gate2Step = 0;

// ── 스텝모터 config ───────────────────────
#define MOTOR_INTERFACE 1
AccelStepper stepper(MOTOR_INTERFACE, CONV_PUL, CONV_DIR);
const int MAX_SPEED    = 6000;
const int ACCELERATION = 1000;
bool convRunning = false;
int   currentSpeed   = 0;     // 텍스트 프로토콜용 (10~100)
float currentSpeedCm = 0.0;   // JSON 프로토콜용 (cm/s)

// ── 딜레이 타이밍 config ──────────────────
float CONV_SPEED_CM  = 1.72;
float GATE1_DISTANCE = 30.2;
float GATE2_DISTANCE = 39.8;

// ── 실측 캘리브레이션 config ──────────────
const float MM_PER_STEP = 0.002867;

// ── L9110S 컨베이어 상태 ──────────────────
bool conv3Running = false;
unsigned long conv3Timer = 0;
#define CONV3_RUN_TIME 2300          // 기본 2초 (tray_cmd 에 duration_ms 없을 때 폴백)
unsigned long conv3RunTime = CONV3_RUN_TIME;  // 실제 사용값 — PC가 duration_ms 로 덮어씀

// ── 딜레이 예약 구조체 ────────────────────
struct GateTimer {
  bool active = false;
  unsigned long triggerTime = 0;
  int gateNum = 0;
};
GateTimer gateQueue[4];

// ── 에러 처리 config ──────────────────────
#define WDT_TIMEOUT     5
#define SERIAL_TIMEOUT  5000
unsigned long lastSerialTime = 0;
bool serialConnected = false;

// ── 상태 전송 config ──────────────────────
// 0 = 주기 송신 끔(권장 — PC의 1명령-1응답 readline 모델 보호)
// 1 = 디버그용 주기 송신(수동 모니터 전용)
#define ENABLE_PERIODIC_STATUS 0
#define STATUS_INTERVAL 200
unsigned long lastStatusTime = 0;

// ── 물리 비상정지 버튼 ───────────────────
volatile bool estopPressed = false;
bool estopHeld = false;    // 디바운스된 현재 눌림 상태 (해제 감지용)
void IRAM_ATTR onEstopPressed() {
  estopPressed = true;   // 인터럽트 핸들러 — 플래그만 세움, 처리는 loop()에서
}

// ── 끝단 센서 상태 ────────────────────────
bool endSensorState = false;
bool lastEndSensorState = false;
unsigned long lastDebounceTime = 0;
#define DEBOUNCE_DELAY 50

// ── 시리얼 버퍼 ───────────────────────────
String inputBuffer = "";

// ── 함수 선언 ─────────────────────────────
void pushGate(int gateNum);
void updateGates();
void updateConveyor();
void updateGateQueue();
void sendStatus(bool force);
void updateEndSensor();
float getConveyorSpeedMmPerSec();
void scheduleGate(int gateNum, unsigned long delayMs);
void parseCommand(String cmd);
void parseJsonCommand(const String& cmd);
void setConvSpeed(int speed);
void setConvSpeedCm(float cmPerSec);
void stopConveyor();
void emergencyStop();
void conv2Start();
void conv2Stop();
void startConv3(unsigned long runMs = CONV3_RUN_TIME);
void updateConv3();

// ── 비상 정지 ─────────────────────────────
void emergencyStop() {
  stopConveyor();
  conv2Stop();
  digitalWrite(CONV3_A, LOW); 
  digitalWrite(CONV3_B, LOW);
  conv3Running = false;
  gate1Servo.write(SERVO_IDLE);
  gate2Servo.write(SERVO_IDLE);
  gate1Busy = false;
  gate2Busy = false;
  gate1Step = 0;
  gate2Step = 0;
  for (int i = 0; i < 4; i++) gateQueue[i].active = false;
}

// ── 끝단 센서 업데이트 ────────────────────
//  부품 감지(active) 하강엣지에서 sensor_triggered 1회 송신 → PC가 촬영/검사.
//  ⚠️ GPIO34~39는 입력 전용이라 내부 풀업/풀다운이 없다. 외부 풀업 저항(10kΩ→3V3) 필수.
//     (active-low 센서 가정: !digitalRead). 센서가 active-high면 부호 반전 제거.
void updateEndSensor() {
  bool reading = !digitalRead(END_SENSOR);
  if (reading != lastEndSensorState) {
    lastDebounceTime = millis();
  }
  if (millis() - lastDebounceTime >= DEBOUNCE_DELAY) {
    if (reading != endSensorState) {
      endSensorState = reading;
      if (endSensorState) {  // 부품 감지 시작 → 트리거
        Serial.println("{\"type\":\"sensor_triggered\",\"timestamp\":" + String(millis()) + "}");
      }
    }
  }
  lastEndSensorState = reading;
}

// ── 실제 속도 계산 (mm/s) ─────────────────
float getConveyorSpeedMmPerSec() {
  return abs(stepper.speed()) * MM_PER_STEP;
}

// ── A모터 컨베이어 (중복 부품 반환, 상시 ON) — 무음 헬퍼 ──
void conv2Start() {
  digitalWrite(CONV2_A, HIGH);
  digitalWrite(CONV2_B, LOW);
}

void conv2Stop() {
  digitalWrite(CONV2_A, LOW);
  digitalWrite(CONV2_B, LOW);
}

// ── B모터 컨베이어 (다음 빈 트레이 공급, 2초) — 무음 헬퍼 ─
void startConv3(unsigned long runMs) {
  conv3RunTime = (runMs > 0) ? runMs : CONV3_RUN_TIME;   // 0/미지정이면 기본값
  digitalWrite(CONV3_A, HIGH);
  digitalWrite(CONV3_B, LOW);
  conv3Running = true;
  conv3Timer = millis();
}

void updateConv3() {
  if (conv3Running && millis() - conv3Timer >= conv3RunTime) {
    digitalWrite(CONV3_A, LOW);
    digitalWrite(CONV3_B, LOW);
    conv3Running = false;
  }
}

// ── 푸셔 실행 — 무음 헬퍼 ─────────────────
void pushGate(int gateNum) {
  if (gateNum == 1 && !gate1Busy) {
    gate1Busy = true;
    gate1Step = 1;
    gate1Servo.write(SERVO_PUSH);
    gate1Timer = millis();
  }
  else if (gateNum == 2 && !gate2Busy) {
    gate2Busy = true;
    gate2Step = 1;
    gate2Servo.write(SERVO_PUSH);
    gate2Timer = millis();
  }
}

// ── 푸셔 업데이트 (논블로킹 복귀) ─────────
void updateGates() {
  if (gate1Busy) {
    if (gate1Step == 1 && millis() - gate1Timer >= HOLD_TIME) {
      gate1Servo.write(SERVO_IDLE);
      gate1Timer = millis();
      gate1Step = 2;
    }
    else if (gate1Step == 2 && millis() - gate1Timer >= 200) {
      gate1Busy = false;
      gate1Step = 0;
    }
  }
  if (gate2Busy) {
    if (gate2Step == 1 && millis() - gate2Timer >= HOLD_TIME) {
      gate2Servo.write(SERVO_IDLE);
      gate2Timer = millis();
      gate2Step = 2;
    }
    else if (gate2Step == 2 && millis() - gate2Timer >= 200) {
      gate2Busy = false;
      gate2Step = 0;
    }
  }
}

// ── 딜레이 예약 등록 (텍스트 프로토콜용) ──
void scheduleGate(int gateNum, unsigned long delayMs) {
  lastSerialTime = millis();
  for (int i = 0; i < 4; i++) {
    if (!gateQueue[i].active) {
      gateQueue[i].active = true;
      gateQueue[i].gateNum = gateNum;
      gateQueue[i].triggerTime = millis() + delayMs;
      Serial.println("{\"scheduled\": \"GATE" + String(gateNum) + "\", \"delay\": " + String(delayMs) + "}");
      return;
    }
  }
  Serial.println("{\"error\": \"QUEUE FULL\"}");
}

// ── 딜레이 큐 업데이트 ────────────────────
void updateGateQueue() {
  for (int i = 0; i < 4; i++) {
    if (gateQueue[i].active && millis() >= gateQueue[i].triggerTime) {
      gateQueue[i].active = false;
      pushGate(gateQueue[i].gateNum);
    }
  }
}

// ── 스텝모터 속도 설정 (텍스트: 10~100) ───
void setConvSpeed(int speed) {
  currentSpeed = speed;
  int actualSpeed = map(speed, 10, 100, 500, 6000);
  stepper.setMaxSpeed(actualSpeed);
  stepper.setAcceleration(ACCELERATION);
  stepper.setSpeed(actualSpeed);
  convRunning = true;
}

// ── 스텝모터 속도 설정 (JSON: cm/s) ───────
//  cm/s → mm/s → steps/s (캘리브레이션 MM_PER_STEP 사용). 0 이하면 정지.
void setConvSpeedCm(float cmPerSec) {
  if (cmPerSec <= 0.0) {
    stopConveyor();
    return;
  }
  float stepsPerSec = (cmPerSec * 10.0) / MM_PER_STEP;
  if (stepsPerSec > MAX_SPEED) stepsPerSec = MAX_SPEED;
  currentSpeedCm = cmPerSec;
  currentSpeed   = 0;
  stepper.setMaxSpeed(stepsPerSec);
  stepper.setAcceleration(ACCELERATION);
  stepper.setSpeed(stepsPerSec);
  convRunning = true;
}

// ── 스텝모터 정지 ─────────────────────────
void stopConveyor() {
  currentSpeed   = 0;
  currentSpeedCm = 0.0;
  stepper.setSpeed(0);
  //stepper.stop();
  convRunning = false;
}

// ── 스텝모터 업데이트 ─────────────────────
void updateConveyor() {
  if (convRunning) {
    stepper.runSpeed();
  }
}

// ── 상태 JSON 전송 (force=true면 즉시 1회) ─
void sendStatus(bool force) {
  if (!force && millis() - lastStatusTime < STATUS_INTERVAL) return;
  lastStatusTime = millis();

  String gate1State  = gate1Busy ? "pushing" : "idle";
  String gate2State  = gate2Busy ? "pushing" : "idle";
  String convState   = convRunning ? "running" : "stopped";
  String conv3State  = conv3Running ? "running" : "stopped";
  String sensorState = endSensorState ? "true" : "false";

  int totalHeap = ESP.getHeapSize();
  int freeHeap  = ESP.getFreeHeap();
  int usedHeap  = totalHeap - freeHeap;

  String json = "{";
  json += "\"type\": \"status\", ";
  json += "\"gate1\": \"" + gate1State + "\", ";
  json += "\"gate2\": \"" + gate2State + "\", ";
  json += "\"conv\": \"" + convState + "\", ";
  json += "\"conv_speed\": " + String(currentSpeed) + ", ";
  json += "\"conv_speed_cm\": " + String(currentSpeedCm, 2) + ", ";
  json += "\"conv_speed_mms\": " + String(getConveyorSpeedMmPerSec(), 1) + ", ";
  json += "\"conv3\": \"" + conv3State + "\", ";
  json += "\"end_sensor\": " + sensorState + ", ";
  json += "\"heap_total\": " + String(totalHeap) + ", ";
  json += "\"heap_used\": " + String(usedHeap) + ", ";
  json += "\"heap_free\": " + String(freeHeap);
  json += "}";

  Serial.println(json);
}

// ── JSON 명령 파서 (PC ↔ serial_ctrl.py) ──
//  명령마다 정확히 1줄 응답을 보냄. 응답에는 반드시 "status":"ok" 포함.
void parseJsonCommand(const String& cmd) {
  JsonDocument doc;
  DeserializationError err = deserializeJson(doc, cmd);
  if (err) {
    Serial.println("{\"type\":\"error\",\"status\":\"error\",\"message\":\"BAD JSON\"}");
    return;
  }

  const char* type = doc["type"] | "";

  if (strcmp(type, "gate_cmd") == 0) {
    int gateNum = doc["gate"].as<int>();     // "1"(문자열)·1(숫자) 모두 변환
    pushGate(gateNum);                       // PC가 타이밍 계산 → 즉시 푸셔
    JsonDocument res;
    res["type"]      = "gate_ack";
    res["gate"]      = String(gateNum);
    res["action"]    = (const char*)(doc["action"] | "push");
    res["status"]    = "ok";
    res["timestamp"] = millis();
    serializeJson(res, Serial);
    Serial.println();
  }
  else if (strcmp(type, "conveyor_cmd") == 0) {
    float speed = doc["speed"] | 0.0;        // cm/s (0.0 = 정지)
    setConvSpeedCm(speed);
    JsonDocument res;
    res["type"]      = "conveyor_ack";
    res["action"]    = (const char*)(doc["action"] | "set_speed");
    res["speed"]     = speed;
    res["status"]    = "ok";
    res["timestamp"] = millis();
    serializeJson(res, Serial);
    Serial.println();
  }
  else if (strcmp(type, "tray_cmd") == 0) {
    unsigned long runMs = doc["duration_ms"] | CONV3_RUN_TIME;  // PC가 보낸 값 우선, 없으면 기본 2초
    startConv3(runMs);                       // 컨3 — 다음 빈 트레이 공급
    JsonDocument res;
    res["type"]      = "tray_ack";
    res["action"]    = (const char*)(doc["action"] | "advance");
    res["status"]    = "ok";
    res["timestamp"] = millis();
    serializeJson(res, Serial);
    Serial.println();
  }
  else if (strcmp(type, "emergency_stop") == 0) {
    emergencyStop();
    Serial.println("{\"type\":\"estop_ack\",\"status\":\"ok\"}");
  }
  else if (strcmp(type, "ping") == 0) {
    Serial.println("{\"type\":\"pong\",\"status\":\"ok\"}");
  }
  else {
    Serial.println("{\"type\":\"error\",\"status\":\"error\",\"message\":\"UNKNOWN TYPE\"}");
  }
}

// ── 시리얼 파서 (JSON 우선, 텍스트 폴백) ──
void parseCommand(String cmd) {
  cmd.trim();
  if (cmd.length() == 0) return;
  lastSerialTime = millis();
  serialConnected = true;

  // JSON 명령 (PC/serial_ctrl)
  if (cmd[0] == '{') {
    parseJsonCommand(cmd);
    return;
  }

  // ── 이하 수동 시리얼 모니터 테스트용 텍스트 프로토콜 (폴백) ──
  if (cmd == "GATE1:PUSH") {
    if (!gate1Busy) {
      Serial.println("{\"ack\": \"GATE1_PUSH\"}");
      pushGate(1);
    } else {
      Serial.println("{\"error\": \"GATE1 BUSY\"}");
    }
  }
  else if (cmd == "GATE2:PUSH") {
    if (!gate2Busy) {
      Serial.println("{\"ack\": \"GATE2_PUSH\"}");
      pushGate(2);
    } else {
      Serial.println("{\"error\": \"GATE2 BUSY\"}");
    }
  }
  else if (cmd.startsWith("CONV:SPEED:")) {
    int speed = cmd.substring(11).toInt();
    if (speed >= 10 && speed <= 100) {
      setConvSpeed(speed);
      Serial.println("{\"ack\": \"CONV_SPEED_" + String(speed) + "\"}");
    } else {
      Serial.println("{\"error\": \"INVALID SPEED\"}");
    }
  }
  else if (cmd == "CONV:START") {
    setConvSpeed(100);
    Serial.println("{\"ack\": \"CONV_START\"}");
  }
  else if (cmd == "CONV:STOP") {
    stopConveyor();
    Serial.println("{\"ack\": \"CONV_STOP\"}");
  }
  else if (cmd.startsWith("GATE1:DELAY:")) {
    unsigned long delayMs = cmd.substring(12).toInt();
    scheduleGate(1, delayMs);
  }
  else if (cmd.startsWith("GATE2:DELAY:")) {
    unsigned long delayMs = cmd.substring(12).toInt();
    scheduleGate(2, delayMs);
  }
  else if (cmd == "GATE1:AUTO") {
    unsigned long delay1 = (GATE1_DISTANCE / CONV_SPEED_CM) * 1000;
    scheduleGate(1, delay1);
  }
  else if (cmd == "GATE2:AUTO") {
    unsigned long delay2 = (GATE2_DISTANCE / CONV_SPEED_CM) * 1000;
    scheduleGate(2, delay2);
  }
  else if (cmd == "CONV2:START") {
    conv2Start();
    Serial.println("{\"ack\": \"CONV2_START\"}");
  }
  else if (cmd == "CONV2:STOP") {
    conv2Stop();
    Serial.println("{\"ack\": \"CONV2_STOP\"}");
  }
  else if (cmd == "CONV3:RUN") {
    startConv3();
    Serial.println("{\"ack\": \"CONV3_RUN\"}");
  }
  else if (cmd == "STATUS") {
    sendStatus(true);
  }
  else if (cmd == "PING") {
    Serial.println("{\"ack\": \"PONG\"}");
  }
  else {
    Serial.println("{\"error\": \"UNKNOWN CMD\"}");
  }
}

// ── setup ─────────────────────────────────
void setup() {
  Serial.begin(115200);

  // Watchdog 초기화
  esp_task_wdt_config_t wdt_config = {
    .timeout_ms = WDT_TIMEOUT * 1000,
    .idle_core_mask = 0,
    .trigger_panic = true
  };
  esp_task_wdt_init(&wdt_config);
  esp_task_wdt_add(NULL);

  // 서보 초기화
  gate1Servo.attach(GATE1_PIN);
  gate2Servo.attach(GATE2_PIN);
  gate1Servo.write(SERVO_IDLE);
  gate2Servo.write(SERVO_IDLE);

  // 스텝모터 초기화
  stepper.setMaxSpeed(MAX_SPEED);
  stepper.setAcceleration(ACCELERATION);
  pinMode(CONV_ENBL, OUTPUT);
  digitalWrite(CONV_ENBL, LOW);

  // 끝단 센서 초기화 — GPIO34는 내부 풀업 불가(입력전용). 외부 풀업 저항 필요.
  pinMode(END_SENSOR, INPUT);

  // 물리 비상정지 버튼 — GPIO25, INPUT_PULLUP (버튼 GND연결, 눌리면 LOW)
  pinMode(ESTOP_PIN, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(ESTOP_PIN), onEstopPressed, FALLING);

  // L9110S 초기화
  pinMode(CONV2_A, OUTPUT);
  pinMode(CONV2_B, OUTPUT);
  pinMode(CONV3_A, OUTPUT);
  pinMode(CONV3_B, OUTPUT);
  digitalWrite(CONV3_A, LOW);
  digitalWrite(CONV3_B, LOW);

  // A모터 전원 들어오자마자 시작
  conv2Start();

  // 딜레이 큐 초기화
  for (int i = 0; i < 4; i++) gateQueue[i].active = false;

  lastSerialTime = millis();
  lastStatusTime = millis();

  Serial.println("{\"type\": \"status\", \"status\": \"ok\", \"message\": \"ESP32 READY\", "
    "\"heap_total\": " + String(ESP.getHeapSize()) + ", "
    "\"heap_free\": " + String(ESP.getFreeHeap()) + "}");
}

// ── loop ──────────────────────────────────
void loop() {
  esp_task_wdt_reset();

  // 물리 비상정지 버튼 — 눌림(FALLING 인터럽트) + 해제(폴링) 양쪽 신호 전송
  // 디바운스: 모터 EMI 스파이크가 FALLING 인터럽트를 오발화시킴 → 핀이 실제로
  // LOW(눌림)를 ~20ms 유지하는지 확인해 노이즈를 걸러낸다. 스파이크는 즉시 HIGH 복귀.
  if (estopPressed) {
    estopPressed = false;
    bool reallyPressed = true;
    for (int i = 0; i < 4; i++) {
      delay(5);
      if (digitalRead(ESTOP_PIN) == HIGH) { reallyPressed = false; break; }  // 노이즈 — 무시
    }
    if (reallyPressed && !estopHeld) {     // 새 눌림(중복 방지)
      estopHeld = true;
      emergencyStop();
      Serial.println("{\"type\":\"emergency_stop\",\"source\":\"button\",\"status\":\"ok\"}");
    }
  }
  // 버튼 해제 감지 — 눌림 상태에서 핀이 ~20ms 동안 HIGH(떨어짐) 유지되면 해제 통보.
  // (모터 재가동은 Python/WPF '컨베이어 시작'이 담당 — 해제만으로 자동 재시작 안 함)
  if (estopHeld && digitalRead(ESTOP_PIN) == HIGH) {
    bool reallyReleased = true;
    for (int i = 0; i < 4; i++) {
      delay(5);
      if (digitalRead(ESTOP_PIN) == LOW) { reallyReleased = false; break; }  // 노이즈 — 무시
    }
    if (reallyReleased) {
      estopHeld = false;
      Serial.println("{\"type\":\"emergency_clear\",\"source\":\"button\",\"status\":\"ok\"}");
    }
  }

  updateGates();
  updateConveyor();
  updateGateQueue();
  updateEndSensor();
  updateConv3();
#if ENABLE_PERIODIC_STATUS
  sendStatus(false);   // ⚠️ 켜면 PC의 1명령-1응답 readline을 깨뜨림
#endif

  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      parseCommand(inputBuffer);
      inputBuffer = "";
    } else if (c != '\r') {
      inputBuffer += c;
    }
  }
}
