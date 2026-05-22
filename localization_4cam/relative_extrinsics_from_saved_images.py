import cv2
import numpy as np
import glob
import os
import json
import re

# =========================
# SETTINGS
# =========================

CHECKERBOARD = (9, 6)
SQUARE_SIZE = 23.9  # mm

CAMERAS = ["cam1", "cam2", "cam3", "cam4"]
REFERENCE_CAM = "cam1"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGE_FOLDER = os.path.join(BASE_DIR, "extrinsic_images")

# =========================
# OBJECT POINTS
# =========================

def create_object_points():
    objp = np.zeros(
        (CHECKERBOARD[0] * CHECKERBOARD[1], 3),
        np.float32
    )

    objp[:, :2] = np.mgrid[
        0:CHECKERBOARD[0],
        0:CHECKERBOARD[1]
    ].T.reshape(-1, 2)

    objp *= SQUARE_SIZE
    return objp

# =========================
# LOAD INTRINSICS
# =========================

def load_intrinsics(cam):
    cam_num = cam.replace("cam", "")

    filename = os.path.join(
        BASE_DIR,
        f"camera_{cam_num}_params.json"
    )

    with open(filename, "r") as f:
        data = json.load(f)

    K = np.array(data["intrinsic_matrix"], dtype=np.float32)
    dist = np.array(data["distortion_coef"], dtype=np.float32)

    return K, dist

# =========================
# DETECT CHECKERBOARD
# =========================

