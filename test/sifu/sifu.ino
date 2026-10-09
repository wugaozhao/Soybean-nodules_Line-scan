#define DIR_PIN 9
#define PUL_PIN 10

#define DIR_FORWARD HIGH
#define DIR_BACKWARD LOW

#define MAX_FREQ 30000
#define MIN_FREQ 100

long currentPosition = 0;
bool isRunning = false;

void setup() {
  Serial.begin(115200);
  pinMode(DIR_PIN, OUTPUT);
  pinMode(PUL_PIN, OUTPUT);
  digitalWrite(PUL_PIN, LOW);
  Serial.println("ARDUINO READY");
}

void loop() {
  if (Serial.available() > 0) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    if (cmd.length() > 0) parseCommand(cmd);
  }
}

void parseCommand(String cmd) {
  if (cmd.startsWith("MOVE:")) {
    int col1 = cmd.indexOf(':');
    int col2 = cmd.indexOf(':', col1+1);
    int col3 = cmd.indexOf(':', col2+1);
    int col4 = cmd.indexOf(':', col3+1);
    int col5 = cmd.indexOf(':', col4+1);

    char dir = cmd.substring(col1+1, col2).charAt(0);
    long totalPulses = cmd.substring(col2+1, col3).toInt();
    int startFreq = cmd.substring(col3+1, col4).toInt();
    int targetFreq = cmd.substring(col4+1, col5).toInt();
    int accelSteps = cmd.substring(col5+1).toInt();

    startFreq = constrain(startFreq, MIN_FREQ, MAX_FREQ);
    targetFreq = constrain(targetFreq, MIN_FREQ, MAX_FREQ);

    moveTrapezoid(dir, totalPulses, startFreq, targetFreq, accelSteps);
  }
  else if (cmd == "STOP") {
    isRunning = false;
    Serial.println("STATUS:STOPPED");
  }
  else if (cmd == "RESET") {
    currentPosition = 0;
    Serial.println("POS:0");
    Serial.println("STATUS:READY");
  }
}

void moveTrapezoid(char dir, long total, int startFreq, int targetFreq, int accelSteps) {
  if (isRunning) return;
  isRunning = true;
  Serial.println("STATUS:MOVING");

  digitalWrite(DIR_PIN, (dir == 'F') ? DIR_FORWARD : DIR_BACKWARD);
  delay(10); // 方向建立时间（伺服必须要）

  accelSteps = min((long)accelSteps, total / 2);
  long decelStart = total - accelSteps;

  for (long i = 0; i < total; i++) {
    if (!isRunning) break;

    int freq;
    if (i < accelSteps) {
      freq = map(i, 0, accelSteps, startFreq, targetFreq);
    } 
    else if (i >= decelStart) {
      freq = map(i, decelStart, total, targetFreq, startFreq);
    } 
    else {
      freq = targetFreq;
    }

    // 发脉冲
    digitalWrite(PUL_PIN, HIGH);
    digitalWrite(PUL_PIN, LOW);

    long delayUs = 1000000L / freq;
    delayMicroseconds(delayUs);

    currentPosition += (dir == 'F') ? 1 : -1;
  }

  isRunning = false;
  Serial.print("POS:");
  Serial.println(currentPosition);
  Serial.println("STATUS:COMPLETE");
}