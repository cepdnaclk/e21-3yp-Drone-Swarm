import unittest
from pathlib import Path
import sys

import numpy as np


API_DIR = Path(__file__).resolve().parents[2] / "Drone-swarm-v1" / "computer_code" / "api"
sys.path.insert(0, str(API_DIR))

from controller import Controller, ControlParams


class ControllerStateMachineTests(unittest.TestCase):
    def setUp(self):
        self.controller = Controller(
            ControlParams(
                arming_hold_s=0.1,
                takeoff_ramp_s=1.0,
                landing_ramp_s=1.0,
                z_err_limit_m=10.0,
            )
        )
        self.pos = np.array([1.0, -2.0, 0.0], dtype=np.float32)
        self.vel = np.array([0.1, 0.2, -0.1], dtype=np.float32)

    def step(self):
        return self.controller.step(self.pos, self.vel, heading=0.25, dt=1.0 / 60.0)

    def age_state(self, seconds):
        self.controller._state_entry_t -= seconds

    def test_arm_takeoff_hover_land_cycle(self):
        self.controller.cmd_arm(True)

        packet = self.step()
        self.assertEqual(packet["state"], "ARMING")
        self.assertEqual(packet["armed"], 1)
        self.assertEqual(packet["x_sp"], 1.0)
        self.assertEqual(packet["y_sp"], -2.0)
        self.assertEqual(packet["z_sp"], 0.0)

        self.age_state(0.2)
        packet = self.step()
        self.assertEqual(packet["state"], "READY")

        self.controller.cmd_takeoff(0.5)
        packet = self.step()
        self.assertEqual(packet["state"], "TAKEOFF")
        self.assertEqual(packet["armed"], 2)
        self.assertGreaterEqual(packet["z_sp"], 0.0)

        self.age_state(1.2)
        packet = self.step()
        self.assertEqual(packet["state"], "HOVER")
        self.assertAlmostEqual(packet["z_sp"], 0.5, places=6)

        self.pos[2] = 0.5
        self.controller.cmd_land()
        packet = self.step()
        self.assertEqual(packet["state"], "LANDING")
        self.assertEqual(packet["armed"], 2)

        self.age_state(1.2)
        packet = self.step()
        self.assertEqual(packet["state"], "IDLE")
        self.assertEqual(packet["armed"], 0)
        self.assertFalse(self.controller.is_armed())

    def test_missing_pose_forces_emergency_packet(self):
        packet = self.controller.step(None, self.vel, heading=0.0, dt=0.01)

        self.assertEqual(packet["state"], "EMERGENCY")
        self.assertEqual(packet["armed"], 0)
        self.assertEqual(packet["x"], 0.0)
        self.assertEqual(packet["vx"], 0.0)


class ControllerSerializationTests(unittest.TestCase):
    def test_state_packet_wire_format_is_stable(self):
        packet = {
            "x": 1,
            "y": -2,
            "z": 0.125,
            "vx": 0.1,
            "vy": -0.2,
            "vz": 0.3,
            "yaw_sp": 1.570796,
            "x_sp": 0.5,
            "y_sp": -0.5,
            "z_sp": 0.25,
            "armed": 2,
        }

        self.assertEqual(
            Controller.serialize_state(packet),
            b"S,1.0000,-2.0000,0.1250,0.1000,-0.2000,0.3000,1.5708,0.5000,-0.5000,0.2500,2\n",
        )

    def test_pid_and_trim_wire_formats_are_stable(self):
        self.assertEqual(
            Controller.serialize_pid([1, 2, 3]),
            b"P,1.000000,2.000000,3.000000,0.000000,0.000000,0.000000,0.000000,0.000000,0.000000,0.000000,0.000000,0.000000,0.000000,0.000000,0.000000,0.000000,0.000000\n",
        )
        self.assertEqual(Controller.serialize_trim(1000, 1500, 1501, 1499), b"T,1000,1500,1501,1499\n")


if __name__ == "__main__":
    unittest.main()
