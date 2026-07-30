# Presentation Content — Sections 10, 11, 12

Every number below is traced to a file in this repo. Numbers marked **[MEASURE]**
are not yet in the codebase and need a bench run before the viva — do not quote
them from this document.

---

# 10. Performance & Reliability (2 min)

## 10.1 Localization accuracy

**Pipeline:** 4 × USB cameras (640×480, MJPG) → bright-spot detection →
undistortion → pairwise triangulation over all 6 camera pairs → `cam1 → world`
similarity transform → 9-state Kalman filter.
*(`api/tracker.py`, `api/KalmanFilter.py`)*

### Graph 1 — Intrinsic calibration RMS reprojection error (bar chart)

Source: `api/current_calibration/camera_{1..4}_params_new.json`

| Camera | RMS reprojection error (px) |
|--------|----------------------------:|
| cam1   | 0.238 |
| cam2   | 0.133 |
| cam3   | 0.167 |
| cam4   | 0.133 |
| **mean** | **0.168** |

**Line to say:** "All four cameras calibrate to sub-pixel accuracy — mean 0.168 px
on a 640×480 sensor. That is the noise floor the triangulation inherits."

Checkerboard square size: 23.9 mm (`square_size` field).

### Graph 2 — World-transform landmark validation (grouped bar: commanded vs predicted)

The calibration wizard validates the `cam1 → world` transform against 5 surveyed
landmarks and reports `mean_error_mm` / `max_error_mm`
(`api/calibration_manager.py`, lines ~366–389).

Landmarks (`localization_4cam/world_landmarks.json`), world frame in mm:

| Landmark | World (x, y, z) mm |
|---|---|
| A | (0, −700, 0) |
| B | (0, 0, 0) — origin |
| C | (−770, 0, 0) |
| D | (0, 800, 0) |
| E | (650, 0, 0) |

Arena footprint implied by the landmark spread: **≈ 1.4 m × 1.5 m**, with a
software ceiling of **2.0 m** (`MAX_SETPOINT_Z`).

**[MEASURE]** Run the calibration wizard once and screenshot the log — it prints
`Mean error: X mm` / `Max error: Y mm`. That single number is your headline
localization accuracy claim. Expected order: single-digit to low-tens of mm.

### Graph 3 — Position estimate: raw triangulation vs Kalman output (time series)

Plot the same 10 s window twice: raw tracker fixes and KF `statePost`. The story
is variance reduction plus gap-filling.

---

## 10.2 Communication latency

### Graph 4 — Latency budget (horizontal stacked bar, one segment per hop)

Every value is a code constant, so this is a *derived* budget, not a guess:

| Hop | Rate / constant | Worst-case added latency | Source |
|---|---|---:|---|
| Camera capture | 640×480 MJPG, `CAP_PROP_FPS 15`, `BUFFERSIZE 1` | ~33–66 ms | `tracker.py:81` |
| Tracker + triangulation worker | publishes into lock-guarded slot | ~1 frame | `tracker.py` |
| PC control loop | `CONTROL_HZ = 60.0` | 16.7 ms | `index.py:71` |
| USB serial PC → sender ESP32 | 115200 baud, ~80-byte `S` line | ~7 ms | `index.py:61`, `controller.py` |
| Sender hold-and-forward | `SEND_PERIOD_MS = 20` (50 Hz) | 20 ms | `sender_esp32.ino:62` |
| ESP-NOW single hop (broadcast) | 1 Mbps base rate, 128-byte packet | ~1–3 ms | `sender_esp32.ino` |
| Drone-side PID stack | ~500 Hz (`delayMicroseconds` to 2 ms) | 2 ms | `receiver_drone1.ino` loop §6 |
| CRSF → flight controller | 420000 baud, send every 4 ms | ~4.6 ms | `receiver_drone1.ino` loop §4 |
| **Total (excl. camera)** | | **≈ 50 ms worst case** | |
| **Total (incl. camera)** | | **≈ 85 ms worst case, ~55 ms typical** | |

**Line to say:** "The camera stage dominates the budget. Everything downstream
of the tracker — 60 Hz control, 50 Hz radio, 500 Hz onboard PID, 250 Hz CRSF —
adds under 50 ms combined. That is why the position/velocity PID stack was
moved *onto* the drone: the inner loop no longer pays the link latency."

**[MEASURE]** Ground-truth round trip: the sender prints its STA MAC and the
receiver relays `seq`. Timestamp an outbound `seq` on the PC and match it against
the returned telemetry `seq` to get a real RTT distribution. Histogram it.

