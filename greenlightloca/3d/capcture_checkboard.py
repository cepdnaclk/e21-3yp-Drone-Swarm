import cv2
import os

# Create folder if it doesn't exist
if not os.path.exists('stereo_calib_images'):
    os.makedirs('stereo_calib_images')

# Initialize both USB cameras
cap0 = cv2.VideoCapture(1, cv2.CAP_DSHOW)
cap1 = cv2.VideoCapture(2, cv2.CAP_DSHOW)

# Apply your working settings to BOTH
for cap in [cap0, cap1]:
    cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
    cap.set(cv2.CAP_PROP_EXPOSURE, -7) # Using your calibrated -8
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

print("1. Hold Checkerboard in view of BOTH cams.")
print("2. Press 'S' to Save a pair. Press 'Q' to Quit.")

count = 0
while True:
    ret0, frame0 = cap0.read()
    ret1, frame1 = cap1.read()
    if not ret0 or not ret1: continue

    cv2.imshow("Cam 0 (Left)", frame0)
    cv2.imshow("Cam 1 (Right)", frame1)

    key = cv2.waitKey(1)
    if key == ord('s'):
        cv2.imwrite(f"stereo_calib_images/left_{count}.jpg", frame0)
        cv2.imwrite(f"stereo_calib_images/right_{count}.jpg", frame1)
        print(f"Saved pair {count}")
        count += 1
    elif key == ord('q'):
        break

cap0.release()
cap1.release()
cv2.destroyAllWindows()