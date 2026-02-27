/*
  CAN/LIN Bus Selector Firmware (LIN + CAN)

  Board wiring (from your schematic):
    MUX1_SEL3 -> D2
    MUX1_SEL2 -> D3
    MUX1_SEL1 -> D4
    MUX1_SEL0 -> D5

    MUX2_SEL3 -> D6
    MUX2_SEL2 -> D7
    MUX2_SEL1 -> D8
    MUX2_SEL0 -> D9

  Hardware assumptions:
    - Both CD74HC4067 EN pins tied to GND (always enabled)
    - In LIN mode:
        VectorChannel1 uses MUX1  -> LIN1..LIN16
        VectorChannel2 uses MUX2  -> LIN17..LIN32
    - In CAN mode:
        MUX1 is repurposed as CANH mux
        MUX2 is repurposed as CANL mux
        One Vector CAN channel connects to ECU via:
          Vector CANH -> MUX1 SIG, Vector CANL -> MUX2 SIG
        CAN buses supported: 1..16
        Selecting CAN n sets BOTH muxes to channel (n-1)

  Serial commands:
    MODE LIN
    MODE CAN
    LIN <1..32>     (or just "1..32" when in LIN mode)
    CAN <1..16>     (or just "1..16" when in CAN mode)
    STATUS
    HELP

  Defaults on boot:
    MODE LIN
    LIN 1 activates LIN1 on VectorChannel1 and keeps LIN17 on VectorChannel2
*/

#include <Arduino.h>

static const uint32_t SERIAL_BAUD = 9600;

// MUX1 (D2..D5)
static const uint8_t MUX1_S3 = 2;
static const uint8_t MUX1_S2 = 3;
static const uint8_t MUX1_S1 = 4;
static const uint8_t MUX1_S0 = 5;

// MUX2 (D6..D9)
static const uint8_t MUX2_S3 = 6;
static const uint8_t MUX2_S2 = 7;
static const uint8_t MUX2_S1 = 8;
static const uint8_t MUX2_S0 = 9;

enum class Mode : uint8_t { LIN, CAN };
static Mode g_mode = Mode::LIN;

// Track current selections
static uint8_t g_lin_v1 = 1;   // LIN1..LIN16 on VectorChannel1 (MUX1)
static uint8_t g_lin_v2 = 17;  // LIN17..LIN32 on VectorChannel2 (MUX2)
static uint8_t g_can = 1;      // CAN1..CAN16 (MUX1=CANH, MUX2=CANL)

static String rxLine;

// -------- low-level mux addressing --------
static void setMuxAddr(uint8_t s0, uint8_t s1, uint8_t s2, uint8_t s3, uint8_t ch0to15)
{
  digitalWrite(s0, (ch0to15 & 0x01) ? HIGH : LOW);
  digitalWrite(s1, (ch0to15 & 0x02) ? HIGH : LOW);
  digitalWrite(s2, (ch0to15 & 0x04) ? HIGH : LOW);
  digitalWrite(s3, (ch0to15 & 0x08) ? HIGH : LOW);
}

static void setMux1Channel(uint8_t ch0to15)
{
  setMuxAddr(MUX1_S0, MUX1_S1, MUX1_S2, MUX1_S3, ch0to15);
}

static void setMux2Channel(uint8_t ch0to15)
{
  setMuxAddr(MUX2_S0, MUX2_S1, MUX2_S2, MUX2_S3, ch0to15);
}

// -------- higher-level selectors --------
static void selectLIN(uint8_t linBus1to32)
{
  if (linBus1to32 < 1 || linBus1to32 > 32)
  {
    Serial.println(F("ERROR: LIN bus must be 1..32"));
    return;
  }

  if (linBus1to32 <= 16)
  {
    uint8_t ch = linBus1to32 - 1;
    setMux1Channel(ch);
    g_lin_v1 = linBus1to32;

    Serial.print(F("LIN: VectorChannel1 -> LIN_"));
    Serial.print(g_lin_v1);
    Serial.println(F(" Activated"));
  }
  else
  {
    uint8_t ch = linBus1to32 - 17;
    setMux2Channel(ch);
    g_lin_v2 = linBus1to32;

    Serial.print(F("LIN: VectorChannel2 -> LIN_"));
    Serial.print(g_lin_v2);
    Serial.println(F(" Activated"));
  }
}

