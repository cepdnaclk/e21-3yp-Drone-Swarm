# Port plan: Low-Cost-Mocap → single drone + `live_3d_tracker_world.py`

This plan replaces the existing pseyepy / SFM / multi-drone pipeline with the
calibrated 4-USB-camera tracker and a **PC-side single-drone control loop**.
The drone uses your existing, working ESP-NOW → CRSF firmware as a dumb
stick-passthrough; only a small heading-telemetry backchannel is added.

Decisions locked in:
- **Frontend:** keep React, trim to one drone, add Takeoff / Land buttons.
- **Heading source:** CRSF telemetry from F4DC → ESP32-C3 → ESP-NOW → sender → USB serial.
- **Takeoff state machine + position/velocity PID:** **on the PC**
  (forced by the existing stick-passthrough firmware design — see §0.1).
- **Wire-format PC ↔ sender ESP32:** keep your existing CSV
  `throttle,roll,pitch,yaw,armed\n`. PC adds a one-line parser for
  inbound `H<yaw>\n`.
- **Wire-format sender ↔ drone over ESP-NOW:** keep your existing binary
  `ControlPacket` struct unchanged. Heading goes back as a separate
  small struct (see §3).
- **Betaflight mode:** **Angle** (sticks = roll/pitch angle setpoint), so a
  60 Hz outer loop on the PC is sufficient.

---

## 0.1 Why control logic lives on the PC

Your current firmware (`drone_transmitter_serial_espnow.ino` and
`drone_receiver_crsf_espnow.ino`) is a **dumb stick passthrough**:

```
Python ──CSV(T,R,P,Y,A)──► sender ESP32 ──ControlPacket──► drone ESP32 ──CRSF──► FC
                                                                  │
                                                                  └── 500 ms failsafe → safe sticks
```

There is no PID, no state machine, no JSON, no setpoint concept on the drone
side. That's a cleaner architecture than the original Low-Cost-Mocap
firmware and we should preserve it. The consequence is that the PC owns:

1. Position PID (x, y, z) → velocity setpoint
2. Velocity PID (vx, vy) → roll/pitch tilt setpoint (Betaflight Angle mode)
   and (vz) → throttle adjustment around hover throttle
3. Yaw PID (heading_setpoint − heading) → yaw stick
4. Takeoff state machine: IDLE → ARMING → TAKEOFF (ramp z setpoint
   0 → 0.20 m over ~2 s) → HOVER → LANDING
5. Conversion to `T,R,P,Y,A` µs values and CSV write to serial

Failsafe is still hardware-enforced by the drone ESP32 (500 ms timeout →
throttle to 1000, disarm via AUX low).

---

## 0.2 Data flow (revised)

```
4 USB cams ──► tracker.py (Threaded capture + bright-spot + triangulate + world tf)
                    │
                    ▼ (x,y,z) in metres, world frame, ~30 Hz
            KalmanFilter.py (single object, 9-state CV/CA, extrapolates to ~60 Hz)
                    │
                    ▼ filtered pos/vel
                Controller.py (state machine + nested PID)
                    │
                    ▼ stick µs (T,R,P,Y,A)
                index.py serial writer ──► sender ESP32 ──ControlPacket──► drone ESP32 ──CRSF──► FC
                    ▲                                                            ▲
                    │ "H<yaw>\n"                                                 │ CRSF telemetry
                    │                                                            │ ATTITUDE frame (0x1E)
              serial reader thread ◄── sender ESP32 ◄── ESP-NOW {h:yaw} ◄────────┘
```

---

## 1. Python backend (`computer_code/api/`)

### NEW `tracker.py`
Wraps the logic in `live_3d_tracker_world.py`:
```python
class Tracker:
    def __init__(self, calibration_dir: str)
    def start(self); def stop(self)
    def latest(self) -> tuple[np.ndarray | None, np.ndarray]
        # (world_xyz_m_or_None, grid_jpeg_bgr)
    def camera_poses_in_world(self) -> list[dict]
```
Internals lifted verbatim from your tracker: `ThreadedCamera`,
`detect_bright_spot`, `undistort_point`, `triangulate_two_cameras`,
`triangulate_from_detected_points`, `cam1_to_world`, `load_intrinsics`,
`load_extrinsics`, `load_world_transform`,
`build_projection_from_camera_pose`.

A background thread runs the per-tick: read 4 cameras → detect → undistort →
triangulate pairwise → average → world transform → publish.

