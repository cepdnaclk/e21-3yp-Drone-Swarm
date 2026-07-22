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
import shutil
import socket
import sys
import threading
import time
import webbrowser

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
# Packaging / path helpers
# =========================

# True when running from a PyInstaller onefile/onedir bundle.
FROZEN = getattr(sys, "frozen", False)
# Directory this script lives in (or the extracted bundle temp dir).
BUNDLE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


def _resource_path(*parts):
    """Locate a read-only file that ships with the app, both in a normal
    checkout and inside a PyInstaller bundle. Tries a few candidate roots so
    the same call works whether data was bundled at the root or under ``api/``."""
    rel = os.path.join(*parts)
    roots = [BUNDLE_DIR, os.path.join(BUNDLE_DIR, "api"),
             os.path.dirname(os.path.abspath(__file__))]
    for root in roots:
        candidate = os.path.join(root, rel)
        if os.path.exists(candidate):
            return candidate
    # Fall back to the first candidate even if missing, so callers get a
    # sensible path to report in errors.
    return os.path.join(roots[0], rel)


def _user_data_dir():
    """Per-user writable directory for fleet.json, uploads, logs and config.
    Never write user-modified files inside the installed app directory."""
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or \
            os.path.join(os.path.expanduser("~"), ".config")
    path = os.path.join(base, "DroneSwarm")
    os.makedirs(path, exist_ok=True)
    return path


DATA_DIR = _user_data_dir()


def _load_app_config():
    """Optional user config at ``<DATA_DIR>/config.json``. Lets non-technical
    users set the serial port / server port without environment variables.
    Environment variables still win over the file (see resolution below)."""
    path = os.path.join(DATA_DIR, "config.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError) as e:
        print(f"[config] failed to read {path}: {e}")
        return {}


_APP_CONFIG = _load_app_config()


def _setting(env_key, cfg_key, default):
    """Resolve a setting: environment variable > config.json > default."""
    if env_key in os.environ:
        return os.environ[env_key]
    if cfg_key in _APP_CONFIG:
        return _APP_CONFIG[cfg_key]
    return default


# =========================
# Config
# =========================

# Serial port / baud: env var, then config.json, then platform default.
_default_port = "COM10" if sys.platform.startswith("win") else "/dev/ttyUSB0"
SERIAL_PORT = str(_setting("SENDER_SERIAL_PORT", "serial_port", _default_port))
SERIAL_BAUD = int(_setting("SENDER_SERIAL_BAUD", "serial_baud", 115200))

# Server bind host / port. Default to 127.0.0.1 in production: the backend
# only serves the local browser UI, so it must not be reachable off-box.
HOST = str(_setting("DRONESWARM_HOST", "host", "127.0.0.1"))
PORT = int(_setting("DRONESWARM_PORT", "port", 3001))

# Auto-shutdown when the last browser tab closes, so the packaged app doesn't
# linger invisibly holding the cameras / serial / TCP port. Enabled for the
# frozen desktop build (or DRONESWARM_IDLE_SHUTDOWN=1); off for `python index.py`
# development, where the server is meant to be long-lived.
IDLE_SHUTDOWN_ENABLED = FROZEN or os.environ.get("DRONESWARM_IDLE_SHUTDOWN") == "1"
IDLE_SHUTDOWN_GRACE_S = float(_setting("DRONESWARM_IDLE_SHUTDOWN_S",
                                       "idle_shutdown_seconds", 45))
# Suppress all browser auto-opening (headless runs, CI, or user preference).
BROWSER_SUPPRESSED = os.environ.get("DRONESWARM_NO_BROWSER") == "1"

CONTROL_HZ = 60.0
EMIT_HZ = 30.0
HEADING_LPF_CUTOFF = 8.0
HEADING_LPF_FS = 50.0       # the drone ESP-NOWs heading at 50 Hz

# fleet.json is user-editable, so it lives in the writable data dir. On first
# run we seed it from the copy that ships with the app (if present).
FLEET_FILE = os.path.join(DATA_DIR, "fleet.json")
if not os.path.exists(FLEET_FILE):
    _seed = _resource_path("fleet.json")
    if os.path.exists(_seed):
        try:
            shutil.copyfile(_seed, FLEET_FILE)
        except OSError as e:
            print(f"[fleet] could not seed {FLEET_FILE}: {e}")
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

# Latest battery reading per drone MAC: {mac: {"pct": int, "mv": int, "t": float}}
_battery_lock = threading.Lock()
_battery = {}

# Last PID gains pushed to the drone. The console's "pid <index> <value>"
# command edits one slot of this and re-sends the full set.
_pid_lock = threading.Lock()
_current_pid = [
    2.5, 0.0, 0.4,      # xy pos
    3.5, 0.5, 0.5,      # z pos
    80.0, 10.0, 5.0,    # yaw
    8.0, 1.0, 0.3,      # xy vel
    120.0, 40.0, 20.0,  # z vel
    0.0, 0.0,           # ground effect
]


# =========================
# Globals
# =========================

# Locate the built React frontend (`npm run build` -> computer_code/dist).
# In a PyInstaller bundle the dist tree is added at the bundle root.
if FROZEN:
    DIST_DIR = os.path.join(BUNDLE_DIR, "dist")
else:
    DIST_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "dist"))

