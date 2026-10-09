// 直线模组步进电机控制 - 梯形加减速
// 引脚配置
#define DIR_PIN 9
#define PUL_PIN 10
#define ENA_PIN 11

// 方向定义
#define DIR_FORWARD HIGH
#define DIR_BACKWARD LOW

// 频率限制：最高 30000Hz
#define MAX_FREQ 30000
#define MIN_FREQ 100

// 全局变量
long currentPosition = 0;
bool isRunning = false;

void setup() {
  Serial.begin(115200);
  
  pinMode(DIR_PIN, OUTPUT);
  pinMode(PUL_PIN, OUTPUT);
  pinMode(ENA_PIN, OUTPUT);
  
  // 使能电机
  digitalWrite(ENA_PIN, LOW);
  digitalWrite(PUL_PIN, LOW);
  
  Serial.println("ARDUINO READY - DIR=9, PUL=10, ENA=11");
  sendStatus("READY");
}

void loop() {
  if (Serial.available() > 0) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    parseCommand(cmd);
  }
}

// 解析上位机命令
void parseCommand(String cmd) {
  if (cmd.startsWith("MOVE:")) {
    // 格式: MOVE:方向:总脉冲:启动频率:目标频率:加速步数
    char dir = cmd.charAt(5);
    long totalPulses = getValue(cmd, ':', 2).toInt();
    int startFreq = getValue(cmd, ':', 3).toInt();
    int targetFreq = getValue(cmd, ':', 4).toInt();
    int accelSteps = getValue(cmd, ':', 5).toInt();

    // 限制在 100~30000Hz 之间
    startFreq = constrain(startFreq, MIN_FREQ, MAX_FREQ);
    targetFreq = constrain(targetFreq, MIN_FREQ, MAX_FREQ);
    
    moveTrapezoid(dir, totalPulses, startFreq, targetFreq, accelSteps);
  }
  else if (cmd == "STOP") {
    emergencyStop();
  }
  else if (cmd == "RESET") {
    currentPosition = 0;
    sendPosition();
    sendStatus("READY");
  }
  else if (cmd == "STATUS?") {
    sendStatus(isRunning ? "MOVING" : "READY");
    sendPosition();
  }
  else if (cmd == "TEST:DIRECTION" || cmd == "TEST:DIR") {
    testDirection();
  }
}

// 梯形加减速运动（核心）
void moveTrapezoid(char dir, long total, int startFreq, int targetFreq, int accelSteps) {
  if (isRunning) return;
  isRunning = true;
  
  // 设置方向
  if (dir == 'F') {
    digitalWrite(DIR_PIN, DIR_FORWARD);
  } else {
    digitalWrite(DIR_PIN, DIR_BACKWARD);
  }
  
  sendStatus("MOVING");
  
  long decelStart = total - accelSteps;

  // 安全保护：加速步数不能超过总脉冲一半
  accelSteps = min((long)accelSteps, total / 2);
  
  for (long i = 0; i < total; i++) {
    if (!isRunning) break;
    
    int freq;
    if (i < accelSteps) {
      // 加速段
      freq = map(i, 0, accelSteps, startFreq, targetFreq);
    }
    else if (i >= decelStart) {
      // 减速段
      freq = map(i, decelStart, total, targetFreq, startFreq);
    }
    else {
      // 匀速段
      freq = targetFreq;
    }

    // 全程限制频率
    freq = constrain(freq, MIN_FREQ, MAX_FREQ);
    
    // 极短脉冲，适配高频
    digitalWrite(PUL_PIN, HIGH);
    delayMicroseconds(2);
    digitalWrite(PUL_PIN, LOW);
    
    // 计算脉冲间隔
    long delayUs = 1000000L / freq / 2;
    delayMicroseconds(delayUs);
    
    // 更新位置
    currentPosition += (dir == 'F') ? 1 : -1;
    
    // 每200脉冲上报一次位置
    if (i % 200 == 0) {
      sendPosition();
    }
  }
  
  sendPosition();
  sendStatus("COMPLETE");
  isRunning = false;
}

// 急停
void emergencyStop() {
  isRunning = false;
  sendStatus("STOPPED");
}

// 方向测试
void testDirection() {
  digitalWrite(DIR_PIN, DIR_FORWARD);
  for (int i = 0; i < 200; i++) {
    digitalWrite(PUL_PIN, HIGH);
    delayMicroseconds(10);
    digitalWrite(PUL_PIN, LOW);
    delayMicroseconds(500);
  }
  delay(500);
  digitalWrite(DIR_PIN, DIR_BACKWARD);
  for (int i = 0; i < 200; i++) {
    digitalWrite(PUL_PIN, HIGH);
    delayMicroseconds(10);
    digitalWrite(PUL_PIN, LOW);
    delayMicroseconds(500);
  }
}

// 发送状态
void sendStatus(String s) {
  Serial.println("STATUS:" + s);
}

// 发送位置
void sendPosition() {
  Serial.println("POS:" + String(currentPosition));
}

// 分割字符串取值
String getValue(String data, char separator, int index) {
  int found = 0;
  int strIndex[] = {0, -1};
  int maxIndex = data.length() - 1;
  
  for (int i = 0; i <= maxIndex && found <= index; i++) {
    if (data.charAt(i) == separator || i == maxIndex) {
      found++;
      strIndex[0] = strIndex[1] + 1;
      strIndex[1] = (i == maxIndex) ? i + 1 : i;
    }
  }
  return found > index ? data.substring(strIndex[0], strIndex[1]) : "";
}