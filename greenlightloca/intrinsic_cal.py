import cv2
import numpy as np
import glob
import os

# =========================================================
# SETTINGS
# =========================================================

# Number of INNER corners in the checkerboard
# Example: if board has 10 x 7 squares, inner corners are 9 x 6
CHECKERBOARD = (9, 6)   # change this

# Real size of one square edge
# Use mm, cm, or m consistently
SQUARE_SIZE = 23.0      # change this if needed

# Folder containing calibration images
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGE_FOLDER = os.path.join(BASE_DIR, "stereo_calib_images")

# File patterns
LEFT_PATTERN = "left_*.jpg"
RIGHT_PATTERN = "right_*.jpg"

# Corner refinement criteria
CRITERIA = (
    cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER,
    30,
    0.001
)

# Show detected corners while processing
SHOW_CORNERS = True


# =========================================================
# PREPARE 3D OBJECT POINTS
# =========================================================

def create_checkerboard_points(checkerboard_size, square_size):
    objp = np.zeros((checkerboard_size[0] * checkerboard_size[1], 3), np.float32)
    objp[:, :2] = np.mgrid[0:checkerboard_size[0], 0:checkerboard_size[1]].T.reshape(-1, 2)
    objp *= square_size
    return objp


# =========================================================
# CALIBRATION FUNCTION FOR ONE CAMERA
# =========================================================

def calibrate_single_camera(image_paths, checkerboard_size, square_size, camera_name="camera"):
    objp = create_checkerboard_points(checkerboard_size, square_size)

    objpoints = []
    imgpoints = []
    image_size = None
    valid_images = []
    failed_images = []

    print(f"\n================ {camera_name.upper()} CAMERA =================")
    print(f"Found {len(image_paths)} images")

    if len(image_paths) == 0:
        print("No images found.")
        return None

    for fname in sorted(image_paths):
        img = cv2.imread(fname)

        if img is None:
            print(f"Could not read: {fname}")
            failed_images.append(fname)
            continue

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        if image_size is None:
            image_size = gray.shape[::-1]

        ret, corners = cv2.findChessboardCornersSB(
            gray,
            checkerboard_size,
            cv2.CALIB_CB_NORMALIZE_IMAGE | cv2.CALIB_CB_EXHAUSTIVE
        )

        if ret:
            corners_refined = corners

            objpoints.append(objp)
            imgpoints.append(corners_refined)
            valid_images.append(fname)

            print(f"[OK] {os.path.basename(fname)}")

            if SHOW_CORNERS:
                vis = img.copy()
                cv2.drawChessboardCorners(vis, checkerboard_size, corners_refined, ret)
                cv2.imshow(f"{camera_name} corners", vis)
                cv2.waitKey(200)
        else:
            print(f"[FAIL] Checkerboard not found: {os.path.basename(fname)}")
            failed_images.append(fname)

    if SHOW_CORNERS:
        cv2.destroyAllWindows()

    if len(objpoints) < 5:
        print(f"\nNot enough valid images for {camera_name} calibration.")
        print("Use at least 5-10 good checkerboard images.")
        return None

    # Calibrate camera
    rms, camera_matrix, dist_coeffs, rvecs, tvecs = cv2.calibrateCamera(
        objpoints,
        imgpoints,
        image_size,
        None,
        None
    )

    # Compute reprojection error
    total_error = 0.0
    for i in range(len(objpoints)):
        projected_points, _ = cv2.projectPoints(
            objpoints[i],
            rvecs[i],
            tvecs[i],
            camera_matrix,
            dist_coeffs
        )
        error = cv2.norm(imgpoints[i], projected_points, cv2.NORM_L2) / len(projected_points)
        total_error += error

    mean_error = total_error / len(objpoints)

    # Print results
    print(f"\n----- {camera_name.upper()} RESULTS -----")
    print(f"Used images: {len(valid_images)} / {len(image_paths)}")
    print(f"RMS error: {rms}")
    print(f"Mean reprojection error: {mean_error}\n")

    print("Camera Matrix:")
    print(camera_matrix)

    print("\nDistortion Coefficients:")
    print(dist_coeffs)

    fx = camera_matrix[0, 0]
    fy = camera_matrix[1, 1]
    cx = camera_matrix[0, 2]
    cy = camera_matrix[1, 2]

    print("\nDerived intrinsic values:")
    print(f"fx = {fx}")
    print(f"fy = {fy}")
    print(f"cx = {cx}")
    print(f"cy = {cy}")

    return {
        "camera_matrix": camera_matrix,
        "dist_coeffs": dist_coeffs,
        "rvecs": rvecs,
        "tvecs": tvecs,
        "rms": rms,
        "mean_error": mean_error,
        "valid_images": valid_images,
        "failed_images": failed_images,
        "image_size": image_size
    }


# =========================================================
# MAIN
# =========================================================

def main():
    left_images = glob.glob(os.path.join(IMAGE_FOLDER, LEFT_PATTERN))
    right_images = glob.glob(os.path.join(IMAGE_FOLDER, RIGHT_PATTERN))

    left_result = calibrate_single_camera(
        left_images,
        CHECKERBOARD,
        SQUARE_SIZE,
        camera_name="left"
    )

    right_result = calibrate_single_camera(
        right_images,
        CHECKERBOARD,
        SQUARE_SIZE,
        camera_name="right"
    )

    # Save results
    if left_result is not None:
        np.savez(
            "left_intrinsics.npz",
            camera_matrix=left_result["camera_matrix"],
            dist_coeffs=left_result["dist_coeffs"],
            rvecs=np.array(left_result["rvecs"], dtype=object),
            tvecs=np.array(left_result["tvecs"], dtype=object),
            rms=left_result["rms"],
            mean_error=left_result["mean_error"],
            image_size=left_result["image_size"]
        )
        print("\nSaved left camera calibration to left_intrinsics.npz")

    if right_result is not None:
        np.savez(
            "right_intrinsics.npz",
            camera_matrix=right_result["camera_matrix"],
            dist_coeffs=right_result["dist_coeffs"],
            rvecs=np.array(right_result["rvecs"], dtype=object),
            tvecs=np.array(right_result["tvecs"], dtype=object),
            rms=right_result["rms"],
            mean_error=right_result["mean_error"],
            image_size=right_result["image_size"]
        )
        print("Saved right camera calibration to right_intrinsics.npz")

    if left_result is not None and right_result is not None:
        print("\n================ SUMMARY ================\n")

        print("LEFT CAMERA")
        print("K_left =")
        print(left_result["camera_matrix"])
        print("dist_left =")
        print(left_result["dist_coeffs"])

        print("\nRIGHT CAMERA")
        print("K_right =")
        print(right_result["camera_matrix"])
        print("dist_right =")
        print(right_result["dist_coeffs"])


if __name__ == "__main__":
    main()