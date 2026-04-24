import cv2 as cv
import numpy as np
import json
import os

#repeat this for each camera by changing CAMERA_ID to 1, 2, and 3 respectively
# --- SETTINGS ---
CAMERA_ID = 4 # Change this to 1, 2, and 3 for the other cameras
CHECKERBOARD = (9, 6) # Number of internal corners (width, height)
SQUARE_SIZE = 0.023 # Size of a square in meters (e.g., 25mm = 0.025)

def calibrate_camera(camera_id):
    criteria = (cv.TERM_CRITERIA_EPS + cv.TERM_CRITERIA_MAX_ITER, 30, 0.001)
    objp = np.zeros((CHECKERBOARD[0] * CHECKERBOARD[1], 3), np.float32)
    objp[:, :2] = np.mgrid[0:CHECKERBOARD[0], 0:CHECKERBOARD[1]].T.reshape(-1, 2)
    objp *= SQUARE_SIZE

    objpoints = []
    imgpoints = []

    # Added CAP_DSHOW to prevent Windows indexing errors
    cap = cv.VideoCapture(camera_id, cv.CAP_DSHOW)
    
    # --- DECREASE RESOLUTION HERE ---
    cap.set(cv.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv.CAP_PROP_FRAME_HEIGHT, 480)

    print(f"--- Camera {camera_id} Calibration ---")
    print("Press 's' to save a frame (need ~20). Press 'q' to calculate and quit.")

    while True:
        ret, frame = cap.read()
        if not ret: break
        
        gray = cv.cvtColor(frame, cv.COLOR_BGR2GRAY)
        ret_corners, corners = cv.findChessboardCorners(gray, CHECKERBOARD, None)

        display = frame.copy()
        if ret_corners:
            cv.drawChessboardCorners(display, CHECKERBOARD, corners, ret_corners)
            cv.putText(display, "Corners Found! Press 's'", (10, 30), cv.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

        cv.putText(display, f"Saved: {len(imgpoints)}/20", (10, 60), cv.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
        cv.imshow(f'Calibration Cam {camera_id}', display)

        key = cv.waitKey(1)
        if key == ord('s') and ret_corners:
            corners_subpix = cv.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
            objpoints.append(objp)
            imgpoints.append(corners_subpix)
            print(f"Captured {len(imgpoints)} frames")
        elif key == ord('q'):
            break

    cap.release()
    cv.destroyAllWindows()

    if len(imgpoints) > 0:
        print("Calculating matrix... Please wait.")
        ret, mtx, dist, _, _ = cv.calibrateCamera(objpoints, imgpoints, gray.shape[::-1], None, None)
        
        data = {
            "intrinsic_matrix": mtx.tolist(),
            "distortion_coef": dist.tolist()
        }
        with open(f"camera_{camera_id}_params.json", "w") as f:
            json.dump(data, f)
        print(f"SUCCESS: Saved camera_{camera_id}_params.json")
    else:
        print("No frames saved. Exiting.")

if __name__ == "__main__":
    calibrate_camera(CAMERA_ID)