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

$env:SENDER_TRANSPORT="udp"
$env:SENDER_UDP_HOST="192.168.4.1"
$env:SENDER_UDP_PORT="4210"
python Drone-swarm-v1/computer_code/api/index.py


"""

import json
import os
import socket
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


def _load_local_env():
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(env_path):
        return
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
    except Exception as e:
        print(f"[env] WARNING: failed to load {env_path}: {e}")


_load_local_env()


# =========================
# Config
# =========================

SERIAL_PORT = os.environ.get("SENDER_SERIAL_PORT", "COM6")
SERIAL_BAUD = int(os.environ.get("SENDER_SERIAL_BAUD", "115200"))
SENDER_TRANSPORT = os.environ.get("SENDER_TRANSPORT", "serial").lower()
SENDER_UDP_HOST = os.environ.get("SENDER_UDP_HOST", "192.168.4.1")
SENDER_UDP_PORT = int(os.environ.get("SENDER_UDP_PORT", "4210"))

CONTROL_HZ = 60.0
EMIT_HZ = 30.0
HEADING_LPF_CUTOFF = 8.0
HEADING_LPF_FS = 50.0       # the drone ESP-NOWs heading at 50 Hz


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
_udp_sock = None
_ser_lock = threading.Lock()           # guards _ser.write() only; reads are on their own thread
_sender_connected_logged = False
_last_sender_drop_log_t = 0.0
_last_serial_retry_t = 0.0
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
        print(f"[sender] serial connected: {SERIAL_PORT} @ {SERIAL_BAUD}")
    except Exception as e:
        print(f"[sender] WARNING: failed to connect serial sender on {SERIAL_PORT}: {e}")
        _ser = None
    return _ser


def _open_udp():
    global _udp_sock
    if _udp_sock is not None:
        return _udp_sock
    try:
        _udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        _udp_sock.setblocking(False)
        print(f"[sender] UDP target ready: {SENDER_UDP_HOST}:{SENDER_UDP_PORT}")
    except Exception as e:
        print(f"[sender] WARNING: failed to open UDP sender socket: {e}")
        _udp_sock = None
    return _udp_sock


def _serial_write(payload: bytes):
    global _sender_connected_logged, _last_sender_drop_log_t, _last_serial_retry_t
    if not payload:
        return
    if SENDER_TRANSPORT == "udp":
        sock = _open_udp()
        if sock is None:
            return
        try:
            sock.sendto(payload, (SENDER_UDP_HOST, SENDER_UDP_PORT))
            if not _sender_connected_logged:
                print(f"[sender] UDP packets sending to ESP32 AP at {SENDER_UDP_HOST}:{SENDER_UDP_PORT}")
                _sender_connected_logged = True
        except Exception as e:
            print(f"[sender] UDP send failed: {e}")
        return

    if _ser is None or not _ser.is_open:
        now = time.perf_counter()
        if now - _last_serial_retry_t > 1.0:
            _last_serial_retry_t = now
            _open_serial()
        if _ser is None or not _ser.is_open:
            if now - _last_sender_drop_log_t > 2.0:
                _last_sender_drop_log_t = now
                print(f"[sender] serial sender not connected on {SERIAL_PORT}; dropping packets")
            return
        return
    try:
        with _ser_lock:
            _ser.write(payload)
        if not _sender_connected_logged:
            print(f"[sender] serial packets sending to ESP32 on {SERIAL_PORT}")
            _sender_connected_logged = True
    except Exception as e:
        print(f"[sender] serial write failed: {e}")


# =========================
# Heading reader thread
# =========================

def _heading_reader_loop():
    global _latest_heading, _latest_heading_t
    print("[heading] reader started")
    while True:
        if SENDER_TRANSPORT == "udp":
            time.sleep(0.5)
            continue
        if _ser is None or not _ser.is_open:
            time.sleep(0.5)
            continue
        try:
            line = _ser.readline().decode(errors="ignore").strip()
        except Exception as e:
            print(f"[heading] read failed: {e}")
            time.sleep(0.5)
            continue
        if not line.startswith("H"):
            continue
        try:
            yaw = float(line[1:])
        except ValueError:
            continue
        filt = _heading_lpf.filter(np.array([yaw], dtype=np.float64))[0]
        with _heading_lock:
            _latest_heading = float(filt)
            _latest_heading_t = time.perf_counter()


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
    print(f"[sender] transport={SENDER_TRANSPORT}")
    if SENDER_TRANSPORT == "udp":
        _open_udp()
    else:
        _open_serial()
    cameras.start()
    threading.Thread(target=_heading_reader_loop, daemon=True, name="HeadingReader").start()
    threading.Thread(target=_control_loop, daemon=True, name="Control").start()
    threading.Thread(target=_emitter_loop, daemon=True, name="Emitter").start()


if __name__ == "__main__":
    _start_background_threads()
    # debug=False -> no Werkzeug reloader (would spawn the threads twice)
    socketio.run(app, host="0.0.0.0", port=3001, debug=False, allow_unsafe_werkzeug=True)
