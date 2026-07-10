"""Shared fixtures for the computer_code API test suite (CO328 Week 6)."""

import os
import sys

import pytest

# Make the api/ package importable when pytest runs from the repo root.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class FakeClock:
    """Deterministic replacement for time.perf_counter.

    Lets tests advance time explicitly so state-machine timings and
    Kalman-filter dt handling can be tested without real sleeps.
    """

    def __init__(self, start: float = 1000.0):
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


@pytest.fixture
def fake_clock():
    return FakeClock()
