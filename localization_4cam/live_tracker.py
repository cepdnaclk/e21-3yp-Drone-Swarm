import cv2 as cv
import numpy as np
import threading
import json
import os
import time
from itertools import combinations

# --- Settings ---
CAMERA_INDICES = [1, 2, 3, 4]  
NUM_CAMERAS = len(CAMERA_INDICES)
CAM_WIDTH = 640
CAM_HEIGHT = 480

BASE_DIR = r"C:\Users\Admin\Desktop\AI-ML Courses\e21-3yp-Drone-Swarm-\localization_4cam"

class ThreadedCamera:
    def __init__(self, src=0):
        self.cap = cv.VideoCapture(src, cv.CAP_DSHOW)
        self.cap.set(cv.CAP_PROP_FRAME_WIDTH, CAM_WIDTH)
        self.cap.set(cv.CAP_PROP_FRAME_HEIGHT, CAM_HEIGHT)
        self.ret, self.frame = self.cap.read()
        self.running = True
        self.thread = threading.Thread(target=self.update, args=())
        self.thread.daemon = True 
        self.thread.start()

    def update(self):
        while self.running:
            self.ret, self.frame = self.cap.read()

    def read(self):
        if self.ret and self.frame is not None:
            return True, self.frame.copy()
        return False, None

    def stop(self):
        self.running = False
        self.thread.join()
        self.cap.release()

def load_system_data():
    print("Loading Intrinsics and Extrinsics...")
    intrinsics = []
    for cam_id in CAMERA_INDICES:
        with open(os.path.join(BASE_DIR, f"camera_{cam_id}_params.json"), "r") as f:
            data = json.load(f)
            intrinsics.append({
                "K": np.array(data["intrinsic_matrix"], dtype=np.float64),
                "D": np.array(data["distortion_coef"], dtype=np.float64)
            })
            
    with open(os.path.join(BASE_DIR, "final_system_calibration.json"), "r") as f:
        data = json.load(f)
        world_matrix = np.array(data["world_matrix"], dtype=np.float64)
        extrinsics = []
        for pose in data["camera_poses"]:
            extrinsics.append({
                "R": np.array(pose["R"], dtype=np.float64),
                "t": np.array(pose["t"], dtype=np.float64)
            })
            
    return intrinsics, extrinsics, world_matrix

def triangulate_point(K1, R1, t1, K2, R2, t2, pt1, pt2):
    # Create projection matrices
    P1 = K1 @ np.hstack((R1, t1))
    P2 = K2 @ np.hstack((R2, t2))
    
    pt1_fmt = np.array([[pt1[0]], [pt1[1]]], dtype=np.float32)
    pt2_fmt = np.array([[pt2[0]], [pt2[1]]], dtype=np.float32)
    
    point_4d = cv.triangulatePoints(P1, P2, pt1_fmt, pt2_fmt)
    point_3d = point_4d[:3, :] / point_4d[3, :]
    return point_3d.flatten()

def main():
    intrinsics, extrinsics, world_matrix = load_system_data()
    
    print(f"Starting cameras {CAMERA_INDICES} for Live Tracking...")
    cameras = [ThreadedCamera(idx) for idx in CAMERA_INDICES]
    time.sleep(1.0) # Warmup
    
    print("\n--- LIVE 3D TRACKING ACTIVE ---")
    print("[q] Save and Quit")
    
    while True:
        frames = []
        detected_points = {} # Will store which cameras saw the LED

        for i, cam in enumerate(cameras):
            ret, frame = cam.read()
            if not ret or frame is None:
                frames.append(np.zeros((CAM_HEIGHT // 2, CAM_WIDTH // 2, 3), dtype=np.uint8))
                continue

            # 1. Find the LED (Red Channel + Anti-Flicker)
            red_channel = frame[:, :, 2]
            _, thresh = cv.threshold(red_channel, 80, 255, cv.THRESH_BINARY)
            contours, _ = cv.findContours(thresh, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
            
            best_cx, best_cy = None, None
            max_area = 0

            for contour in contours:
                area = cv.contourArea(contour)
                if area > 10 and area > max_area:
                    max_area = area
                    moments = cv.moments(contour)
                    if moments["m00"] > 0:
                        best_cx = int(moments["m10"] / moments["m00"])
                        best_cy = int(moments["m01"] / moments["m00"])

            # Draw UI
            cv.putText(frame, f"Cam {CAMERA_INDICES[i]}", (10, 30), cv.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            
            if best_cx is not None:
                detected_points[i] = (best_cx, best_cy)
                cv.drawMarker(frame, (best_cx, best_cy), (0, 255, 0), cv.MARKER_CROSS, 15, 2)
                
            display_frame = cv.resize(frame, (CAM_WIDTH // 2, CAM_HEIGHT // 2))
            frames.append(display_frame)

        # 2. Triangulate the 3D Point
        final_3d_text = "LED Not Found"
        text_color = (0, 0, 255) # Red text if no tracking

        # We need at least 2 cameras to see the LED to calculate depth!
        if len(detected_points) >= 2:
            raw_3d_points = []
            
            # Create pairs of every camera that saw the LED
            cam_ids = list(detected_points.keys())
            for c1, c2 in combinations(cam_ids, 2):
                pt1 = detected_points[c1]
                pt2 = detected_points[c2]
                
                pt_3d = triangulate_point(
                    intrinsics[c1]["K"], extrinsics[c1]["R"], extrinsics[c1]["t"],
                    intrinsics[c2]["K"], extrinsics[c2]["R"], extrinsics[c2]["t"],
                    pt1, pt2
                )
                raw_3d_points.append(pt_3d)
            
            # Average the results from all pairs for maximum stability
            avg_raw_3d = np.mean(raw_3d_points, axis=0)
            
            # Apply the floor leveling matrix!
            # Convert to homogeneous (4D) to multiply by the 4x4 matrix
            homog_pt = np.append(avg_raw_3d, 1.0) 
            world_pt = world_matrix @ homog_pt
            final_coord = world_pt[:3]

            x, y, z = final_coord[0], final_coord[1], final_coord[2]
            
            # Format text: e.g., "X: 0.15m  Y: -0.05m  Z: 1.20m"
            final_3d_text = f"X: {x: .2f}m   Y: {y: .2f}m   Z: {z: .2f}m"
            text_color = (0, 255, 0) # Green text for active tracking

        # 3. Create the 2x2 Grid UI
        if len(frames) == NUM_CAMERAS:
            top_row = np.hstack((frames[0], frames[1]))
            bottom_row = np.hstack((frames[2], frames[3]))
            grid = np.vstack((top_row, bottom_row))
            
            # Draw the live coordinates at the bottom of the screen
            cv.rectangle(grid, (0, CAM_HEIGHT - 40), (CAM_WIDTH, CAM_HEIGHT), (0, 0, 0), -1)
            cv.putText(grid, final_3d_text, (20, CAM_HEIGHT - 12), cv.FONT_HERSHEY_SIMPLEX, 0.8, text_color, 2)
            
            cv.imshow("Live 3D Drone Tracking", grid)

        if cv.waitKey(1) == ord('q'):
            break

    print("Shutting down...")
    for cam in cameras:
        cam.stop()
    cv.destroyAllWindows()

if __name__ == "__main__":
    main()