// 引脚定义 修正：Y:3EN 5DIR 6PUL   Z:9EN 10DIR 11PUL
#define Y_ENA 3
#define Y_DIR 5
#define Y_PUL 6

#define Z_ENA 9
#define Z_DIR 10
#define Z_PUL 11

// 加减速配置 可自行微调
const int ACCEL_STEPS = 80;   // 加速步数（越大起步越缓）
const int MIN_DELAY = 30;     // 最小微秒延时（限制最高速度）

void setup() {
  pinMode(Y_ENA, OUTPUT);
  pinMode(Y_DIR, OUTPUT);
  pinMode(Y_PUL, OUTPUT);
  pinMode(Z_ENA, OUTPUT);
  pinMode(Z_DIR, OUTPUT);
  pinMode(Z_PUL, OUTPUT);

  // 驱动器使能 低电平有效
  digitalWrite(Y_ENA, LOW);
  digitalWrite(Z_ENA, LOW);

  Serial.begin(115200);
}

// 标准梯形加减速运动函数
// pulPin:脉冲脚 dirPin:方向脚 totalPulse:总脉冲 freq:脉冲频率 dir:0/1方向
void motorRun(int pulPin, int dirPin, long totalPulse, int freq, int dir)
{
  digitalWrite(dirPin, dir);

  // 单个脉冲基础延时(us)
  long baseUs = 1000000L / freq / 2;
  if(baseUs < MIN_DELAY) baseUs = MIN_DELAY;

  long curDelay;
  long step;

  // 1. 加速阶段 0 ~ ACCEL_STEPS
  for(step = 0; step < ACCEL_STEPS && step < totalPulse; step++)
  {
    // 从大延时线性降到baseUs
    curDelay = map(step, 0, ACCEL_STEPS, baseUs * 3, baseUs);
    pulseOut(pulPin, curDelay);
  }

  // 2. 匀速阶段
  long uniformEnd = totalPulse - ACCEL_STEPS;
  for(; step < uniformEnd; step++)
  {
    pulseOut(pulPin, baseUs);
  }

  // 3. 减速阶段 最后ACCEL_STEPS步
  for(; step < totalPulse; step++)
  {
    long decelPos = step - uniformEnd;
    curDelay = map(decelPos, 0, ACCEL_STEPS, baseUs, baseUs * 3);
    pulseOut(pulPin, curDelay);
  }
}

// 发一个脉冲
void pulseOut(int pin, long us)
{
  digitalWrite(pin, HIGH);
  delayMicroseconds(us);
  digitalWrite(pin, LOW);
  delayMicroseconds(us);
}

// 串口指令解析
void loop()
{
  if(Serial.available() > 0)
  {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    
    // 格式 Y,脉冲,频率,方向   Z,脉冲,频率,方向   ALT,脉冲,频率,方向
    if(cmd.startsWith("Y,"))
    {
      parseMotorCmd(cmd, Y_PUL, Y_DIR);
      Serial.println("OK");
    }
    else if(cmd.startsWith("Z,"))
    {
      parseMotorCmd(cmd, Z_PUL, Z_DIR);
      Serial.println("OK");
    }
    else if(cmd.startsWith("ALT,"))
    {
      parseMotorCmd(cmd, Y_PUL, Y_DIR);
      parseMotorCmd(cmd, Z_PUL, Z_DIR);
      Serial.println("ALT_OK");
    }
  }
}

void parseMotorCmd(String cmd, int pulPin, int dirPin)
{
  int idx1 = cmd.indexOf(',');
  int idx2 = cmd.indexOf(',', idx1+1);
  int idx3 = cmd.indexOf(',', idx2+1);

  // 修复：toInt() 强转 long 类型，解决编译错误
  long pulse = (long)cmd.substring(idx1+1, idx2).toInt();
  int freq   = cmd.substring(idx2+1, idx3).toInt();
  int dir    = cmd.substring(idx3+1).toInt();

  motorRun(pulPin, dirPin, pulse, freq, dir);
}