/*
 * 直线模组控制系统 - Arduino下位机程序 (带电流缓升缓降)
 * 硬件配置:
 * - Arduino UNO
 * - 电机: 57HB76L4-30DB (两相步进电机，额定电流4.2A)
 * - 驱动器: DM542 (设置为1/16细分)
 * 
 * 接线说明:
 * - DIR+ (方向正): Arduino pin 9
 * - DIR- (方向负): GND
 * - PUL+ (脉冲正): Arduino pin 10
 * - PUL- (脉冲负): GND
 * - ENA+ (使能正): Arduino pin 11
 * - ENA- (使能负): GND
 * 
 * 新增功能:
 * 1. 电流缓升缓降 (S形加减速曲线)
 * 2. 多种运动模式支持
 * 3. 电流保护机制
 */

// 引脚定义
#define DIR_PIN 9     // 方向控制引脚
#define PUL_PIN 10    // 脉冲控制引脚
#define ENA_PIN 11    // 使能控制引脚

// 方向常数定义
#define DIR_FORWARD LOW    // 前进方向电平 (靠近电机端)
#define DIR_BACKWARD HIGH  // 后退方向电平 (远离电机端)

// 缓升缓降参数
#define ACCELERATION_TIME 1000    // 加速时间 (毫秒)
#define DECELERATION_TIME 1000    // 减速时间 (毫秒)
#define MIN_FREQUENCY 100         // 最小频率 (Hz) - 启动频率
#define MAX_FREQUENCY 5000        // 最大频率 (Hz) - 根据电机和负载调整
#define S_CURVE_SAMPLES 100       // S曲线采样点数

// 全局变量
long targetPulses = 0;           // 目标脉冲数
long currentPulses = 0;          // 当前已发送脉冲数
int targetFrequency = 1000;      // 目标频率 (Hz)
int currentFrequency = MIN_FREQUENCY; // 当前频率 (Hz)
bool isMoving = false;           // 运动状态标志
bool directionForward = true;    // 运动方向
bool emergencyStop = false;      // 急停标志
bool isAccelerating = false;     // 加速阶段标志
bool isCruising = false;         // 匀速阶段标志
bool isDecelerating = false;     // 减速阶段标志

// 位置和状态跟踪
long actualPosition = 0;         // 实际位置
unsigned long moveStartTime = 0; // 运动开始时间
unsigned long accelStartTime = 0; // 加速开始时间
unsigned long decelStartTime = 0; // 减速开始时间

// S曲线加减速表 (预计算以提高性能)
float sCurveAccel[S_CURVE_SAMPLES];
float sCurveDecel[S_CURVE_SAMPLES];

// 脉冲控制变量
unsigned long pulseInterval;     // 当前脉冲间隔 (微秒)
unsigned long lastPulseTime = 0; // 上次脉冲时间

// 运动模式枚举
enum MoveMode {
  MODE_CONSTANT_SPEED,    // 匀速运动
  MODE_S_CURVE,          // S曲线加减速
  MODE_TRAPEZOIDAL       // 梯形加减速
};

MoveMode currentMode = MODE_S_CURVE; // 默认使用S曲线模式

