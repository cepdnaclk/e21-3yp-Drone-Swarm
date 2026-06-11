"""
4-USB-camera bright-spot tracker, refactored from live_3d_tracker_world.py.

Owns:
  - 4 ThreadedCamera capture loops
  - Per-frame bright-spot detection + undistortion + pairwise triangulation
  - cam1 -> world transform (scale, R, t)
  - A worker thread that publishes (latest_world_xyz_m, grid_jpeg_bytes) into
    a lock-guarded slot for the backend to consume at its own cadence.

Calibration files live in `<this_dir>/calibration/` by default:
    camera_{1..4}_params_new.json
    cam{2..4}_relative_to_cam1.npz
    cam1_to_world_transform.npz

The raw triangulation + cam1_to_world output is assumed to be in millimetres
(matching the DISPLAY_IN_METERS=True convention in live_3d_tracker_world.py).
This module converts to METRES at the public API boundary so the rest of the
backend (Kalman, controller, takeoff target = 0.20 m) works in SI units.
"""

import os
import json
import time
import threading
from itertools import combinations

import cv2 as cv
import numpy as np


# =========================
# DEFAULTS (override via constructor args / env)
# =========================

DEFAULT_CAMERA_INDICES = [1, 2, 4, 3]
DEFAULT_CAMERA_NAMES = ["cam1", "cam2", "cam3", "cam4"]
DEFAULT_CAM_WIDTH = 640
DEFAULT_CAM_HEIGHT = 480

DEFAULT_THRESHOLD = 180
DEFAULT_MIN_BLOB_AREA = 3
DEFAULT_MAX_BLOB_AREA = 5000


# =========================
# Threaded camera (lifted verbatim, minor tidy)
# =========================

class ThreadedCamera:
    def __init__(self, src, width, height):
        self.src = src
        self.width = width
        self.height = height
        self.cap = None
        self.ret = False
        self.frame = None
        self.running = True
        self.lock = threading.Lock()
        self.fail_count = 0

        self._open_camera()

        self.thread = threading.Thread(target=self._update, daemon=True)
        self.thread.start()

    def _open_camera(self):
        if self.cap is not None:
            self.cap.release()
            time.sleep(0.5)

        print(f"[tracker] opening camera {self.src}")
        self.cap = cv.VideoCapture(self.src, cv.CAP_DSHOW)

        self.cap.set(cv.CAP_PROP_FOURCC, cv.VideoWriter_fourcc(*'MJPG'))
        self.cap.set(cv.CAP_PROP_FPS, 15)
        self.cap.set(cv.CAP_PROP_FRAME_WIDTH, self.width)
        self.cap.set(cv.CAP_PROP_FRAME_HEIGHT, self.height)
        self.cap.set(cv.CAP_PROP_BUFFERSIZE, 1)

        if not self.cap.isOpened():
            print(f"[tracker] WARNING: camera {self.src} failed to open")
            return False

        time.sleep(0.5)
        ret, frame = self.cap.read()

        with self.lock:
            self.ret = ret
            self.frame = frame if ret else None

        print(f"[tracker] camera {self.src} reopen status: {ret}")
        return ret

    def _update(self):
        while self.running:
            if self.cap is None or not self.cap.isOpened():
                print(f"[tracker] camera {self.src} is not opened, reopening...")
                self._open_camera()
                time.sleep(1)
                continue

            ret, frame = self.cap.read()

            if not ret or frame is None:
                self.fail_count += 1
                print(f"[tracker] camera {self.src} lost frame {self.fail_count}")

                if self.fail_count >= 30:
                    print(f"[tracker] reopening camera {self.src}")
                    self._open_camera()
                    self.fail_count = 0

                time.sleep(0.05)
                continue

            self.fail_count = 0

            with self.lock:
                self.ret = ret
                self.frame = frame

    def read(self):
        with self.lock:
            if self.frame is None:
                return False, None
            return self.ret, self.frame.copy()

    def stop(self):
        self.running = False
        self.thread.join(timeout=1.0)
        if self.cap is not None:
            self.cap.release()
# =========================
# Calibration loaders
# =========================

def _load_intrinsics(calib_dir):
    intrinsics = []
    for cam_num in range(1, 5):
        path = os.path.join(calib_dir, f"camera_{cam_num}_params_new.json")
        if not os.path.exists(path):
            raise FileNotFoundError(f"Missing intrinsic file: {path}")
        with open(path, "r") as f:
            data = json.load(f)
        intrinsics.append({
            "K": np.array(data["intrinsic_matrix"], dtype=np.float64),
            "D": np.array(data["distortion_coef"], dtype=np.float64),
        })
    return intrinsics


