// motor_debug_simple.ino
// Simple Arduino Uno stepper/servo pulse debug program.
//
// Default wiring:
//   PUL_PIN -> driver PUL/STEP
//   DIR_PIN -> driver DIR
//   UPPER_LIMIT_PIN -> upper/end-near-motor NPN sensor output (Arduino pin 2)
//   LOWER_LIMIT_PIN -> lower/far-from-motor NPN sensor output (Arduino pin 3)
//
// Direction mapping:
//   D0 / DIR LOW  -> near motor end / upper limit direction
//   D1 / DIR HIGH -> far from motor end / lower limit direction
//
// Limit relays:
//   COM -> Arduino GND
//   NO  -> Arduino input pin
// Inputs use INPUT_PULLUP:
//   relay open = HIGH, relay closed/limit triggered = LOW.
//
// Serial commands, newline terminated:
//   D0 / D1      Set direction
//   F1000        Set pulse frequency in Hz
//   P2000        Output 2000 pulses
//   S            Stop immediately
//   R            Query status

const int PUL_PIN = 9;
const int DIR_PIN = 10;
const int UPPER_LIMIT_PIN = 2;
const int LOWER_LIMIT_PIN = 3;

const unsigned int PULSE_WIDTH_US = 3;
const bool LIMIT_ACTIVE_LOW = true;
const bool DIRECTION_FAR_MOTOR = true;
const bool DIRECTION_NEAR_MOTOR = false;
const unsigned long LIMIT_DEBOUNCE_MS = 50;

volatile bool isRunning = false;
volatile bool direction = true;
volatile long targetPulses = 0;
volatile long currentPulses = 0;
volatile int pulseFreq = 500;
volatile unsigned long pulseIntervalUs = 2000;

unsigned long lastPulseTime = 0;
int upperLastRaw = HIGH;
int lowerLastRaw = HIGH;
unsigned long upperRawChangedAt = 0;
unsigned long lowerRawChangedAt = 0;
bool upperDebouncedActive = false;
bool lowerDebouncedActive = false;

void setup() {
  pinMode(PUL_PIN, OUTPUT);
  pinMode(DIR_PIN, OUTPUT);
  pinMode(UPPER_LIMIT_PIN, INPUT_PULLUP);
  pinMode(LOWER_LIMIT_PIN, INPUT_PULLUP);
  digitalWrite(PUL_PIN, LOW);
  digitalWrite(DIR_PIN, DIRECTION_FAR_MOTOR ? HIGH : LOW);
  initLimitDebounce();

  Serial.begin(9600);
  Serial.setTimeout(20);
  updatePulseInterval();

  Serial.println(F("READY:MOTOR_DEBUG_SIMPLE"));
  Serial.println(F("CMD:D0/D1,F<Hz>,P<pulses>,S,R"));
  sendStatus();
}

bool isRawActive(int value) {
  return LIMIT_ACTIVE_LOW ? (value == LOW) : (value == HIGH);
}

bool readLimitActive(int pin) {
  int value = digitalRead(pin);
  return isRawActive(value);
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

void loop() {
  updateLimitDebounce();
  handleSerial();
  runMotor();
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

  if (cmd.startsWith("D")) {
    int value = cmd.substring(1).toInt();
    direction = (value == 1);
    digitalWrite(DIR_PIN, direction ? HIGH : LOW);
    Serial.print(F("OK:DIR:"));
    Serial.println(direction ? 1 : 0);
  } else if (cmd.startsWith("F")) {
    int value = cmd.substring(1).toInt();
    if (value < 1 || value > 20000) {
      Serial.println(F("ERR:FREQ_RANGE"));
      return;
    }
    pulseFreq = value;
    updatePulseInterval();
    Serial.print(F("OK:FREQ:"));
    Serial.println(pulseFreq);
  } else if (cmd.startsWith("P")) {
    long value = cmd.substring(1).toInt();
    if (value <= 0) {
      Serial.println(F("ERR:PULSES"));
      return;
    }
    if (direction == DIRECTION_NEAR_MOTOR && upperActive()) {
      Serial.println(F("ERR:UPPER_ALREADY_ACTIVE"));
      sendStatus();
      return;
    }
    if (direction == DIRECTION_FAR_MOTOR && lowerActive()) {
      Serial.println(F("ERR:LOWER_ALREADY_ACTIVE"));
      sendStatus();
      return;
    }
    targetPulses = value;
    currentPulses = 0;
    isRunning = true;
    lastPulseTime = micros();
    Serial.println(F("EVENT:STARTED"));
    sendStatus();
  } else if (cmd == "S") {
    stopMotor();
    Serial.println(F("EVENT:STOPPED"));
    sendStatus();
  } else if (cmd == "R") {
    sendStatus();
  } else {
    Serial.println(F("ERR:UNKNOWN_CMD"));
  }
}

void runMotor() {
  if (!isRunning) {
    return;
  }

  if (direction == DIRECTION_NEAR_MOTOR && upperActive()) {
    stopMotor();
    Serial.println(F("EVENT:UPPER_LIMIT"));
    sendStatus();
    return;
  }

  if (direction == DIRECTION_FAR_MOTOR && lowerActive()) {
    stopMotor();
    Serial.println(F("EVENT:LOWER_LIMIT"));
    sendStatus();
    return;
  }

  if (currentPulses >= targetPulses) {
    stopMotor();
    Serial.println(F("EVENT:DONE"));
    sendStatus();
    return;
  }

  unsigned long now = micros();
  if (now - lastPulseTime < pulseIntervalUs) {
    return;
  }

  digitalWrite(PUL_PIN, HIGH);
  delayMicroseconds(PULSE_WIDTH_US);
  digitalWrite(PUL_PIN, LOW);

  currentPulses++;
  lastPulseTime = now;
}

void stopMotor() {
  isRunning = false;
  digitalWrite(PUL_PIN, LOW);
}

void updatePulseInterval() {
  pulseIntervalUs = 1000000UL / (unsigned long)pulseFreq;
}

void sendStatus() {
  Serial.print(F("STATUS:STATE:"));
  Serial.print(isRunning ? F("RUNNING") : F("STOPPED"));
  Serial.print(F(";DIR:"));
  Serial.print(direction ? 1 : 0);
  Serial.print(F(";FREQ:"));
  Serial.print(pulseFreq);
  Serial.print(F(";PULSES:"));
  Serial.print(currentPulses);
  Serial.print(F("/"));
  Serial.print(targetPulses);
  Serial.print(F(";UPPER:"));
  Serial.print(upperActive() ? 1 : 0);
  Serial.print(F(";LOWER:"));
  Serial.print(lowerActive() ? 1 : 0);
  Serial.print(F(";URAW:"));
  Serial.print(upperRaw());
  Serial.print(F(";LRAW:"));
  Serial.println(lowerRaw());
}
