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


def save_intrinsics_json(cam, K, dist, rms_error, image_size, valid_count):
    cam_num = cam.replace("cam", "")

    output_path = os.path.join(
        BASE_DIR,
        f"camera_{cam_num}_params_test.json"
    )

    data = {
        "intrinsic_matrix": K.tolist(),
        "distortion_coef": dist.tolist(),
        "rms_error": float(rms_error),
        "image_size": {
            "width": int(image_size[0]),
            "height": int(image_size[1])
        },
        "valid_images": int(valid_count),
        "square_size": float(SQUARE_SIZE)
    }

    with open(output_path, "w") as f:
        json.dump(data, f, indent=4)

    print(f"Saved {output_path}")


def calibrate_camera_from_saved_images(cam):
    objp = create_object_points()

    object_points = []
    image_points = []

    image_paths = sorted(
        glob.glob(
            os.path.join(
                IMAGE_FOLDER,
                f"{cam}_*.jpg"
            )
        )
    )

    image_size = None

    print(f"\n========== {cam.upper()} ==========")

    for path in image_paths:
        img = cv2.imread(path)

        if img is None:
            print(f"[IMAGE LOAD FAIL] {os.path.basename(path)}")
            continue

        image_size = (img.shape[1], img.shape[0])

        found, corners = detect_corners(img)

        if not found:
            print(f"[FAIL] {os.path.basename(path)}")
            continue

        object_points.append(objp)
        image_points.append(corners)

        print(f"[OK] {os.path.basename(path)}")

    if len(object_points) < 5:
        print("Not enough valid checkerboard images")
        return

    rms_error, K, dist, rvecs, tvecs = cv2.calibrateCamera(
        object_points,
        image_points,
        image_size,
        None,
        None
    )

    print("\nImage size:", image_size)
    print("Valid images:", len(object_points))
    print("RMS error:", rms_error)

    print("\nIntrinsic matrix:")
    print(K)

    print("\nDistortion coefficients:")
    print(dist)

    save_intrinsics_json(
        cam,
        K,
        dist,
        rms_error,
        image_size,
        len(object_points)
    )


def main():
    for cam in CAMERAS:
        calibrate_camera_from_saved_images(cam)


if __name__ == "__main__":
    main()