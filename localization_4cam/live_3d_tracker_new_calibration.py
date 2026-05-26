import cv2 as cv
import numpy as np
import threading
import json
import os
import time
from itertools import combinations

# =========================
# SETTINGS
# =========================

CAMERA_INDICES = [1, 2, 3, 4]
CAMERA_NAMES = ["cam1", "cam2", "cam3", "cam4"]

CAM_WIDTH = 640
CAM_HEIGHT = 480

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

THRESHOLD_VALUE = 180
MIN_BLOB_AREA = 3
MAX_BLOB_AREA = 5000

USE_GRAYSCALE = True

# If your output is in mm, set this True to display meters
DISPLAY_IN_METERS = True


# =========================
# THREADED CAMERA
# =========================

class ThreadedCamera:
    def __init__(self, src):
        self.src = src

        self.cap = cv.VideoCapture(src, cv.CAP_DSHOW)

        self.cap.set(cv.CAP_PROP_FRAME_WIDTH, CAM_WIDTH)
        self.cap.set(cv.CAP_PROP_FRAME_HEIGHT, CAM_HEIGHT)
        self.cap.set(cv.CAP_PROP_BUFFERSIZE, 1)

        # Optional fixed exposure settings.
        # These may or may not work depending on webcam driver.
        # Uncomment and tune if needed.
        #
        # self.cap.set(cv.CAP_PROP_AUTO_EXPOSURE, 0.25)
        # self.cap.set(cv.CAP_PROP_EXPOSURE, -8)
        # self.cap.set(cv.CAP_PROP_GAIN, 0)

        self.ret, self.frame = self.cap.read()

        self.running = True
        self.lock = threading.Lock()

        self.thread = threading.Thread(target=self.update, daemon=True)
        self.thread.start()

    def update(self):
        while self.running:
            ret, frame = self.cap.read()

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
        self.thread.join()
        self.cap.release()


# =========================
# LOAD CALIBRATION
# =========================

def load_intrinsics():
    intrinsics = []

    for cam_num in range(1, 5):
        filename = os.path.join(
            BASE_DIR,
            f"camera_{cam_num}_params.json"
        )

        with open(filename, "r") as f:
            data = json.load(f)

        K = np.array(
            data["intrinsic_matrix"],
            dtype=np.float64
        )

        D = np.array(
            data["distortion_coef"],
            dtype=np.float64
        )

        intrinsics.append({
            "K": K,
            "D": D
        })

        print(f"[OK] Loaded camera_{cam_num}_params.json")

    return intrinsics


def load_extrinsics():
    """
    World coordinate system = cam1 coordinate system.

    For cam1:
        camera center C = [0,0,0]
        camera orientation R_cam_to_world = I

    For cam2/cam3/cam4:
        load from camX_relative_to_cam1.npz

    Expected saved meaning:
        R = camera orientation in cam1/world frame
        t = camera center in cam1/world frame
    """

    extrinsics = []

    # cam1 identity
    extrinsics.append({
        "R_cam_to_world": np.eye(3, dtype=np.float64),
        "C_world": np.zeros((3, 1), dtype=np.float64)
    })

    for cam_num in range(2, 5):
        filename = os.path.join(
            BASE_DIR,
            f"cam{cam_num}_relative_to_cam1.npz"
        )

        data = np.load(filename)

        R_cam_to_world = np.array(
            data["R"],
            dtype=np.float64
        )

        C_world = np.array(
            data["t"],
            dtype=np.float64
        ).reshape(3, 1)

        extrinsics.append({
            "R_cam_to_world": R_cam_to_world,
            "C_world": C_world
        })

        print(f"[OK] Loaded cam{cam_num}_relative_to_cam1.npz")

    return extrinsics


def build_projection_from_camera_pose(R_cam_to_world, C_world):
    """
    cv.triangulatePoints needs projection matrix that maps:

        X_world -> X_camera

    If:
        R_cam_to_world = camera orientation in world
        C_world = camera center in world

    Then:
        R_world_to_cam = R_cam_to_world.T
        t_world_to_cam = -R_world_to_cam @ C_world

    Since we undistort image points into normalized camera coordinates,
    projection matrix is:

        P = [R_world_to_cam | t_world_to_cam]

    not K @ [R|t].
    """

    R_world_to_cam = R_cam_to_world.T
    t_world_to_cam = -R_world_to_cam @ C_world

    P = np.hstack(
        (
            R_world_to_cam,
            t_world_to_cam
        )
    )

    return P


