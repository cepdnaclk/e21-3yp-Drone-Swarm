import cv2
import numpy as np
import os
import json
import threading

# =========================
# SETTINGS
# =========================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CAMERAS = ["cam1", "cam2", "cam3", "cam4"]
CAMERA_INDICES = [1, 2, 3, 4]

WIDTH = 640
HEIGHT = 480

MIN_BLOB_AREA = 3
MAX_BLOB_AREA = 5000

PREVIEW_WIDTH = 1200
PREVIEW_HEIGHT = 800

# =========================
# THREADED CAMERA
# =========================

class ThreadedCamera:
    def __init__(self, index):
        self.index = index
        self.cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)

        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

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

    def release(self):
        self.running = False
        self.thread.join()
        self.cap.release()

# =========================
# LOAD INTRINSICS
# =========================

def load_intrinsics(cam_num):
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

    dist = np.array(
        data["distortion_coef"],
        dtype=np.float64
    )

    return K, dist

# =========================
# LOAD EXTRINSICS
# =========================

def load_camera_poses():
    """
    Returns world-to-camera poses for triangulation.

    World coordinate system = cam1 coordinate system.

    For cam1:
        X_cam1 = I * X_world + 0

    For cam2/cam3/cam4:
        The saved npz is assumed to contain:
            R = camera-to-world rotation
            t = camera center position in world/cam1 coordinates

        So we convert:
            R_world_to_cam = R.T
            t_world_to_cam = -R.T @ C
    """

    poses = {}

    poses["cam1"] = {
        "R": np.eye(3, dtype=np.float64),
        "t": np.zeros((3, 1), dtype=np.float64)
    }

    for cam_num in [2, 3, 4]:
        cam = f"cam{cam_num}"

        filename = os.path.join(
            BASE_DIR,
            f"{cam}_relative_to_cam1.npz"
        )

        data = np.load(filename)

        R_cam_to_world = data["R"].astype(np.float64)
        C_world = data["t"].astype(np.float64).reshape(3, 1)

        R_world_to_cam = R_cam_to_world.T
        t_world_to_cam = -R_world_to_cam @ C_world

        poses[cam] = {
            "R": R_world_to_cam,
            "t": t_world_to_cam
        }

    return poses

# =========================
# PROJECTION MATRICES
# =========================

def build_projection_matrices():
    poses = load_camera_poses()

    projection_matrices = {}
    intrinsics = {}
    distortions = {}

    for i, cam in enumerate(CAMERAS):
        cam_num = i + 1

        K, dist = load_intrinsics(cam_num)

        R = poses[cam]["R"]
        t = poses[cam]["t"]

        Rt = np.hstack((R, t))

        P = K @ Rt

        projection_matrices[cam] = P
        intrinsics[cam] = K
        distortions[cam] = dist

    return projection_matrices, intrinsics, distortions

# =========================
# RED BRIGHT SPOT DETECTION
# =========================

def detect_red_bright_spot(frame, threshold):
    """
    Uses only the red channel.
    Low red intensities are blackened.
    Brightest valid blob is selected.
    """

    red_channel = frame[:, :, 2]

    _, mask = cv2.threshold(
        red_channel,
        threshold,
        255,
        cv2.THRESH_BINARY
    )

    mask = cv2.medianBlur(mask, 5)

    kernel = np.ones((3, 3), np.uint8)

    mask = cv2.morphologyEx(
        mask,
        cv2.MORPH_OPEN,
        kernel
    )

    mask = cv2.morphologyEx(
        mask,
        cv2.MORPH_CLOSE,
        kernel
    )

    contours, _ = cv2.findContours(
        mask,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE
    )

    best_contour = None
    best_area = 0

    for contour in contours:
        area = cv2.contourArea(contour)

        if area < MIN_BLOB_AREA:
            continue

        if area > MAX_BLOB_AREA:
            continue

        if area > best_area:
            best_area = area
            best_contour = contour

    display = np.zeros_like(frame)
    display[:, :, 2] = mask

    if best_contour is None:
        return False, None, display, mask

    M = cv2.moments(best_contour)

    if M["m00"] == 0:
        return False, None, display, mask

    cx = int(M["m10"] / M["m00"])
    cy = int(M["m01"] / M["m00"])

    cv2.circle(
        display,
        (cx, cy),
        10,
        (0, 255, 0),
        2
    )

    cv2.drawContours(
        display,
        [best_contour],
        -1,
        (0, 255, 0),
        2
    )

    cv2.putText(
        display,
        f"({cx}, {cy})",
        (cx + 12, cy - 12),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (0, 255, 0),
        1
    )

    return True, (cx, cy), display, mask

# =========================
# UNDISTORT POINT
# =========================

def undistort_point(point, K, dist):
    pts = np.array(
        [[[point[0], point[1]]]],
        dtype=np.float64
    )

    undistorted = cv2.undistortPoints(
        pts,
        K,
        dist,
        P=K
    )

    x = undistorted[0, 0, 0]
    y = undistorted[0, 0, 1]

    return x, y

