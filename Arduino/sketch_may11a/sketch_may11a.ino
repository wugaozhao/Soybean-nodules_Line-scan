#include <AccelStepper.h>

// 引脚定义
#define Y_STEP  6

#define Y_DIR   5
#define Y_EN    3
#define Z_STEP  11
#define Z_DIR   10
#define Z_EN    9

AccelStepper yMotor(AccelStepper::DRIVER, Y_STEP, Y_DIR);
AccelStepper zMotor(AccelStepper::DRIVER, Z_STEP, Z_DIR);

String inputBuffer = "";
boolean newCommand = false;

boolean wasMovingY = false;
boolean wasMovingZ = false;

void setup() {
  Serial.begin(9600);
  inputBuffer.reserve(200);

  pinMode(Y_EN, OUTPUT);
  pinMode(Z_EN, OUTPUT);
  digitalWrite(Y_EN, LOW);
  digitalWrite(Z_EN, LOW);

  yMotor.setMaxSpeed(10000);      // 最大速度提高至10000
  yMotor.setAcceleration(3000);
  zMotor.setMaxSpeed(10000);
  zMotor.setAcceleration(3000);
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      newCommand = true;
      break;
    }
    inputBuffer += c;
  }

  if (newCommand) {
    newCommand = false;
    parseCommand(inputBuffer);
    inputBuffer = "";
  }

  yMotor.run();
  zMotor.run();

  boolean movingY = (yMotor.distanceToGo() != 0);
  boolean movingZ = (zMotor.distanceToGo() != 0);
  if (wasMovingY && !movingY && !movingZ) {
    Serial.println("OK");
  }
  if (wasMovingZ && !movingZ && !movingY) {
    Serial.println("OK");
  }
  wasMovingY = movingY;
  wasMovingZ = movingZ;
}

void parseCommand(String cmd) {
  cmd.trim();
  if (cmd.length() == 0) return;

  if (cmd == "STOP") {
    yMotor.stop();
    zMotor.stop();
    yMotor.move(0);
    zMotor.move(0);
    Serial.println("OK");
    return;
  }

  if (cmd.startsWith("SPEED ")) {
    long speed = cmd.substring(6).toInt();
    if (speed > 10000) speed = 10000;
    yMotor.setMaxSpeed(speed);
    zMotor.setMaxSpeed(speed);
    Serial.println("OK");
    return;
  }

  // 加速度设置命令
  if (cmd.startsWith("ACCEL ")) {
    long acc = cmd.substring(6).toInt();
    if (acc < 100) acc = 100;
    yMotor.setAcceleration(acc);
    zMotor.setAcceleration(acc);
    Serial.println("OK");
    return;
  }

  if (cmd.startsWith("Y")) {
    long pulses = cmd.substring(1).toInt();
    yMotor.move(pulses);
    return;
  }

  if (cmd.startsWith("Z")) {
    long pulses = cmd.substring(1).toInt();
    zMotor.move(pulses);
    return;
  }
}