def _load_extrinsics(calib_dir):
    """Return list of {R_cam_to_cam1, C_cam1} for cams 1..4; cam1 is identity."""
    extrinsics = [{
        "R_cam_to_cam1": np.eye(3, dtype=np.float64),
        "C_cam1": np.zeros((3, 1), dtype=np.float64),
    }]
    for cam_num in range(2, 5):
        path = os.path.join(calib_dir, f"cam{cam_num}_relative_to_cam1.npz")
        if not os.path.exists(path):
            raise FileNotFoundError(f"Missing extrinsic file: {path}")
        data = np.load(path)
        extrinsics.append({
            "R_cam_to_cam1": np.array(data["R"], dtype=np.float64),
            "C_cam1": np.array(data["t"], dtype=np.float64).reshape(3, 1),
        })
    return extrinsics


def _load_world_transform(calib_dir):
    """world_point_mm = scale * R @ cam1_point + t (returns floats / 3x3 / 3x1)."""
    path = os.path.join(calib_dir, "cam1_to_world_transform.npz")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Missing world transform file: {path}")
    data = np.load(path)
    scale = float(data["scale"])
    R = np.array(data["R"], dtype=np.float64)
    t = np.array(data["t"], dtype=np.float64).reshape(3, 1)
    return scale, R, t


def _build_projection(R_cam_to_cam1, C_cam1):
    """P = [R_cam1_to_cam | t_cam1_to_cam], for use with undistorted normalised points."""
    R_cam1_to_cam = R_cam_to_cam1.T
    t_cam1_to_cam = -R_cam1_to_cam @ C_cam1
    return np.hstack((R_cam1_to_cam, t_cam1_to_cam))


# =========================
# Detection + triangulation
# =========================

