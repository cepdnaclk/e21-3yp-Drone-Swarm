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

    def test_touchdown_clears_the_fleet_arm_latch(self):
        # Landing auto-disarms without going through cmd_arm, so the latch has
        # to be cleared there too -- otherwise the fleet stays hot while the
        # operator walks out to the pad. Done in the controller rather than
        # left to the UI's arm heartbeat, so it holds with no browser attached.
        self.controller.cmd_fleet_arm(True)
        self.controller.cmd_arm(True)
        self.step()
        self.age_state(0.2)
        self.step()

        self.controller.cmd_takeoff(0.5)
        self.step()
        self.age_state(1.2)
        self.step()

        self.pos[2] = 0.5
        self.controller.cmd_land()
        self.step()
        self.assertTrue(self.controller.is_fleet_armed())  # still hot mid-descent

        self.age_state(1.2)
        packet = self.step()
        self.assertEqual(packet["state"], "IDLE")
        self.assertEqual(packet["fleet_armed"], 0)
        self.assertFalse(self.controller.is_fleet_armed())

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
            "fleet_armed": 1,
        }

        self.assertEqual(
            Controller.serialize_state(packet),
            b"S,1.0000,-2.0000,0.1250,0.1000,-0.2000,0.3000,1.5708,0.5000,-0.5000,0.2500,2,1\n",
        )

    def test_pid_and_trim_wire_formats_are_stable(self):
        self.assertEqual(
            Controller.serialize_pid([1, 2, 3]),
            b"P,1.000000,2.000000,3.000000,0.000000,0.000000,0.000000,0.000000,0.000000,0.000000,0.000000,0.000000,0.000000,0.000000,0.000000,0.000000,0.000000,0.000000\n",
        )
        self.assertEqual(Controller.serialize_trim(1000, 1500, 1501, 1499), b"T,1000,1500,1501,1499\n")


class FleetArmTests(unittest.TestCase):
    """The fleet-arm latch is broadcast to drones the radio is not pointed at,
    so every path that disarms has to clear it."""

    def setUp(self):
        self.c = Controller()

    def test_latch_is_off_until_asked_for(self):
        self.assertFalse(self.c.is_fleet_armed())

    def test_latch_survives_arming_the_tracked_drone(self):
        self.c.cmd_fleet_arm(True)
        self.c.cmd_arm(True)
        self.assertTrue(self.c.is_fleet_armed())

    def test_disarming_always_clears_the_latch(self):
        # A single latch cannot park one drone while holding the others armed,
        # so "disarm" must never leave the rest of the fleet spinning.
        self.c.cmd_fleet_arm(True)
        self.c.cmd_arm(False)
        self.assertFalse(self.c.is_fleet_armed())

    def test_latch_rides_in_both_packet_builders(self):
        self.c.cmd_fleet_arm(True)
        self.assertEqual(self.c._packet_safe()["fleet_armed"], 1)
        pkt = self.c._packet([0, 0, 0], [0, 0, 0], 0.0, 1, 0.0, 0.0, 0.2)
        self.assertEqual(pkt["fleet_armed"], 1)

    def test_safe_packet_keeps_the_latch_when_pose_is_lost(self):
        # _packet_safe is what goes out when the tracked drone loses pose;
        # dropping the bit there would disarm the parked fleet on every blink.
        self.c.cmd_fleet_arm(True)
        line = Controller.serialize_state(self.c._packet_safe()).decode()
        self.assertTrue(line.endswith(",0,1\n"), line)


if __name__ == "__main__":
    unittest.main()