def detect_corners(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    found, corners = cv2.findChessboardCornersSB(
        gray,
        CHECKERBOARD,
        cv2.CALIB_CB_NORMALIZE_IMAGE |
        cv2.CALIB_CB_EXHAUSTIVE
    )

    return found, corners

# =========================
# POSE FUNCTIONS
# =========================

def solve_pose(img_path, objp, K, dist):
    img = cv2.imread(img_path)

    if img is None:
        return None, None, None

    found, corners = detect_corners(img)

    if not found:
        return None, None, None

    success, rvec, tvec = cv2.solvePnP(
        objp,
        corners,
        K,
        dist
    )

    if not success:
        return None, None, None

    R, _ = cv2.Rodrigues(rvec)

    projected, _ = cv2.projectPoints(
        objp,
        rvec,
        tvec,
        K,
        dist
    )

    error = cv2.norm(
        corners,
        projected,
        cv2.NORM_L2
    ) / len(projected)

    return R, tvec, error


def invert_pose(R, t):
    R_inv = R.T
    t_inv = -R.T @ t
    return R_inv, t_inv


def relative_pose_from_ref_to_cam(R_ref, t_ref, R_cam, t_cam):
    """
    solvePnP gives:
        X_camera = R * X_checkerboard + t

    This computes:
        X_cam = R_rel * X_ref + t_rel

    So t_rel is the position of cam reference origin
    expressed in current camera coordinates.
    """

    R_ref_inv, t_ref_inv = invert_pose(R_ref, t_ref)

    R_rel = R_cam @ R_ref_inv
    t_rel = t_cam + R_cam @ t_ref_inv

    return R_rel, t_rel

# =========================
# SET FINDING
# =========================

def get_available_set_numbers():
    all_sets = set()

    for cam in CAMERAS:
        pattern = os.path.join(IMAGE_FOLDER, f"{cam}_*.jpg")
        paths = glob.glob(pattern)

        for path in paths:
            name = os.path.basename(path)

            match = re.match(rf"{cam}_(\d+)\.jpg", name)

            if match:
                all_sets.add(int(match.group(1)))

    return sorted(all_sets)

# =========================
# AVERAGE ROTATION
# =========================

def average_rotation(R_list):
    R_mean = np.mean(R_list, axis=0)

    U, _, Vt = np.linalg.svd(R_mean)
    R_avg = U @ Vt

    if np.linalg.det(R_avg) < 0:
        U[:, -1] *= -1
        R_avg = U @ Vt

    return R_avg

# =========================
# MAIN RELATIVE EXTRINSICS
# =========================

def compute_relative_extrinsics_from_saved_images():
    objp = create_object_points()

    intrinsics = {
        cam: load_intrinsics(cam)
        for cam in CAMERAS
    }

    set_numbers = get_available_set_numbers()

    if len(set_numbers) == 0:
        print("No saved image sets found.")
        return

    relative_R = {
        cam: []
        for cam in CAMERAS
        if cam != REFERENCE_CAM
    }

    relative_t = {
        cam: []
        for cam in CAMERAS
        if cam != REFERENCE_CAM
    }

    print("\nFound image set numbers:")
    print(set_numbers)

    for number in set_numbers:
        print(f"\n========== SET {number} ==========")

        poses = {}
        errors = {}
        valid_set = True

        for cam in CAMERAS:
            img_path = os.path.join(
                IMAGE_FOLDER,
                f"{cam}_{number}.jpg"
            )

            if not os.path.exists(img_path):
                print(f"[MISSING] {cam}_{number}.jpg")
                valid_set = False
                break

            K, dist = intrinsics[cam]

            R, t, error = solve_pose(
                img_path,
                objp,
                K,
                dist
            )

            if R is None:
                print(f"[FAIL] {cam}_{number}.jpg")
                valid_set = False
                break

            poses[cam] = (R, t)
            errors[cam] = error

            print(
                f"[OK] {cam}_{number}.jpg "
                f"| error = {error:.4f}"
            )

        if not valid_set:
            print("[SKIPPED SET]")
            continue

        R_ref, t_ref = poses[REFERENCE_CAM]

        for cam in CAMERAS:
            if cam == REFERENCE_CAM:
                continue

            R_cam, t_cam = poses[cam]

            R_rel, t_rel = relative_pose_from_ref_to_cam(
                R_ref,
                t_ref,
                R_cam,
                t_cam
            )

            # After computing R_rel, t_rel
            distance = np.linalg.norm(t_rel)

            print(
                f"{cam} relative distance in set {number}: "
                f"{distance:.2f} mm"
            )

            relative_R[cam].append(R_rel)
            relative_t[cam].append(t_rel)

    # =========================
    # FINAL AVERAGE
    # =========================

    results = {
        REFERENCE_CAM: {
            "R": np.eye(3),
            "t": np.zeros((3, 1))
        }
    }

    print("\n=========== FINAL RELATIVE EXTRINSICS ===========\n")

    for cam in CAMERAS:
        if cam == REFERENCE_CAM:
            continue

        if len(relative_R[cam]) == 0:
            print(f"No valid relative poses for {cam}")
            continue

        R_avg = average_rotation(relative_R[cam])
        t_avg = np.mean(relative_t[cam], axis=0)

        results[cam] = {
            "R": R_avg,
            "t": t_avg
        }

        print(f"{cam} relative to {REFERENCE_CAM}")
        print("R =")
        print(R_avg)
        print("t =")
        print(t_avg.flatten())

        distance_from_ref = np.linalg.norm(t_avg)

        print(
            f"Distance from {REFERENCE_CAM} to {cam}: "
            f"{distance_from_ref:.2f} mm"
        )

        np.savez(
            os.path.join(
                BASE_DIR,
                f"{cam}_relative_to_{REFERENCE_CAM}.npz"
            ),
            R=R_avg,
            t=t_avg
        )

        print(f"Saved {cam}_relative_to_{REFERENCE_CAM}.npz\n")

    # =========================
    # CAMERA-TO-CAMERA DISTANCES
    # =========================

    print("\n=========== CAMERA DISTANCES ===========\n")

    cam_positions = {}

    cam_positions[REFERENCE_CAM] = np.zeros((3, 1))

    for cam in CAMERAS:
        if cam == REFERENCE_CAM:
            continue

        if cam in results:
            cam_positions[cam] = results[cam]["t"]

    for i in range(len(CAMERAS)):
        for j in range(i + 1, len(CAMERAS)):
            cam_a = CAMERAS[i]
            cam_b = CAMERAS[j]

            if cam_a not in cam_positions or cam_b not in cam_positions:
                continue

            d = np.linalg.norm(
                cam_positions[cam_a] -
                cam_positions[cam_b]
            )

            print(f"{cam_a} <-> {cam_b}: {d:.2f} mm")

# =========================
# RUN
# =========================

if __name__ == "__main__":
    compute_relative_extrinsics_from_saved_images()