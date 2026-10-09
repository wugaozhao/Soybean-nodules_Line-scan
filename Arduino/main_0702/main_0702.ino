// main_0702.ino
// Arduino Uno lower-controller for stepper module + two NPN limit sensors.
//
// Wiring default:
//   PUL_PIN         -> stepper driver PUL
//   DIR_PIN         -> stepper driver DIR
//   UPPER_LIMIT_PIN -> upper/end-near-motor NPN sensor output (Arduino pin 2)
//   LOWER_LIMIT_PIN -> lower/far-from-motor NPN sensor output (Arduino pin 3)
//
// Limit relays:
//   COM -> Arduino GND
//   NO  -> Arduino input pin
// Inputs use INPUT_PULLUP:
//   relay open = HIGH, relay closed/limit triggered = LOW.
//
// Direction mapping:
//   D1 / DIR HIGH -> near motor end / upper limit direction
//   D0 / DIR LOW  -> far from motor end / lower limit direction

const int PUL_PIN = 9;
const int DIR_PIN = 10;
const int UPPER_LIMIT_PIN = 2;
const int LOWER_LIMIT_PIN = 3;

const bool LIMIT_ACTIVE_LOW = true;
const bool DIRECTION_FAR_MOTOR = false;
const bool DIRECTION_NEAR_MOTOR = true;
const bool DEFAULT_DOWN_DIRECTION = DIRECTION_FAR_MOTOR;
const bool ENABLE_POWER_ON_HOMING = false;
const unsigned int PULSE_WIDTH_US = 3;
const int HOME_FREQ = 500;
const unsigned long POWER_ON_HOME_DELAY_MS = 2500;
const unsigned long LIMIT_DEBOUNCE_MS = 5;

volatile long targetPulses = 0;
volatile long currentPulses = 0;
volatile int targetFreq = 1000;
volatile int accelTime = 500;
volatile int decelTime = 500;
volatile bool direction = true;
volatile bool downDirection = DEFAULT_DOWN_DIRECTION;
volatile bool isRunning = false;

volatile long maxTravelPulses = 999999;
volatile long accelPulses = 0;
volatile long decelPulses = 0;
volatile long constPulses = 0;
volatile float currentFreq = 0;
volatile unsigned long pulseInterval = 1000000UL;
volatile bool upperLimitTrip = false;
volatile bool lowerLimitTrip = false;
unsigned long lastPulseTime = 0;
bool powerOnHomingPending = false;
unsigned long powerOnHomingDueTime = 0;
int upperLastRaw = HIGH;
int lowerLastRaw = HIGH;
unsigned long upperRawChangedAt = 0;
unsigned long lowerRawChangedAt = 0;
bool upperDebouncedActive = false;
bool lowerDebouncedActive = false;

String lastStopReason = "IDLE";

bool isRawActive(int value) {
  return LIMIT_ACTIVE_LOW ? (value == LOW) : (value == HIGH);
}

bool readLimitActive(int pin) {
  int value = digitalRead(pin);
  return isRawActive(value);
}

void upperLimitISR() {
  if (readLimitActive(UPPER_LIMIT_PIN)) {
    upperLimitTrip = true;
  }
}

void lowerLimitISR() {
  if (readLimitActive(LOWER_LIMIT_PIN)) {
    lowerLimitTrip = true;
  }
}

int upperRaw() {
  return digitalRead(UPPER_LIMIT_PIN);
}

int lowerRaw() {
  return digitalRead(LOWER_LIMIT_PIN);
}

bool upperActive() {
  return upperDebouncedActive;
}

bool lowerActive() {
  return lowerDebouncedActive;
}

bool upperInstantActive() {
  return upperLimitTrip || readLimitActive(UPPER_LIMIT_PIN);
}

bool lowerInstantActive() {
  return lowerLimitTrip || readLimitActive(LOWER_LIMIT_PIN);
}

void syncLimitTripLatches() {
  if (!readLimitActive(UPPER_LIMIT_PIN)) {
    upperLimitTrip = false;
  }
  if (!readLimitActive(LOWER_LIMIT_PIN)) {
    lowerLimitTrip = false;
  }
}

