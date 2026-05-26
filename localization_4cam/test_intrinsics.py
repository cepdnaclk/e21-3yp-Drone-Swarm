import cv2
import numpy as np
import glob
import os
import json

CHECKERBOARD = (9, 6)
SQUARE_SIZE = 23.9

CAMERAS = ["cam1", "cam2", "cam3", "cam4"]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGE_FOLDER = os.path.join(BASE_DIR, "extrinsic_images")


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


def detect_corners(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    found, corners = cv2.findChessboardCornersSB(
        gray,
        CHECKERBOARD,
        cv2.CALIB_CB_NORMALIZE_IMAGE |
        cv2.CALIB_CB_EXHAUSTIVE
    )

    return found, corners


def load_old_intrinsics(cam):
    cam_num = cam.replace("cam", "")

    filename = os.path.join(
        BASE_DIR,
        f"camera_{cam_num}_params.json"
    )

    with open(filename, "r") as f:
        data = json.load(f)

    K_old = np.array(data["intrinsic_matrix"], dtype=np.float64)
    dist_old = np.array(data["distortion_coef"], dtype=np.float64)

    return K_old, dist_old


def check_intrinsics_from_extrinsic_images():
    objp = create_object_points()

    for cam in CAMERAS:
        print(f"\n========== {cam.upper()} ==========")

        image_paths = sorted(
            glob.glob(
                os.path.join(
                    IMAGE_FOLDER,
                    f"{cam}_*.jpg"
                )
            )
        )

        object_points = []
        image_points = []

        image_size = None

        for path in image_paths:
            img = cv2.imread(path)

            if img is None:
                continue

            image_size = (
                img.shape[1],
                img.shape[0]
            )

            found, corners = detect_corners(img)

            if found:
                object_points.append(objp)
                image_points.append(corners)

                print(f"[OK] {os.path.basename(path)}")
            else:
                print(f"[FAIL] {os.path.basename(path)}")

        if len(object_points) < 5:
            print("Not enough valid checkerboard images")
            continue

        ret, K_new, dist_new, rvecs, tvecs = cv2.calibrateCamera(
            object_points,
            image_points,
            image_size,
            None,
            None
        )

        K_old, dist_old = load_old_intrinsics(cam)

        print("\nImage size:")
        print(image_size)

        print("\nOLD intrinsic matrix:")
        print(K_old)

        print("\nNEW intrinsic matrix from extrinsic images:")
        print(K_new)

        print("\nOLD distortion:")
        print(dist_old)

        print("\nNEW distortion:")
        print(dist_new)

        print("\nCalibration reprojection error:")
        print(ret)

        print("\nDifference in fx/fy:")
        print("fx old/new:", K_old[0, 0], K_new[0, 0])
        print("fy old/new:", K_old[1, 1], K_new[1, 1])

        print("\nDifference in cx/cy:")
        print("cx old/new:", K_old[0, 2], K_new[0, 2])
        print("cy old/new:", K_old[1, 2], K_new[1, 2])


if __name__ == "__main__":
    check_intrinsics_from_extrinsic_images()