app = Flask(__name__, static_folder=DIST_DIR, static_url_path="")
CORS(app, supports_credentials=True)
# Force threading mode so socketio.emit() from our plain threading.Thread
# workers (control / heading / emitter) actually reaches connected clients.
# Without this, Flask-SocketIO will pick eventlet if it's installed and emits
# from non-green threads silently never get delivered.
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")


def _open_ui(url):
    """Open the local UI in the default browser, honouring DRONESWARM_NO_BROWSER."""
    if BROWSER_SUPPRESSED:
        print(f"[boot] browser auto-open suppressed; open {url} manually")
        return
    webbrowser.open(url)


def _another_instance_running():
    """True if a Drone Swarm server is already listening on our port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", PORT)) == 0


# Single-instance guard: if another copy is already serving on our port, hand
# off to it (open the browser at the running server) and exit *before* we touch
# the USB cameras or serial port — so a second double-click can never disturb
# the instance that's already running.
if __name__ == "__main__" and _another_instance_running():
    print(f"[boot] Drone Swarm already running on http://127.0.0.1:{PORT} "
          f"- opening it instead of starting a second copy")
    _open_ui(f"http://127.0.0.1:{PORT}")
    sys.exit(0)

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
            with _battery_lock:
                _battery[mac] = {"pct": pct, "mv": mv, "t": time.perf_counter()}
            socketio.emit("drone-telemetry", {
                "mac": mac,
                "battery": pct,
                "battery_mv": mv,
            })
            _algorithm_runner.notify_telemetry({
                "mac": mac, "battery": pct, "battery_mv": mv,
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
# Console command dispatch
# =========================

_radio_lock = threading.Lock()


def _broadcast_fleet():
    with _fleet_lock:
        socketio.emit("fleet", {"drones": list(_fleet),
                                "selected_mac": _selected_drone_mac})


def _resolve_target(target):
    """Resolve a console target to a fleet entry. "all" resolves to the
    currently selected drone: the sender ESP-NOW *broadcasts* every state
    packet to the whole fleet, but each packet carries a target MAC and only
    the matching drone acts on it -- so commands still address one drone at a
    time. Raises ValueError on bad or inactive targets."""
    if not target or target == "all":
        with _fleet_lock:
            sel = _selected_drone_mac
            for d in _fleet:
                if sel and d["mac"] == sel and d["active"]:
                    return dict(d)
            # No valid selection yet: fall back to the first active drone.
            for d in _fleet:
                if d["active"]:
                    return dict(d)
        raise ValueError("no active drone in the fleet")
    with _fleet_lock:
        for d in _fleet:
            if d["id"] == target or d["mac"] == _normalise_mac(str(target)):
                if not d["active"]:
                    raise ValueError(f"drone '{d['name']}' is on standby")
                return dict(d)
    raise ValueError(f"unknown target '{target}'")


def _retarget_radio(mac: str, force: bool = False):
    """Point the sender ESP32 at `mac`. Broadcasts the new selection to all
    UI clients so MoCap/Console/Drones views stay in sync. `force` re-sends
    the M-line even when we think the sender already targets `mac` (used at
    boot to re-sync a sender that kept running across a backend restart)."""
    global _selected_drone_mac
    with _radio_lock:
        changed = _selected_drone_mac != mac
        if changed or force:
            _selected_drone_mac = mac
            _serial_write(f"M,{mac}\n".encode("ascii"))
    if changed:
        _broadcast_fleet()


def _current_position():
    with _state_lock:
        pos = _emit_state["pos"]
    return list(pos) if pos else None


def _console_dispatch(command: str, args, target_entry):
    """Execute one console command. Returns the ack text.
    Raises ValueError with a user-facing message on bad input."""

    def _floats(n):
        if len(args) < n:
            raise ValueError(f"{command} needs {n} argument(s)")
        try:
            return [float(a) for a in args[:n]]
        except ValueError:
            raise ValueError(f"{command}: arguments must be numbers")

    if command == "arm":
        if not args or args[0].lower() not in ("on", "off"):
            raise ValueError("usage: arm <on|off>")
        on = args[0].lower() == "on"
        controller.cmd_arm(on)
        return f"{'armed' if on else 'disarmed'} (state {controller.get_state()})"

    if command == "takeoff":
        (z,) = _floats(1)
        if z <= 0 or z > 2.0:
            raise ValueError("takeoff: z must be in (0, 2.0] metres")
        if not controller.is_armed():
            raise ValueError("takeoff: drone is not armed (send 'arm on' first)")
        controller.cmd_takeoff(z)
        return f"takeoff to {z:.2f} m commanded"

    if command == "land":
        controller.cmd_land()
        return f"landing (state {controller.get_state()})"

    if command == "goto":
        x, y, z = _floats(3)
        controller.cmd_setpoint(x, y, z)
        return f"setpoint -> ({x:.2f}, {y:.2f}, {z:.2f})"

    if command == "move":
        dx, dy, dz = _floats(3)
        sx, sy, sz, _ = controller.get_setpoint()
        controller.cmd_setpoint(sx + dx, sy + dy, sz + dz)
        return f"setpoint -> ({sx + dx:.2f}, {sy + dy:.2f}, {sz + dz:.2f})"

    if command == "yaw":
        (yaw,) = _floats(1)
        controller.cmd_yaw(yaw)
        return f"yaw setpoint -> {yaw:.3f} rad"

    if command == "hover":
        # The controller holds the latched setpoint by itself; hover is an
        # acknowledgement that nothing will be retargeted for N seconds.
        secs = _floats(1)[0] if args else 0.0
        return f"holding setpoint{f' for {secs:.1f} s' if secs else ''}"

    if command == "trim":
        t = _floats(4)
        _serial_write(Controller.serialize_trim(int(t[0]), int(t[1]), int(t[2]), int(t[3])))
        return f"trim -> T{int(t[0])} R{int(t[1])} P{int(t[2])} Y{int(t[3])}"

    if command == "pid":
        idx_f, value = _floats(2)
        idx = int(idx_f)
        if not 0 <= idx < 17:
            raise ValueError("pid: index must be 0..16")
        with _pid_lock:
            _current_pid[idx] = value
            gains = list(_current_pid)
        _serial_write(Controller.serialize_pid(gains))
        return f"pid[{idx}] -> {value:g} (full set re-sent)"

    if command == "estop":
        controller.cmd_arm(False)
        return "EMERGENCY STOP — disarmed"

    if command == "ping":
        pos = _current_position()
        with _battery_lock:
            batt = dict(_battery)
        pos_txt = ("(" + ", ".join(f"{v:.2f}" for v in pos) + ")") if pos else "unknown"
        if target_entry:
            b = batt.get(target_entry["mac"])
            batt_txt = f"{b['pct']}% ({b['mv']} mV)" if b else "no battery data"
            return (f"{target_entry['name']}: state {controller.get_state()}, "
                    f"pos {pos_txt}, battery {batt_txt}")
        return f"state {controller.get_state()}, pos {pos_txt}, {len(batt)} drone(s) reporting battery"

    raise ValueError(f"unknown command '{command}'")


@socketio.on("console-command")
def on_console_command(data):
    if not isinstance(data, dict):
        return
    target = str(data.get("target", "all"))
    command = str(data.get("command", "")).strip().lower()
    args = [str(a) for a in (data.get("args") or [])]

    try:
        entry = _resolve_target(target)
        _retarget_radio(entry["mac"])
        text = f"[{entry['name']}] {_console_dispatch(command, args, entry)}"
        socketio.emit("console-ack", {"target": target, "text": text})
        print(f"[console] {target}: {command} {' '.join(args)} -> {text}")
    except ValueError as e:
        socketio.emit("console-error", {"target": target, "text": str(e)})
    except Exception as e:  # never let a console command kill the handler
        socketio.emit("console-error", {"target": target, "text": f"internal error: {e}"})
        print(f"[console] ERROR on '{command}': {e}")


# =========================
# Algorithm runner
# =========================

UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")


class AlgorithmStopped(Exception):
    """Raised inside user scripts when the UI requests a stop."""


class AlgorithmRunner:
    """Executes an uploaded .py mission script on a worker thread.

    The script gets a set of premade functions (arm, takeoff, goto, ...) that
    drive the single shared Controller. Exactly one script runs at a time.
    A stop request raises AlgorithmStopped at the next API call / wait tick.
    """

    def __init__(self):
        self._thread = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._telemetry_callbacks = []
        self.filename = None

    # ---- lifecycle ----

    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, filename: str, source: str) -> str:
        with self._lock:
            if self.running():
                raise ValueError("an algorithm is already running — stop it first")
            try:
                code = compile(source, filename, "exec")
            except SyntaxError as e:
                raise ValueError(f"syntax error: line {e.lineno}: {e.msg}")

            os.makedirs(UPLOADS_DIR, exist_ok=True)
            safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", filename) or "algorithm.py"
            path = os.path.join(UPLOADS_DIR, f"{int(time.time())}_{safe_name}")
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(source)
            except OSError as e:
                print(f"[algo] WARNING: could not persist upload: {e}")

            self._stop.clear()
            self._telemetry_callbacks = []
            self.filename = filename
            self._thread = threading.Thread(
                target=self._run, args=(code,), daemon=True, name="Algorithm")
            self._thread.start()
            return path

    def stop(self):
        self._stop.set()

    def notify_telemetry(self, packet: dict):
        for cb in list(self._telemetry_callbacks):
            try:
                cb(packet)
            except AlgorithmStopped:
                pass
            except Exception as e:
                self._log(f"on_telemetry callback error: {e}", stream="err")

    # ---- internals ----

    def _log(self, text, stream="out"):
        socketio.emit("algorithm-log", {"text": str(text), "stream": stream})

    def _status(self, status, error=None):
        socketio.emit("algorithm-status",
                      {"status": status, "filename": self.filename, "error": error})

    def _check_stop(self):
        if self._stop.is_set():
            raise AlgorithmStopped()

    def _sleep(self, seconds: float):
        """Stop-aware sleep in 50 ms slices."""
        deadline = time.perf_counter() + max(0.0, float(seconds))
        while time.perf_counter() < deadline:
            self._check_stop()
            time.sleep(min(0.05, max(0.0, deadline - time.perf_counter())))
        self._check_stop()

    def _wait_for_state(self, want, timeout: float):
        """Block until controller state is one of `want` (or timeout)."""
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            self._check_stop()
            if controller.get_state() in want:
                return True
            time.sleep(0.05)
        return False

    # ---- premade function API exposed to scripts ----

    def _build_api(self):
        runner = self

        def log(*parts):
            runner._log(" ".join(str(p) for p in parts))

        def arm(drone_id=None):
            runner._check_stop()
            controller.cmd_arm(True)
            if not runner._wait_for_state(("READY",), timeout=5.0):
                raise RuntimeError("arm: controller did not reach READY within 5 s")
            log("armed")

        def disarm(drone_id=None):
            controller.cmd_arm(False)
            log("disarmed")

        def takeoff(z, drone_id=None):
            runner._check_stop()
            z = float(z)
            if not controller.is_armed():
                raise RuntimeError("takeoff: not armed — call arm() first")
            controller.cmd_takeoff(z)
            if not runner._wait_for_state(("HOVER",), timeout=20.0):
                raise RuntimeError("takeoff: did not reach HOVER within 20 s")
            log(f"hovering at {z:.2f} m")

        def land(drone_id=None):
            runner._check_stop()
            controller.cmd_land()
            runner._wait_for_state(("IDLE",), timeout=15.0)
            log("landed")

        def goto(x, y, z, drone_id=None):
            runner._check_stop()
            controller.cmd_setpoint(float(x), float(y), float(z))
            log(f"setpoint ({float(x):.2f}, {float(y):.2f}, {float(z):.2f})")

        def move(dx, dy, dz, drone_id=None):
            runner._check_stop()
            sx, sy, sz, _ = controller.get_setpoint()
            goto(sx + float(dx), sy + float(dy), sz + float(dz))

        def set_yaw(yaw, drone_id=None):
            runner._check_stop()
            controller.cmd_yaw(float(yaw))

        def wait(seconds):
            runner._sleep(seconds)

        def get_position(drone_id=None):
            pos = _current_position()
            return tuple(pos) if pos else None

        def get_battery(drone_id):
            mac = None
            with _fleet_lock:
                for d in _fleet:
                    if drone_id in (d["id"], d["name"]) or \
                       _normalise_mac(str(drone_id)) == d["mac"]:
                        mac = d["mac"]
                        break
            if mac is None:
                mac = _normalise_mac(str(drone_id))
            with _battery_lock:
                b = _battery.get(mac)
            return float(b["pct"]) if b else None

        def list_active():
            with _fleet_lock:
                return [d["id"] for d in _fleet if d["active"]]

        def get_state():
            return controller.get_state()

        def on_telemetry(callback):
            if callable(callback):
                runner._telemetry_callbacks.append(callback)

        return {
            "arm": arm, "disarm": disarm,
            "takeoff": takeoff, "land": land,
            "goto": goto, "move": move, "set_yaw": set_yaw,
            "wait": wait,
            "get_position": get_position, "get_battery": get_battery,
            "list_active": list_active, "get_state": get_state,
            "on_telemetry": on_telemetry,
            "log": log, "print": log,
        }

    def _run(self, code):
        self._status("running")
        self._log(f"--- {self.filename} started ---", stream="sys")
        try:
            exec(code, {"__name__": "__main__", **self._build_api()})
            self._log(f"--- {self.filename} finished ---", stream="sys")
            self._status("finished")
        except AlgorithmStopped:
            self._log(f"--- {self.filename} stopped by user ---", stream="sys")
            self._status("stopped")
        except Exception as e:
            self._log(f"ERROR: {type(e).__name__}: {e}", stream="err")
            self._status("error", error=f"{type(e).__name__}: {e}")
        finally:
            # Safety net: never leave the drone airborne or armed when the
            # script is done. Landing auto-disarms at touchdown.
            state = controller.get_state()
            if state in ("TAKEOFF", "HOVER"):
                self._log("safety: script ended while flying — landing", stream="sys")
                controller.cmd_land()
            elif state in ("ARMING", "READY"):
                self._log("safety: script ended while armed — disarming", stream="sys")
                controller.cmd_arm(False)


_algorithm_runner = AlgorithmRunner()


@socketio.on("algorithm-upload")
def on_algorithm_upload(data):
    """Receive a .py mission script and start executing it. The return value
    doubles as the socket.io ack payload for the frontend's callback."""
    if not isinstance(data, dict):
        return {"ok": False, "error": "bad payload"}
    filename = str(data.get("filename", "algorithm.py"))
    source = data.get("source")
    if not filename.lower().endswith(".py"):
        return {"ok": False, "error": "only .py files are supported"}
    if not isinstance(source, str) or not source.strip():
        return {"ok": False, "error": "empty script"}
    try:
        _algorithm_runner.start(filename, source)
        return {"ok": True}
    except ValueError as e:
        return {"ok": False, "error": str(e)}