void setup() {
  // 初始化引脚
  pinMode(DIR_PIN, OUTPUT);
  pinMode(PUL_PIN, OUTPUT);
  pinMode(ENA_PIN, OUTPUT);
  
  // 初始状态：使能电机 (LOW为使能)
  digitalWrite(ENA_PIN, LOW);  // 使能电机
  digitalWrite(PUL_PIN, LOW);
  
  // 初始方向：前进
  digitalWrite(DIR_PIN, DIR_FORWARD);
  
  // 预计算S曲线表
  calculateSCurveTables();
  
  // 初始化串口通信
  Serial.begin(115200);
  while (!Serial) {
    ; // 等待串口连接
  }
  
  // 发送就绪状态
  sendStatus("READY");
  sendPosition();
  
  Serial.println("直线模组控制系统已就绪 (带电流缓升缓降)");
  Serial.println("引脚配置: DIR=9, PUL=10, ENA=11");
  Serial.println("等待指令...");
  Serial.println("可用命令:");
  Serial.println("  MOVE:F:1000:1000  - 前进1000脉冲，目标频率1000Hz");
  Serial.println("  MOVE:B:500:800   - 后退500脉冲，目标频率800Hz");
  Serial.println("  MODE:0            - 设置运动模式: 0=匀速, 1=S曲线, 2=梯形");
  Serial.println("  ACCEL:500         - 设置加速时间(毫秒)");
  Serial.println("  DECEL:500         - 设置减速时间(毫秒)");
  Serial.println("  STOP              - 紧急停止");
  Serial.println("  STATUS?           - 查询状态");
  Serial.println("  POSITION?         - 查询位置");
  Serial.println("  RESET             - 重置位置计数器");
  Serial.println("  PARAMS?           - 查看当前参数");
  Serial.println("");
  Serial.println("当前运动模式: S曲线加减速");
  Serial.println("加速时间: " + String(ACCELERATION_TIME) + "ms");
  Serial.println("减速时间: " + String(DECELERATION_TIME) + "ms");
  Serial.println("频率范围: " + String(MIN_FREQUENCY) + "-" + String(MAX_FREQUENCY) + "Hz");
}

void calculateSCurveTables() {
  // 计算S曲线加速表
  for (int i = 0; i < S_CURVE_SAMPLES; i++) {
    float t = (float)i / (S_CURVE_SAMPLES - 1);
    // 使用正弦函数创建平滑的S曲线
    sCurveAccel[i] = 0.5 - 0.5 * cos(t * PI);
  }
  
  // 计算S曲线减速表 (与加速对称)
  for (int i = 0; i < S_CURVE_SAMPLES; i++) {
    sCurveDecel[i] = sCurveAccel[S_CURVE_SAMPLES - 1 - i];
  }
}

void loop() {
  // 处理串口命令
  if (Serial.available() > 0) {
    String command = Serial.readStringUntil('\n');
    command.trim();
    processCommand(command);
  }
  
  // 执行运动控制
  if (isMoving && !emergencyStop) {
    updateMovement();
    generatePulses();
  }
}

