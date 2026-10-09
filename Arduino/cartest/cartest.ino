// 步进电机引脚定义（根据你的硬件连接）
const int pls = 3;   // 脉冲引脚
const int dir = 4;   // 方向引脚
const int eng = 5;   // 使能引脚（低电平有效）

// 串口指令缓冲区
String inputBuffer = "";
bool commandReady = false;

void setup() {
  pinMode(pls, OUTPUT);
  pinMode(dir, OUTPUT);
  pinMode(eng, OUTPUT);

  // 初始状态
  digitalWrite(pls, LOW);
  digitalWrite(dir, LOW);
  digitalWrite(eng, LOW);  // 使能电机（拉低使能引脚）

  Serial.begin(9600);
  Serial.println("READY");
}

void loop() {
  // 读取串口数据直到换行符
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      inputBuffer.trim();
      if (inputBuffer.length() > 0) {
        commandReady = true;
      }
    } else {
      inputBuffer += c;
    }
  }

  // 处理完整指令
  if (commandReady) {
    commandReady = false;
    String cmd = inputBuffer;
    inputBuffer = "";

    // 指令格式: P,steps,freq,dir
    if (cmd.startsWith("P,")) {
      // 解析参数
      int idx1 = cmd.indexOf(',', 2);
      int idx2 = cmd.lastIndexOf(',');
      if (idx1 > 0 && idx2 > idx1) {
        long steps = cmd.substring(2, idx1).toInt();
        int freq = cmd.substring(idx1 + 1, idx2).toInt();
        int direction = cmd.substring(idx2 + 1).toInt();

        // 设置方向 (0=正转, 1=反转)
        digitalWrite(dir, direction ? HIGH : LOW);
        delayMicroseconds(5);  // 方向建立时间

        // 生成脉冲
        if (freq > 0) {
          unsigned long halfPeriod = 500000UL / freq;
          if (halfPeriod < 2) halfPeriod = 2;

          for (long i = 0; i < steps; i++) {
            digitalWrite(pls, HIGH);
            delayMicroseconds(halfPeriod);
            digitalWrite(pls, LOW);
            delayMicroseconds(halfPeriod);
          }
        }

        Serial.println("OK");
      } else {
        Serial.println("ERR: format");
      }
    } else {
      Serial.println("ERR: unknown cmd");
    }
  }
}