@socketio.on("algorithm-stop")
def on_algorithm_stop(_data=None):
    if _algorithm_runner.running():
        _algorithm_runner.stop()
        return {"ok": True}
    return {"ok": False, "error": "no algorithm running"}


# =========================
# Flask routes
# =========================

@app.route("/")
def serve_index():
    """Serve the built React SPA entry point."""
    return app.send_static_file("index.html")


@app.errorhandler(404)
def spa_fallback(_e):
    """Client-side routing fallback. Real API/socket routes are matched before
    this, so any other 404 returns the SPA shell. Missing /api/* paths still
    return the shell, which is harmless for this local single-page app."""
    return app.send_static_file("index.html")


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
# Client tracking + idle auto-shutdown
# =========================
#
# When the last browser tab closes we exit after a grace period so the packaged
# app doesn't keep running invisibly. We NEVER shut down while a drone is armed
# or flying: closing a tab must not drop the control link mid-flight. A short
# grace also rides out an ordinary page refresh (disconnect + reconnect).

_client_lock = threading.Lock()
_client_count = 0
_idle_timer = None            # threading.Timer, guarded by _client_lock


def _controller_is_safe():
    """True when it's safe to stop the backend (no armed/airborne drone)."""
    try:
        return controller.get_state() == "IDLE" and not controller.is_armed()
    except Exception:
        return True


