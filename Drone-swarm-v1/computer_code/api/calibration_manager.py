"""
Camera-calibration wizard backend.

Runs the pipeline that previously lived in loose scripts under
`localization_4cam/`, as one guided session:

    1. intrinsics   capture checkerboard images per camera, cv.calibrateCamera
                    -> camera_{N}_params_new.json
                    (port of intrinsic_calibration_single_camera.py)
    2. extrinsics   capture synchronized 4-cam checkerboard sets, solvePnP per
                    set, average the poses relative to cam1
                    -> cam{2..4}_relative_to_cam1.npz
                    (port of EX_CAL.py's capture UI +
                     relative_extrinsics_from_saved_images.py; the unused
                     camN_extrinsics.npz step is dropped)
    3. landmarks    live-triangulate the LED at known world points, fit a
                    similarity transform  world = scale * R @ cam1 + t
                    -> world_landmarks.json + cam1_to_world_transform.npz
                    (replaces hand-editing world_landmarks.json +
                     compute_world_transform.py)
    4. verify       live world-coordinate tracking on the STAGED calibration;
                    the user either accepts (promote to current_calibration/,
                    previous set kept in calibration_backup/) or cancels.

A session can start from any step; earlier artifacts are copied from
current_calibration/ into the staging folder so the staged set is always
complete and self-consistent. Restarting is allowed from any session step
>= the chosen start step; that step's and all later staged artifacts are
cleared (changing a step invalidates everything downstream). Cancel discards
the staging folder entirely and restarts the normal tracker.

While a session is active the caller (index.py) stops the tracker, pauses the
control loop and refuses flight/algorithm commands; this module owns the USB
cameras for the whole session.

All linear units are MILLIMETRES (matching the original scripts); the verify
step also reports metres. Sessions do not survive a backend restart — staging
is wiped on the next start.
"""

import glob
import json
import os
import re
import shutil
import threading
import time
from datetime import datetime
from itertools import combinations

import cv2 as cv
import numpy as np

from tracker import (
    ThreadedCamera,
    _build_projection,
    _detect_bright_spot,
    _triangulate_from_detected,
)

# =========================
# Constants
# =========================

STEPS = ["intrinsics", "extrinsics", "landmarks", "verify"]
NUM_CAMERAS = 4

MIN_INTRINSIC_IMAGES = 10       # cv.calibrateCamera lower bound (script used 10)
RECOMMENDED_INTRINSIC_IMAGES = 15
MIN_EXTRINSIC_SETS = 5
RECOMMENDED_EXTRINSIC_SETS = 10
MIN_LANDMARKS = 3
RECOMMENDED_LANDMARKS = 5

DEFAULT_CHECKERBOARD = (9, 6)   # inner corners (cols, rows)
DEFAULT_SQUARE_SIZE_MM = 23.9

INTRINSIC_FILES = [f"camera_{n}_params_new.json" for n in range(1, 5)]
EXTRINSIC_FILES = [f"cam{n}_relative_to_cam1.npz" for n in range(2, 5)]
WORLD_FILES = ["cam1_to_world_transform.npz"]

STREAM_HZ = 15.0
STATUS_HZ = 4.0
LOG_CAP = 300                   # lines kept per step

MIN_BLOB_AREA = 3
MAX_BLOB_AREA = 5000


# =========================
# Pure pipeline functions (ported from the localization_4cam scripts;
# module-level so they can be exercised against recorded data in tests)
# =========================

def create_object_points(checkerboard, square_size_mm):
    objp = np.zeros((checkerboard[0] * checkerboard[1], 3), np.float32)
    objp[:, :2] = np.mgrid[0:checkerboard[0], 0:checkerboard[1]].T.reshape(-1, 2)
    objp *= square_size_mm
    return objp


def detect_corners(img, checkerboard):
    gray = cv.cvtColor(img, cv.COLOR_BGR2GRAY)
    found, corners = cv.findChessboardCornersSB(
        gray, checkerboard,
        cv.CALIB_CB_NORMALIZE_IMAGE | cv.CALIB_CB_EXHAUSTIVE)
    return found, corners


def calibrate_intrinsics_from_folder(folder, checkerboard, square_size_mm, log):
    """Port of intrinsic_calibration_single_camera.calibrate_intrinsics().
    Returns (params_dict, result_dict) or raises ValueError."""
    objp = create_object_points(checkerboard, square_size_mm)
    object_points, image_points = [], []
    per_image = []
    image_size = None

    image_paths = sorted(glob.glob(os.path.join(folder, "*.jpg")))
    log(f"Found {len(image_paths)} images")

    for path in image_paths:
        name = os.path.basename(path)
        img = cv.imread(path)
        if img is None:
            log(f"[LOAD FAIL] {name}")
            per_image.append({"name": name, "ok": False})
            continue
        image_size = (img.shape[1], img.shape[0])
        found, corners = detect_corners(img, checkerboard)
        if found:
            object_points.append(objp)
            image_points.append(corners)
            per_image.append({"name": name, "ok": True})
            log(f"[OK] {name}")
        else:
            per_image.append({"name": name, "ok": False})
            log(f"[FAIL] {name}")

    if len(object_points) < MIN_INTRINSIC_IMAGES:
        raise ValueError(
            f"only {len(object_points)} valid checkerboard images — need at "
            f"least {MIN_INTRINSIC_IMAGES} (use {RECOMMENDED_INTRINSIC_IMAGES}-25 good ones)")

    rms_error, K, dist, _rvecs, _tvecs = cv.calibrateCamera(
        object_points, image_points, image_size, None, None)

    params = {
        "intrinsic_matrix": K.tolist(),
        "distortion_coef": dist.tolist(),
        "rms_error": float(rms_error),
        "image_size": {"width": int(image_size[0]), "height": int(image_size[1])},
        "valid_images": int(len(object_points)),
        "square_size": float(square_size_mm),
    }
    result = {
        "rms_error": float(rms_error),
        "fx": float(K[0, 0]), "fy": float(K[1, 1]),
        "cx": float(K[0, 2]), "cy": float(K[1, 2]),
        "distortion": [float(x) for x in np.ravel(dist)],
        "valid_images": int(len(object_points)),
        "total_images": len(image_paths),
        "image_size": [int(image_size[0]), int(image_size[1])],
        "per_image": per_image,
    }
    log(f"RMS error: {rms_error:.4f}")
    log(f"fx={K[0,0]:.2f} fy={K[1,1]:.2f} cx={K[0,2]:.2f} cy={K[1,2]:.2f}")
    return params, result


def load_intrinsics_json(path):
    with open(path, "r") as f:
        data = json.load(f)
    K = np.array(data["intrinsic_matrix"], dtype=np.float32)
    dist = np.array(data["distortion_coef"], dtype=np.float32)
    return K, dist


def solve_pose(img_path, objp, K, dist, checkerboard):
    """Port of relative_extrinsics_from_saved_images.solve_pose()."""
    img = cv.imread(img_path)
    if img is None:
        return None, None, None
    found, corners = detect_corners(img, checkerboard)
    if not found:
        return None, None, None
    success, rvec, tvec = cv.solvePnP(objp, corners, K, dist)
    if not success:
        return None, None, None
    R, _ = cv.Rodrigues(rvec)
    projected, _ = cv.projectPoints(objp, rvec, tvec, K, dist)
    error = cv.norm(corners, projected, cv.NORM_L2) / len(projected)
    return R, tvec, error


