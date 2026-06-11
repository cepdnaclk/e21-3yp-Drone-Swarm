// Mocap PC <-> drone bridge (laptop-side ESP32, WiFi UDP/USB serial <-> ESP-NOW).
//
// Direction PC -> drone:
//   Creates a WiFi AP and reads three line-based formats from UDP port 4210.
//   USB serial @ 115200 is kept as a fallback/debug input. Parsed commands are
//   forwarded as a binary StatePacket (msg_type-tagged) via ESP-NOW @ 50 Hz:
//
//     "S,x,y,z,vx,vy,vz,yaw_sp,x_sp,y_sp,z_sp,armed\n"  -> msg_type 0
//     "P,<17 floats>\n"                                  -> msg_type 2 (PID + ground effect)
//     "T,trim_t,trim_r,trim_p,trim_y\n"                  -> msg_type 3
//
//   State packets are streamed at the 50 Hz periodic timer. P/T packets are
//   sent immediately on parse (rare events).
//
// Direction drone -> PC:
//   ESP-NOW receives a binary TelemetryPacket (CRSF attitude relayed by the
//   drone ESP32-C3), and prints "H<yaw_rad>\n" over USB serial so the Python
//   backend can fuse heading.
//
// Also: prints this board's STA MAC at boot so you can paste it into the
// drone firmware's `senderAddress[]`.

#include <esp_now.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <esp_wifi.h>
#include <string.h>

// ================= USER SETTINGS =================
uint8_t receiverAddress[] = { 0x10, 0x00, 0x3B, 0xB1, 0x5B, 0x8C };
#define ESPNOW_CHANNEL 1
#define SEND_PERIOD_MS 20   // 50 Hz state stream
#define DEBUG_CMD_PRINT 0

// Laptop connects to this AP, then sends UDP command lines to 192.168.4.1:4210.
// Password must be at least 8 characters for WPA2. Change it before field tests.
#define AP_SSID "DroneSender"
#define AP_PASS "drone1234"
#define UDP_PORT 4210
#define AP_MAX_CLIENTS 4

// Set to 1 to test only the WiFi AP. Use this if the laptop cannot see the
// SSID. Once the SSID is stable, set back to 0 for UDP/ESP-NOW bridge mode.
#define AP_DIAGNOSTIC_ONLY 1
// =================================================

// Tagged ESP-NOW packet. msg_type selects which fields the receiver applies.
// Fields are always sent (cheap on ESP-NOW); receiver dispatches on msg_type.
typedef struct __attribute__((packed)) {
  float    x,  y,  z;            // world position metres
  float    vx, vy, vz;           // world velocity m/s
  float    yaw_sp;               // yaw setpoint radians
  float    x_sp, y_sp, z_sp;     // position setpoints metres
  // 17 floats for PID + ground effect (msg_type=2 only):
  //   [0..2]  xy pos kp/ki/kd       [3..5]  z pos kp/ki/kd
  //   [6..8]  yaw pos kp/ki/kd      [9..11] xy vel kp/ki/kd
  //   [12..14] z vel kp/ki/kd       [15] groundEffectCoef [16] groundEffectOffset
  float    pid[17];
  int16_t  trim_t, trim_r, trim_p, trim_y;
  uint8_t  armed;                // 0 or 1
  uint8_t  msg_type;             // 0=state, 2=pid_gains, 3=trim
  uint32_t seq;
} StatePacket;

// MUST match the struct in drone_receiver_crsf_espnow.ino exactly.
typedef struct __attribute__((packed)) {
  int16_t  pitch_centirad;   // 1/10000 rad (CRSF native units)
  int16_t  roll_centirad;
  int16_t  yaw_centirad;
  uint32_t seq;
} TelemetryPacket;

StatePacket latestState = {};
uint32_t lastSend = 0;
uint32_t lastApCheck = 0;
uint32_t seqCounter = 0;
String inputLine = "";
WiFiUDP udp;

// Parse N comma-separated floats from `line` starting at offset `start`.
// Returns true on success, false if any field is missing or non-numeric.
static bool parseFloats(const String &line, int start, float *out, int n) {
  for (int i = 0; i < n; i++) {
    int comma = line.indexOf(',', start);
    String part = (comma == -1) ? line.substring(start) : line.substring(start, comma);
    part.trim();
    if (part.length() == 0) return false;
    out[i] = part.toFloat();
    if (comma == -1 && i != n - 1) return false;
    start = comma + 1;
  }
  return true;
}

