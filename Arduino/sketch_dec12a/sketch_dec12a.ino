void setup() {
  // put your setup code here, to run once:
  pinMode(10,OUTPUT);//STEP
  pinMode(9,OUTPUT);//DIR
  pinMode(11,OUTPUT);//EN
  digitalWrite(11, LOW);
}

void loop() {
  // put your main code here, to run repeatedly:
  digitalWrite(9,HIGH);
  for (int i=1;i<=6400;i++){
     digitalWrite(10,HIGH);
     delayMicroseconds(120);
     digitalWrite(10,LOW);
     delayMicroseconds(120);
  }
  delay(1000);
  digitalWrite(9,LOW);
  for (int i=1;i<=6400;i++){
     digitalWrite(10,HIGH);
     delayMicroseconds(120);
     digitalWrite(10,LOW);
     delayMicroseconds(120);
  }
  delay(1000);
}
