import cv2
import numpy as np
import glob
import os
import json
import threading

# =========================
# SETTINGS
# =========================

CHECKERBOARD = (9, 6)
SQUARE_SIZE = 23.4

CAMERAS = ["cam1", "cam2", "cam3", "cam4"]
CAMERA_INDICES = [0, 2, 3, 4]   # change if needed

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGE_FOLDER = os.path.join(BASE_DIR, "extrinsic_images")

os.makedirs(IMAGE_FOLDER, exist_ok=True)

# =========================
# THREADED CAMERA CLASS
# =========================

class ThreadedCamera:
    def __init__(self, index, width=640, height=480):
        self.index = index
        self.cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)

        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        self.ret, self.frame = self.cap.read()
        self.running = True
        self.lock = threading.Lock()

        self.thread = threading.Thread(target=self.update)
        self.thread.daemon = True
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
# OBJECT POINTS
# =========================

def create_object_points():
    objp = np.zeros((CHECKERBOARD[0] * CHECKERBOARD[1], 3), np.float32)

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
        f"camera_{cam_num}_params_new.json"
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

    ret, corners = cv2.findChessboardCornersSB(
        gray,
        CHECKERBOARD,
        cv2.CALIB_CB_NORMALIZE_IMAGE | cv2.CALIB_CB_EXHAUSTIVE
    )

    return ret, corners

# =========================
# LIVE VIEW
# =========================

def live_checkerboard_view():

    cams = [
        ThreadedCamera(idx)
        for idx in CAMERA_INDICES
    ]

    window_name = "4 Camera Checkerboard Detection"

    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, 1200, 700)

    print("\nLive view started")
    print("Press SPACE to save images")
    print("Press Q to quit live view and compute extrinsics\n")

    save_count = 1

    while True:
        frames = []
        clean_frames = []
        detected_status = []

        for i, cam in enumerate(cams):
            ret, frame = cam.read()

            if not ret or frame is None:
                frame = np.zeros((480, 640, 3), dtype=np.uint8)
                clean_frame = frame.copy()

                cv2.putText(
                    frame,
                    f"{CAMERAS[i]}: CAMERA ERROR",
                    (30, 50),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1,
                    (0, 0, 255),
                    2
                )

                frames.append(frame)
                clean_frames.append(clean_frame)
                detected_status.append(False)
                continue

            clean_frame = frame.copy()

            found, corners = detect_corners(frame)
            detected_status.append(found)

            if found:
                cv2.drawChessboardCorners(
                    frame,
                    CHECKERBOARD,
                    corners,
                    found
                )

                text = f"{CAMERAS[i]}: DETECTED"
                color = (0, 255, 0)

            else:
                text = f"{CAMERAS[i]}: NOT DETECTED"
                color = (0, 0, 255)

            cv2.putText(
                frame,
                text,
                (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                color,
                2
            )

            frames.append(frame)
            clean_frames.append(clean_frame)

        top = np.hstack((frames[0], frames[1]))
        bottom = np.hstack((frames[2], frames[3]))
        combined = np.vstack((top, bottom))

        display = cv2.resize(combined, (1200, 700))
        cv2.imshow(window_name, display)

        key = cv2.waitKey(1) & 0xFF

        if key == ord(" "):

            if all(detected_status):

                for i, frame in enumerate(clean_frames):
                    filename = os.path.join(
                        IMAGE_FOLDER,
                        f"{CAMERAS[i]}_{save_count}.jpg"
                    )

                    cv2.imwrite(filename, frame)

                print(f"[SAVED] Image set {save_count}")
                save_count += 1

            else:
                print("[NOT SAVED] Checkerboard not detected in all 4 cameras")

        elif key == ord("q"):
            break

    for cam in cams:
        cam.release()

    cv2.destroyAllWindows()

# =========================
# COMPUTE CAMERA POSE
# =========================

def compute_camera_pose(cam):
    objp = create_object_points()

    K, dist = load_intrinsics(cam)

    rvecs = []
    tvecs = []
    errors = []

    image_paths = sorted(
        glob.glob(os.path.join(IMAGE_FOLDER, f"{cam}_*.jpg"))
    )

    print(f"\n========== {cam.upper()} ==========")

    if len(image_paths) == 0:
        print("No images found")
        return None

    for path in image_paths:
        img = cv2.imread(path)

        if img is None:
            print(f"[IMAGE LOAD FAIL] {os.path.basename(path)}")
            continue

        ret, corners = detect_corners(img)

        if not ret:
            print(f"[CHECKERBOARD FAIL] {os.path.basename(path)}")
            continue

        success, rvec, tvec = cv2.solvePnP(
            objp,
            corners,
            K,
            dist
        )

        if not success:
            print(f"[PnP FAIL] {os.path.basename(path)}")
            continue

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

        rvecs.append(rvec)
        tvecs.append(tvec)
        errors.append(error)

        print(
            f"[OK] {os.path.basename(path)} "
            f"| error = {error:.4f}"
        )

    if len(rvecs) == 0:
        print("No valid poses")
        return None

    errors = np.array(errors)

    best_idx = np.argsort(errors)[
        :max(3, len(errors) // 2)
    ]

    R_list = []
    t_list = []

    for i in best_idx:
        R, _ = cv2.Rodrigues(rvecs[i])
        R_list.append(R)
        t_list.append(tvecs[i])

    t_avg = np.mean(t_list, axis=0)

    R_avg = np.mean(R_list, axis=0)

    U, _, Vt = np.linalg.svd(R_avg)
    R_avg = U @ Vt

    return R_avg, t_avg

# =========================
# CAMERA CENTER
# =========================

def get_camera_center(R, t):
    return -R.T @ t

# =========================
# MAIN
# =========================

def main():

    live_checkerboard_view()

    camera_poses = {}

    for cam in CAMERAS:

        try:
            result = compute_camera_pose(cam)

            if result is None:
                continue

            R, t = result
            C = get_camera_center(R, t)

            camera_poses[cam] = (R, t, C)

            print("\nFinal Pose")
            print("R =\n", R)
            print("t =\n", t)
            print("Camera Center =\n", C)

            np.savez(
                os.path.join(BASE_DIR, f"{cam}_extrinsics.npz"),
                R=R,
                t=t,
                C=C
            )

            print(f"Saved {cam}_extrinsics.npz")

        except Exception as e:
            print(f"ERROR in {cam}: {e}")

    print("\n=========== FINAL CAMERA POSITIONS ===========\n")

    for cam, (_, _, C) in camera_poses.items():
        print(f"{cam}: {C.flatten()}")

if __name__ == "__main__":
    main()