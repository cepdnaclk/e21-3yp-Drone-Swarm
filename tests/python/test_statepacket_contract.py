"""The StatePacket wire contract, checked across every board that speaks it.

Receivers drop any ESP-NOW packet whose length or protocol version doesn't
match their own build, so a sender and receiver compiled from different
revisions don't degrade -- the drone simply stops responding. These tests fail
the build instead, which is the only cheap place to catch it: nothing else in
CI compiles the sketches.
"""
import re
import sys
import unittest
from pathlib import Path


V1 = Path(__file__).resolve().parents[2] / "Drone-swarm-v1"
SENDER = V1 / "sender_esp32" / "sender_esp32.ino"
RECEIVERS = sorted((V1 / "receiver_esp32").glob("receiver_drone*/receiver_drone*.ino"))

sys.path.insert(0, str(V1 / "computer_code" / "api"))
from controller import Controller  # noqa: E402

STRUCT_RE = re.compile(
    r"typedef struct __attribute__\(\(packed\)\) \{(.*?)\} StatePacket;",
    re.DOTALL,
)
FIELD_RE = re.compile(r"^\s*(u?int\d+_t|float)\s+([^;]+);", re.MULTILINE)
# C scalar sizes on the ESP32 (32-bit, packed struct -> no padding).
SIZES = {"float": 4, "uint8_t": 1, "int8_t": 1, "uint16_t": 2,
         "int16_t": 2, "uint32_t": 4, "int32_t": 4}


def parse_state_packet(path):
    """Return [(type, name, count), ...] for the StatePacket in `path`."""
    body = STRUCT_RE.search(path.read_text(encoding="utf-8", errors="replace"))
    assert body, f"no StatePacket struct found in {path}"
    text = re.sub(r"//.*", "", body.group(1))
    fields = []
    for ctype, names in FIELD_RE.findall(text):
        for name in names.split(","):
            name = name.strip()
            array = re.match(r"^(\w+)\[(\d+)\]$", name)
            if array:
                fields.append((ctype, array.group(1), int(array.group(2))))
            else:
                fields.append((ctype, name, 1))
    return fields


def struct_size(fields):
    return sum(SIZES[ctype] * count for ctype, _, count in fields)


def proto_version(path):
    m = re.search(r"#define\s+STATE_PROTO_VER\s+(\d+)",
                  path.read_text(encoding="utf-8", errors="replace"))
    return int(m.group(1)) if m else None


class StatePacketContractTests(unittest.TestCase):
    def test_three_receiver_sketches_exist(self):
        self.assertEqual(len(RECEIVERS), 3, [p.name for p in RECEIVERS])

    def test_every_board_declares_the_same_struct(self):
        reference = parse_state_packet(SENDER)
        for path in RECEIVERS:
            self.assertEqual(parse_state_packet(path), reference,
                             f"{path.name} StatePacket differs from the sender's")

    def test_every_board_declares_the_same_protocol_version(self):
        reference = proto_version(SENDER)
        self.assertIsNotNone(reference, "sender has no STATE_PROTO_VER")
        for path in RECEIVERS:
            self.assertEqual(proto_version(path), reference,
                             f"{path.name} STATE_PROTO_VER differs from the sender's")

    def test_struct_carries_the_fleet_arm_bit_and_a_version(self):
        names = [name for _, name, _ in parse_state_packet(SENDER)]
        self.assertIn("fleet_armed", names)
        self.assertIn("proto_ver", names)
        self.assertIn("target", names)

    def test_struct_size_is_pinned(self):
        # A size change means every board must be reflashed together; make that
        # a deliberate edit here rather than a surprise on the bench.
        self.assertEqual(struct_size(parse_state_packet(SENDER)), 130)

    def test_every_hand_built_state_packet_carries_the_fleet_bit(self):
        # serialize_state defaults fleet_armed to 0 rather than raising, because
        # a KeyError in the control loop would be worse than a dropped bit. That
        # makes an omission silent -- and a silently dropped bit disarms the
        # whole parked fleet -- so catch it structurally instead.
        import ast
        for path in (V1 / "computer_code" / "api" / "index.py",
                     V1 / "computer_code" / "api" / "controller.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Dict):
                    continue
                keys = {k.value for k in node.keys
                        if isinstance(k, ast.Constant) and isinstance(k.value, str)}
                if {"armed", "x_sp", "z_sp"} <= keys:
                    self.assertIn(
                        "fleet_armed", keys,
                        f"{path.name}:{node.lineno} builds a state packet "
                        f"without fleet_armed")

    def test_sender_parses_as_many_s_line_fields_as_python_sends(self):
        m = re.search(r"parseFloats\(line, 2, f, (\d+)\)",
                      SENDER.read_text(encoding="utf-8", errors="replace"))
        self.assertIsNotNone(m, "could not find the S-line parse in the sender")
        expected = int(m.group(1))

        line = Controller.serialize_state({
            "x": 0.0, "y": 0.0, "z": 0.0,
            "vx": 0.0, "vy": 0.0, "vz": 0.0,
            "yaw_sp": 0.0, "x_sp": 0.0, "y_sp": 0.0, "z_sp": 0.0,
            "armed": 0, "fleet_armed": 0,
        }).decode().strip()
        emitted = len(line.split(",")) - 1  # minus the leading "S"

        self.assertEqual(
            emitted, expected,
            "serialize_state emits %d fields but the sender parses %d -- a "
            "short line makes parseStateLine bail and the sender stops "
            "updating state entirely" % (emitted, expected))


if __name__ == "__main__":
    unittest.main()
