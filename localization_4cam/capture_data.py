import cv2 as cv
import numpy as np
import threading
import time

# --- Explicitly set your camera indices here ---
CAMERA_INDICES = [1, 2, 3, 4]  
NUM_CAMERAS = len(CAMERA_INDICES)

# Lower resolution to prevent USB bandwidth lag
CAM_WIDTH = 640
CAM_HEIGHT = 480

class ThreadedCamera:
    def __init__(self, src=0):
        # Added cv.CAP_DSHOW for Windows stability!
        self.cap = cv.VideoCapture(src, cv.CAP_DSHOW)
        
        # Force low resolution
        self.cap.set(cv.CAP_PROP_FRAME_WIDTH, CAM_WIDTH)
        self.cap.set(cv.CAP_PROP_FRAME_HEIGHT, CAM_HEIGHT)
        
        self.ret, self.frame = self.cap.read()
        self.running = True
        
        # Start the background thread
        self.thread = threading.Thread(target=self.update, args=())
        self.thread.daemon = True 
        self.thread.start()

    def update(self):
        # Constantly pull frames to keep the buffer empty and fresh
        while self.running:
            self.ret, self.frame = self.cap.read()

    def read(self):
        # Return the latest frame instantly without waiting
        if self.ret and self.frame is not None:
            return True, self.frame.copy()
        return False, None

    def stop(self):
        self.running = False
        self.thread.join()
        self.cap.release()

def main():
    print(f"Starting cameras on ports {CAMERA_INDICES} at {CAM_WIDTH}x{CAM_HEIGHT}... Please wait.")
    
    # Initialize cameras using the specific numbers [1, 2, 3, 4]
    cameras = [ThreadedCamera(idx) for idx in CAMERA_INDICES]
    
    # Give cameras a second to warm up and auto-expose
    time.sleep(1.0) 
    
    wand_points = []
    floor_points = []
    recording_wand = False

    print("\n--- Data Capture (Threaded) ---")
    print("[SPACE] Toggle Wand Dance Recording")
    print("[f]     Record a Floor Point (for leveling)")
    print("[q]     Save and Quit\n")

    while True:
        frames = []
        current_frame_points = []

        for i, cam in enumerate(cameras):
            ret, frame = cam.read()
            if not ret or frame is None:
                current_frame_points.append([np.nan, np.nan])
                # If a camera drops, append a blank black frame so the UI doesn't crash
                frames.append(np.zeros((CAM_HEIGHT // 2, CAM_WIDTH // 2, 3), dtype=np.uint8))
                continue

            # 1. Find the bright LED
            gray = cv.cvtColor(frame, cv.COLOR_BGR2GRAY)
            _, thresh = cv.threshold(gray, 110, 255, cv.THRESH_BINARY)
            moments = cv.moments(thresh)
            
            if moments["m00"] > 0:
                cx = int(moments["m10"] / moments["m00"])
                cy = int(moments["m01"] / moments["m00"])
                current_frame_points.append([cx, cy])
                cv.circle(frame, (cx, cy), 5, (0, 255, 0), -1)
            else:
                current_frame_points.append([np.nan, np.nan]) # Not seen
            
            # 2. Add visual UI text to the frame (Shows actual camera index)
            if recording_wand:
                cv.putText(frame, "REC WAND", (10, 30), cv.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            cv.putText(frame, f"Cam {CAMERA_INDICES[i]}", (10, 60), cv.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            
            # Resize the frame by half ONLY for the display so all 4 fit on your screen
            display_frame = cv.resize(frame, (CAM_WIDTH // 2, CAM_HEIGHT // 2))
            frames.append(display_frame)

        # 3. Create a 2x2 visual grid
        if len(frames) == NUM_CAMERAS:
            top_row = np.hstack((frames[0], frames[1]))
            bottom_row = np.hstack((frames[2], frames[3]))
            grid = np.vstack((top_row, bottom_row))
            cv.imshow("Camera Feeds", grid)

        # 4. Save data if recording
        if recording_wand:
            wand_points.append(current_frame_points)

        # 5. Handle Keyboard inputs
        key = cv.waitKey(1)
        if key == 32: # SPACEBAR
            recording_wand = not recording_wand
            print(f"Wand Recording: {'ON' if recording_wand else 'OFF'}")
        
        elif key == ord('f'):
            floor_points.append(current_frame_points)
            print(f"Saved Floor Point {len(floor_points)}")
            
        elif key == ord('q'):
            break

    # Clean up threads safely
    print("Shutting down cameras...")
    for cam in cameras:
        cam.stop()
    cv.destroyAllWindows()

    # Save tracking data to disk
    np.save("wand_points.npy", np.array(wand_points, dtype=np.float32))
    np.save("floor_points.npy", np.array(floor_points, dtype=np.float32))
    print(f"Saved {len(wand_points)} wand points and {len(floor_points)} floor points.")

if __name__ == "__main__":
    main()