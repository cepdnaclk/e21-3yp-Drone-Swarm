#include <esp_now.h>
#include <WiFi.h>

// ================= USER SETTINGS =================
// Receiver ESP32 MAC address. This matches your old receiver code.
uint8_t receiverAddress[] = { 0xC0, 0x4E, 0x30, 0x4B, 0x80, 0x3B };
#define ESPNOW_CHANNEL 1
#define SEND_PERIOD_MS 20   // 50 Hz from transmitter to receiver
// Set to 1 only when debugging with a serial monitor.
// Printing every command can cause USB-serial backpressure and multi-second control lag
// if the PC isn't reading the ESP32's serial output.
#define DEBUG_CMD_PRINT 0
// =================================================

typedef struct __attribute__((packed)) {
  uint16_t throttle_us;   // 1000-2000
  uint16_t roll_us;       // 1000-2000
  uint16_t pitch_us;      // 1000-2000
  uint16_t yaw_us;        // 1000-2000
  uint8_t armed;          // 0/1
  uint32_t seq;
} ControlPacket;

ControlPacket cmd = {1000, 1500, 1500, 1500, 0, 0};
uint32_t lastSend = 0;
String inputLine = "";

uint16_t clampUS(long v) {
  if (v < 1000) return 1000;
  if (v > 2000) return 2000;
  return (uint16_t)v;
}

void parseSerialCommand(String line) {
  line.trim();
  if (line.length() == 0) return;

  // Expected format from Python:
  // throttle,roll,pitch,yaw,armed
  // Example: 1000,1500,1500,1500,0
  long vals[5];
  int start = 0;

  for (int i = 0; i < 5; i++) {
    int comma = line.indexOf(',', start);
    String part;
    if (comma == -1) {
      part = line.substring(start);
      if (i < 4) return; // not enough values
    } else {
      part = line.substring(start, comma);
    }
    part.trim();
    vals[i] = part.toInt();
    start = comma + 1;
  }

  cmd.throttle_us = clampUS(vals[0]);
  cmd.roll_us     = clampUS(vals[1]);
  cmd.pitch_us    = clampUS(vals[2]);
  cmd.yaw_us      = clampUS(vals[3]);
  cmd.armed       = vals[4] ? 1 : 0;

  // Extra safety: when disarmed, force throttle low.
  if (!cmd.armed) cmd.throttle_us = 1000;

#if DEBUG_CMD_PRINT
  Serial.print("CMD ");
  Serial.print(cmd.throttle_us); Serial.print(',');
  Serial.print(cmd.roll_us); Serial.print(',');
  Serial.print(cmd.pitch_us); Serial.print(',');
  Serial.print(cmd.yaw_us); Serial.print(',');
  Serial.println(cmd.armed);
#endif
}

// Compatible callback for newer ESP32 Arduino core.
void OnDataSent(const wifi_tx_info_t *info, esp_now_send_status_t status) {
  // Keep quiet for speed. Uncomment for debugging.
  // Serial.println(status == ESP_NOW_SEND_SUCCESS ? "ESP-NOW OK" : "ESP-NOW FAIL");
}

void setup() {
  Serial.begin(115200);
  delay(500);

  WiFi.mode(WIFI_STA);
  WiFi.setChannel(ESPNOW_CHANNEL);

  if (esp_now_init() != ESP_OK) {
    Serial.println("Error initializing ESP-NOW");
    return;
  }

  esp_now_register_send_cb(OnDataSent);

  esp_now_peer_info_t peerInfo = {};
  memcpy(peerInfo.peer_addr, receiverAddress, 6);
  peerInfo.channel = ESPNOW_CHANNEL;
  peerInfo.encrypt = false;

  if (esp_now_add_peer(&peerInfo) != ESP_OK) {
    Serial.println("Failed to add ESP-NOW peer");
    return;
  }

  Serial.println("Transmitter ready: Python Serial -> ESP-NOW");
  Serial.println("Format: throttle,roll,pitch,yaw,armed");
}

void loop() {
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n') {
      parseSerialCommand(inputLine);
      inputLine = "";
    } else if (c != '\r') {
      inputLine += c;
      if (inputLine.length() > 80) inputLine = "";
    }
  }

  if (millis() - lastSend >= SEND_PERIOD_MS) {
    lastSend = millis();
    cmd.seq++;
    esp_now_send(receiverAddress, (uint8_t *)&cmd, sizeof(cmd));
  }
}