void clearOppositeLimitTrip(bool moveDirection) {
  if (moveDirection == downDirection) {
    upperLimitTrip = false;
  } else {
    lowerLimitTrip = false;
  }
}

void initLimitDebounce() {
  upperLastRaw = upperRaw();
  lowerLastRaw = lowerRaw();
  upperRawChangedAt = millis();
  lowerRawChangedAt = millis();
  upperDebouncedActive = isRawActive(upperLastRaw);
  lowerDebouncedActive = isRawActive(lowerLastRaw);
}

void updateOneLimitDebounce(int raw, int &lastRaw, unsigned long &changedAt, bool &debouncedActive) {
  unsigned long now = millis();
  if (raw != lastRaw) {
    lastRaw = raw;
    changedAt = now;
    return;
  }
  if (now - changedAt >= LIMIT_DEBOUNCE_MS) {
    debouncedActive = isRawActive(raw);
  }
}

void updateLimitDebounce() {
  updateOneLimitDebounce(upperRaw(), upperLastRaw, upperRawChangedAt, upperDebouncedActive);
  updateOneLimitDebounce(lowerRaw(), lowerLastRaw, lowerRawChangedAt, lowerDebouncedActive);
}

void setup() {
  pinMode(PUL_PIN, OUTPUT);
  pinMode(DIR_PIN, OUTPUT);
  pinMode(UPPER_LIMIT_PIN, INPUT_PULLUP);
  pinMode(LOWER_LIMIT_PIN, INPUT_PULLUP);

  digitalWrite(PUL_PIN, LOW);
  digitalWrite(DIR_PIN, downDirection ? HIGH : LOW);
  initLimitDebounce();
  attachInterrupt(digitalPinToInterrupt(UPPER_LIMIT_PIN), upperLimitISR, CHANGE);
  attachInterrupt(digitalPinToInterrupt(LOWER_LIMIT_PIN), lowerLimitISR, CHANGE);

  Serial.begin(9600);
  Serial.setTimeout(20);
  Serial.println(F("READY:MAIN_0702"));
  Serial.println(F("CMD:F<Hz>,A<ms>,B<ms>,D<0/1>,P<pulses>,M<maxPulses>,T<dir>,<pulses>,G,H,S,R"));

  if (ENABLE_POWER_ON_HOMING) {
    preparePowerOnHoming();
  } else {
    powerOnHomingPending = false;
    lastStopReason = "IDLE";
    Serial.println(F("EVENT:POWER_ON_HOMING_DISABLED"));
  }
  sendStatus();
}

void preparePowerOnHoming() {
  if (upperActive() || upperInstantActive()) {
    lastStopReason = "UPPER_LIMIT";
    Serial.println(F("EVENT:POWER_ON_UPPER_READY"));
    return;
  }

  powerOnHomingPending = true;
  powerOnHomingDueTime = millis() + POWER_ON_HOME_DELAY_MS;
  lastStopReason = "POWER_ON_HOME_PENDING";
  Serial.println(F("EVENT:POWER_ON_HOMING_PENDING"));
}

void handlePowerOnHoming() {
  if (!powerOnHomingPending || isRunning) {
    return;
  }
  if (upperActive() || upperInstantActive()) {
    powerOnHomingPending = false;
    lastStopReason = "UPPER_LIMIT";
    Serial.println(F("EVENT:POWER_ON_UPPER_READY"));
    sendStatus();
    return;
  }
  if ((long)(millis() - powerOnHomingDueTime) < 0) {
    return;
  }

  powerOnHomingPending = false;
  targetFreq = HOME_FREQ;
  startMove(!downDirection, maxTravelPulses, false, "HOMING_STARTED");
}

void calculateAccelDecel() {
  if (targetPulses <= 0 || targetFreq <= 0) {
    return;
  }

  accelPulses = accelTime > 0 ? (long)(targetFreq * accelTime / 2000.0) : 0;
  decelPulses = decelTime > 0 ? (long)(targetFreq * decelTime / 2000.0) : 0;

  if (accelPulses + decelPulses > targetPulses) {
    float ratio = (float)targetPulses / (float)(accelPulses + decelPulses);
    accelPulses = (long)(accelPulses * ratio);
    decelPulses = (long)(decelPulses * ratio);
    constPulses = 0;
  } else {
    constPulses = targetPulses - accelPulses - decelPulses;
  }

  currentFreq = accelPulses > 0 ? 1 : targetFreq;
  pulseInterval = (unsigned long)(1000000.0 / currentFreq);
}

