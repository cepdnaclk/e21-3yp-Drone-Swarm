#include <esp_now.h>
#include <WiFi.h>
#include <esp_wifi.h>

// ================= USER SETTINGS =================
// CRSF UART from this ESP32 receiver to Betaflight FC
// Your old code used RX=20, TX=21. Keep these if your wiring is same.
#define CRSF_RX_PIN 20
#define CRSF_TX_PIN 21

// ESP-NOW Wi-Fi channel. Must match transmitter.
#define ESPNOW_CHANNEL 1

// Failsafe: if no valid command arrives, disarm and zero throttle.
#define FAILSAFE_MS 500

// Set to 1 only when debugging with a serial monitor.
// Printing every received packet can add latency/jitter.
#define DEBUG_RX_PRINT 0
// =================================================

HardwareSerial CRSFSerial(1);

// Keep struct fixed-size. Do not use int/bool because size can differ.
typedef struct __attribute__((packed)) {
  uint16_t throttle_us;   // 1000-2000
  uint16_t roll_us;       // 1000-2000, center 1500
  uint16_t pitch_us;      // 1000-2000, center 1500
  uint16_t yaw_us;        // 1000-2000, center 1500
  uint8_t armed;          // 0/1
  uint32_t seq;           // packet counter
} ControlPacket;

ControlPacket lastCmd;
uint32_t lastRecvTime = 0;
uint16_t channels[16];

uint8_t crc8(const uint8_t *ptr, uint8_t len) {
  uint8_t crc = 0;
  while (len--) {
    crc ^= *ptr++;
    for (uint8_t i = 0; i < 8; i++) {
      crc = (crc & 0x80) ? (crc << 1) ^ 0xD5 : (crc << 1);
    }
  }
  return crc;
}

uint16_t usToCRSF(uint16_t us) {
  us = constrain(us, 1000, 2000);
  return map(us, 1000, 2000, 172, 1811);
}

void setSafeChannels() {
  for (int i = 0; i < 16; i++) channels[i] = 992; // neutral
  channels[0] = usToCRSF(1500); // roll
  channels[1] = usToCRSF(1500); // pitch
  channels[2] = usToCRSF(1000); // throttle low
  channels[3] = usToCRSF(1500); // yaw
  channels[4] = usToCRSF(1000); // AUX1 arm LOW
}

void applyCommandToChannels(const ControlPacket &cmd) {
  for (int i = 0; i < 16; i++) channels[i] = 992;

  channels[0] = usToCRSF(cmd.roll_us);     // CH1 Roll
  channels[1] = usToCRSF(cmd.pitch_us);    // CH2 Pitch
  channels[2] = usToCRSF(cmd.throttle_us); // CH3 Throttle
  channels[3] = usToCRSF(cmd.yaw_us);      // CH4 Yaw
  channels[4] = cmd.armed ? usToCRSF(2000) : usToCRSF(1000); // CH5 Arm switch
}

void sendCRSF() {
  uint8_t packet[26];
  packet[0] = 0xC8; // flight controller address
  packet[1] = 24;   // length: type + 22 payload + crc
  packet[2] = 0x16; // RC channels packed

  uint32_t buffer = 0;
  uint8_t bits = 0;
  int idx = 3;

  for (int i = 0; i < 16; i++) {
    buffer |= ((uint32_t)(channels[i] & 0x07FF)) << bits;
    bits += 11;
    while (bits >= 8) {
      packet[idx++] = buffer & 0xFF;
      buffer >>= 8;
      bits -= 8;
    }
  }

  packet[25] = crc8(&packet[2], 23);
  CRSFSerial.write(packet, 26);
}

void OnDataRecv(const esp_now_recv_info *info, const uint8_t *incomingData, int len) {
  if (len != sizeof(ControlPacket)) return;

  memcpy(&lastCmd, incomingData, sizeof(lastCmd));
  lastRecvTime = millis();
  applyCommandToChannels(lastCmd);

#if DEBUG_RX_PRINT
  Serial.print("RX seq="); Serial.print(lastCmd.seq);
  Serial.print(" arm="); Serial.print(lastCmd.armed);
  Serial.print(" T="); Serial.print(lastCmd.throttle_us);
  Serial.print(" R="); Serial.print(lastCmd.roll_us);
  Serial.print(" P="); Serial.print(lastCmd.pitch_us);
  Serial.print(" Y="); Serial.println(lastCmd.yaw_us);
#endif
}

void setup() {
  Serial.begin(115200);
  delay(500);

  setSafeChannels();

  // CRSF: RX from FC telemetry optional, TX to FC receiver input is important.
  CRSFSerial.begin(420000, SERIAL_8N1, CRSF_RX_PIN, CRSF_TX_PIN);

  WiFi.mode(WIFI_STA);
  WiFi.setChannel(ESPNOW_CHANNEL);

  // Keep your fixed receiver MAC from the old sketch.
  uint8_t newMAC[] = { 0xC0, 0x4E, 0x30, 0x4B, 0x80, 0x3B };
  esp_wifi_set_mac(WIFI_IF_STA, newMAC);

  if (esp_now_init() != ESP_OK) {
    Serial.println("ESP-NOW init failed");
    return;
  }

  esp_now_register_recv_cb(OnDataRecv);
  Serial.println("Receiver ready: ESP-NOW -> CRSF");
}

void loop() {
  if (millis() - lastRecvTime > FAILSAFE_MS) {
    setSafeChannels();
  }

  sendCRSF();
  delay(4); // about 250 Hz CRSF output to FC
}
