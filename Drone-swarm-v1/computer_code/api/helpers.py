"""
Thin Cameras singleton that wraps `tracker.Tracker` for the Flask/SocketIO
backend. Everything related to pseyepy / OpenCV-SFM / multi-LED correspondence
/ floor + origin calibration has been removed; the new pipeline uses the
pre-calibrated 4-USB-camera world tracker.
"""

from Singleton import Singleton
from tracker import Tracker


@Singleton
class Cameras:
    def __init__(self):
        self.tracker = Tracker()
        self._started = False

    # ---- lifecycle ----

    def start(self):
        if not self._started:
            self.tracker.start()
            self._started = True

    def stop(self):
        if self._started:
            self.tracker.stop()
            self._started = False

    @property
    def started(self):
        return self._started

    def reload_calibration(self):
        """Re-read calibration files (used after the wizard promotes a new set)."""
        self.tracker.reload_calibration()

    # ---- read API ----

    def get_grid_jpeg(self):
        _, jpeg = self.tracker.latest()
        return jpeg

    def latest_xyz_m(self):
        return self.tracker.latest_xyz_m()

    def latest_xyz_m_with_id(self):
        return self.tracker.latest_xyz_m_with_id()

    def fps(self):
        return self.tracker.fps()

    def set_threshold(self, value):
        self.tracker.set_threshold(value)

    def set_thresholds(self, values):
        self.tracker.set_thresholds(values)

    def get_camera_indices(self):
        return list(self.tracker.camera_indices)

    def set_camera_indices(self, indices):
        """Change USB device indices; reloads the cameras if already running."""
        self.tracker.set_camera_indices(indices)

    # ---- frontend init payload ----

    def camera_poses_in_world(self):
        return self.tracker.camera_poses_in_world()

    def world_matrix_4x4_metres(self):
        return self.tracker.world_matrix_4x4_metres()

    @property
    def num_cameras(self):
        return len(self.tracker.camera_indices)
