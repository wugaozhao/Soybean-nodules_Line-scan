#include <AccelStepper.h>

// 引脚定义
#define Y_EN     3
#define Z_STEP   11
#define Z_DIR    10
#define Z_EN     9

AccelStepper zMotor(AccelStepper::DRIVER, Z_STEP, Z_DIR);

long pulseAmount = 10000;   // 默认单程脉冲数
long target = 0;            // 目标位置（相对运动）
int state = 0;              // 0=空闲, 1=正向运动中, 2=反向运动中
String inputBuffer = "";

void setup() {
  Serial.begin(9600);
  inputBuffer.reserve(100);

  // 使能引脚初始化
  pinMode(Y_EN, OUTPUT);
  digitalWrite(Y_EN, HIGH);   // Y轴默认失能（假设）
  pinMode(Z_EN, OUTPUT);
  digitalWrite(Z_EN, LOW);    // Z轴使能

  // 电机参数设置
  zMotor.setMaxSpeed(10000);      // 最大速度（步/秒），后续可通过 FREQ 命令修改
  zMotor.setAcceleration(3000);   // 加速度
  zMotor.setCurrentPosition(0);   // 当前位置归零
  zMotor.move(0);                 // 无运动
  state = 0;
}

void loop() {
  // 读取串口命令（以换行结束）
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      parseCommand(inputBuffer);
      inputBuffer = "";
    } else {
      inputBuffer += c;
    }
  }

  // 运动状态机
  if (state != 0) {
    zMotor.run();                     // 必须频繁调用以维持运动
    if (zMotor.distanceToGo() == 0) { // 到达目标位置
      if (state == 1) {               // 正向刚结束
        Serial.println("FORWARD_END");
        target = -pulseAmount;        // 准备反向运动
        zMotor.move(target);
        state = 2;                    // 切换到反向运动状态
      } 
      else if (state == 2) {          // 反向刚结束
        Serial.println("ROUND_TRIP_END");
        state = 0;
        zMotor.move(0);               // 停止
      }
    }
  }
}

void parseCommand(String cmd) {
  cmd.trim();
  if (cmd.length() == 0) return;

  // --- 停止 ---
  if (cmd == "STOP") {
    if (state != 0) {
      zMotor.stop();          // 立即停止（无减速，若需减速可用 zMotor.stop() 然后设置新目标）
      zMotor.move(0);         // 清除目标
      state = 0;
      Serial.println("STOPPED");
    } else {
      Serial.println("ALREADY STOPPED");
    }
    return;
  }

  // --- 启动一次往返 ---
  if (cmd == "START") {
    if (state == 0) {
      state = 1;
      target = pulseAmount;
      zMotor.move(target);
      Serial.println("STARTED");
    } else {
      Serial.println("ALREADY RUNNING");
    }
    return;
  }

  // --- 设置单程脉冲数 ---
  if (cmd.startsWith("PULSES ")) {
    if (state != 0) {
      Serial.println("STOP FIRST");
      return;
    }
    long val = cmd.substring(7).toInt();
    if (val > 0 && val <= 1000000) {
      pulseAmount = val;
      Serial.println("PULSES SET TO " + String(pulseAmount));
    } else {
      Serial.println("INVALID PULSES");
    }
    return;
  }

  // --- 新增：设置脉冲频率（最大速度） ---
  if (cmd.startsWith("FREQ ")) {
    if (state != 0) {
      Serial.println("STOP FIRST");
      return;
    }
    long val = cmd.substring(5).toInt();
    if (val > 0 && val <= 200000) {   // 上限200kHz，可根据驱动器实际能力调整
      zMotor.setMaxSpeed(val);
      Serial.println("FREQ SET TO " + String(val));
    } else {
      Serial.println("INVALID FREQ");
    }
    return;
  }

  // 未知命令
  Serial.println("UNKNOWN CMD");
}