### NEW `controller.py`
Owns the state machine + PID. Pure functions over numpy + a small class
holding integrator state. Public API:
```python
class Controller:
    def __init__(self, params: ControlParams): ...
    def step(self, pos, vel, heading, dt) -> tuple[int,int,int,int,int]
        # returns (throttle_us, roll_us, pitch_us, yaw_us, armed)
    def cmd_arm(self, armed: bool): ...
    def cmd_takeoff(self, target_z: float = 0.20): ...
    def cmd_land(self): ...
    def cmd_setpoint(self, x, y, z): ...
    def set_pid(self, pid_dict): ...
    def set_trim(self, t,r,p,y): ...
    def state(self) -> str  # "IDLE" | "ARMING" | "TAKEOFF" | "HOVER" | "LANDING"
```
State machine transitions:
- **IDLE**: `armed=0`, throttle=1000, sticks centered.
- **ARMING** (entered on `cmd_arm(True)`): `armed=1`, throttle held at idle
  (≈1050), sticks centered for 300 ms, then auto-transition to a
  *waiting-for-takeoff-cmd* sub-state where it holds idle throttle.
- **TAKEOFF** (entered on `cmd_takeoff(z)`): linearly ramp internal
  `z_setpoint` from current `pos.z` to `target_z` over 2.0 s. PID active.
  `xy_setpoint` latched to current `xy` at entry.
- **HOVER**: PID active on latched `xy_setpoint` and `z_setpoint = target_z`.
  Heading setpoint = heading at entry, or whatever PC most recently set.
- **LANDING** (entered on `cmd_land()`): ramp `z_setpoint` to 0 over 1.5 s,
  then `armed=0` and back to IDLE.
- **EMERGENCY**: PC `cmd_arm(False)`, comm dropout from tracker > 500 ms,
  z error > 0.5 m for > 500 ms → IDLE.

PID math:
- Outer position loop (60 Hz): `vel_sp = Kp_pos*(pos_sp - pos) + ...`
  clamped to ±MAX_VEL.
- Inner velocity loop (60 Hz): for xy, `tilt_sp = Kp_vel*(vel_sp - vel) + ...`
  clamped to ±MAX_TILT degrees. For z,
  `throttle = HOVER_THROTTLE + Kp_velz*(vel_sp_z - vel_z) + ...`.
- Stick conversion (Betaflight Angle mode):
  - `roll_us  = 1500 + tilt_sp_roll  / MAX_TILT_DEG * 500`
  - `pitch_us = 1500 + tilt_sp_pitch / MAX_TILT_DEG * 500`
  - `yaw_us   = 1500 + yaw_pid_out  * 500`
  - `throttle_us = clamp(throttle, 1000, 2000)`
- All ints, clamped, with deadband around 1500 ±2 to avoid jitter.

Seed values (tune later):
- `HOVER_THROTTLE = 1480` (highly drone-dependent; set during bench test)
- `MAX_TILT_DEG = 15`
- Position PID: `Kp_xy=2.5, Ki_xy=0.0, Kd_xy=0.4`, `Kp_z=3.5, Ki_z=0.5, Kd_z=0.5`
- Velocity PID: `Kp_vxy=8, Ki_vxy=1.0, Kd_vxy=0.3` (output in degrees of tilt),
  `Kp_vz=120, Ki_vz=40, Kd_vz=20` (output in µs)
- Yaw PID: `Kp_yaw=80, Ki_yaw=10, Kd_yaw=5` (output in µs centered on 1500)

### REWRITE `KalmanFilter.py`
Strip multi-object. 9-state CV/CA stays. Public API:
```python
class KalmanFilter:
    def __init__(self): ...
    def update(self, world_xyz: np.ndarray) -> tuple[np.ndarray, np.ndarray]
        # returns (pos, vel)
    def predict_only(self, dt) -> tuple[np.ndarray, np.ndarray]
        # used when tracker has no new point this tick
    def reset(self): ...
```
Heading filtering moves out — it lives next to the serial reader in
`index.py` (`LowPassFilter(dims=1)`).

### REWRITE `helpers.py`
Strip to ≤80 lines. Just the `Cameras` singleton shim that wraps `Tracker`
and exposes `get_grid_jpeg()` / `latest_state()` to `index.py`.
Delete `bundle_adjustment`, `find_point_correspondance_and_object_points`,
`locate_objects`, `triangulate_points`, `make_square`, `_find_dot`,
`drawlines`, `numpy_fillna`.

### REWRITE `index.py`
- `num_objects = 1`. Serial port from `SENDER_SERIAL_PORT` env (default `COM5`).
  **Baud `115200`** to match your existing transmitter, not `1000000`.