void loop() {
  updateLimitDebounce();
  runMotor();
  handleSerial();
  handlePowerOnHoming();
}

void handleSerial() {
  if (Serial.available() <= 0) {
    return;
  }

  String cmd = Serial.readStringUntil('\n');
  cmd.trim();
  if (cmd.length() == 0) {
    return;
  }

  if (cmd.startsWith("F")) {
    int freq = cmd.substring(1).toInt();
    if (freq > 0 && freq <= 20000) {
      targetFreq = freq;
      Serial.print(F("OK:FREQ:"));
      Serial.println(targetFreq);
    } else {
      Serial.println(F("ERR:FREQ_RANGE"));
    }
  } else if (cmd.startsWith("A")) {
    int value = cmd.substring(1).toInt();
    if (value >= 0 && value <= 5000) {
      accelTime = value;
      Serial.print(F("OK:ACCEL:"));
      Serial.println(accelTime);
    } else {
      Serial.println(F("ERR:ACCEL_RANGE"));
    }
  } else if (cmd.startsWith("B")) {
    int value = cmd.substring(1).toInt();
    if (value >= 0 && value <= 5000) {
      decelTime = value;
      Serial.print(F("OK:DECEL:"));
      Serial.println(decelTime);
    } else {
      Serial.println(F("ERR:DECEL_RANGE"));
    }
  } else if (cmd.startsWith("D")) {
    int value = cmd.substring(1).toInt();
    direction = (value == 1);
    digitalWrite(DIR_PIN, direction ? HIGH : LOW);
    Serial.print(F("OK:DIR:"));
    Serial.println(direction ? 1 : 0);
  } else if (cmd.startsWith("P")) {
    long pulses = cmd.substring(1).toInt();
    if (pulses <= 0) {
      Serial.println(F("ERR:PULSES"));
      return;
    }
    bool movingDown = (direction == DIRECTION_FAR_MOTOR);
    powerOnHomingPending = false;
    startMove(direction, pulses, movingDown, "RUN_STARTED");
  } else if (cmd.startsWith("M")) {
    long value = cmd.substring(1).toInt();
    if (value > 0) {
      maxTravelPulses = value;
      Serial.print(F("OK:MAX_PULSES:"));
      Serial.println(maxTravelPulses);
    } else {
      Serial.println(F("ERR:MAX_PULSES"));
    }
  } else if (cmd.startsWith("T")) {
    int commaIndex = cmd.indexOf(',');
    if (commaIndex <= 1) {
      Serial.println(F("ERR:DEBUG_FORMAT"));
      return;
    }
    int dirValue = cmd.substring(1, commaIndex).toInt();
    long pulses = cmd.substring(commaIndex + 1).toInt();
    if (pulses <= 0) {
      Serial.println(F("ERR:DEBUG_PULSES"));
      return;
    }
    bool moveDirection = (dirValue == 1);
    bool movingDown = (moveDirection == downDirection);
    powerOnHomingPending = false;
    startMove(moveDirection, pulses, movingDown, "DEBUG_STARTED");
  } else if (cmd == "G") {
    powerOnHomingPending = false;
    startMove(downDirection, maxTravelPulses, true, "RUN_STARTED");
  } else if (cmd == "H") {
    powerOnHomingPending = false;
    startMove(!downDirection, maxTravelPulses, false, "HOMING_STARTED");
  } else if (cmd == "S") {
    stopMotor("STOPPED");
    Serial.println(F("EVENT:STOPPED"));
  } else if (cmd == "R") {
    sendStatus();
  } else {
    Serial.println(F("ERR:UNKNOWN_CMD"));
  }
}

