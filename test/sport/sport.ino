/*
 * 直线模组  UNO + DM542
 * 兼容旧协议：DIR X 1 / X1000 / X-1000 / STOP
 */

const byte PUL_PIN = 2;
const byte DIR_PIN = 3;
const byte ENA_PIN = 4;

long  pulses      = 0;
bool  dirFwd      = true;
bool  running     = false;
bool  dirChanged  = false;
unsigned long dirChangeTime = 0;

void setup() {
  pinMode(PUL_PIN, OUTPUT);
  pinMode(DIR_PIN, OUTPUT);
  pinMode(ENA_PIN, OUTPUT);
  digitalWrite(ENA_PIN, LOW);
  Serial.begin(9600);
}

void loop() {
  if (dirChanged && (micros() - dirChangeTime >= 1000)) {
    dirChanged = false;
    running    = true;
  }

  if (running && pulses > 0) {
    digitalWrite(PUL_PIN, HIGH);
    delayMicroseconds(100);
    digitalWrite(PUL_PIN, LOW);
    delayMicroseconds(100);
    pulses--;
  } else if (running) {
    running = false;
    Serial.println("OK");
  }
}

void serialEvent() {
  String cmd = Serial.readStringUntil('\n');
  cmd.trim();
  if (cmd.length() == 0) return;

  if (cmd.startsWith("DIR")) {
    int dirVal = cmd.substring(7).toInt();
    if (dirVal != dirFwd) {
      dirFwd     = dirVal;
      dirChanged = true;
      digitalWrite(DIR_PIN, dirFwd ? LOW : HIGH);
      dirChangeTime = micros();
    }
    return;
  }

  if (cmd[0] == 'X') {
    int  p      = cmd.substring(1).toInt();
    bool newDir = (p >= 0);
    pulses      = abs(p);

    if (newDir != dirFwd) {
      dirFwd     = newDir;
      dirChanged = true;
      digitalWrite(DIR_PIN, dirFwd ? LOW : HIGH);
      dirChangeTime = micros();
    } else {
      running = true;
    }
  }

  if (cmd == "STOP") {
    pulses = 0;
    running = false;
  }
}