#include <SoftwareSerial.h>

SoftwareSerial RFID(2, 3); // RX=D2, TX=D3

void setup() {
  Serial.begin(9600);
  RFID.begin(9600);
  delay(300);

  // 强制重置读写器
  byte reset[] = {0x05,0x09,0xD0,0x30,0x00,0x00,0x00,0x13,0xAA};
  RFID.write(reset, 9);
  delay(500);

  // 强制设置：主动读卡号模式
  byte setMode[] = {0x01,0x09,0xA1,0x30,0x02,0x00,0x00, 0x6F, 0xAA};
  RFID.write(setMode, 9);

  Serial.println("=== RFID 已启动，等待刷卡 ===");
}

void loop() {
  while (RFID.available()) {
    byte b = RFID.read();
    Serial.print(b, HEX);
    Serial.print(" ");
  }
}