import cv2
import numpy as np

# --- 1. LOAD STEREO DATA ---
# '../' moves up from the '3d' folder to find the file in 'GREENLIGHTLOCA'
DATA_PATH = "stereo_data.npz"

try:
    data = np.load(DATA_PATH)
    m1, d1, m2, d2, R, T = data['m1'], data['d1'], data['m2'], data['d2'], data['R'], data['T']
    print("Stereo Data Loaded Successfully.")
except:
    print(f"Error: Could not find {DATA_PATH}. Check your folder structure!")
    exit()

# Setup Projection Matrices for 3D Triangulation
P1 = np.dot(m1, np.hstack((np.eye(3), np.zeros((3, 1)))))
P2 = np.dot(m2, np.hstack((R, T)))

# --- 2. INDIVIDUAL HSV SETTINGS (FROM TUNER SCREENSHOTS) ---
# Cam 0 - Hue 58-99, Sat 0-36, Val 200-255
LOWER_0 = np.array([58, 0, 200])
UPPER_0 = np.array([99, 36, 255])

# Cam 1 - Hue 54-87, Sat 0-60, Val 200-255
LOWER_1 = np.array([54, 0, 200])
UPPER_1 = np.array([87, 60, 255])

# Shared Tracking Settings
CORE_FILL = 15
EXPOSURE_VAL = -7
kernel = np.ones((CORE_FILL, CORE_FILL), np.uint8)

# --- 3. HELPER FUNCTION FOR DETECTION ---
def get_led_center(frame, lower, upper):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, lower, upper)
    # Make the tiny dot larger for better contour detection
    mask = cv2.dilate(mask, kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if cnts:
        c = max(cnts, key=cv2.contourArea)
        if cv2.contourArea(c) >= 1:
            x, y, w, h = cv2.boundingRect(c)
            # Return center point as float for high-precision math
            return [float(x + w/2), float(y + h/2)], (x, y, w, h)
    return None, None

# --- 4. INITIALIZE CAPTURE ---
cap0 = cv2.VideoCapture(1, cv2.CAP_DSHOW)
cap1 = cv2.VideoCapture(2, cv2.CAP_DSHOW)

for cap in [cap0, cap1]:
    cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
    cap.set(cv2.CAP_PROP_EXPOSURE, EXPOSURE_VAL)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

print("Starting 3D Localization. Hold the LED in view of both cameras.")
print("Press 'q' to stop.")

# --- 5. MAIN LOOP ---
while True:
    ret0, frame0 = cap0.read()
    ret1, frame1 = cap1.read()
    
    if not ret0 or not ret1:
        continue

    # Use unique HSV ranges for each camera sensor
    p0, box0 = get_led_center(frame0, LOWER_0, UPPER_0)
    p1, box1 = get_led_center(frame1, LOWER_1, UPPER_1)

    if p0 and p1:
        # Prepare points for TriangulatePoints (must be 2xN)
        p0_pts = np.array([p0], dtype=np.float32).T
        p1_pts = np.array([p1], dtype=np.float32).T
        
        # Triangulate to find 3D position
        points_4d_hom = cv2.triangulatePoints(P1, P2, p0_pts, p1_pts)
        # Normalize from Homogeneous to 3D Cartesian coordinates
        points_3d = points_4d_hom[:3] / points_4d_hom[3]
        
        X, Y, Z = points_3d.flatten()
        
        # Format the coordinates for display
        loc_text = f"X:{int(X)} Y:{int(Y)} Z:{int(Z)} mm"
        cv2.putText(frame0, loc_text, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        print(f"TRACKING -> {loc_text}")

        # Draw visual feedback
        for (f, b) in [(frame0, box0), (frame1, box1)]:
            x, y, w, h = b
            cv2.rectangle(f, (x, y), (x + w, y + h), (0, 255, 0), 2)

    # Show the combined result
    combined_view = np.hstack((frame0, frame1))
    cv2.imshow("Kelaniya MPF 3D Localizer", combined_view)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap0.release()
cap1.release()
cv2.destroyAllWindows()