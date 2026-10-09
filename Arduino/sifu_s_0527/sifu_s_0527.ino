// 电机控制引脚定义
const int PUL_PIN = 9;   // 脉冲输出引脚
const int DIR_PIN = 10;  // 方向控制引脚

// 电机参数
volatile long targetPulses = 0;     // 目标脉冲数
volatile long currentPulses = 0;    // 当前已输出脉冲数
volatile int targetFreq = 1000;     // 目标运行频率(Hz)
volatile int accelTime = 500;       // 加速时间(ms)
volatile int decelTime = 500;       // 减速时间(ms)
volatile bool direction = true;     // 运行方向 true=正转 false=反转
volatile bool isRunning = false;    // 电机运行状态

// 加减速计算变量
volatile long accelPulses = 0;      // 加速阶段脉冲数
volatile long decelPulses = 0;      // 减速阶段脉冲数
volatile long constPulses = 0;      // 匀速阶段脉冲数
volatile float currentFreq = 0;     // 当前频率
volatile unsigned long pulseInterval = 1000; // 当前脉冲间隔(微秒)
unsigned long lastPulseTime = 0;    // 上一次脉冲输出时间

void setup() {
  pinMode(PUL_PIN, OUTPUT);
  pinMode(DIR_PIN, OUTPUT);
  digitalWrite(PUL_PIN, LOW);
  digitalWrite(DIR_PIN, HIGH); // 默认正转
  
  Serial.begin(9600);
  Serial.println("Arduino电机控制器(加减速版)已就绪");
  Serial.println("指令格式:");
  Serial.println("F<频率> - 设置目标频率(Hz)");
  Serial.println("D<0/1> - 设置方向(0=反转,1=正转)");
  Serial.println("A<时间> - 设置加速时间(ms)");
  Serial.println("B<时间> - 设置减速时间(ms)");
  Serial.println("P<脉冲数> - 设置目标脉冲数并启动");
  Serial.println("S - 立即停止电机");
  Serial.println("R - 查询运行状态");
}

// 计算加减速参数
void calculateAccelDecel() {
  if (targetPulses == 0 || targetFreq == 0) return;
  
  // 计算加速和减速阶段需要的脉冲数
  accelPulses = (long)(targetFreq * accelTime / 2000.0);
  decelPulses = (long)(targetFreq * decelTime / 2000.0);
  
  // 如果总脉冲数不足以完成完整的加减速
  if (accelPulses + decelPulses > targetPulses) {
    // 按比例缩短加减速阶段
    float ratio = (float)targetPulses / (accelPulses + decelPulses);
    accelPulses = (long)(accelPulses * ratio);
    decelPulses = (long)(decelPulses * ratio);
    constPulses = 0;
  } else {
    constPulses = targetPulses - accelPulses - decelPulses;
  }
  
  currentFreq = 0;
  pulseInterval = 1000000; // 初始频率1Hz
}

void loop() {
  // 处理串口指令
  if (Serial.available() > 0) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    
    if (cmd.startsWith("F")) {
      int freq = cmd.substring(1).toInt();
      if (freq > 0 && freq <= 20000) {
        targetFreq = freq;
        Serial.print("目标频率已设置为: ");
        Serial.print(freq);
        Serial.println(" Hz");
      } else {
        Serial.println("错误: 频率范围应为1-20000Hz");
      }
    }
    else if (cmd.startsWith("D")) {
      int dir = cmd.substring(1).toInt();
      direction = (dir == 1);
      digitalWrite(DIR_PIN, direction ? HIGH : LOW);
      Serial.print("方向已设置为: ");
      Serial.println(direction ? "正转" : "反转");
    }
    else if (cmd.startsWith("A")) {
      int time = cmd.substring(1).toInt();
      if (time >= 0 && time <= 5000) {
        accelTime = time;
        Serial.print("加速时间已设置为: ");
        Serial.print(time);
        Serial.println(" ms");
      } else {
        Serial.println("错误: 加速时间范围应为0-5000ms");
      }
    }
    else if (cmd.startsWith("B")) {
      int time = cmd.substring(1).toInt();
      if (time >= 0 && time <= 5000) {
        decelTime = time;
        Serial.print("减速时间已设置为: ");
        Serial.print(time);
        Serial.println(" ms");
      } else {
        Serial.println("错误: 减速时间范围应为0-5000ms");
      }
    }
    else if (cmd.startsWith("P")) {
      long pulses = cmd.substring(1).toInt();
      if (pulses > 0) {
        targetPulses = pulses;
        currentPulses = 0;
        calculateAccelDecel();
        isRunning = true;
        Serial.print("开始运行，目标脉冲数: ");
        Serial.println(targetPulses);
      } else {
        Serial.println("错误: 脉冲数必须大于0");
      }
    }
    else if (cmd == "S") {
      isRunning = false;
      currentPulses = 0;
      targetPulses = 0;
      digitalWrite(PUL_PIN, LOW);
      Serial.println("电机已紧急停止");
    }
    else if (cmd == "R") {
      Serial.print("状态:");
      Serial.print(isRunning ? "运行中" : "停止");
      Serial.print(" 进度:");
      Serial.print(currentPulses);
      Serial.print("/");
      Serial.print(targetPulses);
      Serial.print(" 频率:");
      Serial.print(currentFreq);
      Serial.println(" Hz");
    }
    else {
      Serial.println("未知指令");
    }
  }
  
  // 电机脉冲输出主循环（加减速控制）
  if (isRunning && currentPulses < targetPulses) {
    unsigned long now = micros();
    if (now - lastPulseTime >= pulseInterval) {
      // 输出脉冲
      digitalWrite(PUL_PIN, HIGH);
      delayMicroseconds(2); // 确保脉冲宽度足够
      digitalWrite(PUL_PIN, LOW);
      
      currentPulses++;
      lastPulseTime = now;
      
      // 更新当前频率（加减速逻辑）
      if (currentPulses < accelPulses) {
        // 加速阶段
        currentFreq = (float)currentPulses * targetFreq / accelPulses;
      } 
      else if (currentPulses < accelPulses + constPulses) {
        // 匀速阶段
        currentFreq = targetFreq;
      } 
      else {
        // 减速阶段
        long decelPos = currentPulses - accelPulses - constPulses;
        currentFreq = targetFreq * (1.0 - (float)decelPos / decelPulses);
      }
      
      // 确保频率不低于1Hz
      if (currentFreq < 1) currentFreq = 1;
      
      // 更新脉冲间隔
      pulseInterval = 1000000 / currentFreq;
      
      // 运行完成
      if (currentPulses >= targetPulses) {
        isRunning = false;
        currentFreq = 0;
        Serial.println("运行完成");
      }
    }
  }
}