/*
 * Arduino A - 小车步进电机控制
 * 协议：
 *   "MAF"  前进（连续）
 *   "MAB"  后退（连续）
 *   "MAS"  停止
 * 默认脉冲频率：500 Hz（可在 SPEED_HZ 修改）
 * 接线示例（可后续修改）：
 *   STEP_PIN = 5
 *   DIR_PIN  = 6
 *   ENABLE_PIN = 7（可选，低电平使能）
 */

#include <AccelStepper.h>

// ---------- 用户可修改参数 ----------
const int STEP_PIN = 5;
const int DIR_PIN = 6;
const int ENABLE_PIN = 7;   // 不需要使能引脚可注释掉
const float SPEED_HZ = 500; // 脉冲频率（Hz）

// ---------- 对象初始化 ----------
AccelStepper stepper(AccelStepper::DRIVER, STEP_PIN, DIR_PIN);

// 运动方向标记
bool moving = false;
bool direction = true; // true=前进, false=后退

void setup() {
  Serial.begin(115200);

  pinMode(ENABLE_PIN, OUTPUT);
  digitalWrite(ENABLE_PIN, LOW); // 使能电机

  stepper.setMaxSpeed(SPEED_HZ); // 设置最大速度（频率）
  stepper.setSpeed(0);
}

void loop() {
  // 检查串口指令
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();

    if (cmd == "MAF") {        // 前进
      direction = true;
      digitalWrite(DIR_PIN, direction ? HIGH : LOW);
      stepper.setSpeed(SPEED_HZ);
      moving = true;
    }
    else if (cmd == "MAB") {  // 后退
      direction = false;
      digitalWrite(DIR_PIN, direction ? HIGH : LOW);
      stepper.setSpeed(-SPEED_HZ); // 负速度实现反转
      moving = true;
    }
    else if (cmd == "MAS") {  // 停止
      stepper.setSpeed(0);
      moving = false;
    }
  }

  // 保持脉冲输出
  if (moving) {
    stepper.runSpeed();
  }
}