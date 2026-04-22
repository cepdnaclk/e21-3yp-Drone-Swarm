import cv2
import numpy as np
import glob

CHECKERBOARD = (9, 6)
SQUARE_SIZE = 23 # mm (Measure your printed square!)

objp = np.zeros((CHECKERBOARD[0]*CHECKERBOARD[1], 3), np.float32)
objp[:,:2] = np.mgrid[0:CHECKERBOARD[0], 0:CHECKERBOARD[1]].T.reshape(-1,2) * SQUARE_SIZE

objpoints, imgpts_l, imgpts_r = [], [], []

images_l = sorted(glob.glob('stereo_calib_images/left_*.jpg'))
images_r = sorted(glob.glob('stereo_calib_images/right_*.jpg'))

for img_l, img_r in zip(images_l, images_r):
    l, r = cv2.imread(img_l), cv2.imread(img_r)
    gray_l, gray_r = cv2.cvtColor(l, cv2.COLOR_BGR2GRAY), cv2.cvtColor(r, cv2.COLOR_BGR2GRAY)
    ret_l, corners_l = cv2.findChessboardCorners(gray_l, CHECKERBOARD, None)
    ret_r, corners_r = cv2.findChessboardCorners(gray_r, CHECKERBOARD, None)

    if ret_l and ret_r:
        objpoints.append(objp)
        imgpts_l.append(cv2.cornerSubPix(gray_l, corners_l, (11,11), (-1,-1), (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)))
        imgpts_r.append(cv2.cornerSubPix(gray_r, corners_r, (11,11), (-1,-1), (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)))

# Calibrate
ret, m1, d1, m2, d2, R, T, E, F = cv2.stereoCalibrate(objpoints, imgpts_l, imgpts_r, None, None, None, None, gray_l.shape[::-1])

# Save Results
np.savez("stereo_data.npz", m1=m1, d1=d1, m2=m2, d2=d2, R=R, T=T)
print(f"Calibration Complete! Baseline distance: {abs(T[0][0])} mm")