def _shutdown_now():
    print("[shutdown] no clients connected and controller idle - exiting", flush=True)
    try:
        cameras.stop()
    except Exception:
        pass
    # os._exit skips buffer flushing, so flush first or the log lines vanish
    # when stdout is redirected to a file.
    sys.stdout.flush()
    sys.stderr.flush()
    # Hard exit: from a background timer thread the Werkzeug server can't be
    # stopped cleanly, and a process exit reliably releases the TCP port, the
    # USB cameras and the serial port. Daemon threads die with the process.
    os._exit(0)


def _cancel_idle_timer_locked():
    global _idle_timer
    if _idle_timer is not None:
        _idle_timer.cancel()
        _idle_timer = None


def _arm_idle_timer_locked():
    global _idle_timer
    _cancel_idle_timer_locked()
    _idle_timer = threading.Timer(IDLE_SHUTDOWN_GRACE_S, _maybe_shutdown)
    _idle_timer.daemon = True
    _idle_timer.start()


def _maybe_shutdown():
    with _client_lock:
        if _client_count > 0:
            return  # a tab reconnected during the grace period
        if not _controller_is_safe():
            print("[shutdown] grace elapsed but a drone is armed/flying - "
                  "staying up (will re-check).", flush=True)
            _arm_idle_timer_locked()
            return
    _shutdown_now()


