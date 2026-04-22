import cv2
import numpy as np
import glob

chessboard_size = (9,6)
square_size = 0.025  # measure your square size in meters

objp = np.zeros((9*6,3), np.float32)
objp[:,:2] = np.mgrid[0:9,0:6].T.reshape(-1,2)
objp *= square_size

def calibrate(folder):
    objpoints = []
    imgpoints = []

    images = glob.glob(folder + "/*.jpg")

    for fname in images:
        img = cv2.imread(fname)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        ret, corners = cv2.findChessboardCorners(gray, chessboard_size, None)

        if ret:
            objpoints.append(objp)
            imgpoints.append(corners)

    ret, mtx, dist, rvecs, tvecs = cv2.calibrateCamera(
        objpoints, imgpoints, gray.shape[::-1], None, None
    )

    print("Intrinsic Matrix:\n", mtx)
    print("Distortion:\n", dist)
    return mtx, dist

print("Camera 1:")
mtx1, dist1 = calibrate("calib_cam1")

print("\nCamera 2:")
mtx2, dist2 = calibrate("calib_cam2")