def camera_position_in_ref_frame(R_ref, t_ref, R_cam, t_cam):
    """solvePnP gives X_camera = R @ X_board + t; returns cam pose in the
    reference camera's frame (port of the original helper)."""
    R_ref_cam = R_ref @ R_cam.T
    t_ref_cam = t_ref - R_ref @ R_cam.T @ t_cam
    return R_ref_cam, t_ref_cam


def average_rotation(R_list):
    R_mean = np.mean(R_list, axis=0)
    U, _, Vt = np.linalg.svd(R_mean)
    R_avg = U @ Vt
    if np.linalg.det(R_avg) < 0:
        U[:, -1] *= -1
        R_avg = U @ Vt
    return R_avg


def compute_relative_extrinsics(image_folder, intrinsics_by_cam, checkerboard,
                                square_size_mm, log):
    """Port of relative_extrinsics_from_saved_images.py. `intrinsics_by_cam`
    maps "cam1".."cam4" -> (K, dist). Returns (npz_data, results) where
    npz_data maps "cam2".."cam4" -> {"R","t"} ready to save."""
    cameras = [f"cam{n}" for n in range(1, 5)]
    ref = "cam1"
    objp = create_object_points(checkerboard, square_size_mm)

    all_sets = set()
    for cam in cameras:
        for path in glob.glob(os.path.join(image_folder, f"{cam}_*.jpg")):
            m = re.match(rf"{cam}_(\d+)\.jpg", os.path.basename(path))
            if m:
                all_sets.add(int(m.group(1)))
    set_numbers = sorted(all_sets)
    log(f"Found image set numbers: {set_numbers}")
    if not set_numbers:
        raise ValueError("no saved image sets found")

    relative_R = {cam: [] for cam in cameras if cam != ref}
    relative_t = {cam: [] for cam in cameras if cam != ref}
    set_rows = []

    for number in set_numbers:
        log(f"========== SET {number} ==========")
        poses, errors = {}, {}
        valid_set = True
        for cam in cameras:
            img_path = os.path.join(image_folder, f"{cam}_{number}.jpg")
            if not os.path.exists(img_path):
                log(f"[MISSING] {cam}_{number}.jpg")
                valid_set = False
                break
            K, dist = intrinsics_by_cam[cam]
            R, t, error = solve_pose(img_path, objp, K, dist, checkerboard)
            if R is None:
                log(f"[FAIL] {cam}_{number}.jpg")
                valid_set = False
                break
            poses[cam] = (R, t)
            errors[cam] = error
            log(f"[OK] {cam}_{number}.jpg | error = {error:.4f}")

        row = {"set": number, "valid": valid_set,
               "errors": {c: (float(errors[c]) if c in errors else None) for c in cameras},
               "distances_mm": {}}
        if not valid_set:
            log("[SKIPPED SET]")
            set_rows.append(row)
            continue

        R_ref, t_ref = poses[ref]
        for cam in cameras:
            if cam == ref:
                continue
            R_cam, t_cam = poses[cam]
            R_rel, t_rel = camera_position_in_ref_frame(R_ref, t_ref, R_cam, t_cam)
            distance = float(np.linalg.norm(t_rel))
            row["distances_mm"][cam] = distance
            log(f"{cam} relative distance in set {number}: {distance:.2f} mm")
            relative_R[cam].append(R_rel)
            relative_t[cam].append(t_rel)
        set_rows.append(row)

    npz_data = {}
    per_cam = {}
    log("=========== FINAL RELATIVE EXTRINSICS ===========")
    for cam in cameras:
        if cam == ref:
            continue
        if len(relative_R[cam]) == 0:
            raise ValueError(f"no valid relative poses for {cam} — capture more sets")
        R_avg = average_rotation(relative_R[cam])
        t_avg = np.mean(relative_t[cam], axis=0)
        npz_data[cam] = {"R": R_avg, "t": t_avg}
        distance = float(np.linalg.norm(t_avg))
        per_cam[cam] = {
            "t_mm": [float(x) for x in np.ravel(t_avg)],
            "distance_from_cam1_mm": distance,
            "sets_used": len(relative_R[cam]),
        }
        log(f"{cam} relative to {ref}: distance {distance:.2f} mm "
            f"({len(relative_R[cam])} sets)")

    positions = {ref: np.zeros((3, 1))}
    for cam, d in npz_data.items():
        positions[cam] = d["t"]
    pair_distances = {}
    log("=========== CAMERA DISTANCES ===========")
    for i in range(len(cameras)):
        for j in range(i + 1, len(cameras)):
            a, b = cameras[i], cameras[j]
            dist_ab = float(np.linalg.norm(positions[a] - positions[b]))
            pair_distances[f"{a}-{b}"] = dist_ab
            log(f"{a} <-> {b}: {dist_ab:.2f} mm")

    valid_sets = sum(1 for r in set_rows if r["valid"])
    results = {
        "sets_total": len(set_numbers),
        "sets_valid": valid_sets,
        "per_set": set_rows,
        "per_cam": per_cam,
        "pair_distances_mm": pair_distances,
    }
    return npz_data, results


def estimate_similarity_transform(cam_points, world_points, allow_scale=True):
    """Port of compute_world_transform.estimate_similarity_transform():
    finds world = scale * R @ cam + t."""
    cam_points = np.asarray(cam_points, dtype=np.float64)
    world_points = np.asarray(world_points, dtype=np.float64)
    assert cam_points.shape == world_points.shape
    assert cam_points.shape[1] == 3

    cam_centroid = np.mean(cam_points, axis=0)
    world_centroid = np.mean(world_points, axis=0)
    cam_centered = cam_points - cam_centroid
    world_centered = world_points - world_centroid

    H = cam_centered.T @ world_centered
    U, S, Vt = np.linalg.svd(H)
    R = Vt.T @ U.T
    if np.linalg.det(R) < 0:
        Vt[-1, :] *= -1
        R = Vt.T @ U.T

    if allow_scale:
        cam_var = np.sum(cam_centered ** 2)
        scale = np.sum(S) / cam_var
    else:
        scale = 1.0

    t = world_centroid.reshape(3, 1) - scale * R @ cam_centroid.reshape(3, 1)
    return scale, R, t


def compute_world_transform(landmarks, log):
    """Port of compute_world_transform.main(). `landmarks` is a list of
    {"name", "cam1", "world"} in mm. Returns (npz_data, results)."""
    if len(landmarks) < MIN_LANDMARKS:
        raise ValueError(f"need at least {MIN_LANDMARKS} landmarks")
    names = [lm["name"] for lm in landmarks]
    cam_points = np.array([lm["cam1"] for lm in landmarks], dtype=np.float64)
    world_points = np.array([lm["world"] for lm in landmarks], dtype=np.float64)

    scale, R, t = estimate_similarity_transform(cam_points, world_points,
                                                allow_scale=True)
    log("========== CAM1 TO WORLD TRANSFORM ==========")
    log(f"scale = {scale:.6f}")

    per_landmark = []
    errors = []
    log("========== LANDMARK ERRORS ==========")
    for name, cam_pt, world_pt in zip(names, cam_points, world_points):
        predicted = (scale * R @ cam_pt.reshape(3, 1) + t).reshape(3)
        error = float(np.linalg.norm(predicted - world_pt))
        errors.append(error)
        per_landmark.append({
            "name": name,
            "world_mm": [float(x) for x in world_pt],
            "predicted_mm": [float(x) for x in predicted],
            "error_mm": error,
        })
        log(f"{name}: expected {np.round(world_pt, 1).tolist()} "
            f"predicted {np.round(predicted, 1).tolist()} error {error:.2f} mm")

    mean_err = float(np.mean(errors))
    max_err = float(np.max(errors))
    log(f"Mean error: {mean_err:.2f} mm")
    log(f"Max error: {max_err:.2f} mm")

    npz_data = {"scale": scale, "R": R, "t": t}
    results = {
        "scale": float(scale),
        "mean_error_mm": mean_err,
        "max_error_mm": max_err,
        "per_landmark": per_landmark,
    }
    return npz_data, results


