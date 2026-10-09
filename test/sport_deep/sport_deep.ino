/*
 * 直线模组控制系统 - Arduino下位机程序 (引脚修正版)
 * 硬件配置:
 * - Arduino UNO
 * - 电机: 57HB76L4-30DB (两相步进电机)
 * - 驱动器: DM542 (设置为1/16细分)
 * 
 * 接线说明 (根据用户提供):
 * - DIR+ (方向正): Arduino pin 9
 * - DIR- (方向负): GND
 * - PUL+ (脉冲正): Arduino pin 10
 * - PUL- (脉冲负): GND
 * - ENA+ (使能正): Arduino pin 11
 * - ENA- (使能负): GND
 */

// 引脚定义 (根据用户提供)
#define DIR_PIN 9     // 方向控制引脚
#define PUL_PIN 10    // 脉冲控制引脚
#define ENA_PIN 11    // 使能控制引脚

// 方向常数定义 - 如果方向相反，请交换这两个值
#define DIR_FORWARD LOW    // 前进方向电平 (靠近电机端)
#define DIR_BACKWARD HIGH  // 后退方向电平 (远离电机端)

// 全局变量
long targetPulses = 0;      // 目标脉冲数
long currentPulses = 0;     // 当前脉冲计数
int pulseFrequency = 1000;  // 脉冲频率 (Hz)
bool isMoving = false;      // 运动状态标志
bool directionForward = true; // 运动方向 true=前进(靠近电机端)
bool emergencyStop = false; // 急停标志

// 定时器变量 (用于生成精确脉冲)
unsigned long pulseDelay;   // 脉冲间隔 (微秒)
unsigned long lastPulseTime = 0; // 上次脉冲时间

// 用于跟踪位置的变量（考虑方向）
long actualPosition = 0; // 实际位置（考虑方向的正负）

void setup() {
  // 初始化引脚
  pinMode(DIR_PIN, OUTPUT);
  pinMode(PUL_PIN, OUTPUT);
  pinMode(ENA_PIN, OUTPUT);
  
  // 初始状态：使能电机（LOW为使能）
  digitalWrite(ENA_PIN, LOW);  // LOW = 使能电机
  digitalWrite(PUL_PIN, LOW);
  
  // 初始方向：前进
  digitalWrite(DIR_PIN, DIR_FORWARD);
  
  // 初始化串口通信
  Serial.begin(115200);
  while (!Serial) {
    ; // 等待串口连接
  }
  
  // 发送就绪状态
  sendStatus("READY");
  sendPosition();
  
  Serial.println("直线模组控制系统已就绪 (引脚: DIR=9, PUL=10, ENA=11)");
  Serial.println("等待指令...");
  Serial.println("可用命令:");
  Serial.println("  MOVE:F:1000:1000  - 前进1000脉冲，频率1000Hz");
  Serial.println("  MOVE:B:500:800   - 后退500脉冲，频率800Hz");
  Serial.println("  STOP             - 紧急停止");
  Serial.println("  STATUS?          - 查询状态");
  Serial.println("  POSITION?        - 查询位置");
  Serial.println("  RESET            - 重置位置计数器");
  Serial.println("  TEST:DIRECTION   - 方向测试");
  Serial.println("");
  Serial.println("方向定义:");
  Serial.println("  前进(F): 靠近电机端");
  Serial.println("  后退(B): 远离电机端");
  Serial.println("");
  Serial.println("如果方向相反，请修改DIR_FORWARD和DIR_BACKWARD的定义");
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
      
      // 设置频率
      pulseFrequency = freqStr.toInt();
      if (pulseFrequency < 100 || pulseFrequency > 10000) {
        Serial.println("警告: 频率超出推荐范围(100-10000Hz)，已限制");
        pulseFrequency = constrain(pulseFrequency, 100, 10000);
      }
      
      // 计算脉冲间隔 (微秒)
      pulseDelay = 1000000 / pulseFrequency / 2; // 除以2是因为每个脉冲有高电平和低电平
      
      // 重置状态
      currentPulses = 0;
      isMoving = true;
      emergencyStop = false;
      
      Serial.print("开始运动: ");
      Serial.print(targetPulses);
      Serial.print(" 脉冲, ");
      Serial.print(pulseFrequency);
      Serial.println(" Hz");
      
      sendStatus("MOVING");
    } else {
      Serial.println("错误: 命令格式不正确");
    }
    
  } else if (command == "STOP") {
    emergencyStop = true;
    isMoving = false;
    Serial.println("紧急停止");
    sendStatus("STOPPED");
    
  } else if (command == "STATUS?") {
    sendStatus(isMoving ? "MOVING" : "READY");
    
  } else if (command == "POSITION?") {
    sendPosition();
    
  } else if (command == "RESET") {
    actualPosition = 0;
    Serial.println("位置计数器已重置");
    sendPosition();
    
  } else if (command == "TEST:DIRECTION") {
    testDirection();
    
  } else if (command.length() > 0) {
    Serial.print("未知命令: ");
    Serial.println(command);
  }
}

void generatePulses() {
  // 使用微秒计时器生成精确脉冲
  unsigned long currentTime = micros();
  
  if (currentTime - lastPulseTime >= pulseDelay) {
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
      
      // 每100个脉冲报告一次进度
      if (currentPulses % 100 == 0) {
        sendPosition();
      }
      
      // 检查是否完成运动
      if (currentPulses >= targetPulses) {
        isMoving = false;
        digitalWrite(PUL_PIN, LOW); // 确保脉冲引脚回到低电平
        
        Serial.print("运动完成: 发送 ");
        Serial.print(currentPulses);
        Serial.print(" 脉冲, 实际位置: ");
        Serial.println(actualPosition);
        
        sendStatus("COMPLETE");
        sendPosition();
      }
    }
  }
}

void testDirection() {
  Serial.println("开始方向测试...");
  Serial.println("测试1: 设置方向为前进 (靠近电机端)");
  digitalWrite(DIR_PIN, DIR_FORWARD);
  Serial.print("DIR引脚电平: ");
  Serial.println(DIR_FORWARD == HIGH ? "HIGH" : "LOW");
  Serial.println("如果电机运动方向错误，请修改DIR_FORWARD和DIR_BACKWARD的定义");
  Serial.println("等待3秒...");
  delay(3000);
  
  Serial.println("测试2: 设置方向为后退 (远离电机端)");
  digitalWrite(DIR_PIN, DIR_BACKWARD);
  Serial.print("DIR引脚电平: ");
  Serial.println(DIR_BACKWARD == HIGH ? "HIGH" : "LOW");
  Serial.println("等待3秒...");
  delay(3000);
  
  // 回到前进方向
  digitalWrite(DIR_PIN, DIR_FORWARD);
  Serial.println("测试完成，已设置回前进方向");
}

void sendStatus(String status) {
  Serial.print("STATUS:");
  Serial.println(status);
}

void sendPosition() {
  Serial.print("POS:");
  Serial.println(actualPosition);
}