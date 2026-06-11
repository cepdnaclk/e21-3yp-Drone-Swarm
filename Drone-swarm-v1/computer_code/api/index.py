"""
Single-drone Flask + SocketIO backend.

Pipeline:
    4 USB cams ──► Tracker ──► KalmanFilter ──► Controller ──► S-line serial ──► sender ESP32 ──► drone PIDs

Threads:
    - Tracker worker (inside Tracker; ~30 Hz)
    - HeadingReader (this file; blocks on Serial.readline)
    - Control (this file; ~60 Hz)
    - Flask/SocketIO main thread

Serial protocol (sender_esp32.ino):
    PC -> ESP : "S,x,y,z,vx,vy,vz,yaw_sp,x_sp,y_sp,z_sp,armed\n"  state stream
                "P,<17 floats>\n"  PID + ground-effect gain update (one-shot)
                "T,trim_t,trim_r,trim_p,trim_y\n"  trim update (one-shot)
    ESP -> PC : "H<yaw>\n"      float radians (heading bridge)

Environment:
    SENDER_SERIAL_PORT   default 'COM5' on Windows
    SENDER_SERIAL_BAUD   default 115200
"""

import json
import os
import re
import threading
import time

import numpy as np
import serial
from flask import Flask, Response
from flask_cors import CORS
from flask_socketio import SocketIO

from controller import Controller, ControlParams
from helpers import Cameras
from KalmanFilter import KalmanFilter
from LowPassFilter import LowPassFilter


# =========================
# Config
# =========================

SERIAL_PORT = os.environ.get("SENDER_SERIAL_PORT", "COM6")
SERIAL_BAUD = int(os.environ.get("SENDER_SERIAL_BAUD", "115200"))

CONTROL_HZ = 60.0
EMIT_HZ = 30.0
HEADING_LPF_CUTOFF = 8.0
HEADING_LPF_FS = 50.0       # the drone ESP-NOWs heading at 50 Hz

FLEET_FILE = os.path.join(os.path.dirname(__file__), "fleet.json")
_MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}[:\-]){5}[0-9A-Fa-f]{2}$")


def _normalise_mac(mac: str) -> str:
    return mac.strip().upper().replace("-", ":")


def _load_fleet():
    try:
        with open(FLEET_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []
        out = []
        for entry in data:
            if not isinstance(entry, dict):
                continue
            mac = _normalise_mac(str(entry.get("mac", "")))
            if not _MAC_RE.match(mac):
                continue
            out.append({
                "id": str(entry.get("id") or mac.replace(":", "").lower()),
                "name": str(entry.get("name") or mac),
                "mac": mac,
                "active": bool(entry.get("active", True)),
            })
        return out
    except FileNotFoundError:
        return []
    except (json.JSONDecodeError, OSError) as e:
        print(f"[fleet] failed to load {FLEET_FILE}: {e}")
        return []


def _save_fleet(fleet):
    try:
        with open(FLEET_FILE, "w", encoding="utf-8") as f:
            json.dump(fleet, f, indent=2)
    except OSError as e:
        print(f"[fleet] failed to save {FLEET_FILE}: {e}")


_fleet_lock = threading.Lock()
_fleet = _load_fleet()
_selected_drone_mac = None  # which drone the MoCap section is currently controlling


# =========================
# Globals
# =========================

app = Flask(__name__)
CORS(app, supports_credentials=True)
# Force threading mode so socketio.emit() from our plain threading.Thread
# workers (control / heading / emitter) actually reaches connected clients.
# Without this, Flask-SocketIO will pick eventlet if it's installed and emits
# from non-green threads silently never get delivered.
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

cameras = Cameras.instance()
kf = KalmanFilter()
controller = Controller()

# Serial / heading
_ser = None
_ser_lock = threading.Lock()           # guards _ser.write() only; reads are on their own thread
_heading_lock = threading.Lock()
_latest_heading = None                 # float rad, post-LPF
_latest_heading_t = 0.0
_heading_lpf = LowPassFilter(
    cutoff_frequency=HEADING_LPF_CUTOFF,
    sampling_frequency=HEADING_LPF_FS,
    dims=1,
)

# Control thread shared state for emitter
_state_lock = threading.Lock()
_emit_state = {
    "pos": None, "vel": None, "heading": None, "heading_age": None,
    "setpoint": None, "armed": 0, "state": "IDLE", "fps": 0.0,
}


# =========================
# Serial helpers
# =========================

def _open_serial():
    global _ser
    if _ser is not None and _ser.is_open:
        return _ser
    try:
        _ser = serial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=0.1, write_timeout=0.1)
        print(f"[serial] opened {SERIAL_PORT} @ {SERIAL_BAUD}")
    except Exception as e:
        print(f"[serial] WARNING: failed to open {SERIAL_PORT}: {e}")
        _ser = None
    return _ser