def staged_camera_poses_in_world(extrinsics, world_scale, world_R, world_t):
    """Port of Tracker.camera_poses_in_world() for staged data: R = camera
    axes in world, t = camera centre in world METRES."""
    poses = []
    for ext in extrinsics:
        C_cam1 = ext["C_cam1"]
        C_world_mm = (world_scale * world_R @ C_cam1 + world_t).reshape(3)
        R_cam_to_world = world_R @ ext["R_cam_to_cam1"]
        poses.append({
            "R": R_cam_to_world.tolist(),
            "t": (C_world_mm / 1000.0).tolist(),
        })
    return poses


def staged_world_matrix_4x4_metres(world_scale, world_R, world_t):
    T = np.eye(4)
    T[:3, :3] = world_scale * world_R / 1000.0
    T[:3, 3] = (world_t / 1000.0).reshape(3)
    return T.tolist()


# =========================
# Staged-calibration loaders (schema-identical to tracker's, but kept local so
# partial staging folders produce friendly errors)
# =========================

def _load_staged_intrinsics(staging_dir):
    intrinsics = []
    for n in range(1, 5):
        path = os.path.join(staging_dir, f"camera_{n}_params_new.json")
        if not os.path.exists(path):
            raise ValueError(f"missing staged intrinsics for camera {n}")
        with open(path, "r") as f:
            data = json.load(f)
        intrinsics.append({
            "K": np.array(data["intrinsic_matrix"], dtype=np.float64),
            "D": np.array(data["distortion_coef"], dtype=np.float64),
        })
    return intrinsics


def _load_staged_extrinsics(staging_dir):
    extrinsics = [{
        "R_cam_to_cam1": np.eye(3, dtype=np.float64),
        "C_cam1": np.zeros((3, 1), dtype=np.float64),
    }]
    for n in range(2, 5):
        path = os.path.join(staging_dir, f"cam{n}_relative_to_cam1.npz")
        if not os.path.exists(path):
            raise ValueError(f"missing staged extrinsics for camera {n}")
        data = np.load(path)
        extrinsics.append({
            "R_cam_to_cam1": np.array(data["R"], dtype=np.float64),
            "C_cam1": np.array(data["t"], dtype=np.float64).reshape(3, 1),
        })
    return extrinsics


def _load_staged_world(staging_dir):
    path = os.path.join(staging_dir, "cam1_to_world_transform.npz")
    if not os.path.exists(path):
        raise ValueError("missing staged world transform")
    data = np.load(path)
    return (float(data["scale"]),
            np.array(data["R"], dtype=np.float64),
            np.array(data["t"], dtype=np.float64).reshape(3, 1))


# =========================
# Manager
# =========================

