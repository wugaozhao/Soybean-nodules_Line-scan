// 电机控制引脚定义
const int PUL_PIN = 9;   // 脉冲输出引脚
const int DIR_PIN = 10;  // 方向控制引脚

// 全局变量
volatile long targetPulses = 0;  // 目标脉冲数
volatile long currentPulses = 0; // 当前已输出脉冲数
volatile unsigned long pulseInterval = 1000; // 脉冲间隔(微秒)，初始1kHz
volatile bool isRunning = false; // 电机运行状态
volatile bool direction = true;  // 运行方向 true=正转 false=反转

unsigned long lastPulseTime = 0; // 上一次脉冲输出时间

void setup() {
  // 初始化引脚
  pinMode(PUL_PIN, OUTPUT);
  pinMode(DIR_PIN, OUTPUT);
  digitalWrite(PUL_PIN, LOW);
  digitalWrite(DIR_PIN, HIGH); // 默认正转
  
  // 初始化串口，波特率9600
  Serial.begin(9600);
  Serial.println("Arduino电机控制器已就绪");
  Serial.println("指令格式:");
  Serial.println("F<频率> - 设置脉冲频率(Hz)");
  Serial.println("D<0/1> - 设置方向(0=反转,1=正转)");
  Serial.println("P<脉冲数> - 设置目标脉冲数并启动");
  Serial.println("S - 立即停止电机");
  Serial.println("R - 查询运行状态");
}

void loop() {
  // 处理串口指令
  if (Serial.available() > 0) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim(); // 去除首尾空白字符
    
    if (cmd.startsWith("F")) { // 设置频率
      int freq = cmd.substring(1).toInt();
      if (freq > 0 && freq <= 20000) { // 限制频率范围0-20kHz
        pulseInterval = 1000000 / freq;
        Serial.print("频率已设置为: ");
        Serial.print(freq);
        Serial.println(" Hz");
      } else {
        Serial.println("错误: 频率范围应为1-20000Hz");
      }
    }
    else if (cmd.startsWith("D")) { // 设置方向
      int dir = cmd.substring(1).toInt();
      direction = (dir == 1);
      digitalWrite(DIR_PIN, direction ? HIGH : LOW);
      Serial.print("方向已设置为: ");
      Serial.println(direction ? "正转" : "反转");
    }
    else if (cmd.startsWith("P")) { // 设置脉冲数并启动
      long pulses = cmd.substring(1).toInt();
      if (pulses > 0) {
        targetPulses = pulses;
        currentPulses = 0;
        isRunning = true;
        Serial.print("开始运行，目标脉冲数: ");
        Serial.println(targetPulses);
      } else {
        Serial.println("错误: 脉冲数必须大于0");
      }
    }
    else if (cmd == "S") { // 停止电机
      isRunning = false;
      currentPulses = 0;
      targetPulses = 0;
      digitalWrite(PUL_PIN, LOW);
      Serial.println("电机已停止");
    }
    else if (cmd == "R") { // 查询状态
      Serial.print("状态:");
      Serial.print(isRunning ? "运行中" : "停止");
      Serial.print(" 已输出脉冲:");
      Serial.print(currentPulses);
      Serial.print("/");
      Serial.println(targetPulses);
    }
    else {
      Serial.println("未知指令");
    }
  }
  
  // 电机脉冲输出主循环
  if (isRunning && currentPulses < targetPulses) {
    unsigned long now = micros();
    if (now - lastPulseTime >= pulseInterval) {
      // 输出一个脉冲
      digitalWrite(PUL_PIN, HIGH);
      delayMicroseconds(1); // 最小脉冲宽度
      digitalWrite(PUL_PIN, LOW);
      
      currentPulses++;
      lastPulseTime = now;
      
      // 运行完成
      if (currentPulses >= targetPulses) {
        isRunning = false;
        Serial.println("运行完成");
      }
    }
  }
}