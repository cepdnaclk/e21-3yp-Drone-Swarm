"""Unit tests: _triangulate_from_detected() + _cam1_to_world_mm() (tracker.py).

Tested by: E/21/217 - Kaushalya K. A. D. I.

Test design (Step 1):
  Equivalence classes (_triangulate_from_detected):
    0 or 1 camera detections  -> None (cannot triangulate)
    2 camera detections       -> single-pair triangulation
    3+ camera detections      -> mean of all pairwise estimates
  Boundaries:
    detection count around 2 (the `len(detected) < 2` guard):
      exactly 1 -> None (just outside); exactly 2 -> valid point (just inside)
  Equivalence + boundaries (_cam1_to_world_mm):
    identity transform -> point unchanged
    known scale/R/t    -> matches hand-computed affine result
    scale = 0 (degenerate lower bound) -> collapses to translation t
  Error/negative:
    point with wrong length (2 elems) -> ValueError from reshape(3, 1)
    non-numeric point -> ValueError
External dependencies mocked/stubbed:
  Synthetic pinhole cameras built in-memory (K, D=0, known extrinsics) so
  no calibration files, cameras, or threads are involved. Ground truth is
  produced by projecting a known 3-D point through each synthetic camera
  and asserting the function recovers it. cv2 triangulation used real.
"""

import numpy as np
import pytest

from tracker import (
    _build_projection,
    _cam1_to_world_mm,
    _triangulate_from_detected,
)


# ---------- synthetic camera rig ----------

K = np.array([[600.0, 0.0, 320.0],
              [0.0, 600.0, 240.0],
              [0.0, 0.0, 1.0]])
D = np.zeros((1, 5))

# cam1 at origin; cam2 offset along +x; cam3 offset along +y (all R = I)
CENTRES = [np.zeros((3, 1)),
           np.array([[0.5], [0.0], [0.0]]),
           np.array([[0.0], [0.5], [0.0]])]
EXTRINSICS = [{"R_cam_to_cam1": np.eye(3), "C_cam1": c} for c in CENTRES]
INTRINSICS = [{"K": K, "D": D} for _ in CENTRES]
PROJECTIONS = [_build_projection(e["R_cam_to_cam1"], e["C_cam1"]) for e in EXTRINSICS]

GT_POINT = np.array([0.2, 0.1, 2.0])          # ground truth, cam1 frame


def project_to_pixels(X, cam_idx):
    """Pinhole projection of cam1-frame point X into camera cam_idx."""
    Xc = X.reshape(3, 1) - CENTRES[cam_idx]    # R = I for every camera
    u = K @ (Xc / Xc[2, 0])
    return (float(u[0, 0]), float(u[1, 0]))


def detections(cam_ids):
    return {i: project_to_pixels(GT_POINT, i) for i in cam_ids}


# ---------- equivalence: detection count ----------

def test_no_detections_returns_none():
    assert _triangulate_from_detected({}, INTRINSICS, PROJECTIONS) is None


def test_single_detection_returns_none():
    assert _triangulate_from_detected(detections([0]), INTRINSICS, PROJECTIONS) is None


def test_two_cameras_recover_ground_truth():
    pt = _triangulate_from_detected(detections([0, 1]), INTRINSICS, PROJECTIONS)
    np.testing.assert_allclose(pt, GT_POINT, atol=1e-6)


def test_three_cameras_recover_ground_truth():
    pt = _triangulate_from_detected(detections([0, 1, 2]), INTRINSICS, PROJECTIONS)
    np.testing.assert_allclose(pt, GT_POINT, atol=1e-6)


def test_three_cameras_average_pairwise_estimates():
    """With consistent projections every pair agrees, so mean == pair result."""
    pair = _triangulate_from_detected(detections([0, 1]), INTRINSICS, PROJECTIONS)
    trio = _triangulate_from_detected(detections([0, 1, 2]), INTRINSICS, PROJECTIONS)
    np.testing.assert_allclose(trio, pair, atol=1e-6)


def test_noisy_pixels_give_approximate_point():
    det = detections([0, 1, 2])
    noisy = {i: (px + 0.5, py - 0.5) for i, (px, py) in det.items()}
    pt = _triangulate_from_detected(noisy, INTRINSICS, PROJECTIONS)
    np.testing.assert_allclose(pt, GT_POINT, atol=0.02)   # ~cm-level at 2 m


# ---------- _cam1_to_world_mm ----------

def test_identity_transform_leaves_point_unchanged():
    out = _cam1_to_world_mm([1.0, 2.0, 3.0], 1.0, np.eye(3), np.zeros((3, 1)))
    np.testing.assert_allclose(out, [1.0, 2.0, 3.0])


def test_known_scale_rotation_translation():
    # 90-degree rotation about z: (x, y, z) -> (-y, x, z), then scale 2, then +t
    Rz = np.array([[0.0, -1.0, 0.0],
                   [1.0, 0.0, 0.0],
                   [0.0, 0.0, 1.0]])
    t = np.array([[10.0], [20.0], [30.0]])
    out = _cam1_to_world_mm([1.0, 0.0, 0.0], 2.0, Rz, t)
    np.testing.assert_allclose(out, [10.0, 22.0, 30.0])


def test_zero_scale_collapses_to_translation():
    t = np.array([[5.0], [6.0], [7.0]])
    out = _cam1_to_world_mm([9.0, 9.0, 9.0], 0.0, np.eye(3), t)
    np.testing.assert_allclose(out, [5.0, 6.0, 7.0])


def test_output_shape_is_flat_3vector():
    out = _cam1_to_world_mm([1.0, 2.0, 3.0], 1.0, np.eye(3), np.zeros((3, 1)))
    assert out.shape == (3,)


# ---------- error / negative ----------

def test_wrong_length_point_raises():
    with pytest.raises(ValueError):
        _cam1_to_world_mm([1.0, 2.0], 1.0, np.eye(3), np.zeros((3, 1)))


def test_non_numeric_point_raises():
    with pytest.raises(ValueError):
        _cam1_to_world_mm(["a", "b", "c"], 1.0, np.eye(3), np.zeros((3, 1)))
