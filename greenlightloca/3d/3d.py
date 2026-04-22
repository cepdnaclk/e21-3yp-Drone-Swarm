import cv2 as cv
import numpy as np

# --- 1. LOAD CALIBRATION ---
DATA = np.load("stereo_data.npz")
K1, D1 = DATA['m1'], DATA['d1']

# --- 2. YOUR HSV (Widened slightly for testing) ---
LOWER_0 = np.array([50, 0, 150]) # Lowered Value and Hue floor
UPPER_0 = np.array([110, 80, 255]) 

cap0 = cv.VideoCapture(1, cv.CAP_DSHOW)
cap0.set(cv.CAP_PROP_EXPOSURE, -7)

print("Check the 'Mask' window. If it is black, the LED isn't being detected.")

while True:
    ret, frame = cap0.read()
    if not ret: break

    # The most important step: Undistort first
    undistorted = cv.undistort(frame, K1, D1)
    
    hsv = cv.cvtColor(undistorted, cv.COLOR_BGR2HSV)
    mask = cv.inRange(hsv, LOWER_0, UPPER_0)
    
    # Show the internal logic
    cv.imshow("1. Undistorted Live", undistorted)
    cv.imshow("2. Detection Mask", mask)

    if cv.waitKey(1) == ord('q'): break

cap0.release()
cv.destroyAllWindows()