static void selectCAN(uint8_t canBus1to16)
{
  if (canBus1to16 < 1 || canBus1to16 > 16)
  {
    Serial.println(F("ERROR: CAN bus must be 1..16"));
    return;
  }

  // Always switch CANH & CANL together
  uint8_t ch = canBus1to16 - 1;
  setMux1Channel(ch); // CANH
  setMux2Channel(ch); // CANL
  g_can = canBus1to16;

  Serial.print(F("CAN: CAN"));
  Serial.print(g_can);
  Serial.println(F(" Activated (CANH=MUX1, CANL=MUX2)"));
}

// -------- command parsing --------
static int extractFirstInt(const String &s)
{
  for (uint16_t i = 0; i < s.length(); i++)
  {
    if (isDigit(s[i]))
      return s.substring(i).toInt();
  }
  return -1;
}

static void printStatus()
{
  Serial.print(F("MODE: "));
  Serial.println((g_mode == Mode::LIN) ? F("LIN") : F("CAN"));

  Serial.print(F("LIN STATUS: V1=LIN_"));
  Serial.print(g_lin_v1);
  Serial.print(F(", V2=LIN_"));
  Serial.println(g_lin_v2);

  Serial.print(F("CAN STATUS: CAN"));
  Serial.println(g_can);
}

static void printHelp()
{
  Serial.println(F("Bus Selector Commands:"));
  Serial.println(F("  MODE LIN"));
  Serial.println(F("  MODE CAN"));
  Serial.println(F("  LIN <1..32>   (select LIN bus; also accepts just number in LIN mode)"));
  Serial.println(F("  CAN <1..16>   (select CAN bus; also accepts just number in CAN mode)"));
  Serial.println(F("  STATUS"));
  Serial.println(F("  HELP"));
}

static void setMode(Mode m)
{
  g_mode = m;
  Serial.print(F("MODE set to "));
  Serial.println((g_mode == Mode::LIN) ? F("LIN") : F("CAN"));
}

static void handleCommand(String cmd)
{
  cmd.trim();
  if (cmd.length() == 0) return;

  String up = cmd;
  up.toUpperCase();

  if (up == "HELP" || up == "H" || up == "?")
  {
    printHelp();
    return;
  }

  if (up == "STATUS")
  {
    printStatus();
    return;
  }

  if (up.startsWith("MODE"))
  {
    if (up.indexOf("LIN") >= 0) { setMode(Mode::LIN); return; }
    if (up.indexOf("CAN") >= 0) { setMode(Mode::CAN); return; }
    Serial.println(F("ERROR: Use MODE LIN or MODE CAN"));
    return;
  }

  // Explicit commands
  if (up.startsWith("LIN"))
  {
    int n = extractFirstInt(up);
    if (n < 0) { Serial.println(F("ERROR: LIN needs 1..32")); return; }
    selectLIN((uint8_t)n);
    return;
  }
  if (up.startsWith("CAN"))
  {
    int n = extractFirstInt(up);
    if (n < 0) { Serial.println(F("ERROR: CAN needs 1..16")); return; }
    selectCAN((uint8_t)n);
    return;
  }

  // Implicit numeric command depending on current mode
  int n = extractFirstInt(up);
  if (n < 0)
  {
    Serial.println(F("ERROR: Unknown command. Type HELP."));
    return;
  }

  if (g_mode == Mode::LIN)
  {
    if (n < 1 || n > 32) { Serial.println(F("ERROR: LIN expects 1..32")); return; }
    selectLIN((uint8_t)n);
  }
  else
  {
    if (n < 1 || n > 16) { Serial.println(F("ERROR: CAN expects 1..16")); return; }
    selectCAN((uint8_t)n);
  }
}

// -------- Arduino entry points --------
void setup()
{
  pinMode(MUX1_S0, OUTPUT);
  pinMode(MUX1_S1, OUTPUT);
  pinMode(MUX1_S2, OUTPUT);
  pinMode(MUX1_S3, OUTPUT);

  pinMode(MUX2_S0, OUTPUT);
  pinMode(MUX2_S1, OUTPUT);
  pinMode(MUX2_S2, OUTPUT);
  pinMode(MUX2_S3, OUTPUT);

  Serial.begin(SERIAL_BAUD);
  delay(150);

  Serial.println(F("Bus Selector Ready (LIN + CAN)"));
  printHelp();

  // Default: LIN mode with LIN1 on V1 and LIN17 on V2
  setMode(Mode::LIN);
  selectLIN(1);
  selectLIN(17);
  printStatus();
}

void loop()
{
  while (Serial.available() > 0)
  {
    char c = (char)Serial.read();
    if (c == '\r') continue;

    if (c == '\n')
    {
      String cmd = rxLine;
      rxLine = "";
      handleCommand(cmd);
    }
    else
    {
      if (rxLine.length() < 120) rxLine += c;
    }
  }
}