def _serial_write(payload: bytes):
    if _ser is None or not _ser.is_open or not payload:
        return
    try:
        with _ser_lock:
            _ser.write(payload)
    except Exception as e:
        print(f"[serial] write failed: {e}")


# =========================
# Heading reader thread
# =========================

def _heading_reader_loop():
    global _latest_heading, _latest_heading_t
    print("[serial] reader started")
    while True:
        if _ser is None or not _ser.is_open:
            time.sleep(0.5)
            continue
        try:
            line = _ser.readline().decode(errors="ignore").strip()
        except Exception as e:
            print(f"[serial] read failed: {e}")
            time.sleep(0.5)
            continue
        if not line:
            continue

        if line.startswith("H"):
            # Backward-compat heading line (single-drone): "H<yaw_rad>"
            try:
                yaw = float(line[1:])
            except ValueError:
                continue
            filt = _heading_lpf.filter(np.array([yaw], dtype=np.float64))[0]
            with _heading_lock:
                _latest_heading = float(filt)
                _latest_heading_t = time.perf_counter()

        elif line.startswith("B"):
            # "B<mac>,<mv>,<pct>" — battery telemetry tagged with source MAC.
            parts = line[1:].split(",")
            if len(parts) < 3:
                continue
            mac = _normalise_mac(parts[0])
            if not _MAC_RE.match(mac):
                continue
            try:
                mv = int(parts[1])
                pct = max(0, min(100, int(float(parts[2]))))
            except ValueError:
                continue
            socketio.emit("drone-telemetry", {
                "mac": mac,
                "battery": pct,
                "battery_mv": mv,
            })


# =========================
# Control thread
# =========================

def _control_loop():
    print("[control] loop started @ %.1f Hz" % CONTROL_HZ)
    period = 1.0 / CONTROL_HZ
    next_t = time.perf_counter()
    last_fix_id = -1
    last_step_t = time.perf_counter()
    emit_period = 1.0 / EMIT_HZ
    next_emit_t = next_t

    while True:
        # Pace the loop precisely
        now = time.perf_counter()
        if now < next_t:
            time.sleep(max(0.0, next_t - now))
            now = time.perf_counter()
        next_t += period
        if next_t < now - period:  # we fell behind; resync
            next_t = now + period

        dt = max(1e-3, now - last_step_t)
        last_step_t = now

        # ---- Tracker ----
        xyz, fix_id = cameras.latest_xyz_m_with_id()
        if xyz is not None and fix_id != last_fix_id:
            pos, vel = kf.update(xyz)
            last_fix_id = fix_id
            tracker_fresh = True
        else:
            pos, vel = kf.predict_only(dt)
            tracker_fresh = False

        # ---- Heading ----
        with _heading_lock:
            heading = _latest_heading
            heading_t = _latest_heading_t

        # ---- Controller ----
        if not kf._initialised:
            # Allow bench arming before the tracker has produced its first fix,
            # but do not permit actual closed-loop flight without a pose.
            ctrl_state = controller.get_state()
            if ctrl_state in ("TAKEOFF", "HOVER", "LANDING"):
                pkt = {
                    "x": 0.0, "y": 0.0, "z": 0.0,
                    "vx": 0.0, "vy": 0.0, "vz": 0.0,
                    "yaw_sp": 0.0,
                    "x_sp": 0.0, "y_sp": 0.0, "z_sp": 0.0,
                    "armed": 0, "state": ctrl_state,
                }
            else:
                zero = np.zeros(3, dtype=np.float32)
                pkt = controller.step(zero, zero, heading, dt)
                ctrl_state = pkt["state"]
        else:
            pkt = controller.step(pos, vel, heading, dt)
            ctrl_state = pkt["state"]

        # ---- Serial out ----
        _serial_write(Controller.serialize_state(pkt))

        # ---- Stash for emitter ----
        if now >= next_emit_t:
            next_emit_t += emit_period
            with _state_lock:
                _emit_state["pos"] = None if pos is None else [float(x) for x in pos]
                _emit_state["vel"] = None if vel is None else [float(x) for x in vel]
                _emit_state["heading"] = heading
                _emit_state["heading_age"] = (now - heading_t) if heading_t else None
                _emit_state["setpoint"] = [pkt["x_sp"], pkt["y_sp"], pkt["z_sp"]]
                _emit_state["armed"] = pkt["armed"]
                _emit_state["state"] = ctrl_state
                _emit_state["fps"] = cameras.fps()
                _emit_state["tracker_fresh"] = tracker_fresh