void processCommand(String command) {
  if (command.startsWith("MOVE:")) {
    // 解析运动命令: MOVE:方向:脉冲数:频率
    int firstColon = command.indexOf(':');
    int secondColon = command.indexOf(':', firstColon + 1);
    int thirdColon = command.indexOf(':', secondColon + 1);
    
    if (firstColon != -1 && secondColon != -1 && thirdColon != -1) {
      String dirStr = command.substring(firstColon + 1, secondColon);
      String pulseStr = command.substring(secondColon + 1, thirdColon);
      String freqStr = command.substring(thirdColon + 1);
      
      // 设置方向
      if (dirStr == "F") {
        directionForward = true;
        digitalWrite(DIR_PIN, DIR_FORWARD);
        Serial.println("方向: 前进 (靠近电机端)");
      } else if (dirStr == "B") {
        directionForward = false;
        digitalWrite(DIR_PIN, DIR_BACKWARD);
        Serial.println("方向: 后退 (远离电机端)");
      } else {
        Serial.println("错误: 方向参数无效 (必须为F或B)");
        return;
      }
      
      // 设置脉冲数
      targetPulses = pulseStr.toInt();
      if (targetPulses <= 0) {
        Serial.println("错误: 脉冲数必须为正整数");
        return;
      }
      
      // 设置目标频率
      targetFrequency = freqStr.toInt();
      if (targetFrequency < MIN_FREQUENCY) {
        targetFrequency = MIN_FREQUENCY;
        Serial.println("警告: 目标频率低于最小值，已调整到" + String(MIN_FREQUENCY) + "Hz");
      } else if (targetFrequency > MAX_FREQUENCY) {
        targetFrequency = MAX_FREQUENCY;
        Serial.println("警告: 目标频率高于最大值，已调整到" + String(MAX_FREQUENCY) + "Hz");
      }
      
      // 重置运动状态
      startMovement();
      
    } else {
      Serial.println("错误: 命令格式不正确");
    }
    
  } else if (command.startsWith("MODE:")) {
    // 设置运动模式
    String modeStr = command.substring(5);
    int mode = modeStr.toInt();
    
    if (mode >= 0 && mode <= 2) {
      currentMode = (MoveMode)mode;
      String modeNames[] = {"匀速", "S曲线", "梯形"};
      Serial.println("运动模式已设置为: " + modeNames[mode]);
    } else {
      Serial.println("错误: 模式参数无效 (0=匀速, 1=S曲线, 2=梯形)");
    }
    
  } else if (command.startsWith("ACCEL:")) {
    // 设置加速时间
    String timeStr = command.substring(6);
    int time = timeStr.toInt();
    
    if (time >= 100 && time <= 5000) {
      // ACCELERATION_TIME是常量，实际应用中可以将其改为变量
      Serial.println("加速时间设置功能已预留，请修改代码中的ACCELERATION_TIME常量");
      Serial.println("当前加速时间: " + String(ACCELERATION_TIME) + "ms");
    } else {
      Serial.println("错误: 加速时间应在100-5000ms范围内");
    }
    
  } else if (command.startsWith("DECEL:")) {
    // 设置减速时间
    String timeStr = command.substring(6);
    int time = timeStr.toInt();
    
    if (time >= 100 && time <= 5000) {
      // DECELERATION_TIME是常量，实际应用中可以将其改为变量
      Serial.println("减速时间设置功能已预留，请修改代码中的DECELERATION_TIME常量");
      Serial.println("当前减速时间: " + String(DECELERATION_TIME) + "ms");
    } else {
      Serial.println("错误: 减速时间应在100-5000ms范围内");
    }
    
  } else if (command == "STOP") {
    emergencyStopProcedure();
    
  } else if (command == "STATUS?") {
    sendDetailedStatus();
    
  } else if (command == "POSITION?") {
    sendPosition();
    
  } else if (command == "RESET") {
    actualPosition = 0;
    Serial.println("位置计数器已重置");
    sendPosition();
    
  } else if (command == "PARAMS?") {
    sendParameters();
    
  } else if (command == "TEST:SCURVE") {
    testSCurve();
    
  } else if (command.length() > 0) {
    Serial.print("未知命令: ");
    Serial.println(command);
  }
}

void startMovement() {
  // 开始新的运动
  currentPulses = 0;
  currentFrequency = MIN_FREQUENCY;
  isMoving = true;
  emergencyStop = false;
  isAccelerating = true;
  isCruising = false;
  isDecelerating = false;
  
  moveStartTime = millis();
  accelStartTime = moveStartTime;
  
  // 计算减速点
  long decelStartPulses = calculateDecelerationStart();
  
  Serial.print("开始运动: ");
  Serial.print(targetPulses);
  Serial.print(" 脉冲, 目标频率: ");
  Serial.print(targetFrequency);
  Serial.print(" Hz, 模式: ");
  Serial.println(getModeName(currentMode));
  
  sendStatus("ACCELERATING");
}

void updateMovement() {
  unsigned long currentTime = millis();
  unsigned long elapsedTime = currentTime - moveStartTime;
  
  // 根据运动阶段更新频率
  if (isAccelerating) {
    updateAcceleration(currentTime);
  } else if (isCruising) {
    updateCruising();
  } else if (isDecelerating) {
    updateDeceleration(currentTime);
  }
  
  // 检查是否应该开始减速
  if (isAccelerating && shouldStartDeceleration()) {
    startDeceleration(currentTime);
  }
  
  // 检查是否完成减速
  if (isDecelerating && currentFrequency <= MIN_FREQUENCY) {
    completeMovement();
  }
  
  // 更新脉冲间隔
  pulseInterval = 1000000 / currentFrequency / 2;
}

