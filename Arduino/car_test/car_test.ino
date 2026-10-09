// 旋转电机 - 支持频率设置，固定引脚 pls=3, dir=4, eng=5
#define pls  3
#define dir  4
#define eng  5

bool motorRunning = false;
unsigned int freq = 1000;          // 默认 1000 Hz
unsigned long halfPeriod = 500;    // 默认 1000Hz -> 500us
unsigned long lastStep = 0;
bool stepState = LOW;

void setup() {
  pinMode(pls, OUTPUT);
  pinMode(dir, OUTPUT);
  pinMode(eng, OUTPUT);
  digitalWrite(pls, LOW);
  digitalWrite(dir, LOW);
  digitalWrite(eng, LOW);         // 使能（低有效）
  Serial.begin(9600);
  Serial.println("READY");
}

void loop() {
  // 处理串口命令
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();

    if (cmd.startsWith("RUN,")) {
      // 格式: RUN,方向,频率  方向0=正转,1=反转
      int c1 = cmd.indexOf(',', 4);
      if (c1 > 0) {
        int dirVal = cmd.substring(4, c1).toInt();
        int freqVal = cmd.substring(c1 + 1).toInt();
        if (freqVal > 0 && freqVal <= 20000) {
          freq = freqVal;
          halfPeriod = 500000UL / freq;   // 半周期 us
          if (halfPeriod < 2) halfPeriod = 2;
          digitalWrite(dir, dirVal ? HIGH : LOW);
          motorRunning = true;
          lastStep = micros();
          Serial.println("OK");
        } else {
          Serial.println("ERR: freq range (1-20000)");
        }
      } else {
        Serial.println("ERR: format");
      }
    }
    else if (cmd == "STOP") {
      motorRunning = false;
      digitalWrite(pls, LOW);
      Serial.println("OK");
    }
    else {
      Serial.println("UNKNOWN");
    }
  }

  // 非阻塞脉冲生成
  if (motorRunning) {
    unsigned long now = micros();
    if (now - lastStep >= halfPeriod) {
      lastStep = now;
      stepState = !stepState;
      digitalWrite(pls, stepState);
    }
  }
}