# =========================
# Emitter thread (avoids blocking control loop on socket.emit)
# =========================

def _emitter_loop():
    period = 1.0 / EMIT_HZ
    emit_count = 0
    last_hb = time.perf_counter()
    while True:
        time.sleep(period)
        with _state_lock:
            payload = dict(_emit_state)
        socketio.emit("drone-state", payload)
        emit_count += 1
        now = time.perf_counter()
        if now - last_hb > 2.0:
            pos = payload.get("pos")
            print(f"[emitter] {emit_count / (now - last_hb):.0f} emits/s, "
                  f"last pos={pos}")
            emit_count = 0
            last_hb = now


# =========================
# Flask routes
# =========================

@app.route("/api/camera-stream")
def camera_stream():
    cameras.start()

    def gen():
        boundary = b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
        target_period = 1.0 / 30.0
        next_t = time.perf_counter()
        while True:
            now = time.perf_counter()
            if now < next_t:
                time.sleep(max(0.0, next_t - now))
            next_t = time.perf_counter() + target_period
            jpeg = cameras.get_grid_jpeg()
            if not jpeg:
                continue
            yield boundary + jpeg + b"\r\n"

    return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame")


# =========================
# SocketIO events
# =========================

@socketio.on("connect")
def on_connect():
    """Push pre-baked calibration to the frontend so it can draw camera wireframes."""
    poses = cameras.camera_poses_in_world()
    socketio.emit("camera-pose", {"camera_poses": poses})
    socketio.emit("to-world-coords-matrix",
                  {"to_world_coords_matrix": cameras.world_matrix_4x4_metres()})
    with _fleet_lock:
        socketio.emit("fleet", {"drones": list(_fleet),
                                "selected_mac": _selected_drone_mac})


@socketio.on("drone-fleet-update")
def on_fleet_update(data):
    """Persist the user's edits to fleet.json and rebroadcast to all clients."""
    global _fleet
    if not isinstance(data, dict):
        return
    raw = data.get("drones")
    if not isinstance(raw, list):
        return
    cleaned = []
    seen = set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        mac = _normalise_mac(str(entry.get("mac", "")))
        if not _MAC_RE.match(mac) or mac in seen:
            continue
        seen.add(mac)
        cleaned.append({
            "id": str(entry.get("id") or mac.replace(":", "").lower()),
            "name": str(entry.get("name") or mac),
            "mac": mac,
            "active": bool(entry.get("active", True)),
        })
    with _fleet_lock:
        _fleet = cleaned
        _save_fleet(_fleet)
        socketio.emit("fleet", {"drones": list(_fleet),
                                "selected_mac": _selected_drone_mac})


@socketio.on("mocap-select-drone")
def on_mocap_select_drone(data):
    """Switch the MoCap target. Forwards the MAC to the sender ESP32 as
    'M,<mac>\\n' so it re-aims its ESP-NOW peer."""
    global _selected_drone_mac
    if not isinstance(data, dict):
        return
    mac = _normalise_mac(str(data.get("mac", "")))
    if not _MAC_RE.match(mac):
        return
    with _fleet_lock:
        known = any(d["mac"] == mac for d in _fleet)
    if not known:
        print(f"[mocap] refusing to select unknown MAC {mac}")
        return
    _selected_drone_mac = mac
    _serial_write(f"M,{mac}\n".encode("ascii"))
    socketio.emit("fleet", {"drones": list(_fleet),
                            "selected_mac": _selected_drone_mac})
    print(f"[mocap] selected drone {mac}")


