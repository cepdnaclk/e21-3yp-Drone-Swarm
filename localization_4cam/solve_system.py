import numpy as np
import cv2 as cv
import json
from scipy import linalg

# Settings
CAMERA_INDICES = [1, 2, 3, 4]  # Explicitly using your camera IDs
NUM_CAMERAS = len(CAMERA_INDICES)
SCALE_DISTANCE = 0.15 # 15cm distance between first two floor points

def load_intrinsics():
    matrices, dists = [], []
    for cam_id in CAMERA_INDICES:
        with open(f"camera_{cam_id}_params.json", "r") as f:
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
    point_3d = point_4d[:3, :] / point_4d[3, :]
    return point_3d.flatten()

def main():
    print("Loading data...")
    K, D = load_intrinsics()
    wand_pts = np.load("wand_points.npy")
    floor_pts = np.load("floor_points.npy")

    # 1. Calculate Camera Poses (Extrinsics)
    camera_poses = [{"R": np.eye(3), "t": np.zeros((3, 1))}]
    
    for i in range(NUM_CAMERAS - 1):
        # Print statements updated to show your actual 1, 2, 3, 4 names
        print(f"Solving pose for Camera {CAMERA_INDICES[i]} -> {CAMERA_INDICES[i+1]}...")
        pts1 = wand_pts[:, i, :]
        pts2 = wand_pts[:, i+1, :]

        # Filter out frames where LED wasn't seen in either camera
        valid = ~np.isnan(pts1[:,0]) & ~np.isnan(pts2[:,0])
        p1_valid = pts1[valid]
        p2_valid = pts2[valid]

        # Use standard Essential Matrix instead of SFM module (More stable)
        E, mask = cv.findEssentialMat(p1_valid, p2_valid, K[i], method=cv.RANSAC, prob=0.999, threshold=1.0)
        _, R, t, mask = cv.recoverPose(E, p1_valid, p2_valid, K[i])

        # Chain the transformations to global space (Cam 0 internally, which is your Cam 1)
        R_global = R @ camera_poses[-1]["R"]
        t_global = camera_poses[-1]["t"] + (camera_poses[-1]["R"] @ t)
        
        camera_poses.append({"R": R_global, "t": t_global})

    # 2. Triangulate Floor Points & Apply Scale
    print("Triangulating floor points...")
    floor_3d = []
    for f_pt in floor_pts:
        # Triangulate using your first two cameras as reference
        if not np.isnan(f_pt[0,0]) and not np.isnan(f_pt[1,0]):
            pt3d = triangulate_point(K[0], camera_poses[0]["R"], camera_poses[0]["t"], 
                                     K[1], camera_poses[1]["R"], camera_poses[1]["t"], 
                                     f_pt[0], f_pt[1])
            floor_3d.append(pt3d)
    
    floor_3d = np.array(floor_3d)

    # Scale the world based on the first two floor points
    if len(floor_3d) >= 2:
        measured_dist = np.linalg.norm(floor_3d[0] - floor_3d[1])
        scale_factor = SCALE_DISTANCE / measured_dist
        print(f"Measured distance: {measured_dist:.4f}, Scaling by factor: {scale_factor:.4f}")
        
        for pose in camera_poses:
            pose["t"] *= scale_factor
        floor_3d *= scale_factor
    
    # 3. Floor Leveling (Exact math from your acquire_floor function)
    if len(floor_3d) >= 3:
        print("Calculating World Coordinate Matrix...")
        tmp_A = np.c_[floor_3d[:, 0:2], np.ones(len(floor_3d))]
        tmp_b = floor_3d[:, 2]
        
        fit, _, _, _ = linalg.lstsq(tmp_A, tmp_b)
        
        plane_normal = np.array([[fit[0]], [fit[1]], [-1]])
        plane_normal = plane_normal / linalg.norm(plane_normal)
        up_normal = np.array([[0],[0],[1]], dtype=np.float32)

        G = np.array([
            [np.dot(plane_normal.T,up_normal)[0][0], -linalg.norm(np.cross(plane_normal.T[0],up_normal.T[0])), 0],
            [linalg.norm(np.cross(plane_normal.T[0],up_normal.T[0])), np.dot(plane_normal.T,up_normal)[0][0], 0],
            [0, 0, 1]
        ])
        F = np.array([plane_normal.T[0], ((up_normal-np.dot(plane_normal.T,up_normal)[0][0]*plane_normal)/linalg.norm((up_normal-np.dot(plane_normal.T,up_normal)[0][0]*plane_normal))).T[0], np.cross(up_normal.T[0],plane_normal.T[0])]).T
        
        R_world = F @ G @ linalg.inv(F)
        R_world = R_world @ [[1,0,0],[0,-1,0],[0,0,1]] # Retaining your Y-axis flip
        
        world_matrix = np.vstack((np.c_[R_world, [0,0,0]], [[0,0,0,1]]))
    else:
        print("Not enough floor points to level the world!")
        world_matrix = np.eye(4)

    # 4. Save Final Setup
    final_output = {
        "world_matrix": world_matrix.tolist(),
        "camera_poses": [{"R": p["R"].tolist(), "t": p["t"].tolist()} for p in camera_poses]
    }
    with open("final_system_calibration.json", "w") as f:
        json.dump(final_output, f, indent=4)
    print("SUCCESS: Full system calibration saved to final_system_calibration.json!")

if __name__ == "__main__":
    main()