// Mocap drone-side ESP32-C3 -- DRONE 1 (STA MAC 10:00:3B:B1:5B:8C).
// ESP-NOW <-> CRSF bridge + CRSF telemetry relay back to the laptop +
// nested PID stack (position -> velocity -> stick PWM) running on-board.
//
// Inbound (sender -> here):  StatePacket via ESP-NOW carrying world-frame
//                            position/velocity/setpoints and an armed bit.
//                            PIDs run at 500 Hz, packed RC channels are sent
//                            over CRSF UART to Betaflight FC at ~250 Hz.
//                            500 ms failsafe forces safe sticks if comm dies.
//
// Outbound (here -> sender):  CRSF telemetry ATTITUDE frames (type 0x1E) and
//                            BATTERY_SENSOR frames (type 0x08) received from
//                            the FC TX line are decoded and forwarded as one
//                            TelemetryPacket via ESP-NOW @ 50 Hz. The laptop
//                            ESP32 then prints "H<yaw>" + "B<mac>,..." to USB.
//
// The CRSF UART (RX pin 20 / TX pin 21) is already bidirectional in the
// wiring -- no new wires needed. Enable CRSF telemetry on this UART in
// Betaflight's Ports tab. Battery readings come straight from the FC's own
// voltage sensor (the same one shown in the Betaflight OSD); make sure the
// "Battery Meter" voltage source is configured in Betaflight's Power tab.

#include <esp_now.h>
#include <WiFi.h>
#include <esp_wifi.h>
#include <PID_v1.h>
#include <math.h>

// ================= USER SETTINGS =================
#define CRSF_RX_PIN 20
#define CRSF_TX_PIN 21
#define ESPNOW_CHANNEL 1
#define FAILSAFE_MS 500
#define TELEMETRY_PERIOD_MS 20   // 50 Hz drone -> laptop attitude updates
#define DEBUG_RX_PRINT 0
#define ENABLE_YAW_HOLD 0
#define ENABLE_GROUND_EFFECT 0   // see note in loop() near the multiplier

#define MAX_VEL 100.0
#define ROTOR_RADIUS 0.0225
#define Z_GAIN 0.7
#define ARM_DELAY_MS 100

// ---- Battery ----
// Battery voltage comes from the FC over CRSF telemetry (BATTERY_SENSOR,
// frame type 0x08) -- no extra wiring, the FC already measures the pack.
// The frame carries a "remaining %" field, but Betaflight only fills it in
// when a pack capacity (mAh) is configured; when it reads 0 we fall back to
// a linear voltage->percent map between BATTERY_MIN_MV and BATTERY_MAX_MV.
// Defaults assume a 1S LiPo (3.30 V empty, 4.20 V full); multiply by the
// cell count for bigger packs (e.g. 2S: 6600 / 8400).
#define BATTERY_MIN_MV      3300
#define BATTERY_MAX_MV      4200
// =================================================

// Sender ESP32's STA MAC. Replace with the MAC printed at boot by
// sender_esp32.ino's setup() ("[sender] STA MAC: ...").
uint8_t senderAddress[] = { 0x70, 0x4B, 0xCA, 0x48, 0xC1, 0x24 };

HardwareSerial CRSFSerial(1);

// MUST match sender_esp32.ino exactly.
typedef struct __attribute__((packed)) {
  float    x,  y,  z;
  float    vx, vy, vz;
  float    yaw_sp;
  float    x_sp, y_sp, z_sp;
  float    pid[17];
  int16_t  trim_t, trim_r, trim_p, trim_y;
  uint8_t  armed;
  uint8_t  msg_type;             // 0=state, 2=pid_gains, 3=trim
  uint32_t seq;
} StatePacket;

