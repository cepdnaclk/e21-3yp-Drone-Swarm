"""
Python drone controller for ESP32 transmitter.
Sends: throttle,roll,pitch,yaw,armed over USB serial.

Keyboard controls inside the GUI window:
  W/S : throttle up/down
  A/D : yaw left/right
  Arrow Left/Right : roll left/right
  Arrow Up/Down    : pitch forward/back
  T : smooth takeoff ramp to hover throttle
  Space : center roll/pitch/yaw
  X : throttle minimum
  M : arm/disarm toggle
  Esc : disarm + throttle minimum + quit

Run example:
  python python_drone_controller.py --port COM5
  python python_drone_controller.py --port /dev/ttyUSB0
"""

import argparse
import sys
import time
import tkinter as tk
from tkinter import ttk, messagebox

try:
    import serial
except ImportError:
    print("pyserial is missing. Install it with: pip install pyserial")
    sys.exit(1)

BAUD = 115200
SEND_HZ = 60
STEP = 10
THROTTLE_STEP = 25
TAKEOFF_TARGET = 1080
TAKEOFF_DURATION_MS = 1000
TAKEOFF_INTERVAL_MS = 50

class DroneController:
    def __init__(self, root, port):
        self.root = root
        self.root.title("Python Drone Controller")
        self.port_name = port
        self.ser = None

        self.throttle = 1000
        self.roll = 1500
        self.pitch = 1500
        self.yaw = 1500
        self.armed = 0
        self.last_sent = ""
        self._updating_ui = False
        self._ui_ready = False
        self.takeoff_job = None

        self.connect_serial()
        self.build_ui()
        self.bind_keys()
        self.schedule_send()
        self.root.protocol("WM_DELETE_WINDOW", self.safe_exit)

    def connect_serial(self):
        try:
            self.ser = serial.Serial(self.port_name, BAUD, timeout=0.02)
            time.sleep(2.0)  # ESP32 resets when serial opens
        except Exception as e:
            messagebox.showerror("Serial error", f"Could not open {self.port_name}\n\n{e}")
            raise

    def build_ui(self):
        main = ttk.Frame(self.root, padding=15)
        main.grid(row=0, column=0, sticky="nsew")

        ttk.Label(main, text="Drone Controller", font=("Segoe UI", 16, "bold")).grid(row=0, column=0, columnspan=3, pady=(0, 10))

        self.vars = {
            "Throttle": tk.IntVar(value=self.throttle),
            "Roll": tk.IntVar(value=self.roll),
            "Pitch": tk.IntVar(value=self.pitch),
            "Yaw": tk.IntVar(value=self.yaw),
        }

        row = 1
        for name in ["Throttle", "Roll", "Pitch", "Yaw"]:
            ttk.Label(main, text=name).grid(row=row, column=0, sticky="w")
            from_ = 1000
            to = 2000
            scale = ttk.Scale(main, from_=from_, to=to, orient="horizontal", command=lambda v, n=name: self.slider_changed(n, v))
            # store the scale widget on the instance before calling set() so callbacks
            # triggered by set() can safely access the attribute
            setattr(self, f"{name.lower()}_scale", scale)
            scale.set(self.vars[name].get())
            scale.grid(row=row, column=1, sticky="ew", padx=10)
            ttk.Label(main, textvariable=self.vars[name], width=5).grid(row=row, column=2)
            row += 1

        self.arm_button = ttk.Button(main, text="ARM: OFF", command=self.toggle_arm)
        self.arm_button.grid(row=row, column=0, pady=12, sticky="ew")
        ttk.Button(main, text="TAKEOFF", command=self.start_takeoff).grid(row=row, column=1, pady=12, sticky="ew")
        ttk.Button(main, text="CENTER", command=self.center_controls).grid(row=row, column=2, pady=12, sticky="ew")
        row += 1
        ttk.Button(main, text="STOP", command=self.stop_now).grid(row=row, column=0, columnspan=3, pady=(0, 12), sticky="ew")
        row += 1

        self.status = tk.StringVar(value=f"Connected to {self.port_name}. Disarmed.")
        ttk.Label(main, textvariable=self.status).grid(row=row, column=0, columnspan=3, sticky="w")

        main.columnconfigure(1, weight=1)
        self.root.columnconfigure(0, weight=1)
        self._ui_ready = True

    def bind_keys(self):
        self.root.bind("<KeyPress>", self.on_key)
        self.root.focus_set()

    def clamp(self, v):
        return max(1000, min(2000, int(v)))

    def slider_changed(self, name, value):
        if self._updating_ui or not self._ui_ready:
            return
        value = self.clamp(float(value))
        self.vars[name].set(value)
        setattr(self, name.lower(), value)
        if not self.armed:
            self.throttle = 1000
        self.update_sliders()

    def update_sliders(self):
        self._updating_ui = True
        try:
            self.throttle_scale.set(self.throttle)
            self.roll_scale.set(self.roll)
            self.pitch_scale.set(self.pitch)
            self.yaw_scale.set(self.yaw)
            self.vars["Throttle"].set(self.throttle)
            self.vars["Roll"].set(self.roll)
            self.vars["Pitch"].set(self.pitch)
            self.vars["Yaw"].set(self.yaw)
        finally:
            self._updating_ui = False

    def cancel_takeoff(self):
        if self.takeoff_job is not None:
            self.root.after_cancel(self.takeoff_job)
            self.takeoff_job = None

    def on_key(self, event):
        key = event.keysym.lower()

        if key == "m":
            self.toggle_arm()
        elif key == "t":
            self.start_takeoff()
        elif key == "escape":
            self.safe_exit()
        elif key == "space":
            self.center_controls()
        elif key == "x":
            self.cancel_takeoff()
            self.throttle = 1000
        elif key == "w" and self.armed:
            self.cancel_takeoff()
            self.throttle = self.clamp(self.throttle + THROTTLE_STEP)
        elif key == "s":
            self.cancel_takeoff()
            self.throttle = self.clamp(self.throttle - THROTTLE_STEP)
        elif key == "a":
            self.yaw = self.clamp(self.yaw - STEP)
        elif key == "d":
            self.yaw = self.clamp(self.yaw + STEP)
        elif key == "left":
            self.roll = self.clamp(self.roll - STEP)
        elif key == "right":
            self.roll = self.clamp(self.roll + STEP)
        elif key == "up":
            self.pitch = self.clamp(self.pitch + STEP)
        elif key == "down":
            self.pitch = self.clamp(self.pitch - STEP)

        if not self.armed:
            self.throttle = 1000
        self.update_sliders()

    def toggle_arm(self):
        self.cancel_takeoff()
        if self.armed:
            self.armed = 0
            self.throttle = 1000
        else:
            # safety: only arm at minimum throttle
            if self.throttle != 1000:
                self.throttle = 1000
            self.armed = 1
        self.arm_button.config(text=f"ARM: {'ON' if self.armed else 'OFF'}")
        self.update_sliders()

    def start_takeoff(self):
        if not self.armed:
            self.status.set("Arm first, then start takeoff.")
            return
        self.cancel_takeoff()

        start = self.throttle
        target = self.clamp(TAKEOFF_TARGET)
        if start >= target:
            self.status.set(f"Throttle already at or above {target}.")
            return

        steps = max(1, TAKEOFF_DURATION_MS // TAKEOFF_INTERVAL_MS)
        delta = (target - start) / steps

        def step_ramp(step_index=1):
            if not self.armed:
                self.cancel_takeoff()
                return
            if step_index >= steps:
                self.throttle = target
                self.takeoff_job = None
                self.status.set(f"Takeoff throttle reached: {self.throttle}")
            else:
                self.throttle = self.clamp(round(start + delta * step_index))
                self.status.set(f"Takeoff ramp: {self.throttle}")
                self.takeoff_job = self.root.after(
                    TAKEOFF_INTERVAL_MS, lambda: step_ramp(step_index + 1)
                )
            self.update_sliders()

        step_ramp()

    def center_controls(self):
        self.roll = 1500
        self.pitch = 1500
        self.yaw = 1500
        self.update_sliders()

    def stop_now(self):
        self.cancel_takeoff()
        self.armed = 0
        self.throttle = 1000
        self.center_controls()
        self.arm_button.config(text="ARM: OFF")
        self.send_command(force=True)

    def command_line(self):
        throttle = self.throttle if self.armed else 1000
        return f"{throttle},{self.roll},{self.pitch},{self.yaw},{self.armed}\n"

    def send_command(self, force=False):
        line = self.command_line()
        try:
            if self.ser and self.ser.is_open:
                self.ser.write(line.encode("ascii"))
                self.last_sent = line.strip()
                self.status.set(f"Sent: {self.last_sent}")
        except Exception as e:
            self.status.set(f"Serial send error: {e}")

    def schedule_send(self):
        self.send_command()
        self.root.after(int(1000 / SEND_HZ), self.schedule_send)

    def safe_exit(self):
        try:
            self.cancel_takeoff()
            self.armed = 0
            self.throttle = 1000
            self.roll = self.pitch = self.yaw = 1500
            for _ in range(5):
                self.send_command(force=True)
                time.sleep(0.05)
            if self.ser and self.ser.is_open:
                self.ser.close()
        finally:
            self.root.destroy()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True, help="Serial port of ESP32 transmitter, e.g. COM5 or /dev/ttyUSB0")
    args = parser.parse_args()

    root = tk.Tk()
    DroneController(root, args.port)
    root.mainloop()

if __name__ == "__main__":
    main()
