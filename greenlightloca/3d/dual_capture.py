import cv2
import numpy as np

# --- SETTINGS ---
EXPOSURE_VAL = -7  # Your verified exposure level
CAM0_INDEX = 1     # First USB Webcam
CAM1_INDEX = 2     # Second USB Webcam
# ----------------

# Initialize both USB cameras
cap0 = cv2.VideoCapture(CAM0_INDEX, cv2.CAP_DSHOW)
cap1 = cv2.VideoCapture(CAM1_INDEX, cv2.CAP_DSHOW)

# Apply settings to both cameras
for cap in [cap0, cap1]:
    # Lock settings so they don't jump around
    cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25) 
    cap.set(cv2.CAP_PROP_EXPOSURE, EXPOSURE_VAL)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

if not cap0.isOpened() or not cap1.isOpened():
    print("Error: Could not open one or both USB cameras. Check your indices (1 & 2).")
    exit()

print("Dual Capture Active.")
print("1. Hold the LED so it is visible in BOTH camera windows.")
print("2. Press 'S' to save separate photos for each camera.")
print("3. Press 'Q' to quit.")

while True:
    ret0, frame0 = cap0.read()
    ret1, frame1 = cap1.read()
    
    if ret0 and ret1:
        # Display separate windows so you can check alignment
        cv2.imshow("Cam 0 - Preview", frame0)
        cv2.imshow("Cam 1 - Preview", frame1)
        
        key = cv2.waitKey(1) & 0xFF
        
        if key == ord('s'):
            # Save separate files
            cv2.imwrite("hsv_cam0.jpg", frame0)
            cv2.imwrite("hsv_cam1.jpg", frame1)
            print("Successfully saved 'hsv_cam0.jpg' and 'hsv_cam1.jpg'")
            print("Now upload these to your tuner to find individual HSV values.")
            break
            
        elif key == ord('q'):
            break

cap0.release()
cap1.release()
cv2.destroyAllWindows()