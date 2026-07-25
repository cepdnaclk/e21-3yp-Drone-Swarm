import unittest
from pathlib import Path
import sys

import numpy as np


API_DIR = Path(__file__).resolve().parents[2] / "Drone-swarm-v1" / "computer_code" / "api"
sys.path.insert(0, str(API_DIR))

from KalmanFilter import KalmanFilter
from LowPassFilter import LowPassFilter


class FilterTests(unittest.TestCase):
    def test_low_pass_filter_preserves_dimensions_and_caps_history(self):
        filt = LowPassFilter(cutoff_frequency=10.0, sampling_frequency=100.0, dims=2, buffer_size=4)

        outputs = [filt.filter(np.array([float(i), float(i * 2)])) for i in range(6)]

        self.assertEqual(outputs[-1].shape, (2,))
        self.assertLessEqual(filt.buffered_data.shape[0], 2)
        self.assertEqual(filt.buffered_data.shape[1], 2)

    def test_kalman_filter_initialises_from_first_measurement_and_resets(self):
        filt = KalmanFilter()

        pos, vel = filt.update([1.0, 2.0, 3.0])
        np.testing.assert_allclose(pos, [1.0, 2.0, 3.0])
        np.testing.assert_allclose(vel, [0.0, 0.0, 0.0])

        pos, vel = filt.predict_only(dt=0.05)
        self.assertEqual(pos.shape, (3,))
        self.assertEqual(vel.shape, (3,))

        filt.reset()
        pos, vel = filt.predict_only(dt=0.05)
        np.testing.assert_allclose(pos, [0.0, 0.0, 0.0])
        np.testing.assert_allclose(vel, [0.0, 0.0, 0.0])


if __name__ == "__main__":
    unittest.main()