- Three threads:
  1. **Tracker thread** (in `Tracker`) — fills latest world point @ ~30 Hz.
  2. **Heading reader thread** — `ser.readline()`, on `H...` parse, low-pass,
     store in `latest_heading` (lock).
  3. **Control thread** @ 60 Hz:
     - `pos_raw = tracker.latest_xyz()`. If present, `pos, vel = kf.update(pos_raw)`.
       Else `pos, vel = kf.predict_only(dt)`.
     - `heading = latest_heading`.
     - `(T,R,P,Y,A) = controller.step(pos, vel, heading, dt)`.
     - `ser.write(f"{T},{R},{P},{Y},{A}\n".encode())`.
- SocketIO events (forced single drone):
  - **`arm-drone`** → `controller.cmd_arm(bool)`
  - **`takeoff`** → `controller.cmd_takeoff(data.get("z", 0.20))`
  - **`land`** → `controller.cmd_land()`
  - **`set-drone-pid`** → `controller.set_pid(dict)`
  - **`set-drone-setpoint`** → `controller.cmd_setpoint(x,y,z)`
  - **`set-drone-trim`** → `controller.set_trim(...)`
- SocketIO emits:
  - On connect: `camera-pose` (precomputed from calibration),
    `to-world-coords-matrix`.
  - At 30 Hz: `object-points` with current `pos`, `vel`, `heading`,
    `controller.state()`, `sticks`.
- Delete: `acquire-floor`, `set-origin`, `capture-points`,
  `calculate-camera-pose`, `determine-scale`, `trajectory-planning`.

### File layout
```
computer_code/api/
├── index.py             [rewrite]
├── tracker.py           [new]
├── controller.py        [new — PID + state machine]
├── helpers.py           [strip to ~80 lines]
├── KalmanFilter.py      [rewrite]
├── LowPassFilter.py     [unchanged]
├── Singleton.py         [unchanged]
└── calibration/         [new dir]
    ├── camera_{1..4}_params_new.json
    ├── cam{2..4}_relative_to_cam1.npz
    └── cam1_to_world_transform.npz
```
Delete `camera-params.json`, `camera-params copy.json`, `test.py`.

---

## 2. Drone firmware: `drone_receiver_crsf_espnow.ino` (minimal diff)

**Do NOT change** the existing pinout, `ControlPacket`, `OnDataRecv`,
`sendCRSF`, `crc8`, `usToCRSF`, `setSafeChannels`, or the failsafe logic.

**Add**:

1. A second peer (the sender ESP32 MAC) and ESP-NOW init outbound:
   ```cpp
   uint8_t senderAddress[] = { /* sender ESP32 MAC */ };
   esp_now_peer_info_t senderPeer = {};
   memcpy(senderPeer.peer_addr, senderAddress, 6);
   senderPeer.channel = ESPNOW_CHANNEL;
   esp_now_add_peer(&senderPeer);
   ```

2. A small outbound struct:
   ```cpp
   typedef struct __attribute__((packed)) {
     int16_t  yaw_centirad;   // yaw * 10000 (CRSF ATTITUDE units)
     int16_t  pitch_centirad;
     int16_t  roll_centirad;
     uint32_t seq;
   } TelemetryPacket;
   ```

