import numpy as np
import cv2 as cv
import json
import os
from scipy import linalg
from itertools import combinations

# --- Settings ---
CAMERA_INDICES = [1, 2, 3, 4]  
NUM_CAMERAS = len(CAMERA_INDICES)

# Your manual tape-measure distance between Camera 1 and Camera 2
CAM_1_TO_2_DISTANCE = 2.0  

BASE_DIR = r"C:\Users\Admin\Desktop\AI-ML Courses\e21-3yp-Drone-Swarm-\localization_4cam"

def load_intrinsics():
    matrices, dists = [], []
    for cam_id in CAMERA_INDICES:
        filepath = os.path.join(BASE_DIR, f"camera_{cam_id}_params.json")
        with open(filepath, "r") as f:
            data = json.load(f)
            matrices.append(np.array(data["intrinsic_matrix"]))
            dists.append(np.array(data["distortion_coef"]))
    return matrices, dists

def triangulate_point(K1, R1, t1, K2, R2, t2, pt1, pt2):
    P1 = K1 @ np.hstack((R1, t1))
    P2 = K2 @ np.hstack((R2, t2))
    pt1_fmt = np.array([[pt1[0]], [pt1[1]]], dtype=np.float32)
    pt2_fmt = np.array([[pt2[0]], [pt2[1]]], dtype=np.float32)
    point_4d = cv.triangulatePoints(P1, P2, pt1_fmt, pt2_fmt)
    return (point_4d[:3, :] / point_4d[3, :]).flatten()

