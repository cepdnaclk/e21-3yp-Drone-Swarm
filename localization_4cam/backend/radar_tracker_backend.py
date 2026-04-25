from __future__ import annotations

import json
import os
import threading
import time
from itertools import combinations
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2 as cv
import numpy as np
from flask import Flask, Response, jsonify, send_from_directory
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure


CAMERA_INDICES = [1, 2, 3, 4]
NUM_CAMERAS = len(CAMERA_INDICES)
CAM_WIDTH = 640
CAM_HEIGHT = 480
JPEG_QUALITY = 80
MAX_PATH_POINTS = 60
STATIC_ROOT = Path(__file__).resolve().parents[2] / "frontend" / "radar-tracker"
THREE_STATIC_ROOT = Path(__file__).resolve().parents[2] / "frontend" / "radar-tracker-three"
BASE_DIR = Path(__file__).resolve().parents[1]


class ThreadedCamera:
    def __init__(self, src: int) -> None:
        self.cap = cv.VideoCapture(src, cv.CAP_DSHOW)
        self.cap.set(cv.CAP_PROP_FRAME_WIDTH, CAM_WIDTH)
        self.cap.set(cv.CAP_PROP_FRAME_HEIGHT, CAM_HEIGHT)
        self.ret, self.frame = self.cap.read()
        self.running = True
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self.update, daemon=True)
        self.thread.start()

    def update(self) -> None:
        while self.running:
            ret, frame = self.cap.read()
            with self.lock:
                self.ret = ret
                self.frame = frame

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        with self.lock:
            if self.ret and self.frame is not None:
                return True, self.frame.copy()
        return False, None

    def stop(self) -> None:
        self.running = False
        self.thread.join(timeout=1.0)
        self.cap.release()


def load_system_data() -> Tuple[List[dict], List[dict], np.ndarray]:
    intrinsics = []
    for cam_id in CAMERA_INDICES:
        with open(BASE_DIR / f"camera_{cam_id}_params.json", "r", encoding="utf-8") as f:
            data = json.load(f)
            intrinsics.append(
                {
                    "K": np.array(data["intrinsic_matrix"], dtype=np.float64),
                    "D": np.array(data["distortion_coef"], dtype=np.float64),
                }
            )

    with open(BASE_DIR / "final_system_calibration.json", "r", encoding="utf-8") as f:
        data = json.load(f)
        world_matrix = np.array(data["world_matrix"], dtype=np.float64)
        extrinsics = []
        for pose in data["camera_poses"]:
            extrinsics.append(
                {
                    "R": np.array(pose["R"], dtype=np.float64),
                    "t": np.array(pose["t"], dtype=np.float64),
                }
            )

    return intrinsics, extrinsics, world_matrix


def triangulate_point(
    k1: np.ndarray,
    r1: np.ndarray,
    t1: np.ndarray,
    k2: np.ndarray,
    r2: np.ndarray,
    t2: np.ndarray,
    pt1: Tuple[int, int],
    pt2: Tuple[int, int],
) -> np.ndarray:
    p1 = k1 @ np.hstack((r1, t1))
    p2 = k2 @ np.hstack((r2, t2))
    pt1_fmt = np.array([[pt1[0]], [pt1[1]]], dtype=np.float32)
    pt2_fmt = np.array([[pt2[0]], [pt2[1]]], dtype=np.float32)
    point_4d = cv.triangulatePoints(p1, p2, pt1_fmt, pt2_fmt)
    return (point_4d[:3, :] / point_4d[3, :]).flatten()


