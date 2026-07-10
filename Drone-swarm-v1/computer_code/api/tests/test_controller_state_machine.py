"""Unit tests: Controller.step() / state machine (controller.py).

Tested by: E/21/156 - Gunaratne I. A. T. A.

Test design (Step 1):
  Equivalence classes for `state`:
    C1 disarmed  -> IDLE / EMERGENCY   (packet armed=0)
    C2 armed-parked -> ARMING / READY  (packet armed=1, z_sp=0)
    C3 flying    -> TAKEOFF / HOVER / LANDING (packet armed=2, latched sp)
  Equivalence classes for `pos`/`vel`: valid ndarray vs None (fault).
  Boundaries:
    arming_hold_s = 0.3 s  (exactly on -> stay ARMING; just over -> READY)
    takeoff ramp frac = 1.0 (z_sp == target exactly, TAKEOFF -> HOVER)
    landing ramp frac = 1.0 (z_sp == 0, disarm, -> IDLE)
    z_err_limit_m = 0.5    (== limit is safe; > limit starts violation timer)
    z_err_limit_hold_s = 0.5 (violation must be sustained strictly longer)
  Error/negative:
    pos=None or vel=None -> EMERGENCY safe packet
    cmd_takeoff() while disarmed -> ignored
External dependency mocked: time.perf_counter (module-level in controller).
"""

import numpy as np
import pytest

import controller as controller_mod
from controller import Controller, State


POS0 = np.array([0.1, -0.2, 0.0], dtype=np.float32)
VEL0 = np.zeros(3, dtype=np.float32)
DT = 1.0 / 60.0


@pytest.fixture
def ctl(fake_clock, monkeypatch):
    """Controller wired to a fake, manually-advanced clock."""
    monkeypatch.setattr(controller_mod.time, "perf_counter", fake_clock)
    return Controller(), fake_clock


# ---------- C1: disarmed ----------

def test_initial_state_is_idle_and_disarmed(ctl):
    c, _ = ctl
    pkt = c.step(POS0, VEL0, 0.0, DT)
    assert c.get_state() == "IDLE"
    assert pkt["armed"] == 0
    assert not c.is_armed()


def test_idle_packet_setpoints_track_current_position(ctl):
    c, _ = ctl
    pkt = c.step(POS0, VEL0, 0.0, DT)
    assert (pkt["x_sp"], pkt["y_sp"], pkt["z_sp"]) == pytest.approx(
        (float(POS0[0]), float(POS0[1]), float(POS0[2]))
    )
    assert (pkt["vx"], pkt["vy"], pkt["vz"]) == (0.0, 0.0, 0.0)


def test_cmd_takeoff_ignored_when_disarmed(ctl):
    c, _ = ctl
    c.cmd_takeoff(0.5)
    c.step(POS0, VEL0, 0.0, DT)
    assert c.get_state() == "IDLE"


# ---------- C2: armed-parked (ARMING / READY) ----------

def test_arm_transitions_idle_to_arming_and_latches_xy(ctl):
    c, _ = ctl
    c.cmd_arm(True)
    pkt = c.step(POS0, VEL0, 0.0, DT)
    assert c.get_state() == "ARMING"
    assert pkt["armed"] == 1
    assert pkt["z_sp"] == 0.0
    assert c.get_setpoint()[0] == pytest.approx(float(POS0[0]))
    assert c.get_setpoint()[1] == pytest.approx(float(POS0[1]))


def test_arming_hold_boundary_exactly_on_stays_arming(ctl):
    c, clock = ctl
    c.cmd_arm(True)
    c.step(POS0, VEL0, 0.0, DT)          # -> ARMING at t0
    clock.advance(0.3)                   # exactly arming_hold_s (uses >)
    c.step(POS0, VEL0, 0.0, DT)
    assert c.get_state() == "ARMING"


def test_arming_hold_boundary_just_over_goes_ready(ctl):
    c, clock = ctl
    c.cmd_arm(True)
    c.step(POS0, VEL0, 0.0, DT)
    clock.advance(0.301)                 # just past the boundary
    c.step(POS0, VEL0, 0.0, DT)
    assert c.get_state() == "READY"


# ---------- C3: flying (TAKEOFF / HOVER / LANDING) ----------

def _arm_to_ready(c, clock):
    c.cmd_arm(True)
    c.step(POS0, VEL0, 0.0, DT)
    clock.advance(0.31)
    c.step(POS0, VEL0, 0.0, DT)
    assert c.get_state() == "READY"


def test_takeoff_ramp_reaches_target_exactly_then_hover(ctl):
    c, clock = ctl
    _arm_to_ready(c, clock)
    c.cmd_takeoff(0.20)
    c.step(POS0, VEL0, 0.0, DT)          # latch start z (frac ~ 0)
    clock.advance(5.0)                   # == takeoff_ramp_s -> frac = 1.0
    pkt = c.step(POS0, VEL0, 0.0, DT)
    assert c.get_state() == "HOVER"
    assert pkt["z_sp"] == pytest.approx(0.20)
    assert pkt["armed"] == 2