@socketio.on("arm-drone")
def on_arm(data):
    # Accept either {"droneArmed":[bool,...]} (legacy) or {"armed": bool}
    armed = False
    if isinstance(data, dict):
        if "armed" in data:
            armed = bool(data["armed"])
        elif "droneArmed" in data and isinstance(data["droneArmed"], list) and data["droneArmed"]:
            armed = bool(data["droneArmed"][0])
    print(f"[socket] arm-drone -> armed={armed}")
    controller.cmd_arm(armed)


@socketio.on("takeoff")
def on_takeoff(data):
    z = 0.20
    if isinstance(data, dict) and "z" in data:
        try:
            z = float(data["z"])
        except (ValueError, TypeError):
            pass
    controller.cmd_takeoff(z)


@socketio.on("land")
def on_land(_data):
    controller.cmd_land()


@socketio.on("set-drone-pid")
def on_set_pid(data):
    if not (isinstance(data, dict) and "dronePID" in data):
        return
    gains = data["dronePID"]
    if not isinstance(gains, (list, tuple)) or len(gains) < 15:
        return
    _serial_write(Controller.serialize_pid(gains))


@socketio.on("set-drone-setpoint")
def on_set_setpoint(data):
    if isinstance(data, dict) and "droneSetpoint" in data:
        sp = data["droneSetpoint"]
        if isinstance(sp, list) and len(sp) >= 3:
            try:
                controller.cmd_setpoint(float(sp[0]), float(sp[1]), float(sp[2]))
            except (ValueError, TypeError):
                pass


@socketio.on("set-drone-trim")
def on_set_trim(data):
    if not (isinstance(data, dict) and "droneTrim" in data):
        return
    tr = data["droneTrim"]
    if not (isinstance(tr, list) and len(tr) >= 4):
        return
    try:
        _serial_write(Controller.serialize_trim(int(tr[0]), int(tr[1]), int(tr[2]), int(tr[3])))
    except (ValueError, TypeError):
        pass


@socketio.on("update-camera-settings")
def on_camera_settings(data):
    # Webcams: thresholds are settable per-camera (preferred) or as a single value.
    if not isinstance(data, dict):
        return
    if "thresholds" in data and isinstance(data["thresholds"], list):
        try:
            cameras.set_thresholds([int(v) for v in data["thresholds"]])
        except (ValueError, TypeError):
            pass
    elif "threshold" in data:
        try:
            cameras.set_threshold(int(data["threshold"]))
        except (ValueError, TypeError):
            pass


# Compatibility no-ops so the existing frontend doesn't crash if it still emits them
@socketio.on("capture-points")
def _noop_capture_points(_): pass

@socketio.on("calculate-camera-pose")
def _noop_calculate_pose(_): pass

@socketio.on("acquire-floor")
def _noop_acquire_floor(_): pass

@socketio.on("set-origin")
def _noop_set_origin(_): pass

@socketio.on("determine-scale")
def _noop_determine_scale(_): pass

@socketio.on("triangulate-points")
def on_triangulate_points(_data):
    # Legacy event used to toggle the tracking pipeline. We always track when
    # the camera stream is active, so just make sure cameras are running.
    cameras.start()


# =========================
# Boot
# =========================

def _start_background_threads():
    _open_serial()
    cameras.start()
    threading.Thread(target=_heading_reader_loop, daemon=True, name="HeadingReader").start()
    threading.Thread(target=_control_loop, daemon=True, name="Control").start()
    threading.Thread(target=_emitter_loop, daemon=True, name="Emitter").start()


if __name__ == "__main__":
    _start_background_threads()
    # debug=False -> no Werkzeug reloader (would spawn the threads twice)
    socketio.run(app, host="0.0.0.0", port=3001, debug=False, allow_unsafe_werkzeug=True)