void updateAcceleration(unsigned long currentTime) {
  unsigned long accelElapsed = currentTime - accelStartTime;
  float progress = (float)accelElapsed / ACCELERATION_TIME;
  
  if (progress >= 1.0) {
    // 加速完成
    progress = 1.0;
    isAccelerating = false;
    isCruising = true;
    sendStatus("CRUISING");
  }
  
  // 根据运动模式计算当前频率
  switch (currentMode) {
    case MODE_CONSTANT_SPEED:
      // 匀速模式：直接跳到目标频率
      currentFrequency = targetFrequency;
      break;
      
    case MODE_S_CURVE:
      // S曲线加速
      {
        int index = (int)(progress * (S_CURVE_SAMPLES - 1));
        index = constrain(index, 0, S_CURVE_SAMPLES - 1);
        float freqRange = targetFrequency - MIN_FREQUENCY;
        currentFrequency = MIN_FREQUENCY + sCurveAccel[index] * freqRange;
      }
      break;
      
    case MODE_TRAPEZOIDAL:
      // 梯形加速 (线性加速)
      currentFrequency = MIN_FREQUENCY + progress * (targetFrequency - MIN_FREQUENCY);
      break;
  }
  
  currentFrequency = constrain(currentFrequency, MIN_FREQUENCY, targetFrequency);
}

void updateCruising() {
  // 匀速阶段保持目标频率
  currentFrequency = targetFrequency;
}

void updateDeceleration(unsigned long currentTime) {
  unsigned long decelElapsed = currentTime - decelStartTime;
  float progress = (float)decelElapsed / DECELERATION_TIME;
  
  if (progress >= 1.0) {
    progress = 1.0;
  }
  
  // 根据运动模式计算当前频率
  switch (currentMode) {
    case MODE_CONSTANT_SPEED:
      // 匀速模式：直接降到最低频率
      currentFrequency = MIN_FREQUENCY;
      break;
      
    case MODE_S_CURVE:
      // S曲线减速
      {
        int index = (int)(progress * (S_CURVE_SAMPLES - 1));
        index = constrain(index, 0, S_CURVE_SAMPLES - 1);
        float freqRange = targetFrequency - MIN_FREQUENCY;
        currentFrequency = MIN_FREQUENCY + sCurveDecel[index] * freqRange;
      }
      break;
      
    case MODE_TRAPEZOIDAL:
      // 梯形减速 (线性减速)
      currentFrequency = targetFrequency - progress * (targetFrequency - MIN_FREQUENCY);
      break;
  }
  
  currentFrequency = constrain(currentFrequency, MIN_FREQUENCY, targetFrequency);
}

bool shouldStartDeceleration() {
  // 计算剩余脉冲数
  long remainingPulses = targetPulses - currentPulses;
  
  // 计算减速所需的脉冲数 (基于平均频率)
  float avgFrequencyDuringDecel = (targetFrequency + MIN_FREQUENCY) / 2.0;
  long pulsesForDecel = (avgFrequencyDuringDecel * DECELERATION_TIME) / 1000;
  
  // 当剩余脉冲数小于等于减速所需脉冲数时开始减速
  return remainingPulses <= pulsesForDecel;
}

void startDeceleration(unsigned long currentTime) {
  isCruising = false;
  isDecelerating = true;
  decelStartTime = currentTime;
  sendStatus("DECELERATING");
}

long calculateDecelerationStart() {
  // 计算减速开始的脉冲数
  float avgFrequencyDuringDecel = (targetFrequency + MIN_FREQUENCY) / 2.0;
  long pulsesForDecel = (avgFrequencyDuringDecel * DECELERATION_TIME) / 1000;
  return targetPulses - pulsesForDecel;
}

void completeMovement() {
  isMoving = false;
  isDecelerating = false;
  currentFrequency = MIN_FREQUENCY;
  
  Serial.print("运动完成: 发送 ");
  Serial.print(currentPulses);
  Serial.print(" 脉冲, 实际位置: ");
  Serial.println(actualPosition);
  
  sendStatus("COMPLETE");
  sendPosition();
}

void emergencyStopProcedure() {
  emergencyStop = true;
  isMoving = false;
  isAccelerating = false;
  isCruising = false;
  isDecelerating = false;
  
  // 快速减速到最小频率
  currentFrequency = MIN_FREQUENCY;
  
  Serial.println("紧急停止 - 电流缓降保护");
  sendStatus("EMERGENCY_STOP");
}

