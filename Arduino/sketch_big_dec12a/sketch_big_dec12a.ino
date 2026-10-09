/*
 * 57HB76 最稳单向版
 * 固定 25 µs 周期，高电平 10 µs，40 kHz
 * DIR 9  HIGH，STEP 10，ENA 11 低电平使能
 */
const byte DIR_PIN  = 9;
const byte STEP_PIN = 10;
const byte EN_PIN   = 11;

void setup() {
  pinMode(DIR_PIN , OUTPUT);
  pinMode(STEP_PIN, OUTPUT);
  pinMode(EN_PIN  , OUTPUT);
  digitalWrite(EN_PIN, LOW);   // 使能
  digitalWrite(DIR_PIN, HIGH); // 方向固定

  // Timer1 快速 PWM 模式，TOP=ICR1=49 → 25 µs
  noInterrupts();
  TCCR1A = (1<<COM1B1) | (1<<WGM11);
  TCCR1B = (1<<WGM13) | (1<<CS11);      // 8 分频 0.5 µs
  ICR1   = 49;                          // 25 µs 周期
  OCR1B  = 20;                          // 高电平 10 µs
  TCNT1  = 0;
  interrupts();
}

void loop() {
  // 空循环，电机一直单向匀速
}