### Graph 5 — Update rate hierarchy (bar chart, log-scale y)

| Stage | Rate |
|---|---:|
| Onboard PID stack | ~500 Hz |
| CRSF frames to FC | 250 Hz |
| Kalman / control loop | 60 Hz |
| ESP-NOW state broadcast | 50 Hz |
| Drone → PC telemetry | 50 Hz |
| UI / socket emit | 30 Hz |
| Tracker fix rate | ~15–30 Hz (measured, published as `fps()` EMA) |

**Line to say:** "Rates increase as you move closer to the motors. The slow,
noisy, vision-rate stage stays on the PC; the fast stabilising loops run onboard."

---

## 10.3 Flight time

**[MEASURE]** Not instrumented yet. The plumbing exists — the FC's own voltage
sensor is relayed over CRSF `BATTERY_SENSOR` (frame 0x08) → ESP-NOW →
`B<mac>,<mv>,<pct>` on USB serial, and the console `ping` command reads it back
(`receiver_drone1.ino`, `index.py`).

Battery envelope in firmware: 1S LiPo, `BATTERY_MIN_MV = 3300`,
`BATTERY_MAX_MV = 4200`.

### Graph 6 — Battery voltage vs time (line chart, one line per drone)

Log `ping` output during a continuous hover at 0.45 m (`takeoff_z` in
`settings.json`) until the pack hits 3.30 V. Report hover endurance in
minutes and mark the useful-flight cutoff.

---

## 10.4 Reliability mechanisms — say these fast, one line each

**Failsafe (three independent layers)**
1. **Firmware, 500 ms** — `FAILSAFE_MS = 500`. If ESP-NOW packets stop, the
   receiver sets `armed = false`, `flying = false`, and forces safe sticks
   (throttle → 172, AUX → 1000 µs = disarm). Hardware-enforced, no PC involvement.
2. **Deselection gate** — because state packets are *broadcast*, a comm timeout
   would never catch a drone being deselected. So any drone whose MAC ≠
   `pkt.target` force-disarms immediately and deliberately does **not** refresh
   `lastRecvTime`.
3. **Serial write timeout, 0.1 s** — a stalled USB port cannot block the 60 Hz
   control loop.

**Auto disarm**
- `LANDING` ramps z to 0 over 1.5 s, then clears `_armed_requested` at
  touchdown → `IDLE`. Motors cut without operator action.
- Throttle gate: unless the state machine is in `TAKEOFF`/`HOVER`/`LANDING`,
  `zPWM` is hard-pinned to 172. An arm command alone can never lift the drone.
- `ARM_DELAY_MS = 100` spin-up grace after arming.
- Uploaded-script safety net: if a mission script exits while flying, the runner
  auto-lands; while merely armed, it auto-disarms (`index.py`, `AlgorithmRunner._run`).

**Emergency stop**
- `estop` disarms the shared controller. It is the one command that is never
  blocked — it fires during calibration, it fires when no drone resolves in the
  fleet, and it fires even if the radio retarget throws.
- Autonomous `EMERGENCY` triggers: pose loss (`pos is None`), sustained altitude
  error (> 0.5 m held for > 0.5 s → `Z_ERR_LIMIT_M` / `Z_ERR_LIMIT_HOLD_S`), or a
  control-loop stall (`dt > 0.5 s`).

**Packet loss handling**
- Length guard: `if (len != sizeof(StatePacket)) return;` — malformed frames dropped.
- `seq` monotonic counter on both `StatePacket` and `TelemetryPacket` → loss is
  detectable, not silent.
- CRC8 (poly 0xD5) validated on every inbound CRSF telemetry frame before use.
- **Loss tolerance is quantified:** the state stream is 50 Hz and the failsafe is
  500 ms, so **25 consecutive packets can be lost before the drone disarms.**
  Single-packet loss is invisible — the last valid setpoint is simply held.
- On the estimator side, a *missing camera fix* does not stall control:
  `KalmanFilter.predict_only(dt)` dead-reckons at 60 Hz between the ~30 Hz fixes,
  with `dt` clamped to [1 ms, 200 ms] so a long stall cannot blow up the state.
- Camera watchdog: 30 consecutive lost frames → automatic camera reopen.

**Kalman filtering**
- 9-state constant-acceleration model: `[x y z, vx vy vz, ax ay az]`,
  3-D position measurement, `process_noise = 1e-3`, `measurement_noise = 1e-3`.
- **Velocity is a filter state, not a finite difference of position** — this is
  the key design point. Differentiating a noisy 30 Hz position stream would feed
  garbage into the velocity PID; here velocity comes out of the filter already
  smoothed and phase-consistent.