void startMove(bool moveDirection, long pulses, bool movingDown, const char *startEvent) {
  if (isRunning) {
    Serial.println(F("ERR:BUSY"));
    return;
  }
  syncLimitTripLatches();
  if (movingDown && lowerInstantActive()) {
    lowerDebouncedActive = true;
    Serial.println(F("ERR:LOWER_ALREADY_ACTIVE"));
    sendStatus();
    return;
  }
  if (!movingDown && upperInstantActive()) {
    upperDebouncedActive = true;
    Serial.println(F("ERR:UPPER_ALREADY_ACTIVE"));
    sendStatus();
    return;
  }
  if (pulses <= 0) {
    Serial.println(F("ERR:PULSES"));
    return;
  }

  direction = moveDirection;
  clearOppositeLimitTrip(direction);
  digitalWrite(DIR_PIN, direction ? HIGH : LOW);
  targetPulses = pulses;
  currentPulses = 0;
  calculateAccelDecel();
  isRunning = true;
  lastPulseTime = micros();
  lastStopReason = "RUNNING";
  Serial.print(F("EVENT:"));
  Serial.println(startEvent);
  sendStatus();
}

void runMotor() {
  if (!isRunning) {
    return;
  }

  if (stopForActiveLimit()) {
    return;
  }

  if (currentPulses >= targetPulses) {
    stopMotor("MAX_PULSES");
    Serial.println(F("EVENT:MAX_PULSES"));
    sendStatus();
    return;
  }

  unsigned long now = micros();
  if (now - lastPulseTime < pulseInterval) {
    return;
  }

  digitalWrite(PUL_PIN, HIGH);
  delayMicroseconds(PULSE_WIDTH_US);
  digitalWrite(PUL_PIN, LOW);

  currentPulses++;
  lastPulseTime = now;

  if (stopForActiveLimit()) {
    return;
  }

  updateCurrentFrequency();
}

bool stopForActiveLimit() {
  if (!isRunning) {
    return false;
  }

  if (direction == downDirection && lowerInstantActive()) {
    lowerDebouncedActive = true;
    stopMotor("LOWER_LIMIT");
    Serial.println(F("EVENT:LOWER_LIMIT"));
    sendStatus();
    return true;
  }

  if (direction != downDirection && upperInstantActive()) {
    upperDebouncedActive = true;
    stopMotor("UPPER_LIMIT");
    Serial.println(F("EVENT:UPPER_LIMIT"));
    sendStatus();
    return true;
  }

  return false;
}

void updateCurrentFrequency() {
  if (accelPulses > 0 && currentPulses < accelPulses) {
    currentFreq = (float)currentPulses * targetFreq / (float)accelPulses;
  } else if (currentPulses < accelPulses + constPulses) {
    currentFreq = targetFreq;
  } else if (decelPulses > 0) {
    long decelPos = currentPulses - accelPulses - constPulses;
    currentFreq = targetFreq * (1.0 - (float)decelPos / (float)decelPulses);
  } else {
    currentFreq = targetFreq;
  }

  if (currentFreq < 1) {
    currentFreq = 1;
  }
  pulseInterval = (unsigned long)(1000000.0 / currentFreq);
}

void stopMotor(const char *reason) {
  isRunning = false;
  currentFreq = 0;
  digitalWrite(PUL_PIN, LOW);
  lastStopReason = reason;
  if (reason[0] == 'S') {
    upperLimitTrip = upperInstantActive();
    lowerLimitTrip = lowerInstantActive();
  }
}

void sendStatus() {
  Serial.print(F("STATUS:STATE:"));
  Serial.print(isRunning ? F("RUNNING") : F("STOPPED"));
  Serial.print(F(";PULSES:"));
  Serial.print(currentPulses);
  Serial.print(F("/"));
  Serial.print(targetPulses);
  Serial.print(F(";FREQ:"));
  Serial.print(currentFreq, 0);
  Serial.print(F(";UPPER:"));
  Serial.print(upperActive() ? 1 : 0);
  Serial.print(F(";LOWER:"));
  Serial.print(lowerActive() ? 1 : 0);
  Serial.print(F(";URAW:"));
  Serial.print(upperRaw());
  Serial.print(F(";LRAW:"));
  Serial.print(lowerRaw());
  Serial.print(F(";REASON:"));
  Serial.println(lastStopReason);
}