def main():
    print("Loading data...")
    K, D = load_intrinsics()
    wand_pts = np.load(os.path.join(BASE_DIR, "wand_points.npy"))
    floor_pts = np.load(os.path.join(BASE_DIR, "floor_points.npy"))

    camera_poses = [{"R": np.eye(3), "t": np.zeros((3, 1))}]
    
    # 1. Solve the "Base Pair" (Camera 1 -> 2)
    print(f"\nSolving base pose: Cam {CAMERA_INDICES[0]} -> Cam {CAMERA_INDICES[1]}")
    valid = ~np.isnan(wand_pts[:,0,0]) & ~np.isnan(wand_pts[:,1,0])
    pts1, pts2 = wand_pts[valid, 0, :], wand_pts[valid, 1, :]
    
    E, mask = cv.findEssentialMat(pts1, pts2, K[0], method=cv.RANSAC, prob=0.999, threshold=1.0)
    _, R, t, mask = cv.recoverPose(E, pts1, pts2, K[0])
    camera_poses.append({"R": R, "t": t})

    # 2. Add remaining cameras using Perspective-n-Point (PnP)
    for i in range(2, NUM_CAMERAS):
        print(f"Solving PnP pose for Cam {CAMERA_INDICES[i]}...")
        cloud_3d, img_pts = [], []
        for idx in range(len(wand_pts)):
            seen_by = [c for c in range(len(camera_poses)) if not np.isnan(wand_pts[idx, c, 0])]
            if len(seen_by) >= 2 and not np.isnan(wand_pts[idx, i, 0]):
                c1, c2 = seen_by[0], seen_by[1]
                pt3d = triangulate_point(K[c1], camera_poses[c1]["R"], camera_poses[c1]["t"], 
                                         K[c2], camera_poses[c2]["R"], camera_poses[c2]["t"], 
                                         wand_pts[idx, c1], wand_pts[idx, c2])
                cloud_3d.append(pt3d)
                img_pts.append(wand_pts[idx, i])
                
        cloud_3d = np.array(cloud_3d, dtype=np.float32)
        img_pts = np.array(img_pts, dtype=np.float32)

        if len(cloud_3d) < 15:
            print(f"❌ ERROR: Cam {CAMERA_INDICES[i]} doesn't share enough points with the solved cameras.")
            return

        success, rvec, tvec, inliers = cv.solvePnPRansac(cloud_3d, img_pts, K[i], D[i], flags=cv.SOLVEPNP_ITERATIVE)
        R_i, _ = cv.Rodrigues(rvec)
        camera_poses.append({"R": R_i, "t": tvec})

    # 3. Triangulate Floor Points (Multi-Camera Averaging)
    print("\nTriangulating floor points with multi-camera averaging...")
    floor_3d = []
    for f_pt in floor_pts:
        seen_by = [c for c in range(NUM_CAMERAS) if not np.isnan(f_pt[c, 0])]
        if len(seen_by) >= 2:
            raw_3d_points = []
            for c1, c2 in combinations(seen_by, 2):
                pt3d = triangulate_point(K[c1], camera_poses[c1]["R"], camera_poses[c1]["t"], 
                                         K[c2], camera_poses[c2]["R"], camera_poses[c2]["t"], 
                                         f_pt[c1], f_pt[c2])
                raw_3d_points.append(pt3d)
            avg_pt3d = np.mean(raw_3d_points, axis=0)
            floor_3d.append(avg_pt3d)
            
    floor_3d = np.array(floor_3d)

    # 4. Scale the World 
    print(f"Applying Real-World Scale based on Camera distance: {CAM_1_TO_2_DISTANCE} meters")
    for pose in camera_poses:
        pose["t"] *= CAM_1_TO_2_DISTANCE
    if len(floor_3d) > 0:
        floor_3d *= CAM_1_TO_2_DISTANCE
    
    # 5. Floor Leveling (The "Stand it Upright" Fix)
    if len(floor_3d) >= 3:
        print("Calculating World Matrix (Correcting Axes & Leveling)...")
        
        raw_floor = np.copy(floor_3d)

        # STEP A: Swap the Axes! (OpenCV Y-Down -> Real World Z-Up)
        axis_swap = np.array([
            [1,  0,  0],
            [0,  0,  1],  
            [0, -1,  0]   
        ], dtype=np.float64)
        
        upright_floor = (axis_swap @ floor_3d.T).T
        
        # STEP B: Fit a normal flat plane (Z = aX + bY + c)
        tmp_A = np.c_[upright_floor[:, 0:2], np.ones(len(upright_floor))]
        tmp_b = upright_floor[:, 2]
        fit, _, _, _ = linalg.lstsq(tmp_A, tmp_b)
        
        # STEP C: Find the tilt and rotate it perfectly flat
        plane_normal = np.array([-fit[0], -fit[1], 1.0])
        plane_normal = plane_normal / linalg.norm(plane_normal)
        up_normal = np.array([0.0, 0.0, 1.0])
        
        v = np.cross(plane_normal, up_normal)
        c = np.dot(plane_normal, up_normal)
        s = linalg.norm(v)
        
        if s < 1e-6:
            R_level = np.eye(3)
        else:
            kmat = np.array([
                [0, -v[2], v[1]],
                [v[2], 0, -v[0]],
                [-v[1], v[0], 0]
            ])
            R_level = np.eye(3) + kmat + kmat.dot(kmat) * ((1 - c) / (s ** 2))
            
        # Combine rotations
        R_world = R_level @ axis_swap
        
        # STEP D: Drop the floor exactly to 0.00m
        rotated_floor = (R_world @ raw_floor.T).T
        z_offset = np.mean(rotated_floor[:, 2])
        t_world = np.array([[0], [0], [-z_offset]])
        
        world_matrix = np.vstack((np.c_[R_world, t_world], [0, 0, 0, 1]))
    else:
        print("❌ ERROR: Not enough valid floor points found to level the world!")
        world_matrix = np.eye(4)

    # 6. Save
    final_output = {
        "world_matrix": world_matrix.tolist(),
        "camera_poses": [{"R": p["R"].tolist(), "t": p["t"].tolist()} for p in camera_poses]
    }
    
    save_filepath = os.path.join(BASE_DIR, "final_system_calibration.json")
    with open(save_filepath, "w") as f:
        json.dump(final_output, f, indent=4)
    print(f"\n✅ SUCCESS: Final drift-free calibration saved!")

if __name__ == "__main__":
    main()