def load_system_data():
    print("\nLoading calibration files...\n")

    intrinsics = load_intrinsics()
    extrinsics = load_extrinsics()

    projections = []

    for ext in extrinsics:
        P = build_projection_from_camera_pose(
            ext["R_cam_to_world"],
            ext["C_world"]
        )

        projections.append(P)

    print("\nCalibration loaded successfully.\n")

    return intrinsics, extrinsics, projections


# =========================
# LED DETECTION
# =========================

def detect_bright_spot(frame):
    """
    Works with floppy disk / dark filter.
    Finds the brightest blob.

    Returns:
        (cx, cy), mask
        or
        None, mask
    """

    if USE_GRAYSCALE:
        gray = cv.cvtColor(frame, cv.COLOR_BGR2GRAY)
        detection_img = gray
    else:
        # Use red channel if your LED appears strongest in red channel
        detection_img = frame[:, :, 2]

    blurred = cv.GaussianBlur(
        detection_img,
        (5, 5),
        0
    )

    _, mask = cv.threshold(
        blurred,
        THRESHOLD_VALUE,
        255,
        cv.THRESH_BINARY
    )

    kernel = np.ones((3, 3), np.uint8)

    mask = cv.morphologyEx(
        mask,
        cv.MORPH_OPEN,
        kernel
    )

    mask = cv.morphologyEx(
        mask,
        cv.MORPH_DILATE,
        kernel
    )

    contours, _ = cv.findContours(
        mask,
        cv.RETR_EXTERNAL,
        cv.CHAIN_APPROX_SIMPLE
    )

    best_point = None
    best_area = 0

    for contour in contours:
        area = cv.contourArea(contour)

        if area < MIN_BLOB_AREA:
            continue

        if area > MAX_BLOB_AREA:
            continue

        if area > best_area:
            M = cv.moments(contour)

            if M["m00"] > 0:
                cx = int(M["m10"] / M["m00"])
                cy = int(M["m01"] / M["m00"])

                best_point = (cx, cy)
                best_area = area

    return best_point, mask


# =========================
# TRIANGULATION
# =========================

def undistort_point(pt, K, D):
    """
    Converts distorted pixel coordinate to normalized camera coordinate.
    """

    pts = np.array(
        [[[pt[0], pt[1]]]],
        dtype=np.float64
    )

    undistorted = cv.undistortPoints(
        pts,
        K,
        D
    )

    x = undistorted[0, 0, 0]
    y = undistorted[0, 0, 1]

    return np.array(
        [[x], [y]],
        dtype=np.float64
    )


def triangulate_two_cameras(P1, P2, pt1_norm, pt2_norm):
    point_4d = cv.triangulatePoints(
        P1,
        P2,
        pt1_norm,
        pt2_norm
    )

    point_3d = point_4d[:3] / point_4d[3]

    return point_3d.reshape(3)


def triangulate_from_detected_points(detected_points, intrinsics, projections):
    """
    detected_points:
        dictionary:
            cam_index_in_list -> (u, v)

    Returns:
        averaged 3D point in cam1 coordinate system
    """

    if len(detected_points) < 2:
        return None, []

    points_3d = []

    cam_ids = list(detected_points.keys())

    for c1, c2 in combinations(cam_ids, 2):
        pt1 = detected_points[c1]
        pt2 = detected_points[c2]

        pt1_norm = undistort_point(
            pt1,
            intrinsics[c1]["K"],
            intrinsics[c1]["D"]
        )

        pt2_norm = undistort_point(
            pt2,
            intrinsics[c2]["K"],
            intrinsics[c2]["D"]
        )

        X = triangulate_two_cameras(
            projections[c1],
            projections[c2],
            pt1_norm,
            pt2_norm
        )

        points_3d.append(X)

    if len(points_3d) == 0:
        return None, []

    avg_point = np.mean(
        points_3d,
        axis=0
    )

    return avg_point, points_3d


# =========================
# UI
# =========================

