"""Unit tests: KalmanFilter.update / predict_only / _advance_dt (KalmanFilter.py).

Tested by: E/21/009 - Abeysekera L. B. B.

Test design (Step 1):
  Equivalence classes:
    update():       first call (initialisation) vs subsequent calls (fusion)
    predict_only(): initialised vs not-initialised; dt given vs dt=None
    input types:    list / tuple / np.ndarray of 3 numerics (same class)
  Boundaries (dt clamp in _advance_dt: [1e-3, 0.2] s):
    dt below 1 ms  -> clamped up to exactly 1e-3
    dt above 200 ms -> clamped down to exactly 0.2
    dt inside range -> used as-is
  Error/negative:
    measurement with wrong length (2 or 4 elems) -> ValueError
    non-numeric measurement -> ValueError
External dependencies mocked/stubbed:
  time.perf_counter (module-level in KalmanFilter) -> FakeClock
  LowPassFilter (velocity smoothing) -> identity stub in isolation test
  cv2.KalmanFilter -> real (deterministic numerics, no I/O)
"""

from unittest import mock

import numpy as np
import pytest

import KalmanFilter as kf_mod
from KalmanFilter import KalmanFilter, _transition


@pytest.fixture
def kf(fake_clock, monkeypatch):
    monkeypatch.setattr(kf_mod.time, "perf_counter", fake_clock)
    return KalmanFilter(), fake_clock


# ---------- equivalence: first update initialises ----------

def test_first_update_returns_measurement_and_zero_velocity(kf):
    f, _ = kf
    pos, vel = f.update([1.0, 2.0, 3.0])
    np.testing.assert_allclose(pos, [1.0, 2.0, 3.0], atol=1e-6)
    np.testing.assert_allclose(vel, [0.0, 0.0, 0.0], atol=1e-6)


def test_accepts_list_tuple_and_ndarray(kf):
    f, clock = kf
    for m in ([0.0, 0.0, 0.0], (0.1, 0.1, 0.1), np.array([0.2, 0.2, 0.2])):
        clock.advance(0.02)
        pos, vel = f.update(m)
        assert pos.shape == (3,) and vel.shape == (3,)


def test_stationary_target_converges_to_measurement(kf):
    f, clock = kf
    for _ in range(50):
        clock.advance(1.0 / 60.0)
        pos, vel = f.update([0.5, -0.5, 0.25])
    np.testing.assert_allclose(pos, [0.5, -0.5, 0.25], atol=1e-2)
    np.testing.assert_allclose(vel, [0.0, 0.0, 0.0], atol=5e-2)


def test_velocity_estimated_from_states_with_identity_lpf(fake_clock, monkeypatch):
    """Isolate the KF from the LPF: constant-velocity motion along x."""
    monkeypatch.setattr(kf_mod.time, "perf_counter", fake_clock)
    identity_lpf = mock.Mock()
    identity_lpf.filter.side_effect = lambda v: v
    identity_lpf.buffered_data = np.empty((0, 3))
    with mock.patch.object(kf_mod, "LowPassFilter", return_value=identity_lpf):
        f = KalmanFilter()
    x = 0.0
    for _ in range(100):
        fake_clock.advance(0.02)
        x += 0.02 * 1.0                        # 1 m/s along x
        pos, vel = f.update([x, 0.0, 0.0])
    assert vel[0] == pytest.approx(1.0, abs=0.15)
    assert identity_lpf.filter.called


# ---------- equivalence: predict_only ----------

def test_predict_only_before_init_returns_zeros(kf):
    f, _ = kf
    pos, vel = f.predict_only(0.02)
    np.testing.assert_allclose(pos, [0.0, 0.0, 0.0])
    np.testing.assert_allclose(vel, [0.0, 0.0, 0.0])


def test_predict_only_extrapolates_position(kf):
    f, clock = kf
    x = 0.0
    for _ in range(100):
        clock.advance(0.02)
        x += 0.02
        f.update([x, 0.0, 0.0])
    pos_before, _ = f.predict_only(0.1)
    assert pos_before[0] > x                   # moved forward with no new fix


# ---------- boundaries: dt clamp [1e-3, 0.2] ----------

def _dt_from_transition(f):
    return float(f._kf.transitionMatrix[0, 3])


def test_dt_clamped_up_to_1ms(kf):
    f, clock = kf
    f.update([0.0, 0.0, 0.0])
    clock.advance(0.0001)                      # 0.1 ms, below lower bound
    f.update([0.0, 0.0, 0.0])
    assert _dt_from_transition(f) == pytest.approx(1e-3)


def test_dt_clamped_down_to_200ms(kf):
    f, clock = kf
    f.update([0.0, 0.0, 0.0])
    clock.advance(5.0)                         # way above upper bound
    f.update([0.0, 0.0, 0.0])
    assert _dt_from_transition(f) == pytest.approx(0.2)


def test_dt_inside_range_used_exactly(kf):
    f, clock = kf
    f.update([0.0, 0.0, 0.0])
    clock.advance(0.05)                        # inside [1e-3, 0.2]
    f.update([0.0, 0.0, 0.0])
    assert _dt_from_transition(f) == pytest.approx(0.05)


def test_transition_matrix_kinematics():
    F = _transition(0.1)
    assert F[0, 3] == pytest.approx(0.1)       # x += vx*dt
    assert F[0, 6] == pytest.approx(0.005)     # x += 0.5*ax*dt^2
    assert F[8, 8] == 1.0


# ---------- error / negative ----------

@pytest.mark.parametrize("bad", [[1.0, 2.0], [1.0, 2.0, 3.0, 4.0], []])
def test_wrong_measurement_length_raises(kf, bad):
    f, _ = kf
    with pytest.raises(ValueError):
        f.update(bad)


def test_non_numeric_measurement_raises(kf):
    f, _ = kf
    with pytest.raises(ValueError):
        f.update(["a", "b", "c"])


def test_reset_returns_filter_to_uninitialised(kf):
    f, clock = kf
    f.update([1.0, 1.0, 1.0])
    f.reset()
    pos, vel = f.predict_only(0.02)
    np.testing.assert_allclose(pos, [0.0, 0.0, 0.0])
    p2, v2 = f.update([2.0, 2.0, 2.0])         # re-initialises
    np.testing.assert_allclose(p2, [2.0, 2.0, 2.0], atol=1e-6)
