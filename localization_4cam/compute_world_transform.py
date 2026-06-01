import numpy as np
import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

LANDMARK_FILE = os.path.join(BASE_DIR, "world_landmarks.json")
OUTPUT_FILE = os.path.join(BASE_DIR, "cam1_to_world_transform.npz")


def estimate_similarity_transform(cam_points, world_points, allow_scale=True):
    """
    Finds transform:

        world = scale * R @ cam + t

    cam_points: Nx3
    world_points: Nx3
    """

    cam_points = np.asarray(cam_points, dtype=np.float64)
    world_points = np.asarray(world_points, dtype=np.float64)

    assert cam_points.shape == world_points.shape
    assert cam_points.shape[1] == 3

    cam_centroid = np.mean(cam_points, axis=0)
    world_centroid = np.mean(world_points, axis=0)

    cam_centered = cam_points - cam_centroid
    world_centered = world_points - world_centroid

    H = cam_centered.T @ world_centered

    U, S, Vt = np.linalg.svd(H)

    R = Vt.T @ U.T

    if np.linalg.det(R) < 0:
        Vt[-1, :] *= -1
        R = Vt.T @ U.T

    if allow_scale:
        cam_var = np.sum(cam_centered ** 2)
        scale = np.sum(S) / cam_var
    else:
        scale = 1.0

    t = world_centroid.reshape(3, 1) - scale * R @ cam_centroid.reshape(3, 1)

    return scale, R, t


def apply_transform(point, scale, R, t):
    point = np.asarray(point, dtype=np.float64).reshape(3, 1)
    world = scale * R @ point + t
    return world.reshape(3)


def main():
    with open(LANDMARK_FILE, "r") as f:
        landmarks = json.load(f)

    cam_points = []
    world_points = []
    names = []

    for item in landmarks:
        names.append(item["name"])
        cam_points.append(item["cam1"])
        world_points.append(item["world"])

    cam_points = np.array(cam_points, dtype=np.float64)
    world_points = np.array(world_points, dtype=np.float64)

    if len(cam_points) < 3:
        print("Need at least 3 points")
        return

    scale, R, t = estimate_similarity_transform(
        cam_points,
        world_points,
        allow_scale=True
    )

    print("\n========== CAM1 TO WORLD TRANSFORM ==========")
    print("\nscale =")
    print(scale)

    print("\nR =")
    print(R)

    print("\nt =")
    print(t.flatten())

    print("\n========== LANDMARK ERRORS ==========")

    errors = []

    for name, cam_pt, world_pt in zip(names, cam_points, world_points):
        predicted = apply_transform(cam_pt, scale, R, t)

        error = np.linalg.norm(predicted - world_pt)
        errors.append(error)

        print(f"{name}:")
        print("  expected:", world_pt)
        print("  predicted:", predicted)
        print(f"  error: {error:.2f} mm")

    print("\nMean error:", np.mean(errors), "mm")
    print("Max error:", np.max(errors), "mm")

    np.savez(
        OUTPUT_FILE,
        scale=scale,
        R=R,
        t=t
    )

    print(f"\nSaved: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()