def draw_camera_view(frame, cam_label, point):
    cv.putText(
        frame,
        cam_label,
        (10, 30),
        cv.FONT_HERSHEY_SIMPLEX,
        0.8,
        (255, 255, 255),
        2
    )

    if point is not None:
        cv.drawMarker(
            frame,
            point,
            (0, 255, 0),
            cv.MARKER_CROSS,
            18,
            2
        )

        cv.circle(
            frame,
            point,
            8,
            (0, 255, 0),
            2
        )

        cv.putText(
            frame,
            "LED",
            (point[0] + 10, point[1] - 10),
            cv.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 0),
            2
        )
    else:
        cv.putText(
            frame,
            "NO LED",
            (10, 60),
            cv.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 0, 255),
            2
        )

    return frame


def format_coordinate_text(point_3d):
    if point_3d is None:
        return "3D: LED not found in at least 2 cameras", (0, 0, 255)

    x, y, z = point_3d

    if DISPLAY_IN_METERS:
        x /= 1000.0
        y /= 1000.0
        z /= 1000.0

        text = f"X: {x: .3f} m   Y: {y: .3f} m   Z: {z: .3f} m"
    else:
        text = f"X: {x: .1f} mm   Y: {y: .1f} mm   Z: {z: .1f} mm"

    return text, (0, 255, 0)


# =========================
# MAIN
# =========================

def main():
    intrinsics, extrinsics, projections = load_system_data()

    print("Starting cameras:", CAMERA_INDICES)

    cameras = [
        ThreadedCamera(idx)
        for idx in CAMERA_INDICES
    ]

    time.sleep(1.0)

    window_name = "Live 3D LED Tracking - New Calibration"

    cv.namedWindow(
        window_name,
        cv.WINDOW_NORMAL
    )

    cv.resizeWindow(
        window_name,
        1200,
        700
    )

    print("\n--- LIVE 3D TRACKING ACTIVE ---")
    print("Press q to quit")
    print("Press + to increase threshold")
    print("Press - to decrease threshold\n")

    global THRESHOLD_VALUE

    while True:
        frames = []
        detected_points = {}

        for i, cam in enumerate(cameras):
            ret, frame = cam.read()

            if not ret or frame is None:
                frame = np.zeros(
                    (CAM_HEIGHT, CAM_WIDTH, 3),
                    dtype=np.uint8
                )

                cv.putText(
                    frame,
                    f"{CAMERA_NAMES[i]} ERROR",
                    (20, 40),
                    cv.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (0, 0, 255),
                    2
                )

                frames.append(frame)
                continue

            point, mask = detect_bright_spot(frame)

            if point is not None:
                detected_points[i] = point

            frame = draw_camera_view(
                frame,
                CAMERA_NAMES[i],
                point
            )

            cv.putText(
                frame,
                f"threshold: {THRESHOLD_VALUE}",
                (10, CAM_HEIGHT - 15),
                cv.FONT_HERSHEY_SIMPLEX,
                0.55,
                (255, 255, 255),
                1
            )

            frames.append(frame)

        point_3d, pair_points = triangulate_from_detected_points(
            detected_points,
            intrinsics,
            projections
        )

        coord_text, text_color = format_coordinate_text(point_3d)

        # Resize each camera for grid
        display_frames = [
            cv.resize(frame, (CAM_WIDTH // 2, CAM_HEIGHT // 2))
            for frame in frames
        ]

        top_row = np.hstack(
            (
                display_frames[0],
                display_frames[1]
            )
        )

        bottom_row = np.hstack(
            (
                display_frames[2],
                display_frames[3]
            )
        )

        grid = np.vstack(
            (
                top_row,
                bottom_row
            )
        )

        cv.rectangle(
            grid,
            (0, CAM_HEIGHT - 45),
            (CAM_WIDTH, CAM_HEIGHT),
            (0, 0, 0),
            -1
        )

        cv.putText(
            grid,
            coord_text,
            (20, CAM_HEIGHT - 15),
            cv.FONT_HERSHEY_SIMPLEX,
            0.75,
            text_color,
            2
        )

        cv.imshow(
            window_name,
            grid
        )

        key = cv.waitKey(1) & 0xFF

        if key == ord("q"):
            break

        elif key == ord("+") or key == ord("="):
            THRESHOLD_VALUE = min(
                255,
                THRESHOLD_VALUE + 5
            )

            print("Threshold:", THRESHOLD_VALUE)

        elif key == ord("-") or key == ord("_"):
            THRESHOLD_VALUE = max(
                0,
                THRESHOLD_VALUE - 5
            )

            print("Threshold:", THRESHOLD_VALUE)

    print("Shutting down...")

    for cam in cameras:
        cam.stop()

    cv.destroyAllWindows()


if __name__ == "__main__":
    main()