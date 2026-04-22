import cv2
import numpy as np

# --- SETTINGS FROM YOUR CALIBRATION ---
LOWER_HSV = np.array([42, 0, 183])
UPPER_HSV = np.array([75, 79, 255])
CORE_FILL_VAL = 13  
EXPOSURE_VAL = -8   # Ensure this matches your manual exposure calibration
# -------------------------------------------

cap = cv2.VideoCapture(1, cv2.CAP_DSHOW)
if not cap.isOpened():
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)

# --- LOCK CAMERA ---
cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25) 
cap.set(cv2.CAP_PROP_EXPOSURE, EXPOSURE_VAL)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

print(f"Tracking Started. Min Area set to 1 pixel.")

# Kernel for expanding the tiny dot
kernel = np.ones((CORE_FILL_VAL, CORE_FILL_VAL), np.uint8)

while True:
    ret, frame = cap.read()
    if not ret:
        break

    # 1. Process Frame
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, LOWER_HSV, UPPER_HSV)
    
    # 2. Make the tiny dot BIGGER (Dilation)
    # This helps when the LED is far away and looks like a single pixel
    mask = cv2.dilate(mask, kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    
    # 3. Find Contours
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    if contours:
        # Get the largest object in the mask
        largest_cnt = max(contours, key=cv2.contourArea)
        
        # CHANGED: Lowered threshold to 1. If there's even 1 white pixel, track it.
        if cv2.contourArea(largest_cnt) >= 1:
            x, y, w, h = cv2.boundingRect(largest_cnt)
            cx, cy = x + (w // 2), y + (h // 2)
            
            # Draw Green Box and Red Center Dot
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.circle(frame, (cx, cy), 4, (0, 0, 255), -1)
            
            # Display text
            cv2.putText(frame, f"LED: {cx}, {cy}", (x, y - 10), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

    # 4. Show Windows
    cv2.imshow("LED Tracker", frame)
    cv2.imshow("Mask Logic", mask)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()