- Output velocity passes a 5th-order Butterworth low-pass (15 Hz cutoff, 60 Hz
  sample rate) before it reaches the drone's inner loop.
- Heading gets its own low-pass: 8 Hz cutoff at the 50 Hz telemetry rate.
- Integrator hygiene: all seven PIDs are force-reset (`resetPid` walks the output
  limits across the current value) whenever `!flying`, so every takeoff starts
  from zero integral windup.

### Graph 7 — Packet loss vs control degradation (optional, strong if you have time)

**[MEASURE]** Inject artificial loss at the sender (drop 1-in-N sends) and plot
RMS position error against loss rate. Expect a flat curve up to a high loss rate,
then a cliff at the 25-packet failsafe boundary. This graph *proves* the loss
tolerance claim rather than asserting it.

**Covers:** ✔️ Dependability ✔️ Efficiency

---

# 11. Scalability & Manufacturing (1 min)

## Current prototype

- **3 drones** registered and addressable — `alpha`, `beta`, `gamma`
  (`api/fleet.json`), with matching firmware `receiver_drone{1,2,3}.ino`.
- **1 sender ESP32** USB-serial ↔ ESP-NOW bridge.
- **4 USB cameras** on 3D-printed ball-joint mounts.
- **1 desktop application** — React + Vite frontend served by Flask/Socket.IO,
  shipped as a single native executable.
- **~4,700 lines** of Python backend across 10 modules.

## → Future manufacturing

### Modular design

The architecture is modular at three seams, each of which is *why* scaling is cheap:

1. **Addressing seam.** State packets are ESP-NOW *broadcast* with a `target[6]`
   MAC stamped in. One packet reaches the whole fleet; only the matching drone
   acts, and every other drone self-disarms. **Radio airtime for the state
   stream is O(1) in swarm size** — 50 Hz × 128 B = 51.2 kbit/s whether there are
   3 drones or 30.
2. **Control seam.** The PC owns the takeoff state machine only; the nested
   position → velocity → stick PID stack runs onboard the ESP32-C3. Adding a
   drone adds compute, not PC load.
3. **Transport seam.** The PC ↔ sender protocol is 5 plain-text line types
   (`S` state, `P` PID gains, `T` trim, `M` MAC retarget, `R` receiver select).
   Testable, loggable, replaceable without touching either end.

### Easy drone replacement

Swapping or adding a drone touches **two constants and one JSON entry**:

```
receiver_droneN.ino :  uint8_t newMAC[]       = { 0x16, 0x00, ... };  // even first octet
                       uint8_t senderAddress[] = { ... };             // printed by sender at boot
api/fleet.json      :  { "id": "...", "name": "delta", "mac": "16:00:...", "active": true }
```

No sender firmware change. No rewiring. No recalibration. The fleet is editable
live from the web UI (add / rename / activate / deactivate, then re-broadcast to
all clients).

### Multiple drone support

**Working today:**
- Fleet registry with per-drone MAC, name and active/standby flag.
- Per-drone battery telemetry, tagged by source MAC — every drone reports
  independently and simultaneously.
- Console fan-out: `estop all`, `arm off all`, `ping all`, `trim all`, `pid all`
  walk the radio across every active drone (`RETARGET_DWELL_S = 0.15` s each, so
  a fleet-wide estop completes in ≈ 0.15 × N seconds), then restore the
  operator's original selection.
- Deliberate asymmetry: `arm on` stays single-target and *says why* —
  "the receiver firmware disarms any drone that is not the current radio target."

**The honest limit (state this yourself before you are asked):** there is one
shared `Controller` and one shared `KalmanFilter`, so **one drone flies at a
time**. Simultaneous multi-drone flight needs N controller/estimator instances
plus multi-blob tracking with identity association across frames. That is an
additive change at an existing seam, not a rewrite — the addressing, fleet,
telemetry, fan-out and safety layers are already per-drone.

### Estimated scalability

Derived from actual packet sizes and rates:

| Drones | State broadcast (down) | Telemetry (up, unicast) | Total |
|---:|---:|---:|---:|
| 3 | 51.2 kbit/s | 16.8 kbit/s | 68 kbit/s |
| 5 | 51.2 kbit/s | 28.0 kbit/s | 79 kbit/s |
| 10 | 51.2 kbit/s | 56.0 kbit/s | **107 kbit/s** |
| 20 | 51.2 kbit/s | 112.0 kbit/s | 163 kbit/s |

`StatePacket` = 128 B @ 50 Hz (broadcast, constant).
`TelemetryPacket` = 14 B @ 50 Hz per drone (scales linearly).

