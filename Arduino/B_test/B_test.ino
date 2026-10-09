#include <AccelStepper.h>

#define Y_EN     3
#define Z_STEP   11
#define Z_DIR    10
#define Z_EN     9

AccelStepper zMotor(AccelStepper::DRIVER, Z_STEP, Z_DIR);

long pulseAmount = 10000;
long target = 0;
int state = 0;              // 0=空闲, 1=正向运动中, 2=反向运动中
String inputBuffer = "";

void setup() {
  Serial.begin(9600);
  inputBuffer.reserve(100);

  pinMode(Y_EN, OUTPUT);
  digitalWrite(Y_EN, HIGH);
  pinMode(Z_EN, OUTPUT);
  digitalWrite(Z_EN, LOW);

  zMotor.setMaxSpeed(10000);
  zMotor.setAcceleration(3000);
  zMotor.setCurrentPosition(0);
  zMotor.move(0);
  state = 0;
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      parseCommand(inputBuffer);
      inputBuffer = "";
    } else {
      inputBuffer += c;
    }
  }

  if (state != 0) {
    zMotor.run();
    if (zMotor.distanceToGo() == 0) {
      if (state == 1) {
        Serial.println("FORWARD_END");
        target = -pulseAmount;
        zMotor.move(target);
        state = 2;
      } 
      else if (state == 2) {
        Serial.println("ROUND_TRIP_END");
        state = 0;
        zMotor.move(0);
      }
    }
  }
}

void parseCommand(String cmd) {
  cmd.trim();
  if (cmd.length() == 0) return;

  if (cmd == "STOP") {
    if (state != 0) {
      zMotor.stop();
      zMotor.move(0);
      state = 0;
      Serial.println("STOPPED");
    } else {
      Serial.println("ALREADY STOPPED");
    }
    return;
  }

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

  Serial.println("UNKNOWN CMD");
}