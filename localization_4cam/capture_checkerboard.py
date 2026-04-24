import os
# Fix for OpenBLAS memory errors
os.environ["OPENBLAS_NUM_THREADS"] = "1"

import cv2
import numpy as np
import time

# --- CONFIGURATION ---
CHECKERBOARD = (6, 9)  # Internal corners (Width, Height)
FOLDER = 'quad_camera_images'
CAMERA_INDICES = [1, 2, 3, 4] 

if not os.path.exists(FOLDER):
    os.makedirs(FOLDER)

caps = []

print("Initializing cameras. For each popup, ensure 'Auto Exposure' is checked.")

for i, idx in enumerate(CAMERA_INDICES):
    cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
    if not cap.isOpened():
        print(f"Warning: Camera {idx} could not be opened.")
        continue
    
    # 1. Open the Windows Camera Settings Dialog
    cap.set(cv2.CAP_PROP_SETTINGS, 1) 
    
    # 2. Programmatic Reset
    cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 3) 
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    
    # Initialize the window for this specific camera
    window_name = f"Camera {i} (Index {idx})"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, 400, 300) # Force a smaller size for the screen
    
    time.sleep(0.5)
    caps.append(cap)

if len(caps) == 0:
    print("No cameras detected. Exiting.")
    exit()

print(f"\nSuccessfully connected to {len(caps)} cameras.")
print("--- CONTROLS ---")
print("S: Save Image Set (Must see colorful grid in ALL windows)")
print("Q: Quit")

count = 0
while True:
    frames = []
    all_found = True

    for i, cap in enumerate(caps):
        ret, frame = cap.read()
        window_name = f"Camera {i} (Index {idx})"
        
        if not ret:
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(frame, "NO SIGNAL", (50, 240), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            all_found = False
            frames.append(frame)
            cv2.imshow(window_name, frame)
        else:
            frames.append(frame)
            # Detect checkerboard for visual feedback
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            found, corners = cv2.findChessboardCorners(gray, CHECKERBOARD, 
                                                     cv2.CALIB_CB_ADAPTIVE_THRESH + cv2.CALIB_CB_FAST_CHECK)
            
            view_frame = frame.copy()
            if found:
                cv2.drawChessboardCorners(view_frame, CHECKERBOARD, corners, found)
            else:
                all_found = False
            
            # Show the individual window
            cv2.imshow(f"Camera {i} (Index {idx})", view_frame)

    key = cv2.waitKey(1) & 0xFF
    
    if key == ord('s'):
        if not all_found:
            print("❌ Cannot save: Checkerboard missing in at least one feed.")
        else:
            for i, frame in enumerate(frames):
                filename = f"{FOLDER}/cam{i}_{count}.jpg"
                cv2.imwrite(filename, frame)
            print(f"✅ Set {count} saved!")
            count += 1
        
    elif key == ord('q'):
        break

# Clean up
for cap in caps:
    cap.release()
cv2.destroyAllWindows()