def _client_connected():
    global _client_count
    with _client_lock:
        _client_count += 1
        _cancel_idle_timer_locked()


def _client_disconnected():
    global _client_count
    with _client_lock:
        _client_count = max(0, _client_count - 1)
        if not (IDLE_SHUTDOWN_ENABLED and _client_count == 0):
            return
        _arm_idle_timer_locked()
    print(f"[shutdown] last tab closed - exiting in {IDLE_SHUTDOWN_GRACE_S:.0f}s "
          f"unless a tab reconnects or a drone is flying", flush=True)


# =========================
# SocketIO events
# =========================

@socketio.on("connect")
def on_connect():
    """Push pre-baked calibration to the frontend so it can draw camera wireframes."""
    _client_connected()
    poses = cameras.camera_poses_in_world()
    socketio.emit("camera-pose", {"camera_poses": poses})
    socketio.emit("to-world-coords-matrix",
                  {"to_world_coords_matrix": cameras.world_matrix_4x4_metres()})
    with _fleet_lock:
        socketio.emit("fleet", {"drones": list(_fleet),
                                "selected_mac": _selected_drone_mac})


@socketio.on("disconnect")
def on_disconnect():
    _client_disconnected()


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
        # If the selected drone was removed or deactivated by this edit,
        # fall back to the first active drone so the radio never keeps
        # pointing at a drone the UI says is gone/standby.
        sel = _selected_drone_mac
        still_valid = any(d["mac"] == sel and d["active"] for d in cleaned)
        fallback = next((d["mac"] for d in cleaned if d["active"]), None)
    if not still_valid and fallback is not None:
        _retarget_radio(fallback)
    _broadcast_fleet()


