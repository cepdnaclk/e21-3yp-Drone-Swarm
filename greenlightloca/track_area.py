import cv2
import numpy as np

# --- REFINED VALUES TO IGNORE OUTFITS ---
# Raising the minimum Value (V) to 230 forces the code to only see 'Extreme' brightness
LOWER_HSV = np.array([22, 21, 230]) 
UPPER_HSV = np.array([37, 67, 255])
CORE_FILL = 23

# --- GEOMETRIC CONSTRAINTS ---
MIN_AREA = 30     # Ignore tiny noise specks
MAX_AREA = 1500   # Ignore large objects (like your outfit)
# ----------------------------------------

# Force DirectShow for Windows stability
cap = cv2.VideoCapture(1, cv2.CAP_DSHOW) 
if not cap.isOpened():
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)

cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

print("Targeted Tracking Started. Press 'q' to quit.")
kernel = np.ones((CORE_FILL, CORE_FILL), np.uint8)

while True:
    ret, frame = cap.read()
    if not ret:
        continue

    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, LOWER_HSV, UPPER_HSV)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    for cnt in contours:
        area = cv2.contourArea(cnt)
        
        # 1. FILTER BY AREA: If it's as big as a shirt, ignore it.
        if MIN_AREA < area < MAX_AREA:
            
            x, y, w, h = cv2.boundingRect(cnt)
            aspect_ratio = float(w) / h
            
            # 2. FILTER BY SHAPE: An LED/Flash is roughly square (ratio ~1.0).
            # A sleeve or shirt hit by sun is usually long or wide.
            if 0.5 < aspect_ratio < 2.0:
                
                # Draw the box and the center
                cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
                cx, cy = x + (w // 2), y + (h // 2)
                cv2.circle(frame, (cx, cy), 5, (0, 0, 255), -1)
                
                cv2.putText(frame, "TARGET", (x, y - 10), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
                
                print(f"Tracking Valid Target: Area={int(area)}, Aspect={round(aspect_ratio, 2)}")

    cv2.imshow("Filtered Tracking", frame)
    cv2.imshow("Filtered Mask", mask)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()