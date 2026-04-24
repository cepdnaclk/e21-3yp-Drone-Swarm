#include <esp_now.h>
#include <WiFi.h>
#include <esp_wifi.h>

// CRSF runs on Serial1
HardwareSerial CRSFSerial(1);

struct SimpleCommand {
  int throttle;
  bool armed;
};

// 16 channels
uint16_t channels[16];

// CRC calculation
uint8_t crc8(const uint8_t *ptr, uint8_t len) {
  uint8_t crc = 0;
  while (len--) {
    crc ^= *ptr++;
    for (uint8_t i = 0; i < 8; i++) {
      if (crc & 0x80) crc = (crc << 1) ^ 0xD5;
      else crc <<= 1;
    }
  }
  return crc;
}

// Send CRSF RC frame
void sendCRSF() {
  uint8_t packet[26];

  packet[0] = 0xC8; // address
  packet[1] = 24;   // length
  packet[2] = 0x16; // type (RC channels)

  // Pack 16 channels (11-bit each)
  uint32_t buffer = 0;
  uint8_t bits = 0;
  int idx = 3;

  for (int i = 0; i < 16; i++) {
    buffer |= (channels[i] & 0x07FF) << bits;
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

// ESP-NOW receive
void OnDataRecv(const esp_now_recv_info *info, const uint8_t *incomingData, int len) {
  if (len != sizeof(SimpleCommand)) return;

  SimpleCommand cmd;
  memcpy(&cmd, incomingData, sizeof(cmd));

  Serial.print("Throttle: ");
  Serial.print(cmd.throttle);
  Serial.print(" | Armed: ");
  Serial.println(cmd.armed);

  // Default neutral
  for (int i = 0; i < 16; i++) channels[i] = 992;

  if (cmd.armed) {
    channels[2] = map(cmd.throttle, 1000, 2000, 172, 1811);
    channels[4] = 1811; // arm
  } else {
    channels[2] = 172;
    channels[4] = 172;
  }
}

void setup() {
  Serial.begin(115200);

  // CRSF UART (TX=21, RX=20)
  CRSFSerial.begin(420000, SERIAL_8N1, 20, 21);

  WiFi.mode(WIFI_STA);

  uint8_t newMAC[] = { 0xC0, 0x4E, 0x30, 0x4B, 0x80, 0x3B };
  esp_wifi_set_mac(WIFI_IF_STA, newMAC);

  if (esp_now_init() != ESP_OK) {
    Serial.println("ESP-NOW init failed");
    return;
  }

  esp_now_register_recv_cb(OnDataRecv);

  Serial.println("CRSF TX Ready");
}

void loop() {
  sendCRSF();   // continuously send RC data
  delay(4);     // ~250Hz
}