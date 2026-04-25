import cv2 as cv
import numpy as np
import threading
import json
import os
from itertools import combinations
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D

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
    P1 = K1 @ np.hstack((R1, t1))
    P2 = K2 @ np.hstack((R2, t2))
    pt1_fmt = np.array([[pt1[0]], [pt1[1]]], dtype=np.float32)
    pt2_fmt = np.array([[pt2[0]], [pt2[1]]], dtype=np.float32)
    point_4d = cv.triangulatePoints(P1, P2, pt1_fmt, pt2_fmt)
    return (point_4d[:3, :] / point_4d[3, :]).flatten()

def main():
    intrinsics, extrinsics, world_matrix = load_system_data()
    
    # Find real 3D locations of cameras
    cam_world_positions = []
    for ext in extrinsics:
        cam_origin = -np.linalg.inv(ext["R"]) @ ext["t"]
        homog_cam = np.append(cam_origin, 1.0)
        world_cam = world_matrix @ homog_cam
        cam_world_positions.append(world_cam[:3])

    cameras = [ThreadedCamera(idx) for idx in CAMERA_INDICES]
    print("\n--- LIVE 3D MAP ACTIVE ---")
    
    path_history = []

    # --- Setup Matplotlib 3D Map ---
    plt.ion()
    fig = plt.figure(figsize=(8, 8))
    ax = fig.add_subplot(111, projection='3d')
    
    while True:
        frames = []
        detected_points = {} 

        for i, cam in enumerate(cameras):
            ret, frame = cam.read()
            if not ret or frame is None:
                frames.append(np.zeros((CAM_HEIGHT // 2, CAM_WIDTH // 2, 3), dtype=np.uint8))
                continue

            red_channel = frame[:, :, 2]
            _, thresh = cv.threshold(red_channel, 80, 255, cv.THRESH_BINARY)
            contours, _ = cv.findContours(thresh, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
            
            best_cx, best_cy, max_area = None, None, 0
            for contour in contours:
                area = cv.contourArea(contour)
                if area > 10 and area > max_area:
                    max_area = area
                    m = cv.moments(contour)
                    if m["m00"] > 0:
                        best_cx = int(m["m10"] / m["m00"])
                        best_cy = int(m["m01"] / m["m00"])

            cv.putText(frame, f"Cam {CAMERA_INDICES[i]}", (10, 30), cv.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            if best_cx is not None:
                detected_points[i] = (best_cx, best_cy)
                cv.drawMarker(frame, (best_cx, best_cy), (0, 255, 0), cv.MARKER_CROSS, 15, 2)
                
            frames.append(cv.resize(frame, (CAM_WIDTH // 2, CAM_HEIGHT // 2)))

        final_3d_text = "LED Not Found"
        text_color = (0, 0, 255)

        if len(detected_points) >= 2:
            raw_3d_points = []
            cam_ids = list(detected_points.keys())
            for c1, c2 in combinations(cam_ids, 2):
                pt_3d = triangulate_point(
                    intrinsics[c1]["K"], extrinsics[c1]["R"], extrinsics[c1]["t"],
                    intrinsics[c2]["K"], extrinsics[c2]["R"], extrinsics[c2]["t"],
                    detected_points[c1], detected_points[c2]
                )
                raw_3d_points.append(pt_3d)
            
            avg_raw_3d = np.mean(raw_3d_points, axis=0)
            world_pt = world_matrix @ np.append(avg_raw_3d, 1.0)
            final_coord = world_pt[:3]

            x, y, z = final_coord[0], final_coord[1], final_coord[2]
            final_3d_text = f"X: {x: .2f}m   Y: {y: .2f}m   Z: {z: .2f}m"
            text_color = (0, 255, 0)
            
            path_history.append((x, y, z))
            if len(path_history) > 30: 
                path_history.pop(0)

        # --- Update OpenCV Window ---
        if len(frames) == NUM_CAMERAS:
            top_row = np.hstack((frames[0], frames[1]))
            bottom_row = np.hstack((frames[2], frames[3]))
            camera_grid = np.vstack((top_row, bottom_row))
            
            cv.rectangle(camera_grid, (0, CAM_HEIGHT - 40), (CAM_WIDTH, CAM_HEIGHT), (0, 0, 0), -1)
            cv.putText(camera_grid, final_3d_text, (20, CAM_HEIGHT - 12), cv.FONT_HERSHEY_SIMPLEX, 0.8, text_color, 2)
            cv.imshow("Camera Feeds", camera_grid)

        # --- Update 3D Matplotlib Plot ---
        ax.clear()
        ax.set_title("Live 3D Tracker (Click and Drag to Rotate)")
        ax.set_xlabel("X (meters)")
        ax.set_ylabel("Y (meters)")
        ax.set_zlabel("Altitude Z (meters)")
        
        # Set the size of your room here (e.g., -5m to +5m)
        ax.set_xlim([-5, 5])
        ax.set_ylim([-5, 5])
        ax.set_zlim([0, 5])

        # Draw Cameras
        for idx, cam_pos in enumerate(cam_world_positions):
            ax.scatter(cam_pos[0], cam_pos[1], cam_pos[2], c='blue', marker='^', s=100)
            ax.text(cam_pos[0], cam_pos[1], cam_pos[2], f" Cam {CAMERA_INDICES[idx]}", color='blue')

        # Draw Drone
        if len(path_history) > 0:
            xs = [p[0] for p in path_history]
            ys = [p[1] for p in path_history]
            zs = [p[2] for p in path_history]
            ax.plot(xs, ys, zs, c='red', alpha=0.5) # Tail
            ax.scatter(xs[-1], ys[-1], zs[-1], c='green', marker='o', s=100) # Live Dot

        plt.draw()
        plt.pause(0.001)

        if cv.waitKey(1) == ord('q'):
            break

    for cam in cameras: cam.stop()
    cv.destroyAllWindows()
    plt.close()

if __name__ == "__main__":
    main()