@socketio.on("mocap-select-drone")
def on_mocap_select_drone(data):
    """Switch the MoCap target. Forwards the MAC to the sender ESP32 as
    'M,<mac>\\n' so it re-aims its ESP-NOW peer."""
    if not isinstance(data, dict):
        return
    mac = _normalise_mac(str(data.get("mac", "")))
    if not _MAC_RE.match(mac):
        return
    with _fleet_lock:
        entry = next((d for d in _fleet if d["mac"] == mac), None)
    if entry is None:
        print(f"[mocap] refusing to select unknown MAC {mac}")
        return
    if not entry["active"]:
        print(f"[mocap] refusing to select standby drone {entry['name']} ({mac})")
        _broadcast_fleet()  # snap the requesting client back to the real selection
        return
    _retarget_radio(mac)
    _broadcast_fleet()
    print(f"[mocap] selected drone {entry['name']} ({mac})")


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
    global _current_pid
    if not (isinstance(data, dict) and "dronePID" in data):
        return
    gains = data["dronePID"]
    if not isinstance(gains, (list, tuple)) or len(gains) < 15:
        return
    with _pid_lock:
        _current_pid = [float(x) for x in gains[:17]]
        while len(_current_pid) < 17:
            _current_pid.append(0.0)
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
    # Sync the sender's radio target to our fleet at boot. force=True because
    # the sender may have kept running across a backend restart with a stale
    # target — we re-send the M-line even though we have no selection yet.
    with _fleet_lock:
        boot_mac = next((d["mac"] for d in _fleet if d["active"]), None)
    if boot_mac is not None:
        _retarget_radio(boot_mac, force=True)
        print(f"[boot] radio target -> {boot_mac}")
    cameras.start()
    threading.Thread(target=_heading_reader_loop, daemon=True, name="HeadingReader").start()
    threading.Thread(target=_control_loop, daemon=True, name="Control").start()
    threading.Thread(target=_emitter_loop, daemon=True, name="Emitter").start()


def _maybe_open_browser():
    """Open the local UI in the user's default browser once the server is up.
    Only for the packaged desktop app (or when explicitly requested), so it
    doesn't pop a browser while a developer runs the Vite dev server on :5173."""
    if not (FROZEN or os.environ.get("DRONESWARM_OPEN_BROWSER") == "1"):
        return
    url = f"http://127.0.0.1:{PORT}"
    print(f"[boot] opening browser at {url}")
    threading.Timer(1.5, lambda: _open_ui(url)).start()


if __name__ == "__main__":
    print(f"[boot] data dir: {DATA_DIR}")
    print(f"[boot] serving UI from: {DIST_DIR}")
    _start_background_threads()
    _maybe_open_browser()
    # debug=False -> no Werkzeug reloader (would spawn the threads twice)
    socketio.run(app, host=HOST, port=PORT, debug=False, allow_unsafe_werkzeug=True)
