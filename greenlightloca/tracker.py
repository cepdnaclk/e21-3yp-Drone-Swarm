import cv2
import numpy as np

# --- VALUES SYNCED FROM YOUR SCREENSHOT ---
# Screenshot shows: Hue 41-72, Sat 9-36, Val 200-255
LOWER_HSV = np.array([41, 9, 200])
UPPER_HSV = np.array([72, 36, 255])
CORE_FILL_VAL = 7 # Value from your 'Core Fill' slider
# ----------------------------------------

# Force DirectShow for Windows stability
cap = cv2.VideoCapture(1, cv2.CAP_DSHOW) 

if not cap.isOpened():
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)

cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

# Reduce exposure if possible (prevents the LED from blooming/smearing)
cap.set(cv2.CAP_PROP_EXPOSURE, -6) 

print("LED Tracking Started. Press 'q' to quit.")

# Create kernel for smoothing the detection
kernel = np.ones((CORE_FILL_VAL, CORE_FILL_VAL), np.uint8)

while True:
    ret, frame = cap.read()
    if not ret:
        break

    # Convert BGR to HSV
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    
    # Create the mask
    mask = cv2.inRange(hsv, LOWER_HSV, UPPER_HSV)
    
    # Clean up the mask: removes small noise and fills holes in the LED core
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    
    # Find contours
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    if contours:
        # Track the largest bright object (the LED)
        largest_cnt = max(contours, key=cv2.contourArea)
        
        # Minimum area check to avoid tracking random light reflections
        if cv2.contourArea(largest_cnt) > 20:
            x, y, w, h = cv2.boundingRect(largest_cnt)
            
            # Draw tracking visuals
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cx, cy = x + (w // 2), y + (h // 2)
            cv2.circle(frame, (cx, cy), 5, (0, 0, 255), -1)
            
            cv2.putText(frame, f"LED Center: {cx}, {cy}", (10, 30), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

    # Show the results
    cv2.imshow("Original Feed", frame)
    cv2.imshow("LED Mask", mask)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()