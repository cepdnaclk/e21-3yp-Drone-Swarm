#include <esp_now.h>
#include <esp_wifi.h>
#include <WiFi.h>
#include <ArduinoJson.h>
#include <PID_v1.h>
#include <stdint.h>
#include <EEPROM.h>
#include "sbus.h"

#define batVoltagePin 34
#define MAX_VEL 100
#define ROTOR_RADIUS 0.0225
#define Z_GAIN 0.7

#define DRONE_INDEX 1
#define EEPROM_SIZE 4

unsigned long lastPing;

// UPDATED: Changed pins to 21 (TX) and 20 (RX) for ESP32-C3 Super Mini
bfs::SbusTx sbus_tx(&Serial1, 21, 20, true, false); 
bfs::SbusData data;

bool armed = false;
unsigned long timeArmed = 0;

StaticJsonDocument<1024> json;
int xTrim = 0, yTrim = 0, zTrim = 0, yawTrim = 0;

double groundEffectCoef = 28, groundEffectOffset = -0.035;

// PID Variables
double xPosSetpoint = 0, xPos = 0;
double yPosSetpoint = 0, yPos = 0;
double zPosSetpoint = 0, zPos = 0;
double yawPosSetpoint = 0, yawPos, yawPosOutput;

double xyPosKp = 1, xyPosKi = 0, xyPosKd = 0;
double zPosKp = 1.5, zPosKi = 0, zPosKd = 0;
double yawPosKp = 0.3, yawPosKi = 0.1, yawPosKd = 0.05;

double xVelSetpoint, xVel, xVelOutput;
double yVelSetpoint, yVel, yVelOutput;
double zVelSetpoint, zVel, zVelOutput;

double xyVelKp = 0.2, xyVelKi = 0.03, xyVelKd = 0.05;
double zVelKp = 0.3, zVelKi = 0.1, zVelKd = 0.05;

PID xPosPID(&xPos, &xVelSetpoint, &xPosSetpoint, xyPosKp, xyPosKi, xyPosKd, DIRECT);
PID yPosPID(&yPos, &yVelSetpoint, &yPosSetpoint, xyPosKp, xyPosKi, xyPosKd, DIRECT);
PID zPosPID(&zPos, &zVelSetpoint, &zPosSetpoint, zPosKp, zPosKi, zPosKd, DIRECT);
PID yawPosPID(&yawPos, &yawPosOutput, &yawPosSetpoint, yawPosKp, yawPosKi, yawPosKd, DIRECT);

PID xVelPID(&xVel, &xVelOutput, &xVelSetpoint, xyVelKp, xyVelKi, xyVelKd, DIRECT);
PID yVelPID(&yVel, &yVelOutput, &yVelSetpoint, xyVelKp, xyVelKi, xyVelKd, DIRECT);
PID zVelPID(&zVel, &zVelOutput, &zVelSetpoint, zVelKp, zVelKi, zVelKd, DIRECT);

unsigned long lastLoopTime = micros();
unsigned long lastSbusSend = micros();
float loopFrequency = 2000.0;
float sbusFrequency = 50.0;

#if DRONE_INDEX == 0
  uint8_t newMACAddress[] = { 0xC0, 0x4E, 0x30, 0x4B, 0x61, 0x3A };
#elif DRONE_INDEX == 1
  uint8_t newMACAddress[] = { 0xC0, 0x4E, 0x30, 0x4B, 0x80, 0x3B };
#endif

void OnDataRecv(const uint8_t *mac, const uint8_t *incomingData, int len) {
  DeserializationError err = deserializeJson(json, (char *)incomingData);
  if (err) return;

  if (json.containsKey("pos") && json.containsKey("vel")) {
    xPos = json["pos"][0]; yPos = json["pos"][1]; zPos = json["pos"][2]; yawPos = json["pos"][3];
    xVel = json["vel"][0]; yVel = json["vel"][1]; zVel = json["vel"][2];
  } else if (json.containsKey("armed")) {
    if (json["armed"] != armed && json["armed"]) timeArmed = millis();
    armed = json["armed"];
  } else if (json.containsKey("setpoint")) {
    xPosSetpoint = json["setpoint"][0]; yPosSetpoint = json["setpoint"][1]; zPosSetpoint = json["setpoint"][2];
  }
  lastPing = micros();
}

void resetPid(PID &pid, double min, double max) {
  pid.SetOutputLimits(min, max);
}

void setup() {
  Serial.begin(115200);
  sbus_tx.Begin();
  
  data.failsafe = false;
  data.ch17 = true;
  data.ch18 = true;
  
  // ESP-NOW Setup
  WiFi.mode(WIFI_STA);
  esp_wifi_set_mac(WIFI_IF_STA, &newMACAddress[0]);
  if (esp_now_init() != ESP_OK) return;
  esp_now_register_recv_cb(OnDataRecv);

  // PID Setup
  xPosPID.SetMode(AUTOMATIC); yPosPID.SetMode(AUTOMATIC); zPosPID.SetMode(AUTOMATIC);
  xVelPID.SetMode(AUTOMATIC); yVelPID.SetMode(AUTOMATIC); zVelPID.SetMode(AUTOMATIC);
  
  xPosPID.SetOutputLimits(-MAX_VEL, MAX_VEL);
  xVelPID.SetOutputLimits(-1, 1); // Normalize for SBUS
  
  lastPing = micros();
}

void loop() {
  if (micros() - lastLoopTime < 1e6 / loopFrequency) return;
  lastLoopTime = micros();

  // Failsafe: Disarm if no data for 2 seconds
  if (micros() - lastPing > 2e6) armed = false; [cite: 36, 37]

  if (armed) {
    data.ch[4] = 1800; // Armed signal for Betaflight [cite: 37]
  } else {
    data.ch[4] = 172;  // Disarmed signal [cite: 37]
    resetPid(xVelPID, -1, 1);
  }

  // Compute PID
  xPosPID.Compute(); yPosPID.Compute(); zPosPID.Compute();
  xVelPID.Compute(); yVelPID.Compute(); zVelPID.Compute();

  // Map PID output to SBUS range (standard ~1000-2000ms)
  int xPWM = 992 + (xVelOutput * 811) + xTrim; [cite: 40]
  int yPWM = 992 + (yVelOutput * 811) + yTrim; [cite: 40]
  int zPWM = 992 + (Z_GAIN * zVelOutput * 811) + zTrim; [cite: 41]
  int yawPWM = 992 + (yawPosOutput * 811) + yawTrim; [cite: 42]

  data.ch[0] = -yPWM; // Roll [cite: 43]
  data.ch[1] = xPWM;  // Pitch [cite: 44]
  data.ch[2] = (armed && millis() - timeArmed > 100) ? zPWM : 172; // Throttle [cite: 43, 44]
  data.ch[3] = yawPWM; // Yaw [cite: 44]

  if (micros() - lastSbusSend > 1e6 / sbusFrequency) {
    lastSbusSend = micros();
    sbus_tx.data(data); [cite: 48]
    sbus_tx.Write(); [cite: 48]
  }
}