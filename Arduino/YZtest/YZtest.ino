const int STEP_Y = 2;
const int DIR_Y  = 3;
const int STEP_Z = 4;
const int DIR_Z  = 5;
const int EN_PIN = 6;

String inputBuffer = "";
bool cmdReady = false;

void setup() {
  pinMode(STEP_Y, OUTPUT); pinMode(DIR_Y, OUTPUT);
  pinMode(STEP_Z, OUTPUT); pinMode(DIR_Z, OUTPUT);
  pinMode(EN_PIN, OUTPUT);
  digitalWrite(EN_PIN, LOW);
  Serial.begin(9600);
  Serial.println("YZ_READY");
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      inputBuffer.trim();
      cmdReady = true;
    } else {
      inputBuffer += c;
    }
  }

  if (cmdReady) {
    cmdReady = false;
    String cmd = inputBuffer;
    inputBuffer = "";

    if (cmd.startsWith("Y")) {
      long steps = cmd.substring(1).toInt();
      int dir = (steps >= 0) ? HIGH : LOW;
      steps = abs(steps);
      digitalWrite(DIR_Y, dir);
      delayMicroseconds(5);
      moveMotor(STEP_Y, steps);
      Serial.println("Y_OK");
    }
    else if (cmd.startsWith("Z")) {
      long steps = cmd.substring(1).toInt();
      int dir = (steps >= 0) ? HIGH : LOW;
      steps = abs(steps);
      digitalWrite(DIR_Z, dir);
      delayMicroseconds(5);
      moveMotor(STEP_Z, steps);
      Serial.println("Z_OK");
    }
    else if (cmd == "STOP") {
      Serial.println("YZ_OK");
    }
  }
}

void moveMotor(int stepPin, long steps) {
  unsigned long halfPeriod = 500;   // 1000 Hz
  for (long i = 0; i < steps; i++) {
    digitalWrite(stepPin, HIGH);
    delayMicroseconds(halfPeriod);
    digitalWrite(stepPin, LOW);
    delayMicroseconds(halfPeriod);
  }
}