"""
PC-side flight supervisor.

Owns the takeoff state machine but **no PIDs** -- the nested position/velocity
PID stack now lives on the drone-side ESP32-C3. This module turns
(world-frame filtered position, velocity, FC heading) into a tagged state
dict that the sender ESP32 forwards to the drone as a StatePacket.

Serial protocol the sender ESP32 expects:
    PC -> ESP : "S,x,y,z,vx,vy,vz,yaw_sp,x_sp,y_sp,z_sp,armed\n"
                ints/floats, all metric. armed is 0 or 1.
                "P,<17 floats>\n" pushes a PID + ground-effect gain update.
                "T,trim_t,trim_r,trim_p,trim_y\n" pushes trim.
    ESP -> PC : "H<yaw>\n"      float radians (sender heading bridge)

State machine
-------------
    IDLE      -> armed=0, setpoints = current pos, vel = 0
    ARMING    -> armed=1, setpoints = current pos (hold), real vel
    READY     -> armed=1, idle, waiting for cmd_takeoff()
    TAKEOFF   -> z setpoint ramps from 0 to target_z over TAKEOFF_RAMP_S;
                 xy + heading setpoints latched at entry
    HOVER     -> PID (on drone) holds (xy_target, z_target, heading_target)
    LANDING   -> z setpoint ramps to 0 over LANDING_RAMP_S, then disarm -> IDLE
    EMERGENCY -> immediate disarm (cmd_arm(False), z-error > Z_ERR_LIMIT_M
                 for Z_ERR_LIMIT_HOLD_S, or sustained dt > 0.5 s)
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional


# =========================
# Default tunables
# =========================

@dataclass
class ControlParams:
    # State-machine timings
    arming_hold_s: float = 0.3
    takeoff_ramp_s: float = 5.0
    landing_ramp_s: float = 1.5

    # Safety
    z_err_limit_m: float = 0.5
    z_err_limit_hold_s: float = 0.5


# =========================
# Sub-objects
# =========================

class State(str, Enum):
    IDLE = "IDLE"
    ARMING = "ARMING"
    READY = "READY"
    TAKEOFF = "TAKEOFF"
    HOVER = "HOVER"
    LANDING = "LANDING"
    EMERGENCY = "EMERGENCY"


@dataclass
class _Setpoint:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    heading: float = 0.0


# =========================
# Controller
# =========================

class Controller:
    def __init__(self, params: Optional[ControlParams] = None):
        self.p = params or ControlParams()
        self.state = State.IDLE
        self._state_entry_t = time.perf_counter()
        self._takeoff_target_z = 0.20

        # Endpoints of the z-ramp, latched on entry into TAKEOFF / LANDING.
        # This keeps the ramp continuous with the drone's actual altitude.
        self._takeoff_start_z = 0.0
        self._takeoff_z_latched = False
        self._landing_start_z = 0.0
        self._landing_z_latched = False

        # Latched setpoint (xy + heading captured at TAKEOFF entry; z ramped)
        self._sp = _Setpoint()

        # External-arm flag from PC ("arm-drone" socket event)
        self._armed_requested = False

        # Track sustained large z error -> EMERGENCY
        self._z_err_violation_since: Optional[float] = None

    # ----------------------------------------------------------------
    # Commands from PC / web UI
    # ----------------------------------------------------------------

    def cmd_arm(self, armed: bool):
        self._armed_requested = bool(armed)
        if not armed:
            self._go(State.IDLE)

    def cmd_takeoff(self, target_z: float = 0.20):
        if not self._armed_requested:
            return  # ignored when disarmed
        self._takeoff_target_z = float(target_z)
        if self.state in (State.READY, State.HOVER):
            self._go(State.TAKEOFF)

    def cmd_land(self):
        if self.state in (State.HOVER, State.TAKEOFF):
            self._go(State.LANDING)

    def cmd_setpoint(self, x: float, y: float, z: float):
        # Only retarget once stably hovering; otherwise stash for next HOVER entry.
        self._sp.x = float(x)
        self._sp.y = float(y)
        self._sp.z = float(z)

    def get_state(self) -> str:
        return self.state.value

    def is_armed(self) -> bool:
        return self._armed_requested and self.state not in (State.IDLE, State.EMERGENCY)

    # ----------------------------------------------------------------
    # Main per-tick entry
    # ----------------------------------------------------------------

    def step(self, pos, vel, heading: Optional[float], dt: float) -> dict:
        """
        pos:     np.array([x, y, z]) in metres, world frame (or None)
        vel:     np.array([vx, vy, vz]) in m/s, world frame (or None)
        heading: float, rad, FC yaw (or None if not yet received)
        dt:      seconds since previous step

        Returns: dict with keys x,y,z, vx,vy,vz, yaw_sp, x_sp,y_sp,z_sp, armed,
                 state. The caller serializes this as an "S" line to the
                 sender ESP32 (or uses controller.send_state() to do so).
        """
        # Safety: missing pose => EMERGENCY (FW failsafe will also fire after 500 ms)
        if pos is None or vel is None:
            self._go(State.EMERGENCY)
            return self._packet_safe()

        # Track live FC heading while idle/ready so the latched yaw setpoint
        # is "current heading" the instant TAKEOFF fires.
        if heading is not None and self.state in (State.IDLE, State.ARMING, State.READY):
            self._sp.heading = float(heading)

        # State transitions that aren't command-driven
        self._tick_state(pos)

        if self.state == State.IDLE or self.state == State.EMERGENCY:
            return self._packet_safe(pos=pos)

        if self.state == State.ARMING or self.state == State.READY:
            # Motors armed (FC arm switch HIGH) but PARKED -- throttle stays at
            # minimum on the drone side. Setpoint = current position so the
            # outer PIDs don't wind up.
            return self._packet(pos, vel, heading, armed=1,
                                sp_x=float(pos[0]), sp_y=float(pos[1]), sp_z=0.0)

        # TAKEOFF / HOVER / LANDING all stream the active latched setpoint
        # (with ramped z) to the drone-side PIDs. armed=2 unlocks the z PID
        # output -- the drone will actually fly.
        return self._packet(pos, vel, heading, armed=2,
                            sp_x=self._sp.x, sp_y=self._sp.y, sp_z=self._sp.z)

    # ----------------------------------------------------------------
    # State machine internals
    # ----------------------------------------------------------------

    def _go(self, new_state: State):
        if new_state == self.state:
            return
        self.state = new_state
        self._state_entry_t = time.perf_counter()
        self._z_err_violation_since = None
        if new_state == State.TAKEOFF:
            self._takeoff_z_latched = False    # latch fresh pos on first tick
        if new_state == State.LANDING:
            self._landing_z_latched = False

    def _state_age(self) -> float:
        return time.perf_counter() - self._state_entry_t

    def _tick_state(self, pos):
        # Disarm-overrides
        if not self._armed_requested:
            self._go(State.IDLE)
            return

        # Sustained Z-error -> EMERGENCY (TAKEOFF/HOVER only)
        if self.state in (State.TAKEOFF, State.HOVER):
            z_err = abs(pos[2] - self._sp.z)
            now = time.perf_counter()
            if z_err > self.p.z_err_limit_m:
                if self._z_err_violation_since is None:
                    self._z_err_violation_since = now
                elif now - self._z_err_violation_since > self.p.z_err_limit_hold_s:
                    self._go(State.EMERGENCY)
                    return
            else:
                self._z_err_violation_since = None

        # IDLE -> ARMING when PC requests armed
        if self.state == State.IDLE and self._armed_requested:
            # Latch xy at the LED's current position so HOVER works if we go
            # straight to takeoff without an explicit setpoint.
            self._sp.x = float(pos[0])
            self._sp.y = float(pos[1])
            self._sp.z = 0.0
            self._go(State.ARMING)
            return

        # ARMING -> READY after hold
        if self.state == State.ARMING and self._state_age() > self.p.arming_hold_s:
            self._go(State.READY)
            return

        # TAKEOFF z ramp: starts at the drone's CURRENT altitude (latched on
        # first tick) so the setpoint never lies below the drone -- otherwise
        # the z PID would briefly command a descent right after takeoff.
        if self.state == State.TAKEOFF:
            if not self._takeoff_z_latched:
                self._takeoff_start_z = float(pos[2])
                self._takeoff_z_latched = True
            a = self._state_age()
            frac = min(1.0, a / max(self.p.takeoff_ramp_s, 1e-3))
            self._sp.z = self._takeoff_start_z + frac * (self._takeoff_target_z - self._takeoff_start_z)
            if frac >= 1.0:
                self._sp.z = self._takeoff_target_z
                self._go(State.HOVER)
            return

        # LANDING z ramp: starts at the drone's CURRENT altitude (latched on
        # first tick) and goes to 0 over landing_ramp_s.
        if self.state == State.LANDING:
            if not self._landing_z_latched:
                self._landing_start_z = float(pos[2])
                self._landing_z_latched = True
            a = self._state_age()
            frac = min(1.0, a / max(self.p.landing_ramp_s, 1e-3))
            self._sp.z = self._landing_start_z * (1.0 - frac)
            if frac >= 1.0:
                self._sp.z = 0.0
                self._armed_requested = False  # cut motors at touchdown
                self._go(State.IDLE)
            return

    # ----------------------------------------------------------------
    # Packet builders
    # ----------------------------------------------------------------

    def _packet(self, pos, vel, heading, armed, sp_x, sp_y, sp_z) -> dict:
        return {
            "x":      float(pos[0]),
            "y":      float(pos[1]),
            "z":      float(pos[2]),
            "vx":     float(vel[0]),
            "vy":     float(vel[1]),
            "vz":     float(vel[2]),
            "yaw_sp": float(self._sp.heading),
            "x_sp":   float(sp_x),
            "y_sp":   float(sp_y),
            "z_sp":   float(sp_z),
            "armed":  int(armed),
            "state":  self.state.value,
        }

    def _packet_safe(self, pos=None) -> dict:
        # Disarmed: send setpoints == current position so the drone-side
        # integrators stay parked at zero error. Velocities zeroed.
        px = float(pos[0]) if pos is not None else 0.0
        py = float(pos[1]) if pos is not None else 0.0
        pz = float(pos[2]) if pos is not None else 0.0
        return {
            "x": px, "y": py, "z": pz,
            "vx": 0.0, "vy": 0.0, "vz": 0.0,
            "yaw_sp": float(self._sp.heading),
            "x_sp": px, "y_sp": py, "z_sp": pz,
            "armed": 0,
            "state": self.state.value,
        }

    # ----------------------------------------------------------------
    # Serial helpers
    # ----------------------------------------------------------------

    @staticmethod
    def serialize_state(pkt: dict) -> bytes:
        """Encode a step() dict as one S-line for the sender ESP32."""
        return (
            f"S,{pkt['x']:.4f},{pkt['y']:.4f},{pkt['z']:.4f},"
            f"{pkt['vx']:.4f},{pkt['vy']:.4f},{pkt['vz']:.4f},"
            f"{pkt['yaw_sp']:.4f},"
            f"{pkt['x_sp']:.4f},{pkt['y_sp']:.4f},{pkt['z_sp']:.4f},"
            f"{int(pkt['armed'])}\n"
        ).encode()

    @staticmethod
    def serialize_pid(gains_17) -> bytes:
        """Encode 17 floats (xy/z/yaw pos + xy/z vel + ground-effect 2)."""
        g = [float(x) for x in gains_17]
        if len(g) < 17:
            g = g + [0.0] * (17 - len(g))
        return ("P," + ",".join(f"{x:.6f}" for x in g[:17]) + "\n").encode()

    @staticmethod
    def serialize_trim(t: int, r: int, p: int, y: int) -> bytes:
        return f"T,{int(t)},{int(r)},{int(p)},{int(y)}\n".encode()


# =========================
# Smoke test
# =========================

def _smoke_test():
    """
    Run the controller through IDLE -> ARMING -> READY -> TAKEOFF -> HOVER ->
    LANDING -> IDLE with synthetic perfect-tracking positions, printing
    transitions + emitted state line.
    """
    import numpy as np

    c = Controller()
    pos = np.array([0.0, 0.0, 0.0], dtype=np.float32)
    vel = np.zeros(3, dtype=np.float32)
    heading = 0.0
    dt = 1.0 / 60.0

    def tick(label):
        pkt = c.step(pos.copy(), vel.copy(), heading, dt)
        line = Controller.serialize_state(pkt).decode().strip()
        print(f"  [{c.get_state():<9}] {label:<22} pos.z={pos[2]:+.3f}  "
              f"sp.z={pkt['z_sp']:+.3f}  armed={pkt['armed']}  -> {line}")

    print("Arming the drone...")
    c.cmd_arm(True)
    for _ in range(40):
        tick("idling")
        time.sleep(dt)

    print("Commanding takeoff to 0.20 m...")
    c.cmd_takeoff(0.20)
    for i in range(180):
        # Pretend the drone perfectly follows the z setpoint with a ~50 ms lag
        pos[2] += 0.5 * (c._sp.z - pos[2])
        tick("flying")
        time.sleep(dt)
        if i == 60:
            print("Commanding land...")
            c.cmd_land()

    for _ in range(60):
        pos[2] += 0.5 * (c._sp.z - pos[2])
        tick("landing")
        time.sleep(dt)

    print("Done.")


if __name__ == "__main__":
    _smoke_test()
