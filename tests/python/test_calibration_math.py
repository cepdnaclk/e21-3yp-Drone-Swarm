import math
import unittest
from pathlib import Path
import sys

import numpy as np


API_DIR = Path(__file__).resolve().parents[2] / "Drone-swarm-v1" / "computer_code" / "api"
sys.path.insert(0, str(API_DIR))

from calibration_manager import (
    average_rotation,
    camera_position_in_ref_frame,
    compute_world_transform,
    create_object_points,
    estimate_similarity_transform,
    staged_world_matrix_4x4_metres,
)


class CalibrationMathTests(unittest.TestCase):
    def test_object_points_follow_checkerboard_and_square_size(self):
        points = create_object_points((3, 2), 25.0)

        self.assertEqual(points.shape, (6, 3))
        np.testing.assert_allclose(points[0], [0.0, 0.0, 0.0])
        np.testing.assert_allclose(points[1], [25.0, 0.0, 0.0])
        np.testing.assert_allclose(points[3], [0.0, 25.0, 0.0])

    def test_similarity_transform_recovers_scale_rotation_and_translation(self):
        theta = math.radians(30)
        rotation = np.array(
            [
                [math.cos(theta), -math.sin(theta), 0.0],
                [math.sin(theta), math.cos(theta), 0.0],
                [0.0, 0.0, 1.0],
            ]
        )
        scale = 2.5
        translation = np.array([[100.0], [-50.0], [25.0]])
        cam_points = np.array(
            [
                [0.0, 0.0, 0.0],
                [100.0, 0.0, 0.0],
                [0.0, 100.0, 0.0],
                [0.0, 0.0, 100.0],
            ]
        )
        world_points = np.array([(scale * rotation @ p.reshape(3, 1) + translation).reshape(3) for p in cam_points])

        actual_scale, actual_rotation, actual_translation = estimate_similarity_transform(cam_points, world_points)

        self.assertAlmostEqual(actual_scale, scale, places=6)
        np.testing.assert_allclose(actual_rotation, rotation, atol=1e-6)
        np.testing.assert_allclose(actual_translation, translation, atol=1e-6)

    def test_world_transform_reports_low_error_for_exact_landmarks(self):
        landmarks = [
            {"name": "origin", "cam1": [0, 0, 0], "world": [10, 20, 30]},
            {"name": "x", "cam1": [100, 0, 0], "world": [210, 20, 30]},
            {"name": "y", "cam1": [0, 100, 0], "world": [10, 220, 30]},
            {"name": "z", "cam1": [0, 0, 100], "world": [10, 20, 230]},
        ]

        npz_data, results = compute_world_transform(landmarks, log=lambda _text: None)

        self.assertAlmostEqual(results["mean_error_mm"], 0.0, places=6)
        self.assertAlmostEqual(results["max_error_mm"], 0.0, places=6)
        self.assertAlmostEqual(npz_data["scale"], 2.0, places=6)
        np.testing.assert_allclose(npz_data["t"], [[10.0], [20.0], [30.0]], atol=1e-6)

    def test_camera_position_in_reference_frame_identity_case(self):
        rotation, translation = camera_position_in_ref_frame(
            np.eye(3),
            np.zeros((3, 1)),
            np.eye(3),
            np.array([[100.0], [200.0], [300.0]]),
        )

        np.testing.assert_allclose(rotation, np.eye(3))
        np.testing.assert_allclose(translation, [[-100.0], [-200.0], [-300.0]])

    def test_average_rotation_projects_back_to_valid_rotation(self):
        rotations = [np.eye(3), np.eye(3) + np.diag([0.01, -0.01, 0.0])]

        averaged = average_rotation(rotations)

        np.testing.assert_allclose(averaged.T @ averaged, np.eye(3), atol=1e-6)
        self.assertAlmostEqual(np.linalg.det(averaged), 1.0, places=6)

    def test_staged_world_matrix_converts_millimetres_to_metres(self):
        matrix = staged_world_matrix_4x4_metres(
            world_scale=2.0,
            world_R=np.eye(3),
            world_t=np.array([[1000.0], [2000.0], [3000.0]]),
        )

        np.testing.assert_allclose(
            matrix,
            [
                [0.002, 0.0, 0.0, 1.0],
                [0.0, 0.002, 0.0, 2.0],
                [0.0, 0.0, 0.002, 3.0],
                [0.0, 0.0, 0.0, 1.0],
            ],
        )


if __name__ == "__main__":
    unittest.main()