3. A CRSF telemetry parser reading from `CRSFSerial` (your `CRSF_RX_PIN=20`
   line is already wired to the FC's TX — no extra wiring needed). State
   machine on incoming bytes, sync on address `0xC8`, length, type, payload,
   CRC8 (same poly you already have). On `type == 0x1E` (ATTITUDE):
   - payload is 6 bytes big-endian: `int16_t pitch, roll, yaw` in 1/10000 rad.
   - Copy into `TelemetryPacket`, increment `seq`.

4. In `loop()`, every 20 ms (50 Hz), send `TelemetryPacket` via
   `esp_now_send(senderAddress, ...)`.

5. Flip `DEBUG_RX_PRINT` stays at 0 in flight.

That's the entire firmware diff. Net add: ~80 lines.

---

## 3. Sender firmware: `drone_transmitter_serial_espnow.ino` (minimal diff)

**Do NOT change** the CSV parser, `ControlPacket`, send loop, or send period.

**Add**:

1. `esp_now_register_recv_cb(OnDataRecv)`:
   ```cpp
   void OnDataRecv(const esp_now_recv_info *info, const uint8_t *data, int len) {
     if (len != sizeof(TelemetryPacket)) return;
     TelemetryPacket t;
     memcpy(&t, data, sizeof(t));
     float yaw_rad = t.yaw_centirad / 10000.0f;
     Serial.print("H");
     Serial.println(yaw_rad, 4);
   }
   ```
   (The struct definition is duplicated between the two sketches — that's
   fine and standard for ESP-NOW.)

2. Nothing else changes. The Python side must tolerate the existing
   "Transmitter ready: ..." banner already printed in `setup()`.

Net add: ~20 lines.

---

## 4. React frontend (`computer_code/src/`)

### `App.tsx`
- `NUM_DRONES = 1`, drop `currentDroneIndex`.
- Initial `cameraPoses` and `toWorldCoordsMatrix` no longer hardcoded; they
  arrive from backend on connect.
- Remove UI:
  - "Start capturing points" / "Calculate camera pose"
  - "Acquire floor" / "Set origin"
  - Per-drone armed array → single boolean
- Add UI:
  - **Arm / Disarm** toggle (already exists, just simplify)
  - **Takeoff** button → `socket.emit("takeoff", {z: 0.20})`
  - **Land** button → `socket.emit("land", {})`
  - Live readout: `pos (m)`, `vel (m/s)`, `heading (rad)`, `state`, sticks
    `T R P Y` µs, serial heading age (s).
- PID sliders keep the same 17-element shape; payload now consumed by
  `controller.set_pid()`.

### `components/Toolbar.tsx`
- Drop the drone index selector and capture-for-pose flow.

### `components/Objects.tsx`
- Render one drone, not an array.

### Unchanged: `Points.tsx`, `CameraWireframe.tsx`, `chart.tsx`.
### Hidden behind a flag (not deleted): `TrajectoryPlanningSetpoints.tsx`.

---

## 5. Dependencies

### Python (`requirements.txt`)
```
opencv-python>=4.8
numpy
scipy
flask
flask-cors
flask-socketio
pyserial
eventlet
```
Removed: `pseyepy`, `opencv-contrib-python` (SFM), `ruckig`.

### Arduino — drone ESP32-C3
- ESP-NOW + WiFi (built-in). **No new libraries.** CRSF telemetry parser is
  inline (~50 lines), reusing your existing `crc8`.

### Arduino — sender ESP32
- ESP-NOW + WiFi (built-in). **No new libraries.**

---

## 6. Betaflight one-time config (F4DC)

- Ports tab: the UART connected to the ESP32-C3 → **Serial RX**, protocol
  **CRSF**. Telemetry column **enabled** on that UART (this is what lets
  the FC TX line carry ATTITUDE frames back to the ESP32).
- Receiver tab: Serial-based, **CRSF**.
- Modes tab: AUX1 (ch5) low = disarm, high = arm. **Angle mode** on a
  high AUX or permanently active.
- Failsafe: stage 1 = drop throttle, stage 2 = motor stop.
- Rates: low rates (e.g., RC rate 0.7, super rate 0.1) for indoor PID tuning.

---

## 7. Test / bring-up order

1. Drop calibration files into `computer_code/api/calibration/`.
2. Apply sender-side telemetry diff. Power both ESPs; with the FC powered
   and CRSF telemetry on, confirm `H<yaw>` lines appear on USB serial when
   you rotate the drone by hand.
3. Apply drone-side telemetry diff. Confirm the existing manual CSV
   control still works end-to-end (`echo 1000,1500,1500,1500,0` etc.).
4. `python api/index.py` → backend up.
5. `yarn run dev` → web UI shows 4 camera wireframes + live filtered point.
6. **Props off, drone tethered**, arm: drive PIDs by holding the LED in
   the air and dragging it around; watch sticks respond.
7. **Props on, perimeter net, low ceiling**: emit **Takeoff** with target
   0.20 m. Tune position/velocity/heading PID with the sliders.

---

## 8. Open items (defaults shown, not blockers)

- **PC serial port:** `COM5` default; override with `SENDER_SERIAL_PORT`.
- **Sender ESP32 MAC** (needed in drone firmware): you'll need to read it
  off the sender. I'll wire a `WiFi.macAddress()` printout in setup so
  you can copy it into the drone firmware.
- **`HOVER_THROTTLE`**: needs a one-time bench measurement (tether, find
  the µs value at which the drone just floats). Seed is 1480.
- **Z axis sign of world transform**: assuming +Z = up. If your
  `cam1_to_world_transform.npz` produces -Z = up, flip in `tracker.py`.
- **Tracker fps vs control fps:** webcams cap ~30 fps; Kalman extrapolates
  to 60 Hz control loop. Confirm tracker fps in bring-up.

---

## 9. Phased implementation order

1. `tracker.py` (+ verify it produces a sane stream of points outside of
   the Flask app first via a quick standalone test).
2. `KalmanFilter.py` rewrite + `helpers.py` strip.
3. `controller.py` with the state machine + PID, unit-tested with
   synthetic position inputs (no serial).
4. `index.py` wiring everything together; control thread writes to serial.
5. Sender firmware diff (heading backchannel).
6. Drone firmware diff (CRSF telemetry parser + ESP-NOW out).
7. Frontend trim + Takeoff/Land buttons + status readout.
8. Bench-test order from §7.
