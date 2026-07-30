"""Regression tests for the Console section's command dispatch.

`api/index.py` pulls in cameras and serial at import time, so -- following the
convention of the other backend tests here -- the console functions are
extracted from the AST and exec'd against stubbed collaborators.
"""
import ast
import threading
import unittest
from pathlib import Path


API_INDEX = Path(__file__).resolve().parents[2] / "Drone-swarm-v1" / "computer_code" / "api" / "index.py"

WANTED = {
    "_normalise_mac",
    "CONSOLE_COMMANDS",
    "FANOUT_COMMANDS",
    "ARM_ON_WORDS",
    "ARM_OFF_WORDS",
    "RETARGET_DWELL_S",
    "MAX_SETPOINT_Z",
    "_arm_flag",
    "_console_uses_radio",
    "_resolve_targets",
    "_console_dispatch",
    "_console_emit",
    "on_console_command",
}

FLEET = [
    {"id": "a1", "name": "alpha", "mac": "10:00:3B:B1:5B:8C", "active": True},
    {"id": "b2", "name": "beta", "mac": "14:00:3B:B1:5B:8C", "active": True},
    {"id": "c3", "name": "gamma", "mac": "12:00:3B:B1:5B:8D", "active": True},
]


class _StubController:
    def __init__(self):
        self.state = "IDLE"
        self.armed = False
        self.fleet_armed = False
        self.setpoint = (0.0, 0.0, 0.2, 0.0)
        self.calls = []

    def cmd_arm(self, armed):
        self.armed = bool(armed)
        if not armed:
            self.fleet_armed = False   # mirrors Controller.cmd_arm
        self.calls.append(("arm", self.armed))

    def cmd_fleet_arm(self, armed):
        self.fleet_armed = bool(armed)
        self.calls.append(("fleet_arm", self.fleet_armed))

    def cmd_takeoff(self, z):
        self.calls.append(("takeoff", z))

    def cmd_land(self):
        self.calls.append(("land",))

    def cmd_setpoint(self, x, y, z):
        self.setpoint = (x, y, z, self.setpoint[3])
        self.calls.append(("setpoint", x, y, z))

    def cmd_yaw(self, yaw):
        self.calls.append(("yaw", yaw))

    def get_setpoint(self):
        return self.setpoint

    def get_state(self):
        return self.state

    def is_armed(self):
        return self.armed


class _StubSocketIO:
    """Collects emits; `.on` is a pass-through so the decorator works."""

    def __init__(self):
        self.emits = []

    def on(self, _event):
        return lambda fn: fn

    def emit(self, event, payload=None, **_kw):
        self.emits.append((event, payload))


class _StubCalibration:
    active = False


def _build_namespace():
    module = ast.parse(API_INDEX.read_text(encoding="utf-8"))
    controller = _StubController()
    sio = _StubSocketIO()

    class _SerializeOnly:
        @staticmethod
        def serialize_pid(gains):
            return b"P"

        @staticmethod
        def serialize_trim(t, r, p, y):
            return b"T"

    ns = {
        "__builtins__": __builtins__,
        "threading": threading,
        "time": __import__("time"),
        "controller": controller,
        "Controller": _SerializeOnly,
        "socketio": sio,
        "calibration": _StubCalibration(),
        "NUM_PID": 17,
        "_fleet": [dict(d) for d in FLEET],
        "_fleet_lock": threading.Lock(),
        "_selected_drone_mac": None,
        "_battery": {},
        "_battery_lock": threading.Lock(),
        "_pid_lock": threading.Lock(),
        "_current_pid": [0.0] * 17,
        "_current_position": lambda: [0.0, 0.0, 0.0],
        "_serial_write": lambda payload: None,
    }

    def _retarget_radio(mac, force=False):
        ns["_selected_drone_mac"] = mac

    ns["_retarget_radio"] = _retarget_radio

    for node in module.body:
        names = set()
        if isinstance(node, ast.Assign):
            names = {t.id for t in node.targets if isinstance(t, ast.Name)}
        elif isinstance(node, (ast.ClassDef, ast.FunctionDef)):
            names = {node.name}
        if names & WANTED:
            exec(compile(ast.Module([node], []), str(API_INDEX), "exec"), ns)

    ns["RETARGET_DWELL_S"] = 0.0
    return ns, controller, sio


# Keep the accepted spellings sourced from index.py rather than duplicated.
_CONSTANTS = _build_namespace()[0]
ARM_ON_WORDS = _CONSTANTS["ARM_ON_WORDS"]
ARM_OFF_WORDS = _CONSTANTS["ARM_OFF_WORDS"]


