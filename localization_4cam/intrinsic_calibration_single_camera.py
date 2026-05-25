import cv2
import numpy as np
import os
import json
import glob

CHECKERBOARD = (9, 6)
SQUARE_SIZE = 23.9

CAMERA_INDEX = 4
CAMERA_NUMBER = 3

WIDTH = 640
HEIGHT = 480

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

IMAGE_FOLDER = os.path.join(
    BASE_DIR,
    f"intrinsic_images_camera_{CAMERA_NUMBER}"
)

os.makedirs(IMAGE_FOLDER, exist_ok=True)


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


def live_capture_images():
    cap = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_DSHOW)

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    window_name = "Intrinsic Calibration Capture"

    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, 900, 700)

    print("\nLive capture started")
    print("Press SPACE to save image if checkerboard is detected")
    print("Press Q to finish capture and calculate intrinsics\n")

    save_count = len(
        glob.glob(
            os.path.join(
                IMAGE_FOLDER,
                "*.jpg"
            )
        )
    ) + 1

    while True:
        ret, frame = cap.read()

        if not ret:
            print("Camera read failed")
            break

        clean_frame = frame.copy()

        found, corners = detect_corners(frame)

        if found:
            cv2.drawChessboardCorners(
                frame,
                CHECKERBOARD,
                corners,
                found
            )

            text = "CHECKERBOARD DETECTED"
            color = (0, 255, 0)
        else:
            text = "NOT DETECTED"
            color = (0, 0, 255)

        cv2.putText(
            frame,
            text,
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.9,
            color,
            2
        )

        cv2.putText(
            frame,
            f"Saved images: {save_count - 1}",
            (20, 80),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (255, 255, 255),
            2
        )

        display = cv2.resize(frame, (900, 700))

        cv2.imshow(window_name, display)

        key = cv2.waitKey(1) & 0xFF

        if key == ord(" "):
            found_now, _ = detect_corners(clean_frame)

            if found_now:
                filename = os.path.join(
                    IMAGE_FOLDER,
                    f"cam{CAMERA_NUMBER}_{save_count}.jpg"
                )

                cv2.imwrite(filename, clean_frame)

                print(f"[SAVED] {filename}")

                save_count += 1
            else:
                print("[NOT SAVED] Checkerboard not detected")

        elif key == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


def calibrate_intrinsics():
    objp = create_object_points()

    object_points = []
    image_points = []

    image_paths = sorted(
        glob.glob(
            os.path.join(
                IMAGE_FOLDER,
                "*.jpg"
            )
        )
    )

    image_size = None

    print(f"\nFound {len(image_paths)} images")

    for path in image_paths:
        img = cv2.imread(path)

        if img is None:
            print(f"[LOAD FAIL] {os.path.basename(path)}")
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

    if len(object_points) < 10:
        print("\nNot enough valid images")
        print("Use at least 15-25 good images")
        return

    rms_error, K, dist, rvecs, tvecs = cv2.calibrateCamera(
        object_points,
        image_points,
        image_size,
        None,
        None
    )

    output_path = os.path.join(
        BASE_DIR,
        f"camera_{CAMERA_NUMBER}_params_new.json"
    )

    data = {
        "intrinsic_matrix": K.tolist(),
        "distortion_coef": dist.tolist(),
        "rms_error": float(rms_error),
        "image_size": {
            "width": int(image_size[0]),
            "height": int(image_size[1])
        },
        "valid_images": int(len(object_points)),
        "square_size": float(SQUARE_SIZE)
    }

    with open(output_path, "w") as f:
        json.dump(data, f, indent=4)

    print("\n========== INTRINSICS ==========")
    print("RMS error:", rms_error)
    print("Image size:", image_size)
    print("Valid images:", len(object_points))

    print("\nK =")
    print(K)

    print("\ndist =")
    print(dist)

    print(f"\nSaved: {output_path}")


def main():
    live_capture_images()
    calibrate_intrinsics()


if __name__ == "__main__":
    main()