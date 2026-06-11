// Mocap PC <-> drone bridge (laptop-side ESP32, USB serial <-> ESP-NOW).
//
// Direction PC -> drone:
//   Reads four line-based formats from USB serial @ 115200 and forwards as
//   a binary StatePacket (msg_type-tagged) via ESP-NOW @ 50 Hz to the drone:
//
//     "S,x,y,z,vx,vy,vz,yaw_sp,x_sp,y_sp,z_sp,armed\n"  -> msg_type 0
//     "P,<17 floats>\n"                                  -> msg_type 2 (PID + ground effect)
//     "T,trim_t,trim_r,trim_p,trim_y\n"                  -> msg_type 3
//     "M,AA:BB:CC:DD:EE:FF\n"                            -> retarget ESP-NOW peer (no packet sent)
//
//   State packets are streamed at the 50 Hz periodic timer. P/T packets are
//   sent immediately on parse (rare events). M lines change which drone the
//   MoCap stream is aimed at -- used when the UI selects a different drone.
//
// Direction drone -> PC:
//   ESP-NOW receives a binary TelemetryPacket (CRSF attitude + pack battery
//   relayed by the drone ESP32-C3). Prints two USB-serial lines per packet:
//
//     "H<yaw_rad>\n"                       -- for the heading reader (single-drone path)
//     "B<src_mac>,<mv>,<pct>\n"            -- battery telemetry tagged with the drone's MAC
//
// Also: prints this board's STA MAC at boot so you can paste it into the
// drone firmware's `senderAddress[]`.

#include <esp_now.h>
#include <WiFi.h>
#include <esp_wifi.h>
#include <string.h>

// ================= USER SETTINGS =================
uint8_t receiverAddress[] = { 0x10, 0x00, 0x3B, 0xB1, 0x5B, 0x8C };
#define ESPNOW_CHANNEL 1
#define SEND_PERIOD_MS 20   // 50 Hz state stream
#define DEBUG_CMD_PRINT 0
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

// MUST match the struct in receiver_esp32.ino exactly.
typedef struct __attribute__((packed)) {
  int16_t  pitch_centirad;   // 1/10000 rad (CRSF native units)
  int16_t  roll_centirad;
  int16_t  yaw_centirad;
  uint16_t battery_mv;       // pack voltage in millivolts (from FC CRSF battery frame)
  uint8_t  battery_pct;      // 0..100; FC remaining-% if set, else voltage-mapped
  uint8_t  _pad;
  uint32_t seq;
} TelemetryPacket;

StatePacket latestState = {};
uint32_t lastSend = 0;
uint32_t seqCounter = 0;
String inputLine = "";

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

// Parse two hex nibbles starting at `idx` in `s`. Returns -1 on failure.
static int parseHexByte(const String &s, int idx) {
  if (idx + 1 >= (int)s.length()) return -1;
  auto nib = [](char c) -> int {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return 10 + (c - 'a');
    if (c >= 'A' && c <= 'F') return 10 + (c - 'A');
    return -1;
  };
  int hi = nib(s[idx]);
  int lo = nib(s[idx + 1]);
  if (hi < 0 || lo < 0) return -1;
  return (hi << 4) | lo;
}

// "M,AA:BB:CC:DD:EE:FF" -> change which drone we ESP-NOW state packets to.
// Re-adds the peer if needed. Silently ignored on parse failure.
static void parseMacLine(const String &line) {
  if (line.length() < 19) return;     // "M," + 17 chars MAC = 19
  uint8_t mac[6];
  int idx = 2;
  for (int i = 0; i < 6; i++) {
    int v = parseHexByte(line, idx);
    if (v < 0) return;
    mac[i] = (uint8_t)v;
    idx += 2;
    if (i < 5) {
      if (idx >= (int)line.length() || (line[idx] != ':' && line[idx] != '-')) return;
      idx += 1;
    }
  }

  if (memcmp(mac, receiverAddress, 6) == 0) return;  // nothing to do

  // Remove the old peer (ignore failure -- might not have been added yet),
  // swap the target MAC in, and add the new peer.
  esp_now_del_peer(receiverAddress);
  memcpy(receiverAddress, mac, 6);

  esp_now_peer_info_t peerInfo = {};
  memcpy(peerInfo.peer_addr, receiverAddress, 6);
  peerInfo.channel = ESPNOW_CHANNEL;
  peerInfo.encrypt = false;
  if (esp_now_add_peer(&peerInfo) != ESP_OK) {
    Serial.println("Failed to re-add ESP-NOW peer");
    return;
  }
  Serial.printf("[sender] target -> %02X:%02X:%02X:%02X:%02X:%02X\n",
                mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
}

static void parseSerialLine(const String &line) {
  if (line.length() < 2 || line[1] != ',') return;
  switch (line[0]) {
    case 'S': parseStateLine(line); break;
    case 'P': parsePidLine(line);   break;
    case 'T': parseTrimLine(line);  break;
    case 'M': parseMacLine(line);   break;
    default:                        break;
  }
}

void OnDataSent(const wifi_tx_info_t *info, esp_now_send_status_t status) {
  // Quiet on purpose. Uncomment for debugging.
  // Serial.println(status == ESP_NOW_SEND_SUCCESS ? "ESP-NOW OK" : "ESP-NOW FAIL");
}

// Drone -> PC: decode TelemetryPacket. Prints two USB-serial lines:
//   "H<float>\n"                          for the heading reader (single-drone path)
//   "B<src_mac>,<mv>,<pct>\n"             battery telemetry tagged with the drone MAC
// The Python backend reads both in its serial reader thread.
void OnDataRecv(const esp_now_recv_info *info, const uint8_t *data, int len) {
  if (len != sizeof(TelemetryPacket)) return;
  TelemetryPacket t;
  memcpy(&t, data, sizeof(t));

  float yaw_rad = (float)t.yaw_centirad / 10000.0f;
  Serial.print("H");
  Serial.println(yaw_rad, 4);

  const uint8_t *m = info->src_addr;
  Serial.printf("B%02X:%02X:%02X:%02X:%02X:%02X,%u,%u\n",
                m[0], m[1], m[2], m[3], m[4], m[5],
                (unsigned)t.battery_mv,
                (unsigned)t.battery_pct);
}

void setup() {
  Serial.begin(115200);
  delay(500);

  WiFi.mode(WIFI_STA);
  WiFi.setChannel(ESPNOW_CHANNEL);

  // Print our MAC so the user can paste it into drone_receiver_crsf_espnow.ino
  uint8_t staMac[6];
  esp_wifi_get_mac(WIFI_IF_STA, staMac);
  Serial.printf("[sender] STA MAC: %02X:%02X:%02X:%02X:%02X:%02X\n",
                staMac[0], staMac[1], staMac[2],
                staMac[3], staMac[4], staMac[5]);

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

  Serial.println("Transmitter ready: Python Serial -> ESP-NOW; ESP-NOW -> H<yaw>");
  Serial.println("Format: S,x,y,z,vx,vy,vz,yaw_sp,x_sp,y_sp,z_sp,armed");
}

void loop() {
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
