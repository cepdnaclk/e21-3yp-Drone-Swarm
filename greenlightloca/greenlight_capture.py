import cv2
import numpy as np

def nothing(x):
    pass

# --- INITIALIZE CAMERA ---
cap = cv2.VideoCapture(1, cv2.CAP_DSHOW)
if not cap.isOpened():
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)

# Create a window for the trackbar
cv2.namedWindow("Calibration")
# Exposure usually ranges from -1 (bright) to -13 (dark) on webcams
cv2.createTrackbar("Exposure", "Calibration", 8, 13, nothing) 

print("1. Adjust the slider until the LED is a clear GREEN circle (not white).")
print("2. Press 's' to Save the photo.")
print("3. Press 'q' to Quit.")

while True:
    # Get current position of the trackbar
    exp_val = cv2.getTrackbarPos("Exposure", "Calibration")
    
    # Apply manual exposure (0.25 is often the toggle for manual mode)
    cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25) 
    cap.set(cv2.CAP_PROP_EXPOSURE, -exp_val)

    ret, frame = cap.read()
    if not ret:
        break

    # Display the current exposure value on the frame
    cv2.putText(frame, f"Exposure: {-exp_val}", (10, 30), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
    
    cv2.imshow("Calibration", frame)

    key = cv2.waitKey(1) & 0xFF
    if key == ord('s'):
        # Save the clean frame (without the text)
        clean_ret, clean_frame = cap.read()
        cv2.imwrite("led_calibration_photo.png", clean_frame)
        print(f"Photo saved! Remember this Exposure Value: {-exp_val}")
        break
    elif key == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()