class RadarTrackerService:
    def __init__(self) -> None:
        self.intrinsics, self.extrinsics, self.world_matrix = load_system_data()
        self.cam_world_positions = self._compute_camera_positions()
        self.cameras = [ThreadedCamera(idx) for idx in CAMERA_INDICES]
        self.frames: Dict[int, bytes] = {}
        self.path_history: List[List[float]] = []
        self.latest_state = {
            "status": "starting",
            "timestamp": time.time(),
            "cameras": self._empty_camera_state(),
            "camera_positions": self.cam_world_positions,
            "path_history": [],
            "current_point": None,
            "message": "Tracker starting",
        }
        self.lock = threading.Lock()
        self.running = True
        self.thread = threading.Thread(target=self._tracking_loop, daemon=True)
        self.thread.start()

    def _compute_camera_positions(self) -> List[List[float]]:
        positions = []
        for ext in self.extrinsics:
            cam_origin = -np.linalg.inv(ext["R"]) @ ext["t"]
            homog_cam = np.append(cam_origin, 1.0)
            world_cam = self.world_matrix @ homog_cam
            positions.append(world_cam[:3].astype(float).tolist())
        return positions

    def _empty_camera_state(self) -> List[dict]:
        return [
            {"camera_id": camera_id, "detected": False, "point": None}
            for camera_id in CAMERA_INDICES
        ]

    def _encode_frame(self, frame: np.ndarray) -> bytes:
        ok, encoded = cv.imencode(
            ".jpg",
            frame,
            [int(cv.IMWRITE_JPEG_QUALITY), JPEG_QUALITY],
        )
        return encoded.tobytes() if ok else b""

    def _annotate_frame(
        self,
        frame: np.ndarray,
        camera_id: int,
        detection: Optional[Tuple[int, int]],
        message: str,
        color: Tuple[int, int, int],
    ) -> np.ndarray:
        output = frame.copy()
        cv.putText(
            output,
            f"Cam {camera_id}",
            (14, 32),
            cv.FONT_HERSHEY_SIMPLEX,
            0.85,
            (255, 255, 255),
            2,
        )
        cv.putText(
            output,
            message,
            (14, CAM_HEIGHT - 20),
            cv.FONT_HERSHEY_SIMPLEX,
            0.55,
            color,
            2,
        )
        if detection is not None:
            cv.drawMarker(output, detection, (64, 255, 120), cv.MARKER_CROSS, 18, 2)
        return output

    def _detect_led(self, frame: np.ndarray) -> Optional[Tuple[int, int]]:
        red_channel = frame[:, :, 2]
        _, thresh = cv.threshold(red_channel, 80, 255, cv.THRESH_BINARY)
        contours, _ = cv.findContours(thresh, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)

        best_point = None
        max_area = 0.0
        for contour in contours:
            area = cv.contourArea(contour)
            if area <= 10 or area <= max_area:
                continue
            moments = cv.moments(contour)
            if moments["m00"] <= 0:
                continue
            max_area = area
            best_point = (
                int(moments["m10"] / moments["m00"]),
                int(moments["m01"] / moments["m00"]),
            )

        return best_point

    def _tracking_loop(self) -> None:
        while self.running:
            detected_points: Dict[int, Tuple[int, int]] = {}
            camera_state = []
            encoded_frames: Dict[int, bytes] = {}

            for index, cam in enumerate(self.cameras):
                camera_id = CAMERA_INDICES[index]
                ret, frame = cam.read()
                if not ret or frame is None:
                    blank = np.zeros((CAM_HEIGHT, CAM_WIDTH, 3), dtype=np.uint8)
                    annotated = self._annotate_frame(
                        blank,
                        camera_id,
                        None,
                        "Feed unavailable",
                        (0, 0, 255),
                    )
                    encoded_frames[camera_id] = self._encode_frame(annotated)
                    camera_state.append(
                        {"camera_id": camera_id, "detected": False, "point": None}
                    )
                    continue

                detection = self._detect_led(frame)
                if detection is not None:
                    detected_points[index] = detection
                    camera_state.append(
                        {
                            "camera_id": camera_id,
                            "detected": True,
                            "point": [int(detection[0]), int(detection[1])],
                        }
                    )
                    annotated = self._annotate_frame(
                        frame,
                        camera_id,
                        detection,
                        f"LED ({detection[0]}, {detection[1]})",
                        (96, 255, 96),
                    )
                else:
                    camera_state.append(
                        {"camera_id": camera_id, "detected": False, "point": None}
                    )
                    annotated = self._annotate_frame(
                        frame,
                        camera_id,
                        None,
                        "Scanning for LED",
                        (0, 180, 255),
                    )

                encoded_frames[camera_id] = self._encode_frame(annotated)

            current_point = None
            status = "waiting"
            message = "LED not found in enough cameras"

            if len(detected_points) >= 2:
                raw_3d_points = []
                cam_ids = list(detected_points.keys())
                for c1, c2 in combinations(cam_ids, 2):
                    pt_3d = triangulate_point(
                        self.intrinsics[c1]["K"],
                        self.extrinsics[c1]["R"],
                        self.extrinsics[c1]["t"],
                        self.intrinsics[c2]["K"],
                        self.extrinsics[c2]["R"],
                        self.extrinsics[c2]["t"],
                        detected_points[c1],
                        detected_points[c2],
                    )
                    raw_3d_points.append(pt_3d)

                avg_raw_3d = np.mean(raw_3d_points, axis=0)
                world_pt = self.world_matrix @ np.append(avg_raw_3d, 1.0)
                current_point = world_pt[:3].astype(float).tolist()
                self.path_history.append(current_point)
                if len(self.path_history) > MAX_PATH_POINTS:
                    self.path_history = self.path_history[-MAX_PATH_POINTS:]

                status = "tracking"
                message = (
                    f"Tracking X={current_point[0]:.2f}m "
                    f"Y={current_point[1]:.2f}m Z={current_point[2]:.2f}m"
                )

            with self.lock:
                self.frames = encoded_frames
                self.latest_state = {
                    "status": status,
                    "timestamp": time.time(),
                    "cameras": camera_state,
                    "camera_positions": self.cam_world_positions,
                    "path_history": list(self.path_history),
                    "current_point": current_point,
                    "message": message,
                }

            time.sleep(0.03)

    def get_state_snapshot(self) -> dict:
        with self.lock:
            return {
                "status": self.latest_state["status"],
                "timestamp": self.latest_state["timestamp"],
                "cameras": list(self.latest_state["cameras"]),
                "camera_positions": list(self.latest_state["camera_positions"]),
                "path_history": list(self.latest_state["path_history"]),
                "current_point": self.latest_state["current_point"],
                "message": self.latest_state["message"],
            }

    def get_frame(self, camera_id: int) -> bytes:
        with self.lock:
            return self.frames.get(camera_id, b"")

    def stream_camera(self, camera_id: int):
        while self.running:
            frame = self.get_frame(camera_id)
            if frame:
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
                )
            time.sleep(0.05)

    def render_plot_frame(self) -> bytes:
        state = self.get_state_snapshot()

        fig = Figure(figsize=(8, 5), dpi=140)
        canvas = FigureCanvasAgg(fig)
        ax = fig.add_subplot(111, projection="3d")
        fig.patch.set_facecolor("#08131f")
        ax.set_facecolor("#0d1b2a")

        ax.set_title("Live 3D Tracker", color="white", pad=16)
        ax.set_xlabel("X (meters)", color="white", labelpad=10)
        ax.set_ylabel("Y (meters)", color="white", labelpad=10)
        ax.set_zlabel("Altitude Z (meters)", color="white", labelpad=10)

        ax.set_xlim([-5, 5])
        ax.set_ylim([-5, 5])
        ax.set_zlim([0, 5])
        ax.tick_params(colors="white")
        ax.xaxis.pane.set_facecolor((0.07, 0.12, 0.18, 1.0))
        ax.yaxis.pane.set_facecolor((0.07, 0.12, 0.18, 1.0))
        ax.zaxis.pane.set_facecolor((0.07, 0.12, 0.18, 1.0))
        ax.xaxis._axinfo["grid"]["color"] = (0.6, 0.8, 1.0, 0.12)
        ax.yaxis._axinfo["grid"]["color"] = (0.6, 0.8, 1.0, 0.12)
        ax.zaxis._axinfo["grid"]["color"] = (0.6, 0.8, 1.0, 0.12)
        ax.view_init(elev=24, azim=-58)

        for idx, cam_pos in enumerate(state["camera_positions"]):
            ax.scatter(cam_pos[0], cam_pos[1], cam_pos[2], c="#56d4ff", marker="^", s=80)
            ax.text(
                cam_pos[0],
                cam_pos[1],
                cam_pos[2],
                f" Cam {CAMERA_INDICES[idx]}",
                color="#9fe7ff",
            )

        if state["path_history"]:
            xs = [point[0] for point in state["path_history"]]
            ys = [point[1] for point in state["path_history"]]
            zs = [point[2] for point in state["path_history"]]
            ax.plot(xs, ys, zs, c="#ff6b6b", alpha=0.55, linewidth=2.2)
            ax.scatter(xs[-1], ys[-1], zs[-1], c="#8cff9e", marker="o", s=90)

        fig.tight_layout()
        canvas.draw()
        rgba = np.asarray(canvas.buffer_rgba())
        bgr = cv.cvtColor(rgba, cv.COLOR_RGBA2BGR)
        return self._encode_frame(bgr)

    def shutdown(self) -> None:
        self.running = False
        self.thread.join(timeout=1.0)
        for camera in self.cameras:
            camera.stop()


