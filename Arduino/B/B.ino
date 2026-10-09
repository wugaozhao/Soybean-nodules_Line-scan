/*
 * Arduino B - 相机横移步进电机控制
 * 协议：
 *   "MBF5000"  前进指定步数（例：5000步）
 *   "MBR5000"  后退指定步数
 * 完成后返回 "OK"，上位机凭此信号继续流程
 * 默认脉冲频率：500 Hz（可修改 SPEED_HZ）
 */
#include <AccelStepper.h>

const int STEP_PIN = 8;
const int DIR_PIN = 9;
const int ENABLE_PIN = 10;   // 根据实际接线
const float SPEED_HZ = 500;

AccelStepper stepper(AccelStepper::DRIVER, STEP_PIN, DIR_PIN);
bool busy = false;

void setup() {
  Serial.begin(115200);
  pinMode(ENABLE_PIN, OUTPUT);
  digitalWrite(ENABLE_PIN, LOW);
  stepper.setMaxSpeed(SPEED_HZ);
  stepper.setSpeed(SPEED_HZ);
}

void loop() {
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    if (cmd.startsWith("MBF")) {
      long steps = cmd.substring(3).toInt();
      if (steps > 0) {
        stepper.move(steps);
        busy = true;
      }
    } else if (cmd.startsWith("MBR")) {
      long steps = cmd.substring(3).toInt();
      if (steps > 0) {
        stepper.move(-steps);
        busy = true;
      }
    }
  }

  if (busy) {
    if (stepper.distanceToGo() != 0) {
      stepper.runSpeedToPosition();
    } else {
      busy = false;
      Serial.println("OK");   // 告知上位机运动完成
    }
  }
}