"""Unit tests: Controller.serialize_state / serialize_pid / serialize_trim.

Tested by: E/21/180 - Herath H. M. S. R.

Test design (Step 1):
  Equivalence classes:
    serialize_state: valid packet dict -> single "S,...\\n" ASCII line
    serialize_pid:   sequence of numerics -> "P,<17 floats>\\n"
    serialize_trim:  4 ints (or int-coercible) -> "T,t,r,p,y\\n"
  Boundaries (serialize_pid gain count = 17):
    len 16 -> padded with 0.0 to 17
    len 17 -> passed through exactly
    len 18 -> truncated to 17
    len 0  -> all-zero line (extreme lower bound)
  Error/negative:
    serialize_state with a missing key -> KeyError
    serialize_pid with non-numeric element -> ValueError
    serialize_trim with non-numeric -> ValueError
External dependencies: none (pure functions) - nothing to mock.
"""

import pytest

from controller import Controller


VALID_PKT = {
    "x": 0.1, "y": -0.2, "z": 0.3,
    "vx": 0.01, "vy": 0.02, "vz": -0.03,
    "yaw_sp": 1.5708,
    "x_sp": 0.1, "y_sp": -0.2, "z_sp": 0.2,
    "armed": 2,
    "state": "HOVER",
}


# ---------- serialize_state ----------

def test_state_line_format_and_field_count():
    line = Controller.serialize_state(VALID_PKT).decode()
    assert line.startswith("S,") and line.endswith("\n")
    fields = line.strip().split(",")
    assert len(fields) == 12          # 'S' + 11 values
    assert fields[-1] == "2"          # armed as int


def test_state_line_values_are_4dp_floats():
    line = Controller.serialize_state(VALID_PKT).decode().strip()
    fields = line.split(",")[1:11]
    assert fields[0] == "0.1000"
    assert fields[6] == "1.5708"
    assert all("." in f and len(f.split(".")[1]) == 4 for f in fields)


def test_state_line_armed_boolean_coercion():
    pkt = dict(VALID_PKT, armed=True)   # bool is int-coercible
    line = Controller.serialize_state(pkt).decode().strip()
    assert line.split(",")[-1] == "1"


def test_state_missing_key_raises_keyerror():
    pkt = dict(VALID_PKT)
    del pkt["z_sp"]
    with pytest.raises(KeyError):
        Controller.serialize_state(pkt)


# ---------- serialize_pid (boundary: exactly 17 gains) ----------

def _pid_fields(gains):
    return Controller.serialize_pid(gains).decode().strip().split(",")


def test_pid_exactly_17_passed_through():
    gains = [float(i) for i in range(17)]
    fields = _pid_fields(gains)
    assert fields[0] == "P" and len(fields) == 18
    assert fields[1] == "0.000000" and fields[17] == "16.000000"


def test_pid_16_padded_to_17_with_zero():
    fields = _pid_fields([1.0] * 16)
    assert len(fields) == 18
    assert fields[17] == "0.000000"


def test_pid_18_truncated_to_17():
    gains = [1.0] * 17 + [99.0]
    fields = _pid_fields(gains)
    assert len(fields) == 18
    assert "99.000000" not in fields


def test_pid_empty_list_gives_all_zeros():
    fields = _pid_fields([])
    assert len(fields) == 18
    assert all(f == "0.000000" for f in fields[1:])


def test_pid_non_numeric_raises_valueerror():
    with pytest.raises(ValueError):
        Controller.serialize_pid(["a"] * 17)


# ---------- serialize_trim ----------

def test_trim_line_format():
    assert Controller.serialize_trim(10, -5, 0, 3) == b"T,10,-5,0,3\n"


def test_trim_floats_truncated_to_int():
    assert Controller.serialize_trim(1.9, -2.9, 0.0, 3.5) == b"T,1,-2,0,3\n"


def test_trim_non_numeric_raises_valueerror():
    with pytest.raises(ValueError):
        Controller.serialize_trim("high", 0, 0, 0)