static bool parseInts(const String &line, int start, long *out, int n) {
  for (int i = 0; i < n; i++) {
    int comma = line.indexOf(',', start);
    String part = (comma == -1) ? line.substring(start) : line.substring(start, comma);
    part.trim();
    if (part.length() == 0) return false;
    out[i] = part.toInt();
    if (comma == -1 && i != n - 1) return false;
    start = comma + 1;
  }
  return true;
}

// "S,x,y,z,vx,vy,vz,yaw_sp,x_sp,y_sp,z_sp,armed\n" -> populate latestState (msg_type=0).
// 11 fields: 10 floats + armed (parsed as float, rounded).
static void parseStateLine(const String &line) {
  float f[11];
  if (!parseFloats(line, 2, f, 11)) return;

  latestState.x      = f[0];
  latestState.y      = f[1];
  latestState.z      = f[2];
  latestState.vx     = f[3];
  latestState.vy     = f[4];
  latestState.vz     = f[5];
  latestState.yaw_sp = f[6];
  latestState.x_sp   = f[7];
  latestState.y_sp   = f[8];
  latestState.z_sp   = f[9];
  // armed is a tristate: 0=disarmed, 1=motors armed but parked, 2=flying.
  int armv = (int)(f[10] + 0.5f);
  if (armv < 0) armv = 0;
  if (armv > 2) armv = 2;
  latestState.armed = (uint8_t)armv;
  latestState.msg_type = 0;

#if DEBUG_CMD_PRINT
  Serial.printf("S pos=%.3f,%.3f,%.3f vel=%.3f,%.3f,%.3f yaw_sp=%.3f sp=%.3f,%.3f,%.3f arm=%u\n",
                latestState.x, latestState.y, latestState.z,
                latestState.vx, latestState.vy, latestState.vz,
                latestState.yaw_sp,
                latestState.x_sp, latestState.y_sp, latestState.z_sp,
                latestState.armed);
#endif
}

// "P,<17 floats>\n" -> send PID gain update once (msg_type=2). Does not mutate state stream.
static void parsePidLine(const String &line) {
  float gains[17];
  if (!parseFloats(line, 2, gains, 17)) return;

  StatePacket pkt = latestState;
  memcpy(pkt.pid, gains, sizeof(gains));
  pkt.msg_type = 2;
  pkt.seq = ++seqCounter;
  esp_now_send(receiverAddress, (uint8_t *)&pkt, sizeof(pkt));
}

// "T,trim_t,trim_r,trim_p,trim_y\n" -> send trim update once (msg_type=3).
static void parseTrimLine(const String &line) {
  long t[4];
  if (!parseInts(line, 2, t, 4)) return;

  StatePacket pkt = latestState;
  pkt.trim_t = (int16_t)t[0];
  pkt.trim_r = (int16_t)t[1];
  pkt.trim_p = (int16_t)t[2];
  pkt.trim_y = (int16_t)t[3];
  pkt.msg_type = 3;
  pkt.seq = ++seqCounter;
  esp_now_send(receiverAddress, (uint8_t *)&pkt, sizeof(pkt));
}

static void parseSerialLine(const String &line) {
  if (line.length() < 2 || line[1] != ',') return;
  switch (line[0]) {
    case 'S': parseStateLine(line); break;
    case 'P': parsePidLine(line);   break;
    case 'T': parseTrimLine(line);  break;
    default:                        break;
  }
}

static void parseCommandBuffer(const char *buf, int len) {
  String line = "";
  for (int i = 0; i < len; i++) {
    char c = buf[i];
    if (c == '\n') {
      parseSerialLine(line);
      line = "";
    } else if (c != '\r' && c != '\0') {
      line += c;
      if (line.length() > 256) line = "";
    }
  }
  if (line.length() > 0) {
    parseSerialLine(line);
  }
}

static void pollUdpCommands() {
  int packetSize = udp.parsePacket();
  while (packetSize > 0) {
    char buf[512];
    int len = udp.read(buf, sizeof(buf));
    if (len > 0) {
      parseCommandBuffer(buf, len);
    }
    packetSize = udp.parsePacket();
  }
}

static bool startAccessPoint() {
  IPAddress localIp(192, 168, 4, 1);
  IPAddress gateway(192, 168, 4, 1);
  IPAddress subnet(255, 255, 255, 0);

  WiFi.softAPConfig(localIp, gateway, subnet);
  bool ok = WiFi.softAP(AP_SSID, AP_PASS, ESPNOW_CHANNEL, false, AP_MAX_CLIENTS);
  udp.begin(UDP_PORT);

  IPAddress apIp = WiFi.softAPIP();
  Serial.printf("[sender] WiFi AP: %s  IP: %s  UDP port: %u  channel: %u\n",
                AP_SSID, apIp.toString().c_str(), UDP_PORT, ESPNOW_CHANNEL);
  Serial.printf("[sender] AP start: %s\n", ok ? "OK" : "FAILED");
  return ok;
}