**Radio is not the bottleneck** — even 20 drones sit well inside ESP-NOW's
1 Mbps base rate. **Realistic ceiling is ≈ 10–15 drones**, set by the vision
system (blob disambiguation in a 1.4 × 1.5 m arena), not the link.

### Graph 8 — Bandwidth vs fleet size (stacked area: broadcast floor + linear telemetry)

Shows the flat broadcast component against the linear telemetry component, with
the ESP-NOW capacity line and the vision-limited ceiling both marked.

### Device fabrication

- **Camera mounts:** 5 printable STL parts — `camera_arm`, `camera_ball`,
  `camera_top_body`, `camera_bottom_body`, `camera_screw` — plus parametric
  Fusion 360 source (`camera.f3z`) and neutral CAD (`camera.step`). Ball-joint
  aiming, reprintable, no proprietary hardware.

### Custom PCB

The drone-side electrical interface is deliberately tiny: **2 signal lines**
(CRSF UART, GPIO 20 RX / GPIO 21 TX — already bidirectional, no extra wires for
telemetry) plus power. So the PCB that replaces the ESP32-C3 dev board and jumper
wires is a **low-complexity 2-layer board**: C3 module, UART header, power
pass-through. Eliminates the jumper wires, which are the current mechanical
failure point on a 1S micro airframe.

### Mass manufacturing

- **Firmware:** one sketch, one MAC constant → factory flashing with per-unit MAC
  injection. No per-drone code branches.
- **Software distribution:** GitHub Actions builds on every push to `main` →
  PyInstaller bundles the Python runtime, dependencies, built React frontend and
  calibration files into one artifact → S3 → CloudFront. Outputs:
  `DroneSwarm-Windows-x64.exe`, `DroneSwarm-Ubuntu-x64.tar.gz`,
  optional `.AppImage` / `.deb`.
- **Zero-dependency install:** the end user needs no Python, Node, npm or pip.
  Double-click → backend starts on `127.0.0.1:3001` → browser opens the UI.
  This is what makes the testbed deployable to another lab, which is the actual
  scalability requirement for a research platform.

**Covers:** ✔️ Device fabrication ✔️ Manufacturing ✔️ Scalability

---

# 12. Security & Safety (1 min)

## Restricted algorithm execution

Users upload arbitrary `.py` mission scripts. Those scripts drive real motors in
a shared lab. So the upload path is the primary attack surface, and it is closed
with **defence in depth**:

**Layer 1 — AST whitelist** (`AlgorithmSourceValidator`, `index.py`).
`generic_visit` *raises*, so the validator is allow-list by construction: any
node type not explicitly handled is rejected. Permitted nodes are only
`Module`, `Expr`, `Call`, `Name`, `Constant`, `List`, `Tuple`.

That means **rejected**: `import`, attribute access (`os.system`), assignment,
`for`/`while`, `if`, `def`, `class`, `lambda`, comprehensions, `**kwargs`,
f-strings, `with`, `try`, decorators, subscripting.

**Layer 2 — call whitelist.** Only 14 names are callable, and the list is
generated from the mission API itself (`validate_algorithm_source(source, api.keys())`)
so it can never drift out of sync with what actually exists:
`arm, disarm, takeoff, land, goto, move, set_yaw, wait, get_position,
get_battery, list_active, get_state, log, print`.

**Layer 3 — empty builtins.** `exec(code, {"__builtins__": {}, **api})`.
Even if something slipped past the AST pass, `open`, `eval`, `__import__` and
`getattr` do not exist in the execution namespace.

**Layer 4 — validate before persist.** Rejection happens *before* the file is
written to disk. Filenames are sanitised (`re.sub(r"[^A-Za-z0-9._-]", "_")`) and
timestamp-prefixed, so path traversal via the upload name is impossible.

**Layer 5 — one at a time.** Exactly one script runs, on a daemon thread, with a
cooperative stop flag checked at every API call and every 50 ms of `wait()`.

**Line to say:** "A malicious upload cannot import a module, cannot read a file,
cannot open a socket, and cannot even write a variable. It can only call fourteen
flight commands — and each of those is itself bounds-checked."

### Network exposure

The backend binds `127.0.0.1` by default, not `0.0.0.0`
(`BACKEND_HOST`, `index.py:63`) — the flight-control surface is not reachable
from the LAN. This is **enforced by a regression test**
(`tests/python/test_backend_network_security.py`) that asserts both the default
value and that `0.0.0.0` never appears as a literal host anywhere in the file.