def test_takeoff_ramp_midpoint_is_half_target(ctl):
    c, clock = ctl
    _arm_to_ready(c, clock)
    c.cmd_takeoff(0.20)
    c.step(POS0, VEL0, 0.0, DT)          # entry tick, start z = 0.0
    clock.advance(2.5)                   # half of takeoff_ramp_s
    pkt = c.step(POS0, VEL0, 0.0, DT)
    assert c.get_state() == "TAKEOFF"
    assert pkt["z_sp"] == pytest.approx(0.10, abs=1e-3)


def test_landing_completes_disarms_and_returns_idle(ctl):
    c, clock = ctl
    _arm_to_ready(c, clock)
    c.cmd_takeoff(0.20)
    c.step(POS0, VEL0, 0.0, DT)
    clock.advance(5.1)
    pos_up = np.array([0.1, -0.2, 0.20], dtype=np.float32)
    c.step(pos_up, VEL0, 0.0, DT)        # HOVER
    c.cmd_land()
    c.step(pos_up, VEL0, 0.0, DT)        # LANDING, latch start z
    clock.advance(1.5)                   # == landing_ramp_s -> frac = 1.0
    pkt = c.step(pos_up, VEL0, 0.0, DT)
    assert c.get_state() == "IDLE"
    assert pkt["armed"] == 0
    assert not c.is_armed()


# ---------- Safety boundaries ----------

def test_z_error_exactly_at_limit_is_safe(ctl):
    c, clock = ctl
    _arm_to_ready(c, clock)
    c.cmd_takeoff(0.20)
    c.step(POS0, VEL0, 0.0, DT)
    clock.advance(5.1)
    hover_pos = np.array([0.1, -0.2, 0.20], dtype=np.float32)
    c.step(hover_pos, VEL0, 0.0, DT)     # HOVER, sp.z = 0.20
    # |z - sp.z| == 0.5 exactly: guard uses strict >, so no violation timer
    edge_pos = np.array([0.1, -0.2, 0.70], dtype=np.float32)
    c.step(edge_pos, VEL0, 0.0, DT)
    clock.advance(1.0)
    c.step(edge_pos, VEL0, 0.0, DT)
    assert c.get_state() == "HOVER"


def test_sustained_z_error_over_limit_triggers_emergency(ctl):
    c, clock = ctl
    _arm_to_ready(c, clock)
    c.cmd_takeoff(0.20)
    c.step(POS0, VEL0, 0.0, DT)
    clock.advance(5.1)
    hover_pos = np.array([0.1, -0.2, 0.20], dtype=np.float32)
    c.step(hover_pos, VEL0, 0.0, DT)     # HOVER
    bad_pos = np.array([0.1, -0.2, 0.85], dtype=np.float32)  # err = 0.65 > 0.5
    c.step(bad_pos, VEL0, 0.0, DT)       # violation timer starts
    clock.advance(0.51)                  # sustained just past hold_s
    pkt = c.step(bad_pos, VEL0, 0.0, DT)
    assert c.get_state() == "EMERGENCY"
    assert pkt["armed"] == 0


def test_transient_z_error_recovers_without_emergency(ctl):
    c, clock = ctl
    _arm_to_ready(c, clock)
    c.cmd_takeoff(0.20)
    c.step(POS0, VEL0, 0.0, DT)
    clock.advance(5.1)
    hover_pos = np.array([0.1, -0.2, 0.20], dtype=np.float32)
    c.step(hover_pos, VEL0, 0.0, DT)
    bad_pos = np.array([0.1, -0.2, 0.85], dtype=np.float32)
    c.step(bad_pos, VEL0, 0.0, DT)       # violation starts
    clock.advance(0.4)                   # < hold_s, then recovers
    c.step(hover_pos, VEL0, 0.0, DT)
    clock.advance(1.0)
    c.step(hover_pos, VEL0, 0.0, DT)
    assert c.get_state() == "HOVER"


# ---------- Error / negative cases ----------

def test_missing_pose_forces_emergency_safe_packet(ctl):
    c, _ = ctl
    c.cmd_arm(True)
    c.step(POS0, VEL0, 0.0, DT)
    pkt = c.step(None, VEL0, 0.0, DT)
    assert c.get_state() == "EMERGENCY"
    assert pkt["armed"] == 0
    assert (pkt["vx"], pkt["vy"], pkt["vz"]) == (0.0, 0.0, 0.0)


def test_missing_velocity_forces_emergency(ctl):
    c, _ = ctl
    c.cmd_arm(True)
    c.step(POS0, VEL0, 0.0, DT)
    c.step(POS0, None, 0.0, DT)
    assert c.get_state() == "EMERGENCY"


def test_disarm_from_any_state_returns_idle(ctl):
    c, clock = ctl
    _arm_to_ready(c, clock)
    c.cmd_arm(False)
    assert c.get_state() == "IDLE"
    assert not c.is_armed()