typedef struct __attribute__((packed)) {
  int16_t  pitch_centirad;
  int16_t  roll_centirad;
  int16_t  yaw_centirad;
  uint16_t battery_mv;       // pack voltage in millivolts (from FC CRSF battery frame)
  uint8_t  battery_pct;      // 0..100; FC remaining-% if set, else voltage-mapped
  uint8_t  _pad;             // keeps the struct 4-byte aligned
  uint32_t seq;
} TelemetryPacket;

TelemetryPacket telem = {0, 0, 0, 0, 0, 0, 0};
uint32_t lastRecvTime = 0;
uint32_t lastTelemSend = 0;
uint32_t lastCRSFSend = 0;
uint32_t lastLoopTime = 0;
uint16_t channels[16];

// ---------------- PID state ----------------

bool armed  = false;   // motors energised (FC arm switch high)
bool flying = false;   // armed AND z PID is allowed to drive throttle
unsigned long timeArmed = 0;

int xTrim = 0, yTrim = 0, zTrim = 0, yawTrim = 0;

double groundEffectCoef = 28.0, groundEffectOffset = -0.035;

double xPosSetpoint = 0, xPos = 0;
double yPosSetpoint = 0, yPos = 0;
double zPosSetpoint = 0, zPos = 0;
double yawPosSetpoint = 0, yawPos = 0, yawPosOutput = 0;

double xyPosKp = 1.0,  xyPosKi = 0.0,  xyPosKd = 0.0;
double zPosKp  = 1.5,  zPosKi  = 0.0,  zPosKd  = 0.0;
double yawPosKp = 0.3, yawPosKi = 0.1, yawPosKd = 0.05;

double xVelSetpoint = 0, xVel = 0, xVelOutput = 0;
double yVelSetpoint = 0, yVel = 0, yVelOutput = 0;
double zVelSetpoint = 0, zVel = 0, zVelOutput = 0;

double xyVelKp = 0.2, xyVelKi = 0.03, xyVelKd = 0.05;
double zVelKp  = 0.3, zVelKi  = 0.1,  zVelKd  = 0.05;

PID xPosPID(&xPos, &xVelSetpoint, &xPosSetpoint, xyPosKp, xyPosKi, xyPosKd, DIRECT);
PID yPosPID(&yPos, &yVelSetpoint, &yPosSetpoint, xyPosKp, xyPosKi, xyPosKd, DIRECT);
PID zPosPID(&zPos, &zVelSetpoint, &zPosSetpoint, zPosKp,  zPosKi,  zPosKd,  DIRECT);
PID yawPosPID(&yawPos, &yawPosOutput, &yawPosSetpoint, yawPosKp, yawPosKi, yawPosKd, DIRECT);

PID xVelPID(&xVel, &xVelOutput, &xVelSetpoint, xyVelKp, xyVelKi, xyVelKd, DIRECT);
PID yVelPID(&yVel, &yVelOutput, &yVelSetpoint, xyVelKp, xyVelKi, xyVelKd, DIRECT);
PID zVelPID(&zVel, &zVelOutput, &zVelSetpoint, zVelKp,  zVelKi,  zVelKd,  DIRECT);

// Linear voltage -> percent map between BATTERY_MIN_MV and BATTERY_MAX_MV.
// Used when the FC's BATTERY_SENSOR frame doesn't carry a remaining-% value
// (Betaflight sends 0 there unless a pack capacity is configured).
uint8_t mvToPct(uint32_t mv) {
  int32_t span = (int32_t)BATTERY_MAX_MV - (int32_t)BATTERY_MIN_MV;
  if (span <= 0) return 0;
  int32_t pct = ((int32_t)mv - (int32_t)BATTERY_MIN_MV) * 100 / span;
  if (pct < 0)   pct = 0;
  if (pct > 100) pct = 100;
  return (uint8_t)pct;
}

// Forces an integrator reset by walking the output limits across the current value.
// This is the same trick the original drone-side firmware used at disarm.
void resetPid(PID &pid, double mn, double mx) {
  pid.SetOutputLimits(0.0, 1.0);
  pid.SetOutputLimits(-1.0, 0.0);
  pid.SetOutputLimits(mn, mx);
}

