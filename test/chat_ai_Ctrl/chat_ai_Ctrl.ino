/* ========= Arduino UNO + CNC Shield =========
   X + A : 平移同步
   Y     : 小车前 / 后
   Z     : 扫描电机
   微动开关：前进 / 回退到位
=========================================== */

#define X_STEP 2
#define Y_STEP 3
#define Z_STEP 4
#define X_DIR  5
#define Y_DIR  6
#define Z_DIR  7
#define EN_PIN 8
#define A_STEP 12
#define A_DIR  13

// -------- 微动开关 --------
#define Y_FWD_LIMIT 9     // 前进到位
#define Y_BWD_LIMIT 10    // 回退到位

// -------- 参数 --------
int speed_car   = 800;
int speed_scan  = 1000;
int speed_slide = 600;
int accel_step  = 10;

char cmd = 0;

// -------- 去抖参数 --------
unsigned long debounceDelay = 20;
bool fwd_triggered = false;
bool bwd_triggered = false;
unsigned long fwd_time = 0;
unsigned long bwd_time = 0;

// -------- 初始化 --------
void setup() {
  Serial.begin(9600);

  pinMode(X_STEP, OUTPUT);
  pinMode(Y_STEP, OUTPUT);
  pinMode(Z_STEP, OUTPUT);
  pinMode(A_STEP, OUTPUT);

  pinMode(X_DIR, OUTPUT);
  pinMode(Y_DIR, OUTPUT);
  pinMode(Z_DIR, OUTPUT);
  pinMode(A_DIR, OUTPUT);

  pinMode(EN_PIN, OUTPUT);

  pinMode(Y_FWD_LIMIT, INPUT_PULLUP);
  pinMode(Y_BWD_LIMIT, INPUT_PULLUP);

  digitalWrite(EN_PIN, HIGH);   // 默认失能
}

// -------- 通用加速脉冲 --------
void accelPulse(int stepPin, int targetFreq) {
  for (int f = 0; f <= targetFreq; f += accel_step) {
    tone(stepPin, f);
    delay(2);
  }
}

void accelPulseDual(int step1, int step2, int targetFreq) {
  for (int f = 0; f <= targetFreq; f += accel_step) {
    tone(step1, f);
    tone(step2, f);
    delay(2);
  }
}

// -------- 运动函数 --------
void carForward() {
  digitalWrite(EN_PIN, LOW);
  digitalWrite(Y_DIR, HIGH);
  fwd_triggered = false;
  accelPulse(Y_STEP, speed_car);
}

void carBackward() {
  digitalWrite(EN_PIN, LOW);
  digitalWrite(Y_DIR, LOW);
  bwd_triggered = false;
  accelPulse(Y_STEP, speed_car);
}

void scanMove() {
  digitalWrite(EN_PIN, LOW);
  digitalWrite(Z_DIR, HIGH);
  accelPulse(Z_STEP, speed_scan);
}

void slideMove() {
  digitalWrite(EN_PIN, LOW);
  digitalWrite(X_DIR, HIGH);
  digitalWrite(A_DIR, HIGH);
  accelPulseDual(X_STEP, A_STEP, speed_slide);
}

void stopAll() {
  noTone(X_STEP);
  noTone(Y_STEP);
  noTone(Z_STEP);
  noTone(A_STEP);
  digitalWrite(EN_PIN, HIGH);
}

// -------- 微动开关检测（去抖） --------
void checkLimitSwitch() {
  unsigned long now = millis();

  // 前进到位
  if (!fwd_triggered && digitalRead(Y_FWD_LIMIT) == LOW) {
    if (fwd_time == 0) fwd_time = now;
    if (now - fwd_time > debounceDelay) {
      fwd_triggered = true;
      stopAll();
      Serial.println("Y_FWD_OK");
    }
  } else {
    fwd_time = 0;
  }

  // 回退到位
  if (!bwd_triggered && digitalRead(Y_BWD_LIMIT) == LOW) {
    if (bwd_time == 0) bwd_time = now;
    if (now - bwd_time > debounceDelay) {
      bwd_triggered = true;
      stopAll();
      Serial.println("Y_BWD_OK");
    }
  } else {
    bwd_time = 0;
  }
}

// -------- 主循环 --------
void loop() {
  checkLimitSwitch();

  if (Serial.available()) {
    cmd = Serial.read();

    switch (cmd) {
      case 'F':
        carForward();
        Serial.println("OK");
        break;

      case 'B':
        carBackward();
        Serial.println("OK");
        break;

      case 'Z':
        scanMove();
        Serial.println("OK");
        break;

      case 'P':
        slideMove();
        Serial.println("OK");
        break;

      case 'S':
        stopAll();
        Serial.println("OK");
        break;

      case 'E':
        stopAll();
        Serial.println("END");
        break;

      default:
        Serial.println("ERR");
        break;
    }
  }
}