class ConsoleCommandTests(unittest.TestCase):
    def setUp(self):
        self.ns, self.controller, self.sio = _build_namespace()

    def send(self, command, target="all", args=()):
        self.sio.emits.clear()
        self.ns["on_console_command"](
            {"target": target, "command": command, "args": list(args)}
        )
        return self.sio.emits

    def acks(self, emits):
        return [p for ev, p in emits if ev == "console-ack"]

    def errors(self, emits):
        return [p for ev, p in emits if ev == "console-error"]

    def notes(self, emits):
        return [p for ev, p in emits if ev == "console-note"]

    # --- fan-out ---------------------------------------------------------

    def test_ping_all_replies_once_per_active_drone(self):
        acks = self.acks(self.send("ping"))
        self.assertEqual([a["target"] for a in acks], ["alpha", "beta", "gamma"])

    def test_ping_all_reports_each_drones_own_battery(self):
        self.ns["_battery"].update({
            "10:00:3B:B1:5B:8C": {"pct": 41, "mv": 3600, "t": 0.0},
            "14:00:3B:B1:5B:8C": {"pct": 77, "mv": 3900, "t": 0.0},
        })
        acks = self.acks(self.send("ping"))
        self.assertIn("41%", acks[0]["text"])
        self.assertIn("77%", acks[1]["text"])
        self.assertIn("no battery data", acks[2]["text"])

    def test_estop_all_reaches_every_drone(self):
        acks = self.acks(self.send("estop"))
        self.assertEqual([a["target"] for a in acks], ["alpha", "beta", "gamma"])
        self.assertFalse(self.controller.armed)

    def test_ping_all_skips_standby_drones(self):
        self.ns["_fleet"][1]["active"] = False
        acks = self.acks(self.send("ping"))
        self.assertEqual([a["target"] for a in acks], ["alpha", "gamma"])

    def test_ping_does_not_move_the_radio(self):
        self.ns["_selected_drone_mac"] = "14:00:3B:B1:5B:8C"
        self.send("ping")
        self.assertEqual(self.ns["_selected_drone_mac"], "14:00:3B:B1:5B:8C")

    def test_fanout_restores_the_operators_radio_selection(self):
        self.ns["_selected_drone_mac"] = "14:00:3B:B1:5B:8C"
        self.send("trim", args=("1", "2", "3", "4"))
        self.assertEqual(self.ns["_selected_drone_mac"], "14:00:3B:B1:5B:8C")

    def test_one_drone_failing_does_not_abort_the_fanout(self):
        real = self.ns["_console_dispatch"]

        def flaky(command, args, entry, fleet_wide=False):
            if entry["name"] == "beta":
                raise ValueError("boom")
            return real(command, args, entry, fleet_wide)

        self.ns["_console_dispatch"] = flaky
        emits = self.send("ping")
        self.assertEqual([a["target"] for a in self.acks(emits)], ["alpha", "gamma"])
        self.assertEqual([e["target"] for e in self.errors(emits)], ["beta"])

    # --- arm ------------------------------------------------------------
    # Both directions reach the whole fleet now: the state packet carries a
    # fleet-arm bit that every drone reads whether or not it is the radio's
    # target, so nothing has to walk the radio.

    def test_arm_reaches_every_active_drone_in_both_directions(self):
        for word in ARM_ON_WORDS + ARM_OFF_WORDS:
            emits = self.send("arm", args=(word,))
            self.assertEqual([a["target"] for a in self.acks(emits)],
                             ["alpha", "beta", "gamma"], word)
            self.assertEqual(self.notes(emits), [], word)

    def test_arm_all_latches_and_clears_the_fleet_bit(self):
        self.send("arm", args=("on",))
        self.assertTrue(self.controller.fleet_armed)
        self.assertTrue(self.controller.armed)
        self.send("arm", args=("off",))
        self.assertFalse(self.controller.fleet_armed)
        self.assertFalse(self.controller.armed)

    def test_arm_all_never_moves_the_radio(self):
        # The fleet bit is broadcast, so there is nothing to walk -- and moving
        # the radio would silently steal MoCap's selection.
        self.ns["_selected_drone_mac"] = "14:00:3B:B1:5B:8C"
        for word in ("on", "off"):
            self.send("arm", args=(word,))
            self.assertEqual(self.ns["_selected_drone_mac"], "14:00:3B:B1:5B:8C", word)

    def test_arm_all_says_which_drones_are_only_parked(self):
        self.ns["_selected_drone_mac"] = "10:00:3B:B1:5B:8C"   # alpha
        acks = {a["target"]: a["text"] for a in self.acks(self.send("arm", args=("on",)))}
        self.assertNotIn("parked", acks["alpha"])
        self.assertIn("parked", acks["beta"])
        self.assertIn("parked", acks["gamma"])

    def test_arm_on_a_single_drone_does_not_latch_the_fleet(self):
        self.send("arm", target="beta", args=("on",))
        self.assertTrue(self.controller.armed)
        self.assertFalse(self.controller.fleet_armed)
        # It does still need the radio pointed at that drone.
        self.assertEqual(self.ns["_selected_drone_mac"], "14:00:3B:B1:5B:8C")

    def test_estop_clears_the_fleet_latch(self):
        self.send("arm", args=("on",))
        self.assertTrue(self.controller.fleet_armed)
        self.send("estop")
        self.assertFalse(self.controller.fleet_armed)
        self.assertFalse(self.controller.armed)

    def test_estop_never_moves_the_radio(self):
        self.ns["_selected_drone_mac"] = "14:00:3B:B1:5B:8C"
        self.send("estop")
        self.assertEqual(self.ns["_selected_drone_mac"], "14:00:3B:B1:5B:8C")

    # --- single-target collapse -----------------------------------------

    def test_flight_command_on_all_collapses_and_explains(self):
        emits = self.send("takeoff", args=("0.5",))
        self.assertEqual(len(self.notes(emits)), 1)
        self.assertIn("cannot be broadcast", self.notes(emits)[0]["text"])

    def test_flight_command_on_all_prefers_the_selected_drone(self):
        self.ns["_selected_drone_mac"] = "12:00:3B:B1:5B:8D"
        acks = self.acks(self.send("goto", args=("0", "0", "0.4")))
        self.assertEqual([a["target"] for a in acks], ["gamma"])

    def test_single_target_command_leaves_the_radio_on_that_drone(self):
        self.send("arm", target="beta", args=("on",))
        self.assertEqual(self.ns["_selected_drone_mac"], "14:00:3B:B1:5B:8C")

    # --- target resolution ----------------------------------------------

    def test_target_matches_id_mac_or_name(self):
        for target in ("b2", "14:00:3B:B1:5B:8C", "14-00-3b-b1-5b-8c", "beta", "BETA"):
            acks = self.acks(self.send("ping", target=target))
            self.assertEqual([a["target"] for a in acks], ["beta"], target)

    def test_standby_target_is_rejected(self):
        self.ns["_fleet"][1]["active"] = False
        errors = self.errors(self.send("ping", target="beta"))
        self.assertIn("standby", errors[0]["text"])

    def test_unknown_target_is_rejected(self):
        errors = self.errors(self.send("ping", target="nope"))
        self.assertIn("unknown target", errors[0]["text"])

    # --- validation ------------------------------------------------------

    def test_unknown_command_reports_before_touching_the_fleet(self):
        self.ns["_fleet"].clear()
        errors = self.errors(self.send("frobnicate"))
        self.assertIn("unknown command", errors[0]["text"])

    def test_empty_command_is_silently_ignored(self):
        self.assertEqual(self.send(""), [])

    def test_estop_still_disarms_when_no_drone_resolves(self):
        self.ns["_fleet"].clear()
        self.controller.armed = True
        acks = self.acks(self.send("estop"))
        self.assertEqual(len(acks), 1)
        self.assertIn("EMERGENCY STOP", acks[0]["text"])
        self.assertFalse(self.controller.armed)

    def test_goto_rejects_altitudes_takeoff_would_refuse(self):
        errors = self.errors(self.send("goto", args=("0", "0", "50")))
        self.assertIn("z must be in", errors[0]["text"])
        self.assertNotIn(("setpoint", 0.0, 0.0, 50.0), self.controller.calls)

    def test_move_rejects_a_delta_that_leaves_the_altitude_envelope(self):
        errors = self.errors(self.send("move", args=("0", "0", "9")))
        self.assertIn("z must be in", errors[0]["text"])

    def test_pid_rejects_fractional_and_out_of_range_indices(self):
        for idx in ("1.5", "99", "-1"):
            errors = self.errors(self.send("pid", args=(idx, "3")))
            self.assertTrue(errors, idx)
            self.assertIn("index must be", errors[0]["text"], idx)

    def test_arm_accepts_the_usual_boolean_spellings(self):
        for flag in ARM_ON_WORDS:
            self.send("arm", args=(flag,))
            self.assertTrue(self.controller.armed, flag)
        for flag in ARM_OFF_WORDS:
            self.send("arm", args=(flag,))
            self.assertFalse(self.controller.armed, flag)

    def test_arm_without_a_usable_argument_reports_usage_only(self):
        for args in ((), ("banana",)):
            emits = self.send("arm", args=args)
            self.assertIn("usage: arm", self.errors(emits)[0]["text"])
            # A usage error must not drag a fan-out note along with it.
            self.assertEqual(self.notes(emits), [])

    def test_hover_rejects_negative_durations(self):
        errors = self.errors(self.send("hover", args=("-5",)))
        self.assertIn("negative", errors[0]["text"])

    def test_calibration_blocks_flight_commands_but_not_estop(self):
        self.ns["calibration"].active = True
        self.assertIn("calibration in progress",
                      self.errors(self.send("takeoff", args=("0.5",)))[0]["text"])
        self.assertTrue(self.acks(self.send("estop")))
        self.assertTrue(self.acks(self.send("ping")))


if __name__ == "__main__":
    unittest.main()
