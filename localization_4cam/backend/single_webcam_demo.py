from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import List, Optional, Tuple

import cv2 as cv
import numpy as np
from flask import Flask, Response, jsonify, send_from_directory
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure


CAMERA_INDEX = 0
CAM_WIDTH = 640
CAM_HEIGHT = 480
JPEG_QUALITY = 80
MAX_PATH_POINTS = 80
STATIC_ROOT = Path(__file__).resolve().parents[2] / "frontend" / "radar-tracker-demo"
THREE_STATIC_ROOT = Path(__file__).resolve().parents[2] / "frontend" / "radar-tracker-demo-three"


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


class SingleWebcamDemoService:
    def __init__(self) -> None:
        self.camera = ThreadedCamera(CAMERA_INDEX)
        self.frame = b""
        self.path_history: List[List[float]] = []
        self.latest_state = {
            "status": "starting",
            "timestamp": time.time(),
            "current_point": None,
            "path_history": [],
            "message": "Starting webcam demo",
            "detection": None,
            "camera_index": CAMERA_INDEX,
        }
        self.lock = threading.Lock()
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def _encode_frame(self, frame: np.ndarray) -> bytes:
        ok, encoded = cv.imencode(
            ".jpg",
            frame,
            [int(cv.IMWRITE_JPEG_QUALITY), JPEG_QUALITY],
        )
        return encoded.tobytes() if ok else b""

    def _detect_flashlight(self, frame: np.ndarray) -> Tuple[Optional[Tuple[int, int]], float]:
        gray = cv.cvtColor(frame, cv.COLOR_BGR2GRAY)
        blurred = cv.GaussianBlur(gray, (11, 11), 0)
        _, thresh = cv.threshold(blurred, 245, 255, cv.THRESH_BINARY)
        contours, _ = cv.findContours(thresh, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)

        best_point = None
        best_area = 0.0
        for contour in contours:
            area = cv.contourArea(contour)
            if area < 20 or area <= best_area:
                continue
            moments = cv.moments(contour)
            if moments["m00"] <= 0:
                continue
            best_area = area
            best_point = (
                int(moments["m10"] / moments["m00"]),
                int(moments["m01"] / moments["m00"]),
            )

        return best_point, float(best_area)

    def _map_to_demo_3d(self, point: Tuple[int, int], area: float) -> List[float]:
        norm_x = point[0] / CAM_WIDTH
        norm_y = point[1] / CAM_HEIGHT

        x = (norm_x - 0.5) * 10.0
        y = (0.5 - norm_y) * 10.0
        z = min(5.0, max(0.2, 0.2 + area / 350.0))
        return [round(x, 3), round(y, 3), round(z, 3)]

    def _annotate_frame(
        self,
        frame: np.ndarray,
        message: str,
        point: Optional[Tuple[int, int]],
    ) -> np.ndarray:
        output = frame.copy()
        cv.putText(
            output,
            f"Webcam {CAMERA_INDEX}",
            (14, 32),
            cv.FONT_HERSHEY_SIMPLEX,
            0.85,
            (255, 255, 255),
            2,
        )
        cv.putText(
            output,
            message,
            (14, CAM_HEIGHT - 18),
            cv.FONT_HERSHEY_SIMPLEX,
            0.58,
            (120, 255, 120) if point else (0, 200, 255),
            2,
        )
        if point is not None:
            cv.drawMarker(output, point, (80, 255, 120), cv.MARKER_CROSS, 20, 2)
            cv.circle(output, point, 16, (80, 255, 120), 2)
        return output

    def _loop(self) -> None:
        while self.running:
            ret, frame = self.camera.read()
            current_point = None
            detection = None
            status = "waiting"
            message = "Point a flashlight at the webcam"

            if ret and frame is not None:
                point, area = self._detect_flashlight(frame)
                if point is not None:
                    current_point = self._map_to_demo_3d(point, area)
                    detection = {"pixel": [point[0], point[1]], "area": round(area, 2)}
                    self.path_history.append(current_point)
                    if len(self.path_history) > MAX_PATH_POINTS:
                        self.path_history = self.path_history[-MAX_PATH_POINTS:]
                    status = "tracking"
                    message = (
                        f"Flashlight detected at ({point[0]}, {point[1]}) "
                        f"-> X={current_point[0]:.2f} Y={current_point[1]:.2f} Z={current_point[2]:.2f}"
                    )

                annotated = self._annotate_frame(frame, message, point)
                encoded = self._encode_frame(annotated)
            else:
                blank = np.zeros((CAM_HEIGHT, CAM_WIDTH, 3), dtype=np.uint8)
                annotated = self._annotate_frame(blank, "Webcam unavailable", None)
                encoded = self._encode_frame(annotated)
                status = "error"
                message = "Webcam unavailable"

            with self.lock:
                self.frame = encoded
                self.latest_state = {
                    "status": status,
                    "timestamp": time.time(),
                    "current_point": current_point,
                    "path_history": list(self.path_history),
                    "message": message,
                    "detection": detection,
                    "camera_index": CAMERA_INDEX,
                }

            time.sleep(0.03)

    def get_state(self) -> dict:
        with self.lock:
            return {
                "status": self.latest_state["status"],
                "timestamp": self.latest_state["timestamp"],
                "current_point": self.latest_state["current_point"],
                "path_history": list(self.latest_state["path_history"]),
                "message": self.latest_state["message"],
                "detection": self.latest_state["detection"],
                "camera_index": self.latest_state["camera_index"],
            }

    def get_frame(self) -> bytes:
        with self.lock:
            return self.frame

    def stream_camera(self):
        while self.running:
            frame = self.get_frame()
            if frame:
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
                )
            time.sleep(0.05)

    def render_plot_frame(self) -> bytes:
        state = self.get_state()
        fig = Figure(figsize=(8, 5), dpi=140)
        canvas = FigureCanvasAgg(fig)
        ax = fig.add_subplot(111, projection="3d")
        fig.patch.set_facecolor("#08131f")
        ax.set_facecolor("#0d1b2a")

        ax.set_title("Single Webcam Flashlight Demo", color="white", pad=16)
        ax.set_xlabel("X (meters)", color="white", labelpad=10)
        ax.set_ylabel("Y (meters)", color="white", labelpad=10)
        ax.set_zlabel("Z (demo depth)", color="white", labelpad=10)
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


def create_app() -> Flask:
    app = Flask(__name__, static_folder=None)
    demo = SingleWebcamDemoService()

    @app.get("/api/health")
    def health():
        return jsonify({"ok": True, "status": demo.get_state()["status"]})

    @app.get("/api/state")
    def state():
        return jsonify(demo.get_state())

    @app.get("/video")
    def video():
        return Response(
            demo.stream_camera(),
            mimetype="multipart/x-mixed-replace; boundary=frame",
        )

    @app.get("/plot/3d")
    def plot_3d():
        return Response(demo.render_plot_frame(), mimetype="image/jpeg")

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

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5051, threaded=True)
