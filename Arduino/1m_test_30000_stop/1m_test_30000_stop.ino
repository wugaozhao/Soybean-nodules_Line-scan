// 直线模组高性能控制 - 定时器中断脉冲 (急停零延迟版)
// 引脚：DIR=9, PUL=10, ENA=11
#define DIR_PIN 9
#define PUL_PIN 10
#define ENA_PIN 11

#define DIR_FORWARD HIGH
#define DIR_BACKWARD LOW

// 全局运动参数 (volatile 确保中断可访问)
volatile long totalSteps = 0;
volatile long stepCounter = 0;
volatile int currentFreq = 0;
volatile bool emergencyStop = false;  // 急停标志，中断直接读取

// 梯形加减速参数
int startFreq = 300;
int targetFreq = 10000;
int accelSteps = 400;
long decelStart = 0;
char dir = 'F';

// 状态
bool isRunning = false;
long currentPosition = 0;

// 定时器初始化 (Timer1, 16MHz)
void initTimer() {
  TCCR1A = 0;
  TCCR1B = 0;
  TCNT1  = 0;
  OCR1A  = 1000;  // 初始1000Hz
  TCCR1B |= (1 << WGM12);  // CTC模式
  TCCR1B |= (1 << CS11);   // 8分频
  TIMSK1 |= (1 << OCIE1A); // 使能比较中断
  sei();  // 开启全局中断
}

// 设置频率 (带安全限制)
void setFreq(int freq) {
  if (freq < 100) freq = 100;
  if (freq > 50000) freq = 50000;
  currentFreq = freq;
  OCR1A = F_CPU / (8UL * freq) - 1;
}

// 定时器中断 - 发脉冲 (最高优先级，急停直接生效)
ISR(TIMER1_COMPA_vect) {
  // 🔥 急停优先：只要急停标志置位，立刻停止发脉冲
  if (emergencyStop || !isRunning || stepCounter >= totalSteps) {
    return;
  }

  // 发一个脉冲
  digitalWrite(PUL_PIN, HIGH);
  delayMicroseconds(2);
  digitalWrite(PUL_PIN, LOW);

  stepCounter++;
  currentPosition += (dir == 'F') ? 1 : -1;
}

void setup() {
  Serial.begin(115200);
  pinMode(DIR_PIN, OUTPUT);
  pinMode(PUL_PIN, OUTPUT);
  pinMode(ENA_PIN, OUTPUT);
  
  digitalWrite(ENA_PIN, LOW);   // 使能电机
  digitalWrite(PUL_PIN, LOW);
  emergencyStop = false;        // 初始化急停标志
  initTimer();
  
  sendStatus("READY");
  Serial.println("ARDUINO READY - 急停零延迟版");
}

void loop() {
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    parseCommand(cmd);
  }
  updateTrapezoid();
}

// 解析命令 (急停命令立刻置位标志)
void parseCommand(String cmd) {
  if (cmd.startsWith("MOVE:")) {
    // 🔥 收到运动命令，自动清除急停标志
    emergencyStop = false;
    
    char d = cmd.charAt(5);
    long total = getValue(cmd, ':', 2).toInt();
    int sFreq = getValue(cmd, ':', 3).toInt();
    int tFreq = getValue(cmd, ':', 4).toInt();
    int aSteps = getValue(cmd, ':', 5).toInt();

    startFreq = constrain(sFreq, 100, 50000);
    targetFreq = constrain(tFreq, 100, 50000);
    accelSteps = aSteps;
    totalSteps = total;
    dir = d;
    decelStart = total - accelSteps;

    stepCounter = 0;
    digitalWrite(DIR_PIN, dir == 'F' ? DIR_FORWARD : DIR_BACKWARD);
    setFreq(startFreq);
    isRunning = true;
    sendStatus("MOVING");
  }
  else if (cmd == "STOP") {
    // 🔥 急停：立刻置位标志，中断立刻停止发脉冲
    emergencyStop = true;
    isRunning = false;
    sendStatus("STOPPED");
    Serial.println("紧急停止生效");
  }
  else if (cmd == "RESET") {
    currentPosition = 0;
    emergencyStop = false;
    sendPosition();
    sendStatus("READY");
  }
  else if (cmd == "STATUS?") {
    sendStatus(isRunning ? "MOVING" : (emergencyStop ? "STOPPED" : "READY"));
    sendPosition();
  }
}

// 梯形加减速 (主循环更新频率，不影响急停)
void updateTrapezoid() {
  // 🔥 急停状态下，不更新任何运动参数
  if (emergencyStop || !isRunning) {
    // 运动完成后自动复位
    if (isRunning && stepCounter >= totalSteps) {
      isRunning = false;
      sendPosition();
      sendStatus("COMPLETE");
    }
    return;
  }

  int freq;
  if (stepCounter < accelSteps) {
    freq = map(stepCounter, 0, accelSteps, startFreq, targetFreq);
  } else if (stepCounter >= decelStart) {
    freq = map(stepCounter, decelStart, totalSteps, targetFreq, startFreq);
  } else {
    freq = targetFreq;
  }

  setFreq(freq);

  // 定期上报位置
  if (stepCounter % 200 == 0) {
    sendPosition();
  }

  // 运动完成检测
  if (stepCounter >= totalSteps) {
    isRunning = false;
    sendPosition();
    sendStatus("COMPLETE");
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

// 字符串分割
String getValue(String data, char sep, int idx) {
  int f = 0, sIdx[] = {0, -1};
  int max = data.length() - 1;
  for (int i = 0; i <= max && f <= idx; i++) {
    if (data[i] == sep || i == max) {
      f++;
      sIdx[0] = sIdx[1] + 1;
      sIdx[1] = (i == max) ? i + 1 : i;
    }
  }
  return f > idx ? data.substring(sIdx[0], sIdx[1]) : "";
}