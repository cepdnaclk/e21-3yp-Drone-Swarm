"""Unit tests: _detect_bright_spot() + Tracker threshold validation (tracker.py).

Tested by: E/21/009 - Abeysekera L. B. B.

Test design (Step 1):
  Equivalence classes (_detect_bright_spot):
    frame with no bright region        -> None
    frame with one valid LED blob      -> centroid (cx, cy)
    frame with two valid blobs         -> centroid of the LARGER blob
    blob brightness <= threshold       -> not detected (same as no blob)
  Boundaries:
    brightness: pixel value == threshold -> rejected (cv.THRESH_BINARY is
      strict >); value = threshold + 1 -> detected
    blob area vs min_blob_area=3: single pixel (erased by blur/morph-open)
      -> None; 5x5 blob (comfortably above) -> detected
    blob area vs max_blob_area=5000: 60x60 (~3.8k px, inside) -> detected;
      80x80 (~6.7k px, outside) -> None
  Equivalence + boundaries (Tracker.set_threshold / set_thresholds - the
  validation layer for the detector's threshold):
    values clipped to [0, 255]: -5 -> 0, 300 -> 255, exactly 0/255 kept
    shorter list padded with its last value; longer list truncated; empty
    list falls back to DEFAULT_THRESHOLD
  Error/negative:
    grayscale (2-D) frame -> cv2.error from cvtColor (expects BGR)
    None frame -> cv2.error
External dependencies mocked/stubbed:
  Tracker's calibration-file loaders (_load_intrinsics, _load_extrinsics,
  _load_world_transform) monkeypatched with synthetic in-memory calibration
  so NO files and NO cameras are touched. cv2 image ops are deterministic
  pure maths, used real.
"""

import cv2 as cv
import numpy as np
import pytest

import tracker as tracker_mod
from tracker import Tracker, _detect_bright_spot, DEFAULT_THRESHOLD


THRESH = 180
MIN_AREA = 3
MAX_AREA = 5000


def black_frame():
    return np.zeros((480, 640, 3), dtype=np.uint8)


def add_blob(frame, cx, cy, size, value=255):
    half = size // 2
    frame[cy - half:cy - half + size, cx - half:cx - half + size] = value
    return frame


def detect(frame):
    return _detect_bright_spot(frame, THRESH, MIN_AREA, MAX_AREA)


# ---------- equivalence ----------

def test_empty_frame_returns_none():
    assert detect(black_frame()) is None


def test_single_led_blob_detected_near_centre():
    f = add_blob(black_frame(), 320, 240, 9)
    pt = detect(f)
    assert pt is not None
    assert abs(pt[0] - 320) <= 2 and abs(pt[1] - 240) <= 2


def test_larger_of_two_blobs_wins():
    f = black_frame()
    add_blob(f, 100, 100, 5)     # small decoy
    add_blob(f, 500, 300, 15)    # the real LED
    pt = detect(f)
    assert abs(pt[0] - 500) <= 2 and abs(pt[1] - 300) <= 2


# ---------- boundaries: brightness threshold (strict >) ----------

def test_brightness_exactly_at_threshold_rejected():
    f = add_blob(black_frame(), 320, 240, 21, value=THRESH)   # == 180
    assert detect(f) is None


def test_brightness_one_above_threshold_detected():
    f = add_blob(black_frame(), 320, 240, 21, value=THRESH + 1)
    assert detect(f) is not None


# ---------- boundaries: blob area ----------

def test_single_pixel_below_min_area_rejected():
    f = add_blob(black_frame(), 320, 240, 1)   # erased by blur + morph-open
    assert detect(f) is None


def test_small_valid_blob_detected():
    f = add_blob(black_frame(), 320, 240, 5)
    assert detect(f) is not None


def test_blob_inside_max_area_detected():
    f = add_blob(black_frame(), 320, 240, 60)  # ~3.8k px < 5000
    assert detect(f) is not None


def test_blob_above_max_area_rejected():
    f = add_blob(black_frame(), 320, 240, 80)  # ~6.7k px > 5000
    assert detect(f) is None


# ---------- error / negative ----------

def test_grayscale_frame_raises_cv_error():
    gray = np.zeros((480, 640), dtype=np.uint8)
    with pytest.raises(cv.error):
        detect(gray)


def test_none_frame_raises_cv_error():
    with pytest.raises(cv.error):
        detect(None)


# ---------- Tracker threshold validation (calibration loaders mocked) ----------

@pytest.fixture
def tracker_no_files(monkeypatch):
    """Tracker built against synthetic in-memory calibration - no files/cameras."""
    K = np.array([[600.0, 0, 320], [0, 600.0, 240], [0, 0, 1.0]])
    D = np.zeros((1, 5))
    monkeypatch.setattr(tracker_mod, "_load_intrinsics",
                        lambda d: [{"K": K, "D": D} for _ in range(4)])
    monkeypatch.setattr(tracker_mod, "_load_extrinsics",
                        lambda d: [{"R_cam_to_cam1": np.eye(3),
                                    "C_cam1": np.zeros((3, 1))} for _ in range(4)])
    monkeypatch.setattr(tracker_mod, "_load_world_transform",
                        lambda d: (1.0, np.eye(3), np.zeros((3, 1))))
    return Tracker()


def test_set_threshold_clips_above_255(tracker_no_files):
    tracker_no_files.set_threshold(300)
    assert tracker_no_files.thresholds == [255, 255, 255, 255]


def test_set_threshold_clips_below_0(tracker_no_files):
    tracker_no_files.set_threshold(-5)
    assert tracker_no_files.thresholds == [0, 0, 0, 0]


def test_set_threshold_boundary_values_kept(tracker_no_files):
    tracker_no_files.set_threshold(0)
    assert tracker_no_files.thresholds == [0, 0, 0, 0]
    tracker_no_files.set_threshold(255)
    assert tracker_no_files.thresholds == [255, 255, 255, 255]


def test_set_thresholds_short_list_padded_with_last(tracker_no_files):
    tracker_no_files.set_thresholds([100])
    assert tracker_no_files.thresholds == [100, 100, 100, 100]


def test_set_thresholds_long_list_truncated(tracker_no_files):
    tracker_no_files.set_thresholds([10, 20, 30, 40, 99])
    assert tracker_no_files.thresholds == [10, 20, 30, 40]


def test_set_thresholds_empty_falls_back_to_default(tracker_no_files):
    tracker_no_files.set_thresholds([])
    assert tracker_no_files.thresholds == [DEFAULT_THRESHOLD] * 4