def _detect_bright_spot(frame, threshold, min_area, max_area):
    gray = cv.cvtColor(frame, cv.COLOR_BGR2GRAY)
    blurred = cv.GaussianBlur(gray, (5, 5), 0)
    _, mask = cv.threshold(blurred, threshold, 255, cv.THRESH_BINARY)
    kernel = np.ones((3, 3), np.uint8)
    mask = cv.morphologyEx(mask, cv.MORPH_OPEN, kernel)
    mask = cv.morphologyEx(mask, cv.MORPH_DILATE, kernel)

    contours, _ = cv.findContours(mask, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
    best_point = None
    best_area = 0
    for contour in contours:
        area = cv.contourArea(contour)
        if area < min_area or area > max_area:
            continue
        if area > best_area:
            M = cv.moments(contour)
            if M["m00"] > 0:
                cx = int(M["m10"] / M["m00"])
                cy = int(M["m01"] / M["m00"])
                best_point = (cx, cy)
                best_area = area
    return best_point


def _undistort_point(pt, K, D):
    pts = np.array([[[pt[0], pt[1]]]], dtype=np.float64)
    u = cv.undistortPoints(pts, K, D)
    return np.array([[u[0, 0, 0]], [u[0, 0, 1]]], dtype=np.float64)


def _triangulate_pair(P1, P2, p1, p2):
    pt4 = cv.triangulatePoints(P1, P2, p1, p2)
    return (pt4[:3] / pt4[3]).reshape(3)


def _triangulate_from_detected(detected, intrinsics, projections):
    """`detected` is {cam_idx: (cx, cy)}. Returns mean of all pairwise estimates, or None."""
    if len(detected) < 2:
        return None
    points_3d = []
    cam_ids = list(detected.keys())
    for c1, c2 in combinations(cam_ids, 2):
        p1n = _undistort_point(detected[c1], intrinsics[c1]["K"], intrinsics[c1]["D"])
        p2n = _undistort_point(detected[c2], intrinsics[c2]["K"], intrinsics[c2]["D"])
        points_3d.append(_triangulate_pair(projections[c1], projections[c2], p1n, p2n))
    if not points_3d:
        return None
    return np.mean(points_3d, axis=0)


def _cam1_to_world_mm(point_cam1, scale, R, t):
    pt = np.asarray(point_cam1, dtype=np.float64).reshape(3, 1)
    return (scale * R @ pt + t).reshape(3)


# =========================
# UI helpers (for the MJPEG grid)
# =========================

def _annotate(frame, label, point, threshold):
    cv.putText(frame, label, (10, 30), cv.FONT_HERSHEY_SIMPLEX,
               0.8, (255, 255, 255), 2)
    if point is not None:
        cv.drawMarker(frame, point, (0, 255, 0), cv.MARKER_CROSS, 18, 2)
        cv.circle(frame, point, 8, (0, 255, 0), 2)
    else:
        cv.putText(frame, "NO LED", (10, 60), cv.FONT_HERSHEY_SIMPLEX,
                   0.7, (0, 0, 255), 2)
    cv.putText(frame, f"th:{threshold}", (10, frame.shape[0] - 10),
               cv.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
    return frame


def _make_grid(frames, half_w, half_h):
    resized = [cv.resize(f, (half_w, half_h)) for f in frames]
    top = np.hstack((resized[0], resized[1]))
    bot = np.hstack((resized[2], resized[3]))
    return np.vstack((top, bot))


# =========================
# Public Tracker
# =========================

class Tracker:
    def __init__(
        self,
        calibration_dir=None,
        camera_indices=None,
        cam_width=DEFAULT_CAM_WIDTH,
        cam_height=DEFAULT_CAM_HEIGHT,
        threshold=DEFAULT_THRESHOLD,
        min_blob_area=DEFAULT_MIN_BLOB_AREA,
        max_blob_area=DEFAULT_MAX_BLOB_AREA,
    ):
        base = os.path.dirname(os.path.abspath(__file__))
        self.calibration_dir = calibration_dir or os.path.join(base, "calibration")
        self.camera_indices = camera_indices or list(DEFAULT_CAMERA_INDICES)
        self.cam_width = cam_width
        self.cam_height = cam_height
        self.threshold = threshold
        self.min_blob_area = min_blob_area
        self.max_blob_area = max_blob_area

        # Calibration
        self.intrinsics = _load_intrinsics(self.calibration_dir)
        self.extrinsics = _load_extrinsics(self.calibration_dir)
        self.projections = [
            _build_projection(e["R_cam_to_cam1"], e["C_cam1"]) for e in self.extrinsics
        ]
        self.world_scale, self.world_R, self.world_t = _load_world_transform(self.calibration_dir)

        # Runtime
        self._cameras = []
        self._worker = None
        self._running = False
        self._lock = threading.Lock()
        self._latest_xyz_m = None       # np.array(3,) or None
        self._latest_jpeg = b""
        self._latest_fix_id = 0         # increments each new triangulation
        self._fps_ema = 0.0
        self._last_tick = 0.0

    # ---- lifecycle ----

    def start(self):
        if self._running:
            return
        print(f"[tracker] opening cameras at indices {self.camera_indices}")
        self._cameras = []

        for idx in self.camera_indices:
            self._cameras.append(ThreadedCamera(idx, self.cam_width, self.cam_height))
            time.sleep(1)
        time.sleep(0.5)  # let cameras warm up
        self._running = True
        self._worker = threading.Thread(target=self._loop, daemon=True)
        self._worker.start()
        print("[tracker] worker thread started")

    def stop(self):
        self._running = False
        if self._worker is not None:
            self._worker.join(timeout=1.0)
            self._worker = None
        for c in self._cameras:
            c.stop()
        self._cameras = []

    # ---- public read API ----

    def latest(self):
        """Returns (world_xyz_m_or_None, grid_jpeg_bytes). Thread-safe snapshot."""
        with self._lock:
            xyz = None if self._latest_xyz_m is None else self._latest_xyz_m.copy()
            return xyz, self._latest_jpeg

    def latest_xyz_m(self):
        with self._lock:
            return None if self._latest_xyz_m is None else self._latest_xyz_m.copy()

    def latest_xyz_m_with_id(self):
        """Returns (xyz_or_None, fix_id). `fix_id` increments each new triangulation;
        the control loop uses it to tell 'new fix' from 'no update this tick'."""
        with self._lock:
            xyz = None if self._latest_xyz_m is None else self._latest_xyz_m.copy()
            return xyz, self._latest_fix_id

    def fps(self):
        with self._lock:
            return self._fps_ema

    def set_threshold(self, value):
        self.threshold = int(np.clip(value, 0, 255))

    # ---- frontend wireframe helpers ----

    def camera_poses_in_world(self):
        """
        Returns list of {"R": [[..]], "t": [..]} per camera, in WORLD coordinates.
        R = camera-axes-in-world (orthonormal).
        t = camera center in world, METRES.
        Suitable for drawing camera wireframes in a 3D scene.
        """
        poses = []
        s = self.world_scale
        Rw = self.world_R
        tw = self.world_t  # 3x1 mm
        for ext in self.extrinsics:
            R_cam_to_cam1 = ext["R_cam_to_cam1"]
            C_cam1 = ext["C_cam1"]  # 3x1 (mm-equivalent in cam1 units)
            # Camera center in world frame, mm
            C_world_mm = (s * Rw @ C_cam1 + tw).reshape(3)
            # Camera axes in world frame (scale is a uniform isotropic scalar -> drops out)
            R_cam_to_world = Rw @ R_cam_to_cam1
            poses.append({
                "R": R_cam_to_world.tolist(),
                "t": (C_world_mm / 1000.0).tolist(),
            })
        return poses

    def world_matrix_4x4_metres(self):
        """4x4 transform that takes cam1 points in cam1 units to world METRES."""
        T = np.eye(4)
        T[:3, :3] = self.world_scale * self.world_R / 1000.0  # mm -> m
        T[:3, 3] = (self.world_t / 1000.0).reshape(3)
        return T.tolist()

    # ---- internals ----

    def _loop(self):
        # Pre-allocated black placeholder for failed reads
        black = np.zeros((self.cam_height, self.cam_width, 3), dtype=np.uint8)

        # JPEG encode params (smaller = faster, fine for monitor video)
        jpeg_params = [int(cv.IMWRITE_JPEG_QUALITY), 70]

        half_w = self.cam_width // 2
        half_h = self.cam_height // 2

        self._last_tick = time.perf_counter()
        last_hb_t = time.perf_counter()
        fix_count = 0
        detect_count = [0] * len(self._cameras)
        loop_count = 0

        while self._running:
            frames = []
            detected = {}
            loop_count += 1

            for i, cam in enumerate(self._cameras):
                ok, frame = cam.read()
                if not ok or frame is None:
                    frame = black.copy()
                    cv.putText(frame, f"{DEFAULT_CAMERA_NAMES[i]} ERROR",
                               (20, 40), cv.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
                    frames.append(frame)
                    continue

                point = _detect_bright_spot(
                    frame, self.threshold, self.min_blob_area, self.max_blob_area
                )
                if point is not None:
                    detected[i] = point
                    detect_count[i] += 1

                _annotate(frame, DEFAULT_CAMERA_NAMES[i], point, self.threshold)
                frames.append(frame)

            # Triangulate
            xyz_m = None
            pt_cam1 = _triangulate_from_detected(detected, self.intrinsics, self.projections)
            if pt_cam1 is not None:
                pt_world_mm = _cam1_to_world_mm(
                    pt_cam1, self.world_scale, self.world_R, self.world_t
                )
                xyz_m = pt_world_mm / 1000.0  # mm -> m
                fix_count += 1

            # Build grid + JPEG
            grid = _make_grid(frames, half_w, half_h)
            ok, jpeg = cv.imencode(".jpg", grid, jpeg_params)
            jpeg_bytes = jpeg.tobytes() if ok else b""

            # FPS EMA
            now = time.perf_counter()
            dt = now - self._last_tick
            self._last_tick = now
            inst = 1.0 / dt if dt > 1e-6 else 0.0
            self._fps_ema = 0.9 * self._fps_ema + 0.1 * inst if self._fps_ema else inst

            with self._lock:
                self._latest_xyz_m = xyz_m
                self._latest_jpeg = jpeg_bytes
                if xyz_m is not None:
                    self._latest_fix_id += 1

            # Once per second, print what each camera is seeing + last world xyz
            if now - last_hb_t > 1.0:
                hb_age = now - last_hb_t
                last_hb_t = now
                cams_str = " ".join(
                    f"c{i}:{detect_count[i]}" for i in range(len(self._cameras))
                )
                xyz_str = (
                    f"pos=({xyz_m[0]:+.3f},{xyz_m[1]:+.3f},{xyz_m[2]:+.3f})m"
                    if xyz_m is not None else "pos=<no fix>"
                )
                print(f"[tracker] {loop_count/hb_age:.0f}Hz loops/s  "
                      f"detect/s {cams_str}  fixes/s={fix_count/hb_age:.0f}  {xyz_str}")
                detect_count = [0] * len(self._cameras)
                fix_count = 0
                loop_count = 0


# =========================
# Standalone smoke test
# =========================

def _smoke_test():
    """Spin the tracker for 10 s and print fps + the latest world point."""
    print("Starting Tracker smoke test...")
    t = Tracker()
    print(f"  calibration_dir = {t.calibration_dir}")
    print(f"  camera_indices  = {t.camera_indices}")
    print(f"  world_scale     = {t.world_scale}")
    t.start()
    try:
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < 10.0:
            xyz, _ = t.latest()
            if xyz is None:
                print(f"  fps={t.fps():.1f}  pos=<no LED>")
            else:
                print(f"  fps={t.fps():.1f}  pos=({xyz[0]:+.3f}, {xyz[1]:+.3f}, {xyz[2]:+.3f}) m")
            time.sleep(0.25)
    finally:
        t.stop()
        print("Tracker stopped.")


if __name__ == "__main__":
    _smoke_test()
