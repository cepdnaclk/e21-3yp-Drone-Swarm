#include <esp_now.h>
#include <WiFi.h>

// MAC Address of your Drone 1 (Receiver)
uint8_t broadcastAddress[] = { 0xC0, 0x4E, 0x30, 0x4B, 0x80, 0x3B };

struct SimpleCommand {
  int throttle;
  bool armed;
};

SimpleCommand cmd;

// ✅ FIXED: Updated signature to match your compiler's requirement
void OnDataSent(const wifi_tx_info_t *info, esp_now_send_status_t status) {
  Serial.print("Send Status: ");
  Serial.println(status == ESP_NOW_SEND_SUCCESS ? "Success" : "Fail");
}

void setup() {
  Serial.begin(115200);
  
  WiFi.mode(WIFI_STA);
  WiFi.setChannel(1); // Ensure this matches the receiver

  if (esp_now_init() != ESP_OK) {
    Serial.println("Error initializing ESP-NOW");
    return;
  }

  // Register the updated callback
  esp_now_register_send_cb(OnDataSent);

  esp_now_peer_info_t peerInfo = {};
  memcpy(peerInfo.peer_addr, broadcastAddress, 6);
  peerInfo.channel = 1;
  peerInfo.encrypt = false;

  if (esp_now_add_peer(&peerInfo) != ESP_OK) {
    Serial.println("Failed to add peer");
    return;
  }

  Serial.println("Transmitter ready...");
}

void loop() {
  // Safe defaults: Low throttle, Disarmed
  cmd.throttle = 1000;
  cmd.armed = true;

  // Send via ESP-NOW
  esp_err_t result = esp_now_send(broadcastAddress, (uint8_t *)&cmd, sizeof(cmd));

  if (result == ESP_OK) {
    Serial.println("Sent packet to ESP-NOW layer");
  } else {
    Serial.println("Error sending packet");
  }

  delay(100); 
}