static void checkAccessPoint() {
  uint32_t now = millis();
  if (now - lastApCheck < 5000) return;
  lastApCheck = now;

  wifi_mode_t mode;
  esp_wifi_get_mode(&mode);
  if (mode != WIFI_MODE_APSTA && mode != WIFI_MODE_AP) {
    Serial.println("[sender] AP not active; restarting WiFi AP");
    WiFi.mode(WIFI_AP_STA);
    esp_wifi_set_ps(WIFI_PS_NONE);
    startAccessPoint();
    return;
  }

  Serial.printf("[sender] AP clients: %u\n", WiFi.softAPgetStationNum());
}

void OnDataSent(const wifi_tx_info_t *info, esp_now_send_status_t status) {
  // Quiet on purpose. Uncomment for debugging.
  // Serial.println(status == ESP_NOW_SEND_SUCCESS ? "ESP-NOW OK" : "ESP-NOW FAIL");
}

// Drone -> PC: decode TelemetryPacket and print yaw as "H<float>\n"
// The Python backend (api/index.py) reads this in its heading reader thread.
void OnDataRecv(const esp_now_recv_info *info, const uint8_t *data, int len) {
  if (len != sizeof(TelemetryPacket)) return;
  TelemetryPacket t;
  memcpy(&t, data, sizeof(t));
  float yaw_rad = (float)t.yaw_centirad / 10000.0f;
  Serial.print("H");
  Serial.println(yaw_rad, 4);
}

void setup() {
  Serial.begin(115200);
  delay(500);

  WiFi.persistent(false);
  WiFi.mode(WIFI_AP_STA);
  WiFi.setSleep(false);
  esp_wifi_set_ps(WIFI_PS_NONE);
  esp_wifi_set_max_tx_power(78);  // 19.5 dBm, max allowed by ESP-IDF units.
  startAccessPoint();

  // Print our MAC so the user can paste it into drone_receiver_crsf_espnow.ino
  uint8_t staMac[6];
  esp_wifi_get_mac(WIFI_IF_STA, staMac);
  Serial.printf("[sender] STA MAC: %02X:%02X:%02X:%02X:%02X:%02X\n",
                staMac[0], staMac[1], staMac[2],
                staMac[3], staMac[4], staMac[5]);

#if AP_DIAGNOSTIC_ONLY
  Serial.println("[sender] AP_DIAGNOSTIC_ONLY=1; ESP-NOW bridge is disabled");
  return;
#endif

  if (esp_now_init() != ESP_OK) {
    Serial.println("Error initializing ESP-NOW");
    return;
  }

  esp_now_register_send_cb(OnDataSent);
  esp_now_register_recv_cb(OnDataRecv);

  esp_now_peer_info_t peerInfo = {};
  memcpy(peerInfo.peer_addr, receiverAddress, 6);
  peerInfo.channel = ESPNOW_CHANNEL;
  peerInfo.encrypt = false;
  if (esp_now_add_peer(&peerInfo) != ESP_OK) {
    Serial.println("Failed to add ESP-NOW peer");
    return;
  }

  // Safe defaults until the PC sends real state.
  latestState.armed = 0;
  latestState.msg_type = 0;

  Serial.println("Transmitter ready: UDP/Serial -> ESP-NOW; ESP-NOW -> H<yaw>");
  Serial.println("WiFi UDP ready: connect laptop to AP and send command lines to 192.168.4.1:4210");
  Serial.println("Format: S,x,y,z,vx,vy,vz,yaw_sp,x_sp,y_sp,z_sp,armed");
}

void loop() {
  checkAccessPoint();

#if AP_DIAGNOSTIC_ONLY
  delay(10);
  return;
#endif

  pollUdpCommands();

  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n') {
      parseSerialLine(inputLine);
      inputLine = "";
    } else if (c != '\r') {
      inputLine += c;
      if (inputLine.length() > 256) inputLine = "";  // guard against runaway P-lines
    }
  }

  if (millis() - lastSend >= SEND_PERIOD_MS) {
    lastSend = millis();
    latestState.msg_type = 0;          // periodic stream is always msg_type=0
    latestState.seq = ++seqCounter;
    esp_now_send(receiverAddress, (uint8_t *)&latestState, sizeof(latestState));
  }
}