// ---------------- CRSF ----------------

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

// Maps a 1000..2000 µs RC range into CRSF's 172..1811 channel range.
// Kept for the safe-channels path (which still thinks in µs).
uint16_t usToCRSF(uint16_t us) {
  us = constrain(us, 1000, 2000);
  return map(us, 1000, 2000, 172, 1811);
}

// PWM values from the PID stack are already in CRSF range (~172..1811 around 992).
// Just clamp and forward -- no µs round-trip.
uint16_t pwmToCRSF(int pwm) {
  if (pwm < 172) pwm = 172;
  if (pwm > 1811) pwm = 1811;
  return (uint16_t)pwm;
}

void setSafeChannels() {
  for (int i = 0; i < 16; i++) channels[i] = 992;
  channels[0] = usToCRSF(1500);
  channels[1] = usToCRSF(1500);
  channels[2] = usToCRSF(1000);
  channels[3] = usToCRSF(1500);
  channels[4] = usToCRSF(1000);
}

void sendCRSF() {
  uint8_t packet[26];
  packet[0] = 0xC8;
  packet[1] = 24;
  packet[2] = 0x16;

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

// ---------------- CRSF telemetry parser ----------------
// Frame: [addr][len][type][payload...][crc]
//   len = type + payload + crc count = payload_size + 2
//   crc8 (poly 0xD5) computed over type + payload (len - 1 bytes from buf[2]).
// Address may be 0xC8 (FC), 0xEA (handset), 0xC8 (broadcast) depending on
// origin -- accept any common value to stay forgiving.

#define CRSF_FRAMETYPE_BATTERY_SENSOR 0x08
#define CRSF_FRAMETYPE_ATTITUDE       0x1E

enum CrsfParseState { CRSF_WAIT_SYNC, CRSF_READ_LEN, CRSF_READ_DATA };
static CrsfParseState crsfState = CRSF_WAIT_SYNC;
static uint8_t crsfBuf[64];
static uint8_t crsfLen = 0;
static uint8_t crsfIdx = 0;

static bool isCrsfAddr(uint8_t b) {
  return (b == 0xC8 || b == 0xEA || b == 0xEC || b == 0xEE);
}

void parseCRSFByte(uint8_t b) {
  switch (crsfState) {
    case CRSF_WAIT_SYNC:
      if (isCrsfAddr(b)) {
        crsfBuf[0] = b;
        crsfState = CRSF_READ_LEN;
      }
      break;

    case CRSF_READ_LEN:
      if (b >= 2 && b <= 62) {
        crsfBuf[1] = b;
        crsfLen = b;
        crsfIdx = 0;
        crsfState = CRSF_READ_DATA;
      } else {
        crsfState = CRSF_WAIT_SYNC;
      }
      break;

    case CRSF_READ_DATA:
      crsfBuf[2 + crsfIdx++] = b;
      if (crsfIdx >= crsfLen) {
        uint8_t type    = crsfBuf[2];
        uint8_t recvCrc = crsfBuf[1 + crsfLen];
        uint8_t calcCrc = crc8(&crsfBuf[2], crsfLen - 1);
        if (recvCrc == calcCrc && type == CRSF_FRAMETYPE_ATTITUDE && crsfLen == 8) {
          // payload at crsfBuf[3..8]: pitch, roll, yaw  (each int16 BE, 1/10000 rad)
          int16_t pitch_cr = ((int16_t)crsfBuf[3] << 8) | crsfBuf[4];
          int16_t roll_cr  = ((int16_t)crsfBuf[5] << 8) | crsfBuf[6];
          int16_t yaw_cr   = ((int16_t)crsfBuf[7] << 8) | crsfBuf[8];
          telem.pitch_centirad = pitch_cr;
          telem.roll_centirad  = roll_cr;
          telem.yaw_centirad   = yaw_cr;
          yawPos = (double)yaw_cr / 10000.0;
        } else if (recvCrc == calcCrc &&
                   type == CRSF_FRAMETYPE_BATTERY_SENSOR && crsfLen == 10) {
          // payload at crsfBuf[3..10]:
          //   [3][4] voltage  (uint16 BE, 0.1 V units)
          //   [5][6] current  (uint16 BE, 0.1 A units)
          //   [7][8][9] fuel  (uint24 BE, mAh drawn)
          //   [10]   remaining percent (uint8; 0 unless capacity set in BF)
          uint16_t volt_dV = ((uint16_t)crsfBuf[3] << 8) | crsfBuf[4];
          uint8_t  fc_pct  = crsfBuf[10];
          uint32_t mv = (uint32_t)volt_dV * 100;
          if (mv > 65535) mv = 65535;
          telem.battery_mv  = (uint16_t)mv;
          telem.battery_pct = (fc_pct > 0 && fc_pct <= 100)
                                ? fc_pct
                                : mvToPct(mv);
        }
        crsfState = CRSF_WAIT_SYNC;
      }
      break;
  }
}

// ---------------- ESP-NOW ----------------

void OnDataRecv(const esp_now_recv_info *info, const uint8_t *incomingData, int len) {
  if (len != sizeof(StatePacket)) return;
  StatePacket pkt;
  memcpy(&pkt, incomingData, sizeof(pkt));
  lastRecvTime = millis();

  if (pkt.msg_type == 0) {
    xPos = pkt.x;     yPos = pkt.y;     zPos = pkt.z;
    xVel = pkt.vx;    yVel = pkt.vy;    zVel = pkt.vz;
    yawPosSetpoint = pkt.yaw_sp;
    xPosSetpoint = pkt.x_sp;
    yPosSetpoint = pkt.y_sp;
    zPosSetpoint = pkt.z_sp;

    // pkt.armed: 0=disarmed, 1=motors armed but parked, 2=armed & flying.
    bool newArmed  = (pkt.armed != 0);
    bool newFlying = (pkt.armed == 2);
    if (newArmed && !armed) {
      timeArmed = millis();
    }
    armed  = newArmed;
    flying = newFlying;

  } else if (pkt.msg_type == 2) {
    xPosPID.SetTunings(pkt.pid[0], pkt.pid[1], pkt.pid[2]);
    yPosPID.SetTunings(pkt.pid[0], pkt.pid[1], pkt.pid[2]);
    zPosPID.SetTunings(pkt.pid[3], pkt.pid[4], pkt.pid[5]);
    yawPosPID.SetTunings(pkt.pid[6], pkt.pid[7], pkt.pid[8]);
    xVelPID.SetTunings(pkt.pid[9], pkt.pid[10], pkt.pid[11]);
    yVelPID.SetTunings(pkt.pid[9], pkt.pid[10], pkt.pid[11]);
    zVelPID.SetTunings(pkt.pid[12], pkt.pid[13], pkt.pid[14]);
    groundEffectCoef   = pkt.pid[15];
    groundEffectOffset = pkt.pid[16];

  } else if (pkt.msg_type == 3) {
    xTrim   = pkt.trim_r;
    yTrim   = pkt.trim_p;
    zTrim   = pkt.trim_t;
    yawTrim = pkt.trim_y;
  }
}

// ---------------- setup / loop ----------------

void setup() {
  Serial.begin(115200);
  delay(500);

  WiFi.mode(WIFI_STA);
  WiFi.setChannel(ESPNOW_CHANNEL);

  uint8_t newMAC[] = { 0x10, 0x00, 0x3B, 0xB1, 0x5B, 0x8C };
  // NOTE: must be a UNICAST MAC -- bit 0 of the first byte must be 0 (even
  // first octet), or esp_wifi_set_mac rejects it and the drone keeps its
  // factory MAC, silently never receiving any ESP-NOW packets aimed at it.
  esp_err_t macErr = esp_wifi_set_mac(WIFI_IF_STA, newMAC);
  if (macErr != ESP_OK) {
    Serial.printf("FATAL: esp_wifi_set_mac failed (err %d) -- MAC must be unicast!\n",
                  (int)macErr);
  }

  uint8_t staMac[6];
  esp_wifi_get_mac(WIFI_IF_STA, staMac);
  Serial.printf("[receiver] STA MAC: %02X:%02X:%02X:%02X:%02X:%02X\n",
                staMac[0], staMac[1], staMac[2],
                staMac[3], staMac[4], staMac[5]);

  setSafeChannels();
  CRSFSerial.begin(420000, SERIAL_8N1, CRSF_RX_PIN, CRSF_TX_PIN);

  if (esp_now_init() != ESP_OK) {
    Serial.println("ESP-NOW init failed");
    return;
  }

  esp_now_register_recv_cb(OnDataRecv);

  // Add the sender ESP32 as an outbound peer so we can ESP-NOW telemetry to it.
  esp_now_peer_info_t senderPeer = {};
  memcpy(senderPeer.peer_addr, senderAddress, 6);
  senderPeer.channel = ESPNOW_CHANNEL;
  senderPeer.encrypt = false;
  if (esp_now_add_peer(&senderPeer) != ESP_OK) {
    Serial.println("Failed to add sender peer (check senderAddress[])");
  }

  // PID configuration -- sample time 0 means "trust the caller's cadence".
  xPosPID.SetMode(AUTOMATIC);    xPosPID.SetSampleTime(0);
  yPosPID.SetMode(AUTOMATIC);    yPosPID.SetSampleTime(0);
  zPosPID.SetMode(AUTOMATIC);    zPosPID.SetSampleTime(0);
  yawPosPID.SetMode(AUTOMATIC);  yawPosPID.SetSampleTime(0);
  xVelPID.SetMode(AUTOMATIC);    xVelPID.SetSampleTime(0);
  yVelPID.SetMode(AUTOMATIC);    yVelPID.SetSampleTime(0);
  zVelPID.SetMode(AUTOMATIC);    zVelPID.SetSampleTime(0);

  xPosPID.SetOutputLimits(-MAX_VEL, MAX_VEL);
  yPosPID.SetOutputLimits(-MAX_VEL, MAX_VEL);
  zPosPID.SetOutputLimits(-MAX_VEL, MAX_VEL);
  yawPosPID.SetOutputLimits(-1, 1);
  xVelPID.SetOutputLimits(-1, 1);
  yVelPID.SetOutputLimits(-1, 1);
  zVelPID.SetOutputLimits(-1, 1);

  lastRecvTime  = millis();
  lastTelemSend = millis();
  lastCRSFSend  = millis();
  lastLoopTime  = micros();

  Serial.println("Receiver ready: ESP-NOW state -> PID -> CRSF; CRSF telem -> ESP-NOW");
}

void loop() {
  // 1) Drain CRSF UART for telemetry frames from FC (cheap, every iteration)
  while (CRSFSerial.available()) {
    parseCRSFByte((uint8_t)CRSFSerial.read());
  }

  // 2) Failsafe if PC comm died -- disarm and force safe sticks.
  bool failsafe = (millis() - lastRecvTime > FAILSAFE_MS);
  if (failsafe) {
    armed  = false;
    flying = false;
  }

  // 3) PID loop runs every loop iteration (~500 Hz pacing below).
  // Park ALL integrators whenever we're not actively flying so that the
  // transition into TAKEOFF starts from a clean slate.
  if (!flying) {
    resetPid(xPosPID,   -MAX_VEL, MAX_VEL);
    resetPid(yPosPID,   -MAX_VEL, MAX_VEL);
    resetPid(zPosPID,   -MAX_VEL, MAX_VEL);
    resetPid(yawPosPID, -1, 1);
    resetPid(xVelPID,   -1, 1);
    resetPid(yVelPID,   -1, 1);
    resetPid(zVelPID,   -1, 1);
  }

  xPosPID.Compute();
  yPosPID.Compute();
  zPosPID.Compute();
  if (ENABLE_YAW_HOLD) {
    yawPosPID.Compute();
  } else {
    resetPid(yawPosPID, -1, 1);
    yawPosOutput = 0.0;
  }
  xVelPID.Compute();
  yVelPID.Compute();
  zVelPID.Compute();

  // PWM in raw CRSF units centred on 992 (=midstick), span ±811 (=full deflection).
  int xPWM   = 992 + (int)(xVelOutput * 811)            + xTrim;
  int yPWM   = 992 + (int)(yVelOutput * 811)            + yTrim;
  int zPWM   = 992 + (int)(Z_GAIN * zVelOutput * 811)   + zTrim;
  int yawPWM = 992 + (int)(yawPosOutput * 811)          + yawTrim;

#if ENABLE_GROUND_EFFECT
  // Ground effect attenuation on throttle near floor. NOTE: with the default
  // coefficient of 28, this formula goes negative (and clamps to 0) for
  // zPos < ~0.025 m -- it will zero out throttle while the drone is on the
  // ground and prevent takeoff. Only enable this once the drone is reliably
  // airborne and you actually want low-altitude bob compensation.
  double denom = 4.0 * (zPos - groundEffectOffset);
  double multiplier = 1.0;
  if (fabs(denom) > 1e-6) {
    double r = (2.0 * ROTOR_RADIUS) / denom;
    multiplier = 1.0 - groundEffectCoef * r * r;
  }
  if (multiplier < 0.0) multiplier = 0.0;
  zPWM = (int)(zPWM * multiplier);
#endif

  // Throttle gate: hard-park throttle at minimum unless we're in the FLYING
  // sub-state (TAKEOFF / HOVER / LANDING on the PC side). This prevents the
  // drone from lifting on arm-only commands. The 100 ms arm-delay is still
  // honoured even after entering FLYING so motors have time to spin up.
  if (!armed || !flying || (millis() - timeArmed) <= ARM_DELAY_MS) {
    zPWM = 172;
  }

  if (failsafe) {
    setSafeChannels();
  } else {
    for (int i = 0; i < 16; i++) channels[i] = 992;
    channels[0] = pwmToCRSF(-yPWM + 1984);  // roll  (axis flipped vs y body)
    channels[1] = pwmToCRSF(xPWM);          // pitch
    channels[2] = pwmToCRSF(zPWM);          // throttle
    channels[3] = pwmToCRSF(yawPWM);        // yaw
    channels[4] = armed ? usToCRSF(2000) : usToCRSF(1000);
  }

  // 4) Send CRSF channels packed to FC at ~250 Hz.
  if (millis() - lastCRSFSend >= 4) {
    lastCRSFSend = millis();
    sendCRSF();
  }

  // 5) Periodically forward latest attitude + battery to laptop at ~50 Hz.
  //    Battery fields are refreshed in parseCRSFByte() whenever the FC sends
  //    a BATTERY_SENSOR telemetry frame (typically a few Hz).
  if (millis() - lastTelemSend >= TELEMETRY_PERIOD_MS) {
    lastTelemSend = millis();
    telem.seq++;
    esp_now_send(senderAddress, (uint8_t *)&telem, sizeof(telem));
  }

  // 6) Pace the main loop at ~500 Hz. 2 ms is the right granularity on C3
  // and matches the spec's "delay(2)" hint without busy-spinning.
  uint32_t now = micros();
  uint32_t elapsed = now - lastLoopTime;
  if (elapsed < 2000) {
    delayMicroseconds(2000 - elapsed);
  }
  lastLoopTime = micros();
}
