import cv2 as cv
import numpy as np

# --- 1. SETTINGS ---
DATA = np.load("stereo_data.npz")
K1, D1 = DATA['m1'], DATA['d1']
K2, D2 = DATA['m2'], DATA['d2']
R, T = DATA['R'], DATA['T']

# Projection Matrices
P1 = K1 @ np.hstack((np.eye(3), np.zeros((3, 1))))
P2 = K2 @ np.hstack((R, T))

# HSV for your specific cameras
LOWER_0, UPPER_0 = np.array([58, 0, 200]), np.array([99, 36, 255])
LOWER_1, UPPER_1 = np.array([54, 0, 200]), np.array([87, 60, 255])

# CAMERA HEIGHT (Measure this: How high are your cameras from the floor in mm?)
CAM_HEIGHT_FROM_FLOOR = 1000 

# --- 2. DLT TRIANGULATION ---
def triangulate_dlt(P1, P2, pt1, pt2):
    A = [pt1[1]*P1[2,:]-P1[1,:], P1[0,:]-pt1[0]*P1[2,:],
         pt2[1]*P2[2,:]-P2[1,:], P2[0,:]-pt2[0]*P2[2,:]]
    A = np.array(A).reshape((4,4))
    _, _, Vh = np.linalg.svd(A)
    return Vh[-1,0:3] / Vh[-1,3]

# --- 3. DETECTION ---
def get_point(frame, lower, upper, K, D):
    frame_undistorted = cv.undistort(frame, K, D)
    hsv = cv.cvtColor(frame_undistorted, cv.COLOR_BGR2HSV)
    mask = cv.inRange(hsv, lower, upper)
    cnts, _ = cv.findContours(mask, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
    if cnts:
        c = max(cnts, key=cv.contourArea)
        M = cv.moments(c)
        if M["m00"] != 0:
            return [float(M["m10"]/M["m00"]), float(M["m01"]/M["m00"])], frame_undistorted
    return None, frame_undistorted

cap0, cap1 = cv.VideoCapture(1, cv.CAP_DSHOW), cv.VideoCapture(2, cv.CAP_DSHOW)
for cap in [cap0, cap1]:
    cap.set(cv.CAP_PROP_EXPOSURE, -7)

print("Drone Localization Active...")

while True:
    ret0, frame0 = cap0.read()
    ret1, frame1 = cap1.read()
    if not ret0 or not ret1: continue

    p0, f0 = get_point(frame0, LOWER_0, UPPER_0, K1, D1)
    p1, f1 = get_point(frame1, LOWER_1, UPPER_1, K2, D2)

    if p0 and p1:
        # RAW COORDINATES (Relative to Left Cam)
        raw_pt = triangulate_dlt(P1, P2, p0, p1)
        
        # --- DRONE AXIS LOGIC ---
        # In Camera Space: x=right, y=down, z=forward
        # We want: X=Right, Y=Forward (Depth), Z=Up (Height)
        
        drone_X = raw_pt[0]             # Lateral
        drone_Y = raw_pt[2]             # Depth (How far into the room)
        drone_Z = -raw_pt[1] + CAM_HEIGHT_FROM_FLOOR # Height from ground
        
        print(f"DRONE POS -> X: {int(drone_X)} Y: {int(drone_Y)} Z: {int(drone_Z)} mm")
        
        cv.putText(f0, f"HEIGHT (Z): {int(drone_Z)}mm", (30, 50), 2, 0.8, (0,255,0), 2)

    cv.imshow("Drone Tracker", np.hstack((f0, f1)))
    if cv.waitKey(1) == ord('q'): break

cap0.release(); cap1.release(); cv.destroyAllWindows()