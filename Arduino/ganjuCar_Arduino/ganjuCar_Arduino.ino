#define led1 4
#define led2 5
#define led3 6
#define led4 7
#define pls 3
#define dir 2
#define ena 9
char label = '0' ;
int car_speed = 6000;
int jj = 0;

void setup() {
  Serial.begin(9600);
  pinMode(led1, OUTPUT);
  pinMode(led2, OUTPUT);
  pinMode(led3, OUTPUT);
  pinMode(led4, OUTPUT);
  pinMode(pls, OUTPUT);
  pinMode(dir, OUTPUT);
  pinMode(ena, OUTPUT);
  digitalWrite(led1, LOW);
  digitalWrite(led2, LOW);
  digitalWrite(led3, LOW);
  digitalWrite(led4, LOW);
  digitalWrite(ena, LOW);
}

void Go(int x) {
  for (jj = 0; jj <= x; jj = jj + 10) {
    tone(pls, jj);
  }
}

void car_go() {
  digitalWrite(ena, HIGH);
  digitalWrite(dir, HIGH);
  digitalWrite(pls, HIGH);
  Go(car_speed);
  delay(200);
}

void car_back() {
  digitalWrite(ena, HIGH);
  digitalWrite(dir, LOW);
  digitalWrite(pls, HIGH);
  Go(car_speed);
  delay(200);
}

void car_stop() {
  noTone(pls);
//digitalWrite(pls, LOW);
  digitalWrite(ena, LOW);
  delay(200);
}

void loop() {
  label = Serial.read();
  if (label == '0'){
    digitalWrite(led1, HIGH);
    digitalWrite(led2, HIGH);
    digitalWrite(led3, HIGH);
    digitalWrite(led4, HIGH);
    Serial.println(label);
  }
  else if (label == '1'){
    digitalWrite(led1, LOW);
    digitalWrite(led2, HIGH);
    digitalWrite(led3, LOW);
    digitalWrite(led4, HIGH);
    Serial.println(label);
  }
  else if (label == '2'){
    digitalWrite(led1, HIGH);
    digitalWrite(led2, LOW);
    digitalWrite(led3, HIGH);
    digitalWrite(led4, LOW);
    Serial.println(label);
  }
  else if (label == '3'){
    digitalWrite(led1, LOW);
    digitalWrite(led2, LOW);
    digitalWrite(led3, LOW);
    digitalWrite(led4, LOW);
    Serial.println(label);
  }
  else if (label == '5') {
    car_back();
    Serial.println(label);
  }
  else if (label == '6') {
    car_go();
    Serial.println(label);
  }
  else if (label == '7') {
    car_stop();
    Serial.println(label);
  }
  else if (label == '8') {
    car_stop();
    digitalWrite(led1, LOW);
    digitalWrite(led2, HIGH);
    digitalWrite(led3, LOW);
    digitalWrite(led4, HIGH);
    Serial.println(label);
  }
}