class CalibrationManager:
    """One instance per backend. All public methods return ack-shaped dicts
    ({"ok": True, ...} / {"ok": False, "error": ...}) and are safe to call
    from socketio handler threads."""

    def __init__(self, base_dir, socketio, hooks):
        """`hooks` supplies the couplings to the rest of the backend:
            stop_tracker()            release the tracker's cameras
            start_tracker()           resume normal tracking
            reload_tracker()          re-read current_calibration files
            emit_tracker_poses()      re-broadcast camera-pose/world-matrix
            get_camera_indices() -> [int]*4
            get_thresholds()     -> [int]*4
            get_drone_state()    -> str  (controller state)
            algorithm_running()  -> bool
        """
        self.base_dir = base_dir
        self.current_dir = os.path.join(base_dir, "current_calibration")
        self.staging_dir = os.path.join(base_dir, "calibration_staging")
        self.backup_dir = os.path.join(base_dir, "calibration_backup")
        self.socketio = socketio
        self.hooks = hooks

        self._lock = threading.RLock()
        self._jpeg_lock = threading.Lock()
        self._corner_lock = threading.Lock()

        self._token = 0              # bumped on start/cancel/accept; stale workers discard
        self._threads_running = False
        self._cameras = []
        self._latest_jpeg = b""
        self._placeholder_jpeg = None

        self._reset_session_fields()

    # ---------------- session field helpers ----------------

    def _reset_session_fields(self):
        self.active = False
        self.phase = "idle"          # idle | starting | ready | applying
        self.step = None
        self.start_step = None
        self.checkerboard = DEFAULT_CHECKERBOARD
        self.square_size_mm = DEFAULT_SQUARE_SIZE_MM
        self.camera_indices = None
        self.cameras_ok = [False] * NUM_CAMERAS
        self.detect_flags = [False] * NUM_CAMERAS
        self.busy = None             # label of running compute, or None
        self.error = None
        self.last_event = None       # "accepted" | "cancelled" | None
        self.active_cam = 1
        self.intr_counts = [0] * NUM_CAMERAS
        self.intr_calibrated = [False] * NUM_CAMERAS
        self.intr_results = {}       # cam number (int) -> result dict
        self.ext_sets = 0
        self.ext_computed = False
        self.ext_results = None
        self.landmarks = []          # [{"name","cam1","world"}]
        self.lm_computed = False
        self.lm_results = None
        self.thresholds = [180] * NUM_CAMERAS
        self.live_cam1_mm = None
        self.live_world_mm = None
        self.staged_poses = None     # verify 3D payload
        self.staged_world_matrix = None
        self.logs = {s: [] for s in STEPS}
        self._staged_intr = None     # loaded staged calibration for live triangulation
        self._staged_proj = None
        self._staged_world = None
        self._corner_cache = {}      # cam idx -> (found, corners)
        self._lm_sampling = False
        self._lm_samples = []

    # ---------------- logging / status ----------------

    def _log(self, step, text):
        with self._lock:
            lines = self.logs.setdefault(step, [])
            lines.append(text)
            if len(lines) > LOG_CAP:
                del lines[:len(lines) - LOG_CAP]
        try:
            self.socketio.emit("calibration-log", {"step": step, "text": text})
        except Exception:
            pass

    def current_info(self):
        """Summary of current_calibration/ for the idle screen."""
        files = {}
        newest = 0.0
        for name in INTRINSIC_FILES + EXTRINSIC_FILES + WORLD_FILES:
            path = os.path.join(self.current_dir, name)
            if os.path.exists(path):
                mtime = os.path.getmtime(path)
                newest = max(newest, mtime)
                files[name] = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
            else:
                files[name] = None
        info = None
        info_path = os.path.join(self.current_dir, "calibration_info.json")
        if os.path.exists(info_path):
            try:
                with open(info_path, "r") as f:
                    info = json.load(f)
            except (OSError, json.JSONDecodeError):
                info = None
        return {
            "files": files,
            "complete": all(v is not None for v in files.values()),
            "newest": (datetime.fromtimestamp(newest).strftime("%Y-%m-%d %H:%M")
                       if newest else None),
            "info": info,
        }

    def status(self):
        with self._lock:
            return {
                "active": self.active,
                "phase": self.phase,
                "step": self.step,
                "start_step": self.start_step,
                "steps": STEPS,
                "params": {
                    "checkerboard": list(self.checkerboard),
                    "square_size_mm": self.square_size_mm,
                },
                "camera_indices": self.camera_indices,
                "cameras_ok": list(self.cameras_ok),
                "detect": list(self.detect_flags),
                "busy": self.busy,
                "error": self.error,
                "last_event": self.last_event,
                "intrinsics": {
                    "active_cam": self.active_cam,
                    "counts": list(self.intr_counts),
                    "calibrated": list(self.intr_calibrated),
                    "results": {str(k): v for k, v in self.intr_results.items()},
                    "min_images": MIN_INTRINSIC_IMAGES,
                    "recommended_images": RECOMMENDED_INTRINSIC_IMAGES,
                },
                "extrinsics": {
                    "sets": self.ext_sets,
                    "computed": self.ext_computed,
                    "results": self.ext_results,
                    "min_sets": MIN_EXTRINSIC_SETS,
                    "recommended_sets": RECOMMENDED_EXTRINSIC_SETS,
                },
                "landmarks": {
                    "points": [dict(p) for p in self.landmarks],
                    "computed": self.lm_computed,
                    "results": self.lm_results,
                    "live_cam1_mm": self.live_cam1_mm,
                    "thresholds": list(self.thresholds),
                    "min_points": MIN_LANDMARKS,
                    "recommended_points": RECOMMENDED_LANDMARKS,
                },
                "verify": {
                    "live_cam1_mm": self.live_cam1_mm,
                    "live_world_mm": self.live_world_mm,
                    "live_world_m": ([v / 1000.0 for v in self.live_world_mm]
                                     if self.live_world_mm else None),
                    "camera_poses": self.staged_poses,
                    "world_matrix": self.staged_world_matrix,
                },
                "logs": {s: list(lines) for s, lines in self.logs.items()},
                "current_info": self.current_info(),
            }

    def _push_status(self):
        try:
            self.socketio.emit("calibration-status", self.status())
        except Exception:
            pass

    # ---------------- lifecycle ----------------

    def start(self, start_from, checkerboard, square_size_mm):
        with self._lock:
            if self.active:
                return {"ok": False, "error": "a calibration session is already active"}
            if start_from not in STEPS[:3]:
                return {"ok": False, "error": f"cannot start from step '{start_from}'"}
            try:
                cols, rows = int(checkerboard[0]), int(checkerboard[1])
                square = float(square_size_mm)
            except (TypeError, ValueError, IndexError):
                return {"ok": False, "error": "bad checkerboard/square size values"}
            if not (2 <= cols <= 30 and 2 <= rows <= 30):
                return {"ok": False, "error": "checkerboard corners must be 2..30"}
            if cols == rows:
                return {"ok": False, "error":
                        "checkerboard must be asymmetric (cols != rows), e.g. 9x6"}
            if not (1.0 <= square <= 200.0):
                return {"ok": False, "error": "square size must be 1..200 mm"}

            state = self.hooks["get_drone_state"]()
            if state not in ("IDLE",):
                return {"ok": False, "error":
                        f"drone must be IDLE to calibrate (state: {state})"}
            if self.hooks["algorithm_running"]():
                return {"ok": False, "error":
                        "an algorithm is running — stop it before calibrating"}

            # Fresh staging folder + prerequisites from current calibration
            try:
                if os.path.isdir(self.staging_dir):
                    shutil.rmtree(self.staging_dir)
                os.makedirs(self.staging_dir)
                self._copy_prereqs(start_from)
            except ValueError as e:
                shutil.rmtree(self.staging_dir, ignore_errors=True)
                return {"ok": False, "error": str(e)}
            except OSError as e:
                return {"ok": False, "error": f"staging folder error: {e}"}

            self._reset_session_fields()
            self.active = True
            self.phase = "starting"
            self.step = start_from
            self.start_step = start_from
            self.checkerboard = (cols, rows)
            self.square_size_mm = square
            self.camera_indices = list(self.hooks["get_camera_indices"]())
            self.thresholds = list(self.hooks["get_thresholds"]())
            self._token += 1
            token = self._token

        self._log(start_from, f"--- session started from step '{start_from}' ---")
        self._log(start_from,
                  f"checkerboard {cols}x{rows} inner corners, square {square} mm")
        self._push_status()

        # Release the tracker's USB cameras before opening our own captures.
        try:
            self.hooks["stop_tracker"]()
        except Exception as e:
            print(f"[calib] tracker stop failed: {e}")

        threading.Thread(target=self._start_worker, args=(token,),
                         daemon=True, name="CalibStart").start()
        return {"ok": True}

    def _copy_prereqs(self, start_from):
        """Copy artifacts for steps before `start_from` from current_calibration
        into staging. Raises ValueError listing anything missing."""
        needed = []
        if start_from in ("extrinsics", "landmarks"):
            needed += INTRINSIC_FILES
        if start_from == "landmarks":
            needed += EXTRINSIC_FILES
        missing = [n for n in needed
                   if not os.path.exists(os.path.join(self.current_dir, n))]
        if missing:
            raise ValueError(
                "current calibration is missing files required to start from "
                f"'{start_from}': {', '.join(missing)} — start from an earlier step")
        for name in needed:
            shutil.copy2(os.path.join(self.current_dir, name),
                         os.path.join(self.staging_dir, name))

    def _start_worker(self, token):
        """Open the 4 cameras (slow on Windows/DSHOW) then mark the session
        ready. The tracker was already stopped by index.py before start()."""
        indices = list(self.camera_indices)
        cams = []
        for idx in indices:
            with self._lock:
                if self._token != token:      # cancelled while starting
                    for c in cams:
                        c.stop()
                    return
            print(f"[calib] opening camera {idx}")
            cams.append(ThreadedCamera(idx, 640, 480))
            time.sleep(1.0)

        with self._lock:
            if self._token != token:
                for c in cams:
                    c.stop()
                return
            self._cameras = cams
            self.phase = "ready"
            self._threads_running = True
            step = self.step

        # If the session starts at landmarks, the staged intrinsics+extrinsics
        # must be loaded for live triangulation right away.
        if step == "landmarks":
            err = self._load_staged_for_step("landmarks")
            if err:
                with self._lock:
                    self.error = err

        threading.Thread(target=self._stream_loop, args=(token,),
                         daemon=True, name="CalibStream").start()
        threading.Thread(target=self._detect_loop, args=(token,),
                         daemon=True, name="CalibDetect").start()
        threading.Thread(target=self._status_loop, args=(token,),
                         daemon=True, name="CalibStatus").start()
        self._log(step, f"cameras opened at indices {indices}")
        self._push_status()

    def _teardown_cameras(self):
        self._threads_running = False
        cams, self._cameras = self._cameras, []
        for c in cams:
            try:
                c.stop()
            except Exception:
                pass

    def cancel(self):
        with self._lock:
            if not self.active:
                return {"ok": False, "error": "no active session"}
            self._token += 1
            self.active = False
            self.phase = "applying"
        self._push_status()

        self._teardown_cameras()
        shutil.rmtree(self.staging_dir, ignore_errors=True)
        try:
            self.hooks["start_tracker"]()
        except Exception as e:
            print(f"[calib] tracker restart after cancel failed: {e}")
        with self._lock:
            self._reset_session_fields()
            self.last_event = "cancelled"
        self._push_status()
        print("[calib] session cancelled, staging discarded")
        return {"ok": True}

    def accept(self):
        with self._lock:
            if not self.active:
                return {"ok": False, "error": "no active session"}
            if self.step != "verify":
                return {"ok": False, "error": "finish all steps before accepting"}
            if self.busy:
                return {"ok": False, "error": f"busy: {self.busy}"}
            self._token += 1
            self.active = False
            self.phase = "applying"
            summary = {
                "accepted_at": datetime.now().isoformat(timespec="seconds"),
                "start_step": self.start_step,
                "params": {"checkerboard": list(self.checkerboard),
                           "square_size_mm": self.square_size_mm},
                "intrinsics_rms": {str(c): r.get("rms_error")
                                   for c, r in self.intr_results.items()},
                "extrinsics": ({"pair_distances_mm": self.ext_results.get("pair_distances_mm"),
                                "sets_valid": self.ext_results.get("sets_valid")}
                               if self.ext_results else None),
                "landmarks": ({"mean_error_mm": self.lm_results.get("mean_error_mm"),
                               "max_error_mm": self.lm_results.get("max_error_mm"),
                               "count": len(self.landmarks)}
                              if self.lm_results else None),
            }
        self._push_status()
        self._teardown_cameras()

        try:
            # Rolling backup of the outgoing calibration
            if os.path.isdir(self.current_dir):
                shutil.rmtree(self.backup_dir, ignore_errors=True)
                shutil.copytree(self.current_dir, self.backup_dir)
            os.makedirs(self.current_dir, exist_ok=True)

            promoted = INTRINSIC_FILES + EXTRINSIC_FILES + WORLD_FILES + \
                ["world_landmarks.json"]
            for name in promoted:
                src = os.path.join(self.staging_dir, name)
                if not os.path.exists(src):
                    raise ValueError(f"staged file missing: {name}")
                shutil.copy2(src, os.path.join(self.current_dir, name))
            with open(os.path.join(self.current_dir, "calibration_info.json"),
                      "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2)

            self.hooks["reload_tracker"]()
        except Exception as e:
            # Promotion failed: leave staging on disk for inspection, restart
            # the tracker on whatever current_calibration now holds.
            print(f"[calib] ACCEPT FAILED: {e}")
            try:
                self.hooks["start_tracker"]()
            except Exception:
                pass
            with self._lock:
                self._reset_session_fields()
                self.error = f"accept failed: {e}"
            self._push_status()
            return {"ok": False, "error": f"accept failed: {e}"}

        try:
            self.hooks["start_tracker"]()
            self.hooks["emit_tracker_poses"]()
        except Exception as e:
            print(f"[calib] tracker restart after accept failed: {e}")

        shutil.rmtree(self.staging_dir, ignore_errors=True)
        with self._lock:
            self._reset_session_fields()
            self.last_event = "accepted"
        self._push_status()
        print("[calib] new calibration accepted and promoted")
        return {"ok": True}

    # ---------------- step navigation ----------------

    def next_step(self):
        with self._lock:
            if not self.active or self.phase != "ready":
                return {"ok": False, "error": "no active session"}
            if self.busy:
                return {"ok": False, "error": f"busy: {self.busy}"}
            idx = STEPS.index(self.step)
            if self.step == "intrinsics":
                if not all(self.intr_calibrated):
                    missing = [str(i + 1) for i, ok in enumerate(self.intr_calibrated) if not ok]
                    return {"ok": False, "error":
                            f"camera(s) {', '.join(missing)} not calibrated yet"}
            elif self.step == "extrinsics":
                if not self.ext_computed:
                    return {"ok": False, "error": "compute the relative extrinsics first"}
            elif self.step == "landmarks":
                if not self.lm_computed:
                    return {"ok": False, "error": "compute the world transform first"}
            elif self.step == "verify":
                return {"ok": False, "error": "already at the last step — accept or cancel"}
            new_step = STEPS[idx + 1]

        err = self._load_staged_for_step(new_step)
        if err:
            return {"ok": False, "error": err}
        with self._lock:
            self.step = new_step
        self._log(new_step, f"--- entered step '{new_step}' ---")
        self._push_status()
        return {"ok": True, "step": new_step}

    def _load_staged_for_step(self, step):
        """(Re)load whatever staged calibration the given step's live view
        needs. Returns an error string or None."""
        try:
            if step in ("landmarks", "verify"):
                intr = _load_staged_intrinsics(self.staging_dir)
                extr = _load_staged_extrinsics(self.staging_dir)
                proj = [_build_projection(e["R_cam_to_cam1"], e["C_cam1"])
                        for e in extr]
                with self._lock:
                    self._staged_intr = intr
                    self._staged_proj = proj
            if step == "verify":
                scale, R, t = _load_staged_world(self.staging_dir)
                extr = _load_staged_extrinsics(self.staging_dir)
                poses = staged_camera_poses_in_world(extr, scale, R, t)
                matrix = staged_world_matrix_4x4_metres(scale, R, t)
                with self._lock:
                    self._staged_world = (scale, R, t)
                    self.staged_poses = poses
                    self.staged_world_matrix = matrix
            return None
        except (ValueError, OSError, KeyError) as e:
            return str(e)

    def restart_from(self, step, cam=None):
        """Clear staged artifacts for `step` and everything after it, then jump
        the session back to `step`. For intrinsics, `cam` limits the wipe to
        one camera's images/params (the other cameras stay calibrated)."""
        with self._lock:
            if not self.active or self.phase != "ready":
                return {"ok": False, "error": "no active session"}
            if self.busy:
                return {"ok": False, "error": f"busy: {self.busy}"}
            if step not in STEPS:
                return {"ok": False, "error": f"unknown step '{step}'"}
            if STEPS.index(step) < STEPS.index(self.start_step):
                return {"ok": False, "error":
                        f"session started at '{self.start_step}' — cancel and start a "
                        "new session to redo earlier steps"}
            if STEPS.index(step) > STEPS.index(self.step):
                return {"ok": False, "error": "cannot restart a step you haven't reached"}

        wipe_from = STEPS.index(step)
        if "landmarks" in STEPS[wipe_from:]:
            self._clear_landmarks_artifacts()
        if "extrinsics" in STEPS[wipe_from:]:
            self._clear_extrinsics_artifacts()
        if step == "intrinsics":
            self._clear_intrinsics_artifacts(cam)

        with self._lock:
            self.step = step
            self.live_cam1_mm = None
            self.live_world_mm = None
        err = self._load_staged_for_step(step)
        if err:
            with self._lock:
                self.error = err
        which = f" (camera {cam})" if (step == "intrinsics" and cam) else ""
        self._log(step, f"--- restarted from step '{step}'{which} ---")
        self._push_status()
        return {"ok": True, "step": step}

    def _clear_intrinsics_artifacts(self, cam=None):
        cams = [int(cam)] if cam else list(range(1, 5))
        with self._lock:
            for n in cams:
                folder = os.path.join(self.staging_dir, f"intrinsic_images_camera_{n}")
                shutil.rmtree(folder, ignore_errors=True)
                try:
                    os.remove(os.path.join(self.staging_dir,
                                           f"camera_{n}_params_new.json"))
                except OSError:
                    pass
                self.intr_counts[n - 1] = 0
                self.intr_calibrated[n - 1] = False
                self.intr_results.pop(n, None)
                if cam:
                    self.active_cam = n

    def _clear_extrinsics_artifacts(self):
        with self._lock:
            shutil.rmtree(os.path.join(self.staging_dir, "extrinsic_images"),
                          ignore_errors=True)
            for name in EXTRINSIC_FILES:
                try:
                    os.remove(os.path.join(self.staging_dir, name))
                except OSError:
                    pass
            self.ext_sets = 0
            self.ext_computed = False
            self.ext_results = None
            self._staged_proj = None
            self._staged_intr = None

    def _clear_landmarks_artifacts(self):
        with self._lock:
            for name in WORLD_FILES + ["world_landmarks.json"]:
                try:
                    os.remove(os.path.join(self.staging_dir, name))
                except OSError:
                    pass
            self.landmarks = []
            self.lm_computed = False
            self.lm_results = None
            self._staged_world = None
            self.staged_poses = None
            self.staged_world_matrix = None

    # ---------------- per-step actions ----------------

    def set_active_camera(self, cam):
        try:
            cam = int(cam)
        except (TypeError, ValueError):
            return {"ok": False, "error": "bad camera number"}
        if not 1 <= cam <= NUM_CAMERAS:
            return {"ok": False, "error": "camera must be 1..4"}
        with self._lock:
            if not self.active:
                return {"ok": False, "error": "no active session"}
            self.active_cam = cam
        self._push_status()
        return {"ok": True}

    def set_thresholds(self, values):
        try:
            vals = [int(np.clip(int(v), 0, 255)) for v in values[:NUM_CAMERAS]]
        except (TypeError, ValueError):
            return {"ok": False, "error": "bad thresholds"}
        with self._lock:
            for i, v in enumerate(vals):
                self.thresholds[i] = v
        return {"ok": True}

    def capture(self):
        """SPACE-equivalent for the current step: save an intrinsic image or a
        synchronized extrinsic set."""
        with self._lock:
            if not self.active or self.phase != "ready":
                return {"ok": False, "error": "no active session"}
            if self.busy:
                return {"ok": False, "error": f"busy: {self.busy}"}
            step = self.step
        if step == "intrinsics":
            return self._capture_intrinsic()
        if step == "extrinsics":
            return self._capture_extrinsic_set()
        return {"ok": False, "error": f"nothing to capture in step '{step}'"}

    def _capture_intrinsic(self):
        with self._lock:
            cam = self.active_cam
            camera = self._cameras[cam - 1] if len(self._cameras) >= cam else None
        if camera is None:
            return {"ok": False, "error": "cameras not ready"}
        ok, frame = camera.read()
        if not ok or frame is None:
            return {"ok": False, "error": f"camera {cam} has no frame"}
        found, _ = detect_corners(frame, self.checkerboard)
        if not found:
            self._log("intrinsics", f"[NOT SAVED] cam{cam}: checkerboard not detected")
            return {"ok": False, "error": "checkerboard not detected — hold it steady"}

        folder = os.path.join(self.staging_dir, f"intrinsic_images_camera_{cam}")
        os.makedirs(folder, exist_ok=True)
        next_i = 1
        for path in glob.glob(os.path.join(folder, f"cam{cam}_*.jpg")):
            m = re.match(rf"cam{cam}_(\d+)\.jpg", os.path.basename(path))
            if m:
                next_i = max(next_i, int(m.group(1)) + 1)
        filename = os.path.join(folder, f"cam{cam}_{next_i}.jpg")
        cv.imwrite(filename, frame)

        with self._lock:
            self.intr_counts[cam - 1] += 1
            # New images invalidate a previous calibration of this camera
            if self.intr_calibrated[cam - 1]:
                self.intr_calibrated[cam - 1] = False
            count = self.intr_counts[cam - 1]
        self._log("intrinsics", f"[SAVED] cam{cam}_{next_i}.jpg ({count} images)")
        self._push_status()
        return {"ok": True, "count": count}

    def _capture_extrinsic_set(self):
        with self._lock:
            cams = list(self._cameras)
        if len(cams) < NUM_CAMERAS:
            return {"ok": False, "error": "cameras not ready"}
        # Grab all four frames as close together as possible before detecting
        frames = []
        for i, camera in enumerate(cams):
            ok, frame = camera.read()
            if not ok or frame is None:
                return {"ok": False, "error": f"camera {i + 1} has no frame"}
            frames.append(frame)

        not_detected = []
        for i, frame in enumerate(frames):
            found, _ = detect_corners(frame, self.checkerboard)
            if not found:
                not_detected.append(f"cam{i + 1}")
        if not_detected:
            self._log("extrinsics",
                      f"[NOT SAVED] checkerboard missing in: {', '.join(not_detected)}")
            return {"ok": False, "error":
                    f"checkerboard not detected in {', '.join(not_detected)}"}

        folder = os.path.join(self.staging_dir, "extrinsic_images")
        os.makedirs(folder, exist_ok=True)
        next_set = 1
        for path in glob.glob(os.path.join(folder, "cam*_*.jpg")):
            m = re.match(r"cam\d+_(\d+)\.jpg", os.path.basename(path))
            if m:
                next_set = max(next_set, int(m.group(1)) + 1)
        for i, frame in enumerate(frames):
            cv.imwrite(os.path.join(folder, f"cam{i + 1}_{next_set}.jpg"), frame)

        with self._lock:
            self.ext_sets += 1
            if self.ext_computed:
                self.ext_computed = False   # new data invalidates the old solve
            sets = self.ext_sets
        self._log("extrinsics", f"[SAVED] image set {next_set} ({sets} sets)")
        self._push_status()
        return {"ok": True, "sets": sets}

    def capture_landmark(self, name, world_xyz):
        with self._lock:
            if not self.active or self.step != "landmarks":
                return {"ok": False, "error": "not in the landmarks step"}
            if self.busy:
                return {"ok": False, "error": f"busy: {self.busy}"}
            name = str(name or "").strip()
            if not name:
                return {"ok": False, "error": "landmark needs a name"}
            if any(lm["name"] == name for lm in self.landmarks):
                return {"ok": False, "error": f"landmark '{name}' already exists"}
            try:
                world = [float(world_xyz[0]), float(world_xyz[1]), float(world_xyz[2])]
            except (TypeError, ValueError, IndexError):
                return {"ok": False, "error": "world coordinates must be 3 numbers (mm)"}
            if self._staged_proj is None:
                return {"ok": False, "error": "staged calibration not loaded"}
            self._lm_samples = []
            self._lm_sampling = True

        # Collect ~1.2 s of triangulated fixes from the stream loop
        deadline = time.perf_counter() + 2.5
        while time.perf_counter() < deadline:
            with self._lock:
                n = len(self._lm_samples)
            if n >= 12:
                break
            time.sleep(0.05)
        with self._lock:
            self._lm_sampling = False
            samples = list(self._lm_samples)
            self._lm_samples = []

        if len(samples) < 5:
            self._log("landmarks",
                      f"[NOT CAPTURED] '{name}': LED not stable "
                      f"({len(samples)} fixes in 2.5 s — need 5)")
            return {"ok": False, "error":
                    "LED not visible/stable in at least 2 cameras — adjust and retry"}

        arr = np.array(samples, dtype=np.float64)
        cam1 = arr.mean(axis=0)
        spread = float(arr.std(axis=0).max())
        point = {
            "name": name,
            "cam1": [float(x) for x in cam1],
            "world": world,
        }
        with self._lock:
            self.landmarks.append(point)
            if self.lm_computed:
                self.lm_computed = False
            count = len(self.landmarks)
        self._log("landmarks",
                  f"[CAPTURED] '{name}' cam1=({cam1[0]:.0f}, {cam1[1]:.0f}, "
                  f"{cam1[2]:.0f}) mm  world=({world[0]:.0f}, {world[1]:.0f}, "
                  f"{world[2]:.0f}) mm  jitter {spread:.1f} mm  "
                  f"[{len(samples)} samples]")
        self._push_status()
        return {"ok": True, "point": point, "count": count}

    def delete_landmark(self, name):
        with self._lock:
            if not self.active or self.step != "landmarks":
                return {"ok": False, "error": "not in the landmarks step"}
            before = len(self.landmarks)
            self.landmarks = [lm for lm in self.landmarks if lm["name"] != name]
            if len(self.landmarks) == before:
                return {"ok": False, "error": f"no landmark named '{name}'"}
            if self.lm_computed:
                self.lm_computed = False
        self._log("landmarks", f"[DELETED] landmark '{name}'")
        self._push_status()
        return {"ok": True}

    # ---------------- computes (run on worker threads) ----------------

    def compute(self):
        with self._lock:
            if not self.active or self.phase != "ready":
                return {"ok": False, "error": "no active session"}
            if self.busy:
                return {"ok": False, "error": f"already computing: {self.busy}"}
            step = self.step
            if step == "intrinsics":
                cam = self.active_cam
                if self.intr_counts[cam - 1] < MIN_INTRINSIC_IMAGES:
                    return {"ok": False, "error":
                            f"camera {cam} has {self.intr_counts[cam - 1]} images — "
                            f"capture at least {MIN_INTRINSIC_IMAGES}"}
                self.busy = f"calibrating camera {cam}"
                target = self._compute_intrinsics_worker
                args = (self._token, cam)
            elif step == "extrinsics":
                if self.ext_sets < MIN_EXTRINSIC_SETS:
                    return {"ok": False, "error":
                            f"{self.ext_sets} sets captured — need at least "
                            f"{MIN_EXTRINSIC_SETS} (aim for {RECOMMENDED_EXTRINSIC_SETS}+)"}
                self.busy = "computing relative extrinsics"
                target = self._compute_extrinsics_worker
                args = (self._token,)
            elif step == "landmarks":
                if len(self.landmarks) < MIN_LANDMARKS:
                    return {"ok": False, "error":
                            f"{len(self.landmarks)} landmarks — need at least "
                            f"{MIN_LANDMARKS} (aim for {RECOMMENDED_LANDMARKS}+)"}
                self.busy = "computing world transform"
                target = self._compute_landmarks_worker
                args = (self._token,)
            else:
                return {"ok": False, "error": f"nothing to compute in step '{step}'"}

        self._push_status()
        threading.Thread(target=target, args=args, daemon=True,
                         name="CalibCompute").start()
        return {"ok": True}

    def _finish_compute(self, token, apply_fn, error):
        """Common tail for compute workers: apply results under the lock unless
        the session token changed (cancel/accept during compute)."""
        with self._lock:
            if self._token != token:
                return
            self.busy = None
            if error:
                self.error = error
            else:
                self.error = None
                apply_fn()
        self._push_status()

    def _compute_intrinsics_worker(self, token, cam):
        log = lambda text: self._log("intrinsics", f"[cam{cam}] {text}")
        folder = os.path.join(self.staging_dir, f"intrinsic_images_camera_{cam}")
        params, result, error = None, None, None
        try:
            log("running cv.calibrateCamera ...")
            params, result = calibrate_intrinsics_from_folder(
                folder, self.checkerboard, self.square_size_mm, log)
            with open(os.path.join(self.staging_dir,
                                   f"camera_{cam}_params_new.json"), "w") as f:
                json.dump(params, f, indent=4)
            log(f"saved camera_{cam}_params_new.json")
        except ValueError as e:
            error = f"camera {cam}: {e}"
            log(f"ERROR: {e}")
        except Exception as e:
            error = f"camera {cam}: {type(e).__name__}: {e}"
            log(f"ERROR: {error}")

        def apply():
            self.intr_calibrated[cam - 1] = True
            self.intr_results[cam] = result
            # Count only the images that actually detected, so the UI shows
            # what the solve used.
        self._finish_compute(token, apply, error)

    def _compute_extrinsics_worker(self, token):
        log = lambda text: self._log("extrinsics", text)
        npz_data, results, error = None, None, None
        try:
            intr = {}
            for n in range(1, 5):
                path = os.path.join(self.staging_dir, f"camera_{n}_params_new.json")
                if not os.path.exists(path):
                    raise ValueError(f"missing staged intrinsics for camera {n}")
                intr[f"cam{n}"] = load_intrinsics_json(path)
            folder = os.path.join(self.staging_dir, "extrinsic_images")
            npz_data, results = compute_relative_extrinsics(
                folder, intr, self.checkerboard, self.square_size_mm, log)
            for cam, data in npz_data.items():
                np.savez(os.path.join(self.staging_dir,
                                      f"{cam}_relative_to_cam1.npz"),
                         R=data["R"], t=data["t"])
                log(f"saved {cam}_relative_to_cam1.npz")
        except ValueError as e:
            error = str(e)
            log(f"ERROR: {e}")
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
            log(f"ERROR: {error}")

        def apply():
            self.ext_computed = True
            self.ext_results = results
        self._finish_compute(token, apply, error)

    def _compute_landmarks_worker(self, token):
        log = lambda text: self._log("landmarks", text)
        npz_data, results, error = None, None, None
        with self._lock:
            landmarks = [dict(lm) for lm in self.landmarks]
        try:
            npz_data, results = compute_world_transform(landmarks, log)
            np.savez(os.path.join(self.staging_dir, "cam1_to_world_transform.npz"),
                     scale=npz_data["scale"], R=npz_data["R"], t=npz_data["t"])
            with open(os.path.join(self.staging_dir, "world_landmarks.json"),
                      "w") as f:
                json.dump(landmarks, f, indent=4)
            log("saved cam1_to_world_transform.npz + world_landmarks.json")
        except ValueError as e:
            error = str(e)
            log(f"ERROR: {e}")
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
            log(f"ERROR: {error}")

        def apply():
            self.lm_computed = True
            self.lm_results = results
        self._finish_compute(token, apply, error)

    # ---------------- live view threads ----------------

    def latest_jpeg(self):
        with self._jpeg_lock:
            if self._latest_jpeg:
                return self._latest_jpeg
        if self._placeholder_jpeg is None:
            img = np.zeros((240, 640, 3), dtype=np.uint8)
            cv.putText(img, "CALIBRATION NOT RUNNING", (110, 130),
                       cv.FONT_HERSHEY_SIMPLEX, 0.8, (120, 120, 120), 2)
            ok, jpeg = cv.imencode(".jpg", img)
            self._placeholder_jpeg = jpeg.tobytes() if ok else b""
        return self._placeholder_jpeg

    def _status_loop(self, token):
        period = 1.0 / STATUS_HZ
        while True:
            with self._lock:
                if self._token != token or not self._threads_running:
                    return
            self._push_status()
            time.sleep(period)

    def _detect_loop(self, token):
        """Continuously refresh checkerboard detection for the capture steps.
        findChessboardCornersSB(EXHAUSTIVE) is slow (~100-300 ms per frame), so
        this runs decoupled from the stream loop and caches its results."""
        while True:
            with self._lock:
                if self._token != token or not self._threads_running:
                    return
                step = self.step
                active_cam = self.active_cam
                cams = list(self._cameras)
            if step not in ("intrinsics", "extrinsics") or not cams:
                with self._corner_lock:
                    self._corner_cache = {}
                time.sleep(0.15)
                continue

            targets = range(NUM_CAMERAS) if step == "extrinsics" else [active_cam - 1]
            flags = list(self.detect_flags)
            for i in targets:
                if i >= len(cams):
                    continue
                ok, frame = cams[i].read()
                if not ok or frame is None:
                    flags[i] = False
                    with self._corner_lock:
                        self._corner_cache.pop(i, None)
                    continue
                found, corners = detect_corners(frame, self.checkerboard)
                flags[i] = bool(found)
                with self._corner_lock:
                    if found:
                        self._corner_cache[i] = corners
                    else:
                        self._corner_cache.pop(i, None)
            if step == "intrinsics":
                for i in range(NUM_CAMERAS):
                    if i != active_cam - 1:
                        flags[i] = False
            with self._lock:
                self.detect_flags = flags
            time.sleep(0.05)

    def _stream_loop(self, token):
        period = 1.0 / STREAM_HZ
        jpeg_params = [int(cv.IMWRITE_JPEG_QUALITY), 70]
        black = np.zeros((480, 640, 3), dtype=np.uint8)

        while True:
            t0 = time.perf_counter()
            with self._lock:
                if self._token != token or not self._threads_running:
                    return
                step = self.step
                active_cam = self.active_cam
                cams = list(self._cameras)
                thresholds = list(self.thresholds)
                staged_intr = self._staged_intr
                staged_proj = self._staged_proj
                staged_world = self._staged_world

            frames = []
            cameras_ok = []
            for i, camera in enumerate(cams):
                ok, frame = camera.read()
                cameras_ok.append(bool(ok and frame is not None))
                if not ok or frame is None:
                    frame = black.copy()
                    cv.putText(frame, f"cam{i + 1} ERROR", (20, 40),
                               cv.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
                frames.append(frame)
            while len(frames) < NUM_CAMERAS:
                cameras_ok.append(False)
                frames.append(black.copy())

            live_cam1 = None
            live_world = None

            if step == "intrinsics":
                view = self._render_intrinsics_view(frames, active_cam)
            elif step == "extrinsics":
                view = self._render_extrinsics_view(frames)
            else:
                # landmarks / verify: LED detection + triangulation
                detected = {}
                for i, frame in enumerate(frames):
                    if not cameras_ok[i]:
                        continue
                    point = _detect_bright_spot(frame, thresholds[i],
                                                MIN_BLOB_AREA, MAX_BLOB_AREA)
                    if point is not None:
                        detected[i] = point
                        cv.drawMarker(frame, point, (0, 255, 0), cv.MARKER_CROSS, 18, 2)
                        cv.circle(frame, point, 8, (0, 255, 0), 2)
                    else:
                        cv.putText(frame, "NO LED", (10, 60),
                                   cv.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                    cv.putText(frame, f"cam{i + 1}  th:{thresholds[i]}", (10, 30),
                               cv.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

                if staged_intr is not None and staged_proj is not None:
                    pt = _triangulate_from_detected(detected, staged_intr, staged_proj)
                    if pt is not None:
                        live_cam1 = [float(x) for x in pt]
                        if step == "verify" and staged_world is not None:
                            s, R, t = staged_world
                            w = (s * R @ pt.reshape(3, 1) + t).reshape(3)
                            live_world = [float(x) for x in w]

                view = self._render_led_view(frames, step, live_cam1, live_world)

            ok, jpeg = cv.imencode(".jpg", view, jpeg_params)
            with self._jpeg_lock:
                self._latest_jpeg = jpeg.tobytes() if ok else b""
            with self._lock:
                self.cameras_ok = cameras_ok
                self.live_cam1_mm = live_cam1
                self.live_world_mm = live_world
                if self._lm_sampling and live_cam1 is not None:
                    self._lm_samples.append(live_cam1)

            elapsed = time.perf_counter() - t0
            time.sleep(max(0.0, period - elapsed))

    def _render_intrinsics_view(self, frames, active_cam):
        frame = frames[active_cam - 1].copy()
        with self._corner_lock:
            corners = self._corner_cache.get(active_cam - 1)
        if corners is not None:
            cv.drawChessboardCorners(frame, self.checkerboard, corners, True)
            text, color = f"cam{active_cam}: CHECKERBOARD DETECTED", (0, 255, 0)
        else:
            text, color = f"cam{active_cam}: NOT DETECTED", (0, 0, 255)
        cv.putText(frame, text, (20, 40), cv.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
        with self._lock:
            count = self.intr_counts[active_cam - 1]
        cv.putText(frame, f"Saved images: {count}", (20, 75),
                   cv.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        return frame

    def _render_extrinsics_view(self, frames):
        annotated = []
        with self._corner_lock:
            cache = dict(self._corner_cache)
        for i, frame in enumerate(frames):
            frame = frame.copy()
            corners = cache.get(i)
            if corners is not None:
                cv.drawChessboardCorners(frame, self.checkerboard, corners, True)
                text, color = f"cam{i + 1}: DETECTED", (0, 255, 0)
            else:
                text, color = f"cam{i + 1}: NOT DETECTED", (0, 0, 255)
            cv.putText(frame, text, (20, 40), cv.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
            annotated.append(cv.resize(frame, (320, 240)))
        top = np.hstack((annotated[0], annotated[1]))
        bottom = np.hstack((annotated[2], annotated[3]))
        grid = np.vstack((top, bottom))
        with self._lock:
            sets = self.ext_sets
        strip = np.zeros((36, grid.shape[1], 3), dtype=np.uint8)
        cv.putText(strip, f"Saved sets: {sets}", (14, 25),
                   cv.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)
        return np.vstack((grid, strip))

    def _render_led_view(self, frames, step, live_cam1, live_world):
        resized = [cv.resize(f, (320, 240)) for f in frames]
        top = np.hstack((resized[0], resized[1]))
        bottom = np.hstack((resized[2], resized[3]))
        grid = np.vstack((top, bottom))
        strip = np.zeros((56, grid.shape[1], 3), dtype=np.uint8)
        if step == "verify":
            if live_world is not None:
                text = (f"WORLD  X:{live_world[0] / 1000.0: .3f}m  "
                        f"Y:{live_world[1] / 1000.0: .3f}m  "
                        f"Z:{live_world[2] / 1000.0: .3f}m")
                color = (0, 255, 0)
            else:
                text, color = "WORLD: LED not seen by 2+ cameras", (0, 0, 255)
        else:
            if live_cam1 is not None:
                text = (f"CAM1  X:{live_cam1[0]: .0f}  Y:{live_cam1[1]: .0f}  "
                        f"Z:{live_cam1[2]: .0f}  mm")
                color = (0, 255, 0)
            else:
                text, color = "CAM1: LED not seen by 2+ cameras", (0, 0, 255)
        cv.putText(strip, text, (14, 24), cv.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
        if step == "verify" and live_cam1 is not None:
            cv.putText(strip, f"cam1 mm: ({live_cam1[0]:.0f}, {live_cam1[1]:.0f}, "
                       f"{live_cam1[2]:.0f})", (14, 48),
                       cv.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
        return np.vstack((grid, strip))