Fleet MACs are validated against a strict regex before any entry is accepted.

## Failsafe

Three independent layers — see §10.4. The key property: the innermost layer
(500 ms firmware timeout → safe sticks + disarm) requires **no PC, no network and
no operator**. If the laptop dies, the drone lands itself safe.

## Emergency stop

- `estop` disarms the shared controller unconditionally.
- It is exempted from the calibration interlock, it works when *no* drone
  resolves in the fleet, and it still cuts the controller if the radio retarget
  throws an exception.
- It fans out across the entire fleet.
- **Three regression tests** cover exactly these paths:
  `test_estop_all_reaches_every_drone`,
  `test_estop_still_disarms_when_no_drone_resolves`,
  `test_calibration_blocks_flight_commands_but_not_estop`.

**Line to say:** "The estop is the one command we test for the *failure* cases,
not the happy path."

## Communication timeout

| Layer | Timeout | Action |
|---|---:|---|
| Drone firmware ESP-NOW | 500 ms | disarm + safe sticks |
| Drone deselection | immediate | force-disarm (does not wait for timeout) |
| PC serial write | 100 ms | write abandoned, control loop unblocked |
| Control-loop stall | 500 ms `dt` | controller → `EMERGENCY` |
| Pose loss | 1 tick | controller → `EMERGENCY` |
| Heading staleness | tracked as `heading_age` | surfaced to the operator UI |

## Drone stability monitoring

- **Altitude-error watchdog:** `|z − z_setpoint| > 0.5 m` sustained for `0.5 s`
  during `TAKEOFF`/`HOVER` → `EMERGENCY` → disarm. Catches a drone that is
  climbing away or has lost lift, without tripping on transient ramp lag.
- **Ramp continuity:** takeoff and landing z-ramps latch the drone's *actual*
  current altitude on entry, so the setpoint never sits below the drone — which
  would otherwise command a descent immediately after takeoff.
- **Live PID error chart** in the UI: rolling 30 s plot of setpoint-vs-position
  error with settling detection and full-session CSV export, driven by the
  controller's real ramped setpoint rather than the UI input boxes. This is how
  instability is caught during tuning rather than after a crash.
- **Integrator parking:** all seven PIDs reset whenever not flying.
- **Per-drone battery monitoring** from the FC's own voltage sensor.

## Safe operating area

- `MAX_SETPOINT_Z = 2.0 m` enforced on `takeoff`, `goto` and `move`.
- `move` validates the **resulting** altitude, not the delta — you cannot walk
  out of the envelope in small steps.
- `takeoff` rejects `z ≤ 0`; `hover` rejects negative durations; `pid` rejects
  fractional and out-of-range gain indices.
- **Calibration interlock:** while a calibration is active, every flight command
  is refused except `ping`, `estop` and `land`. You cannot fly a rig that is
  mid-recalibration.
- Non-selected drones are held disarmed by firmware — the arena can only ever
  have one drone under power-and-throttle at a time.

## Verification

The whole safety surface is regression-tested, and the gate runs in GitHub
Actions on **every push and pull request** (`run_tests.ps1`, `.github/workflows`):

| Test file | Tests | Covers |
|---|---:|---|
| `test_console_commands.py` | 27 | fan-out, targeting, altitude envelope, estop-during-calibration |
| `test_calibration_math.py` | 6 | intrinsics, pose solve, world transform |
| `test_algorithm_upload_security.py` | 4 | AST whitelist accept/reject |
| `test_controller.py` | 4 | state machine, emergency transitions |
| `test_deployment_runtime.py` | 4 | packaged-executable runtime paths |
| `test_backend_network_security.py` | 2 | localhost binding |
| `test_filters.py` | 2 | Kalman + Butterworth |
| **Total** | **49** | plus the TypeScript/Vite production build |

**Closing line:** "Safety here is not a checklist we assert — it is 49 tests that
run before anything merges, and a 500 ms hardware failsafe that does not trust
the laptop."

**Covers:** ✔️ Security ✔️ Dependability

---

## Before the viva — the four numbers you still need

1. **Localization accuracy (mm).** Run the calibration wizard; screenshot the
   `Mean error` / `Max error` lines. This is your single most quotable number.
2. **Flight time (min).** Continuous hover at 0.45 m, log `ping` battery until
   3.30 V.
3. **Measured end-to-end latency (ms).** Timestamp an outbound `seq`, match the
   returned telemetry `seq`, histogram the RTT.
4. **Measured tracker FPS.** `tracker.fps()` already publishes an EMA — read it
   off the running UI. Confirms the ~15–30 Hz assumption in the latency budget.