# =========================
# TRIANGULATION
# =========================

def triangulate_point(detections, projection_matrices, intrinsics, distortions):
    """
    detections:
        {
            "cam1": (u, v),
            "cam2": (u, v),
            ...
        }

    Uses linear multi-view triangulation.
    Needs at least 2 cameras.
    """

    if len(detections) < 2:
        return False, None

    A = []

    for cam, point in detections.items():
        K = intrinsics[cam]
        dist = distortions[cam]
        P = projection_matrices[cam]

        u, v = undistort_point(point, K, dist)

        A.append(u * P[2, :] - P[0, :])
        A.append(v * P[2, :] - P[1, :])

    A = np.array(A, dtype=np.float64)

    try:
        _, _, Vt = np.linalg.svd(A)

        X_homogeneous = Vt[-1]

        if abs(X_homogeneous[3]) < 1e-9:
            return False, None

        X = X_homogeneous[:3] / X_homogeneous[3]

        return True, X.reshape(3, 1)

    except Exception:
        return False, None

# =========================
# TRACKBARS
# =========================

def nothing(x):
    pass


def create_threshold_trackbars(window_name):
    cv2.createTrackbar("cam1 threshold", window_name, 200, 255, nothing)
    cv2.createTrackbar("cam2 threshold", window_name, 200, 255, nothing)
    cv2.createTrackbar("cam3 threshold", window_name, 200, 255, nothing)
    cv2.createTrackbar("cam4 threshold", window_name, 200, 255, nothing)


def get_thresholds(window_name):
    thresholds = {}

    for cam in CAMERAS:
        value = cv2.getTrackbarPos(
            f"{cam} threshold",
            window_name
        )

        thresholds[cam] = value

    return thresholds

# =========================
# MAIN
# =========================

def main():
    projection_matrices, intrinsics, distortions = build_projection_matrices()

    cams = [
        ThreadedCamera(index)
        for index in CAMERA_INDICES
    ]

    window_name = "Red Bright Spot 3D Tracking"

    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, PREVIEW_WIDTH, PREVIEW_HEIGHT)

    create_threshold_trackbars(window_name)

    print("\nLive red bright spot tracking started")
    print("Use trackbars to adjust red intensity threshold per camera")
    print("Press Q to quit\n")

    while True:
        thresholds = get_thresholds(window_name)

        processed_frames = []
        detections = {}

        for i, cam_name in enumerate(CAMERAS):
            ret, frame = cams[i].read()

            if not ret or frame is None:
                display = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)

                cv2.putText(
                    display,
                    f"{cam_name}: CAMERA ERROR",
                    (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (0, 0, 255),
                    2
                )

                processed_frames.append(display)
                continue

            found, point, display, _ = detect_red_bright_spot(
                frame,
                thresholds[cam_name]
            )

            if found:
                detections[cam_name] = point

                status_text = f"{cam_name}: DETECTED  T={thresholds[cam_name]}"
                status_color = (0, 255, 0)
            else:
                status_text = f"{cam_name}: NOT DETECTED  T={thresholds[cam_name]}"
                status_color = (0, 0, 255)

            cv2.putText(
                display,
                status_text,
                (20, 35),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                status_color,
                2
            )

            processed_frames.append(display)

        valid_3d, point_3d = triangulate_point(
            detections,
            projection_matrices,
            intrinsics,
            distortions
        )

        top = np.hstack((processed_frames[0], processed_frames[1]))
        bottom = np.hstack((processed_frames[2], processed_frames[3]))
        combined = np.vstack((top, bottom))

        info_panel = np.zeros((90, combined.shape[1], 3), dtype=np.uint8)

        detected_cams_text = "Detected cameras: " + ", ".join(detections.keys())

        if len(detections) == 0:
            detected_cams_text = "Detected cameras: none"

        cv2.putText(
            info_panel,
            detected_cams_text,
            (20, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (255, 255, 255),
            2
        )

        if valid_3d:
            x = point_3d[0, 0]
            y = point_3d[1, 0]
            z = point_3d[2, 0]

            coord_text = f"3D Coordinate in cam1 frame: X={x:.2f} mm, Y={y:.2f} mm, Z={z:.2f} mm"
            coord_color = (0, 255, 0)

        else:
            coord_text = "3D Coordinate: not available - need detection in at least 2 cameras"
            coord_color = (0, 0, 255)

        cv2.putText(
            info_panel,
            coord_text,
            (20, 65),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            coord_color,
            2
        )

        final_view = np.vstack((combined, info_panel))

        final_view = cv2.resize(
            final_view,
            (PREVIEW_WIDTH, PREVIEW_HEIGHT)
        )

        cv2.imshow(window_name, final_view)

        key = cv2.waitKey(1) & 0xFF

        if key == ord("q"):
            break

    for cam in cams:
        cam.release()

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()