#include <Arduino.h>
#include <Wire.h>
#include <U8g2lib.h>

#ifndef SERIAL_BAUD
#define SERIAL_BAUD 115200
#endif

#ifndef OLED_SDA
#define OLED_SDA 5
#endif

#ifndef OLED_SCL
#define OLED_SCL 6
#endif

#ifndef OLED_GEOMETRY
#define OLED_GEOMETRY 72
#endif

#if OLED_GEOMETRY == 72
U8G2_SSD1306_72X40_ER_F_HW_I2C oled(U8G2_R0, U8X8_PIN_NONE, OLED_SCL, OLED_SDA);
static constexpr int kScreenWidth = 72;
static constexpr int kScreenHeight = 40;
#else
U8G2_SSD1306_128X64_NONAME_F_HW_I2C oled(U8G2_R0, U8X8_PIN_NONE, OLED_SCL, OLED_SDA);
static constexpr int kScreenWidth = 128;
static constexpr int kScreenHeight = 64;
#endif

static String inputLine;
static String currentEmotion = "neutral";
static String currentText = "JKS READY";

static void serialAck(const char *status, const String &detail) {
  Serial.print("{\"status\":\"");
  Serial.print(status);
  Serial.print("\",\"detail\":\"");
  for (size_t i = 0; i < detail.length(); i++) {
    char c = detail[i];
    if (c == '"' || c == '\\') {
      Serial.print('\\');
    }
    if (c >= 0x20 && c <= 0x7e) {
      Serial.print(c);
    }
  }
  Serial.println("\"}");
}

static String jsonValue(const String &line, const char *key) {
  String needle = String("\"") + key + "\"";
  int keyPos = line.indexOf(needle);
  if (keyPos < 0) {
    return "";
  }
  int colon = line.indexOf(':', keyPos + needle.length());
  if (colon < 0) {
    return "";
  }
  int firstQuote = line.indexOf('"', colon + 1);
  if (firstQuote < 0) {
    return "";
  }
  String out;
  bool escaping = false;
  for (int i = firstQuote + 1; i < line.length(); i++) {
    char c = line[i];
    if (escaping) {
      if (c == 'n') {
        out += '\n';
      } else if (c == 'r') {
        out += '\r';
      } else if (c == 't') {
        out += '\t';
      } else {
        out += c;
      }
      escaping = false;
      continue;
    }
    if (c == '\\') {
      escaping = true;
      continue;
    }
    if (c == '"') {
      break;
    }
    out += c;
  }
  return out;
}

static const char *faceForEmotion(const String &emotion) {
  if (emotion == "happy" || emotion == "smile" || emotion == "joy") {
    return "^_^";
  }
  if (emotion == "sad") {
    return "T_T";
  }
  if (emotion == "angry") {
    return ">_<";
  }
  if (emotion == "surprised" || emotion == "wow") {
    return "O_O";
  }
  if (emotion == "thinking" || emotion == "think") {
    return "?_?";
  }
  if (emotion == "speaking" || emotion == "talk") {
    return "^o^";
  }
  if (emotion == "sleepy" || emotion == "sleep") {
    return "-_-";
  }
  return "._.";
}

static String sanitizeText(String text, size_t maxLen) {
  text.trim();
  String out;
  for (size_t i = 0; i < text.length() && out.length() < maxLen; i++) {
    char c = text[i];
    if (c >= 0x20 && c <= 0x7e) {
      out += c;
    }
  }
  return out;
}

static void drawStatus() {
  oled.clearBuffer();

  oled.setFont(u8g2_font_6x13B_tr);
  const char *face = faceForEmotion(currentEmotion);
  int faceWidth = oled.getStrWidth(face);
  int faceX = max(0, (kScreenWidth - faceWidth) / 2);
  int faceY = (kScreenHeight <= 40) ? 15 : 24;
  oled.drawStr(faceX, faceY, face);

  oled.setFont(u8g2_font_5x8_tf);
  String text = sanitizeText(currentText, (kScreenWidth <= 72) ? 14 : 24);
  int textWidth = oled.getStrWidth(text.c_str());
  int textX = max(0, (kScreenWidth - textWidth) / 2);
  int textY = (kScreenHeight <= 40) ? 32 : 49;
  oled.drawStr(textX, textY, text.c_str());

  oled.sendBuffer();
}

static void clearDisplay() {
  currentEmotion = "neutral";
  currentText = "";
  oled.clearBuffer();
  oled.sendBuffer();
}

static void handleCommand(String line) {
  line.trim();
  if (line.length() == 0) {
    return;
  }

  if (line == "clear" || line == "CLEAR") {
    clearDisplay();
    serialAck("ok", "clear");
    return;
  }

  if (line[0] != '{') {
    currentEmotion = "neutral";
    currentText = line;
    drawStatus();
    serialAck("ok", "text");
    return;
  }

  String cmd = jsonValue(line, "cmd");
  if (cmd.length() == 0) {
    cmd = jsonValue(line, "type");
  }

  if (cmd == "clear") {
    clearDisplay();
    serialAck("ok", "clear");
    return;
  }

  if (cmd == "text") {
    String text = jsonValue(line, "text");
    currentEmotion = "neutral";
    currentText = text.length() ? text : " ";
    drawStatus();
    serialAck("ok", "text");
    return;
  }

  if (cmd == "emotion" || cmd == "face") {
    String name = jsonValue(line, "name");
    String text = jsonValue(line, "text");
    currentEmotion = name.length() ? name : "neutral";
    currentText = text.length() ? text : currentEmotion;
    drawStatus();
    serialAck("ok", currentEmotion);
    return;
  }

  serialAck("error", "unknown command");
}

static void scanI2c() {
  Serial.print("i2c scan sda=");
  Serial.print(OLED_SDA);
  Serial.print(" scl=");
  Serial.println(OLED_SCL);

  int found = 0;
  for (uint8_t address = 1; address < 127; address++) {
    Wire.beginTransmission(address);
    uint8_t error = Wire.endTransmission();
    if (error == 0) {
      Serial.print("i2c found 0x");
      if (address < 16) {
        Serial.print('0');
      }
      Serial.println(address, HEX);
      found++;
    }
  }
  if (found == 0) {
    Serial.println("i2c found none");
  }
}

void setup() {
  Serial.begin(SERIAL_BAUD);
  delay(400);

  Serial.println();
  Serial.println("JKS OLED controller boot");
  Serial.print("geometry=");
  Serial.print(OLED_GEOMETRY);
  Serial.print(" sda=");
  Serial.print(OLED_SDA);
  Serial.print(" scl=");
  Serial.println(OLED_SCL);

  Wire.begin(OLED_SDA, OLED_SCL);
  Wire.setClock(400000);
  scanI2c();

  oled.begin();
  oled.setContrast(255);
  currentEmotion = "happy";
  currentText = "JKS READY";
  drawStatus();
  serialAck("ok", "boot");
}

void loop() {
  while (Serial.available() > 0) {
    char c = static_cast<char>(Serial.read());
    if (c == '\n' || c == '\r') {
      if (inputLine.length() > 0) {
        handleCommand(inputLine);
        inputLine = "";
      }
      continue;
    }
    if (inputLine.length() < 240) {
      inputLine += c;
    }
  }
}
