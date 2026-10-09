const int STEP_X = 3;
const int DIR_X  = 4;
const int EN_X   = 5;

String inputBuffer = "";
bool cmdReady = false;

void setup() {
  pinMode(STEP_X, OUTPUT); pinMode(DIR_X, OUTPUT);
  pinMode(EN_X, OUTPUT);
  digitalWrite(EN_X, LOW);
  Serial.begin(9600);
  Serial.println("X_READY");
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

    if (cmd.startsWith("X")) {
      long steps = cmd.substring(1).toInt();
      int dir = (steps >= 0) ? HIGH : LOW;
      steps = abs(steps);
      digitalWrite(DIR_X, dir);
      delayMicroseconds(5);

      unsigned long halfPeriod = 500;  // 1000 Hz
      for (long i = 0; i < steps; i++) {
        digitalWrite(STEP_X, HIGH);
        delayMicroseconds(halfPeriod);
        digitalWrite(STEP_X, LOW);
        delayMicroseconds(halfPeriod);
      }
      Serial.println("X_OK");
    }
    else if (cmd == "STOP") {
      Serial.println("X_OK");
    }
  }
}