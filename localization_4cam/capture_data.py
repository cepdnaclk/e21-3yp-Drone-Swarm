import cv2 as cv
import numpy as np
import threading
import time

# ============================================
# MANUALLY SET WORKING CAMERA INDICES
# ============================================

CAMERA_INDICES = [0, 1, 3, 4]

CAM_WIDTH = 640
CAM_HEIGHT = 480
CAM_FPS = 10

# ============================================
# CAMERA CLASS
# ============================================

class ThreadedCamera:

    def __init__(self, src=0):

        self.src = src

        self.cap = cv.VideoCapture(src, cv.CAP_DSHOW)

        # IMPORTANT
        self.cap.set(
            cv.CAP_PROP_FOURCC,
            cv.VideoWriter_fourcc(*'MJPG')
        )

        self.cap.set(cv.CAP_PROP_FRAME_WIDTH, CAM_WIDTH)
        self.cap.set(cv.CAP_PROP_FRAME_HEIGHT, CAM_HEIGHT)

        # Lower FPS reduces USB bandwidth
        self.cap.set(cv.CAP_PROP_FPS, CAM_FPS)

        # Tiny buffer
        self.cap.set(cv.CAP_PROP_BUFFERSIZE, 1)

        # IMPORTANT:
        # Give camera time to initialize
        time.sleep(1)

        self.ret, self.frame = self.cap.read()

        if not self.ret:
            print(f"[ERROR] Camera {src} failed")
        else:
            print(f"[OK] Camera {src} started")

        self.running = True

        self.thread = threading.Thread(target=self.update)
        self.thread.daemon = True
        self.thread.start()

    def update(self):

        while self.running:

            ret, frame = self.cap.read()

            if ret:
                self.ret = ret
                self.frame = frame

    def read(self):

        if self.ret and self.frame is not None:
            return True, self.frame.copy()

        return False, None

    def stop(self):

        self.running = False

        self.thread.join()

        self.cap.release()

# ============================================
# MAIN
# ============================================

def main():

    print("\nStarting cameras...\n")

    cameras = []

    # IMPORTANT:
    # stagger startup
    for idx in CAMERA_INDICES:

        cam = ThreadedCamera(idx)

        cameras.append(cam)

        # HUGE fix for Windows
        time.sleep(2)

    wand_points = []

    while True:

        frames = []

        for i, cam in enumerate(cameras):

            ret, frame = cam.read()

            if not ret or frame is None:

                blank = np.zeros(
                    (240, 320, 3),
                    dtype=np.uint8
                )

                cv.putText(
                    blank,
                    f"Cam {CAMERA_INDICES[i]} FAIL",
                    (30, 120),
                    cv.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (0, 0, 255),
                    2
                )

                frames.append(blank)

                continue

            # ====================================
            # LED DETECTION
            # ====================================

            gray = cv.cvtColor(frame, cv.COLOR_BGR2GRAY)

            _, thresh = cv.threshold(
                gray,
                110,
                255,
                cv.THRESH_BINARY
            )

            moments = cv.moments(thresh)

            if moments["m00"] > 0:

                cx = int(moments["m10"] / moments["m00"])
                cy = int(moments["m01"] / moments["m00"])

                cv.circle(
                    frame,
                    (cx, cy),
                    8,
                    (0, 255, 0),
                    -1
                )

            cv.putText(
                frame,
                f"Cam {CAMERA_INDICES[i]}",
                (10, 30),
                cv.FONT_HERSHEY_SIMPLEX,
                0.8,
                (255, 255, 255),
                2
            )

            display = cv.resize(frame, (320, 240))

            frames.append(display)

        # Fill missing frames
        while len(frames) < 4:

            frames.append(
                np.zeros((240, 320, 3), dtype=np.uint8)
            )

        top = np.hstack((frames[0], frames[1]))
        bottom = np.hstack((frames[2], frames[3]))

        grid = np.vstack((top, bottom))

        cv.imshow("4 Cam Capture", grid)

        key = cv.waitKey(1)

        if key == ord('q'):
            break

    print("\nStopping cameras...\n")

    for cam in cameras:
        cam.stop()

    cv.destroyAllWindows()

# ============================================

if __name__ == "__main__":
    main()