def create_app() -> Flask:
    app = Flask(__name__, static_folder=None)
    tracker = RadarTrackerService()

    @app.get("/api/health")
    def health():
        return jsonify({"ok": True, "status": tracker.get_state_snapshot()["status"]})

    @app.get("/api/state")
    def state():
        return jsonify(tracker.get_state_snapshot())

    @app.get("/video/<int:camera_id>")
    def video(camera_id: int):
        if camera_id not in CAMERA_INDICES:
            return jsonify({"error": "Unknown camera id"}), 404
        return Response(
            tracker.stream_camera(camera_id),
            mimetype="multipart/x-mixed-replace; boundary=frame",
        )

    @app.get("/plot/3d")
    def plot_3d():
        frame = tracker.render_plot_frame()
        return Response(frame, mimetype="image/jpeg")

    @app.get("/")
    def frontend_index():
        return send_from_directory(STATIC_ROOT, "index.html")

    @app.get("/<path:asset_path>")
    def frontend_assets(asset_path: str):
        return send_from_directory(STATIC_ROOT, asset_path)

    @app.get("/three")
    def frontend_three_index():
        return send_from_directory(THREE_STATIC_ROOT, "index.html")

    @app.get("/three/<path:asset_path>")
    def frontend_three_assets(asset_path: str):
        return send_from_directory(THREE_STATIC_ROOT, asset_path)

    @app.teardown_appcontext
    def teardown(_exception):
        return None

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, threaded=True)
