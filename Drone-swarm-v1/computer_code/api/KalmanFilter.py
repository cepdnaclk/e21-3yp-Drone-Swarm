"""
Single-object 9-state Kalman filter (constant-acceleration model) for fusing
the world-frame position stream from `tracker.py`.

State:        [x, y, z,  vx, vy, vz,  ax, ay, az]   (metres, m/s, m/s^2)
Measurement:  [x, y, z]                              (metres)

Velocity comes out of the filter as a state estimate -- no finite differences
on the raw measurement.

Call pattern from the control loop:
    pos, vel = kf.update(world_xyz_m)             # when tracker has a new fix
    pos, vel = kf.predict_only(dt)                # when it does not
"""

import time
import numpy as np
import cv2 as cv

from LowPassFilter import LowPassFilter


_STATE_DIM = 9
_MEAS_DIM = 3


def _transition(dt):
    """Constant-acceleration state-transition matrix for state above."""
    F = np.eye(_STATE_DIM, dtype=np.float32)
    F[0, 3] = dt
    F[1, 4] = dt
    F[2, 5] = dt
    F[3, 6] = dt
    F[4, 7] = dt
    F[5, 8] = dt
    F[0, 6] = 0.5 * dt * dt
    F[1, 7] = 0.5 * dt * dt
    F[2, 8] = 0.5 * dt * dt
    return F


class KalmanFilter:
    def __init__(
        self,
        process_noise=1e-3,
        measurement_noise=1e-3,
        vel_lpf_cutoff_hz=15.0,
        vel_lpf_fs_hz=60.0,
    ):
        self._kf = cv.KalmanFilter(_STATE_DIM, _MEAS_DIM)
        self._kf.transitionMatrix = _transition(1.0 / vel_lpf_fs_hz)
        self._kf.measurementMatrix = np.zeros((_MEAS_DIM, _STATE_DIM), dtype=np.float32)
        self._kf.measurementMatrix[0, 0] = 1.0
        self._kf.measurementMatrix[1, 1] = 1.0
        self._kf.measurementMatrix[2, 2] = 1.0

        self._kf.processNoiseCov = np.eye(_STATE_DIM, dtype=np.float32) * process_noise
        self._kf.measurementNoiseCov = np.eye(_MEAS_DIM, dtype=np.float32) * measurement_noise
        self._kf.errorCovPost = np.eye(_STATE_DIM, dtype=np.float32) * 1.0
        self._kf.statePost = np.zeros((_STATE_DIM, 1), dtype=np.float32)

        self._initialised = False
        self._last_t = time.perf_counter()

        # Smooth the velocity output a touch; raw KF velocity at 30 Hz tracker
        # can be jittery enough to make the inner-loop vel-PID grumpy.
        self._vel_lpf = LowPassFilter(
            cutoff_frequency=vel_lpf_cutoff_hz,
            sampling_frequency=vel_lpf_fs_hz,
            dims=3,
        )

    # ------------- public API -------------

    def update(self, world_xyz_m):
        """Inject a new position measurement; advance state; return (pos, vel)."""
        xyz = np.asarray(world_xyz_m, dtype=np.float32).reshape(3)

        if not self._initialised:
            self._kf.statePost[0:3, 0] = xyz
            self._kf.statePost[3:, 0] = 0.0
            self._initialised = True
            self._last_t = time.perf_counter()
            return xyz.copy(), np.zeros(3, dtype=np.float32)

        dt = self._advance_dt()
        self._kf.predict()
        self._kf.correct(xyz.reshape(_MEAS_DIM, 1))

        return self._extract()

    def predict_only(self, dt=None):
        """No new measurement this tick; extrapolate. Returns (pos, vel)."""
        if not self._initialised:
            return np.zeros(3, dtype=np.float32), np.zeros(3, dtype=np.float32)

        if dt is None:
            dt = self._advance_dt()
        else:
            self._kf.transitionMatrix = _transition(float(dt))
            self._last_t = time.perf_counter()

        self._kf.predict()
        # No correct() -- just read state.
        return self._extract()

    def reset(self):
        self._kf.statePost = np.zeros((_STATE_DIM, 1), dtype=np.float32)
        self._kf.errorCovPost = np.eye(_STATE_DIM, dtype=np.float32) * 1.0
        self._initialised = False
        self._last_t = time.perf_counter()
        # Drop the LPF history so old velocity samples don't bleed in.
        self._vel_lpf.buffered_data = self._vel_lpf.buffered_data[:0]

    # ------------- internals -------------

    def _advance_dt(self):
        now = time.perf_counter()
        dt = max(1e-3, min(0.2, now - self._last_t))  # clamp [1ms, 200ms]
        self._last_t = now
        self._kf.transitionMatrix = _transition(dt)
        return dt

    def _extract(self):
        pos = self._kf.statePost[0:3, 0].copy()
        vel_raw = self._kf.statePost[3:6, 0].copy()
        vel_filt = self._vel_lpf.filter(vel_raw.astype(np.float64)).astype(np.float32)
        return pos, vel_filt