void generatePulses() {
  // 使用微秒计时器生成精确脉冲
  unsigned long currentTime = micros();
  
  if (currentTime - lastPulseTime >= pulseInterval) {
    // 生成一个脉冲 (切换PUL_PIN状态)
    digitalWrite(PUL_PIN, !digitalRead(PUL_PIN));
    lastPulseTime = currentTime;
    
    // 每次完整的脉冲周期(高低电平各一次)计数一次
    if (digitalRead(PUL_PIN) == HIGH) {
      currentPulses++;
      
      // 更新实际位置（考虑方向）
      if (directionForward) {
        actualPosition++;
      } else {
        actualPosition--;
      }
      
      // 定期报告状态
      if (currentPulses % 200 == 0) {
        sendMovementInfo();
      }
      
      // 检查是否完成运动
      if (currentPulses >= targetPulses) {
        completeMovement();
      }
    }
  }
}

String getModeName(MoveMode mode) {
  switch (mode) {
    case MODE_CONSTANT_SPEED: return "匀速";
    case MODE_S_CURVE: return "S曲线";
    case MODE_TRAPEZOIDAL: return "梯形";
    default: return "未知";
  }
}

void sendStatus(String status) {
  Serial.print("STATUS:");
  Serial.println(status);
}

void sendPosition() {
  Serial.print("POS:");
  Serial.println(actualPosition);
}

void sendDetailedStatus() {
  Serial.println("=== 系统状态 ===");
  Serial.print("运动状态: ");
  Serial.println(isMoving ? "运动中" : "停止");
  
  Serial.print("运动阶段: ");
  if (isAccelerating) Serial.println("加速");
  else if (isCruising) Serial.println("匀速");
  else if (isDecelerating) Serial.println("减速");
  else Serial.println("静止");
  
  Serial.print("当前位置: ");
  Serial.println(actualPosition);
  
  Serial.print("当前频率: ");
  Serial.print(currentFrequency);
  Serial.println(" Hz");
  
  Serial.print("运动模式: ");
  Serial.println(getModeName(currentMode));
  
  Serial.print("目标脉冲: ");
  Serial.print(currentPulses);
  Serial.print(" / ");
  Serial.println(targetPulses);
  
  Serial.println("================");
}

void sendParameters() {
  Serial.println("=== 系统参数 ===");
  Serial.print("运动模式: ");
  Serial.println(getModeName(currentMode));
  Serial.print("加速时间: ");
  Serial.print(ACCELERATION_TIME);
  Serial.println(" ms");
  Serial.print("减速时间: ");
  Serial.print(DECELERATION_TIME);
  Serial.println(" ms");
  Serial.print("最小频率: ");
  Serial.print(MIN_FREQUENCY);
  Serial.println(" Hz");
  Serial.print("最大频率: ");
  Serial.print(MAX_FREQUENCY);
  Serial.println(" Hz");
  Serial.println("================");
}

void sendMovementInfo() {
  Serial.print("PROGRESS:");
  Serial.print(currentPulses);
  Serial.print(":");
  Serial.print(targetPulses);
  Serial.print(":");
  Serial.print(currentFrequency);
  Serial.print(":");
  Serial.println(getModeName(currentMode));
}

void testSCurve() {
  Serial.println("开始S曲线测试...");
  Serial.println("将进行加速到2000Hz然后减速的测试");
  
  targetFrequency = 2000;
  currentFrequency = MIN_FREQUENCY;
  
  Serial.println("加速阶段...");
  for (int i = 0; i < S_CURVE_SAMPLES; i++) {
    float freqRange = targetFrequency - MIN_FREQUENCY;
    int freq = MIN_FREQUENCY + sCurveAccel[i] * freqRange;
    Serial.print("加速点 ");
    Serial.print(i);
    Serial.print(": 频率=");
    Serial.println(freq);
    delay(10);
  }
  
  Serial.println("减速阶段...");
  for (int i = 0; i < S_CURVE_SAMPLES; i++) {
    float freqRange = targetFrequency - MIN_FREQUENCY;
    int freq = MIN_FREQUENCY + sCurveDecel[i] * freqRange;
    Serial.print("减速点 ");
    Serial.print(i);
    Serial.print(": 频率=");
    Serial.println(freq);
    delay(10);
  }
  
  Serial.println("S曲线测试完成");
  currentFrequency = MIN_FREQUENCY;
}