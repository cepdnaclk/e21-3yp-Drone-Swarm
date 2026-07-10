"""Unit tests: LowPassFilter.filter (LowPassFilter.py).

Tested by: E/21/217 - Kaushalya K. A. D. I.

Test design (Step 1):
  Equivalence classes:
    single sample vs long constant stream (steady-state convergence)
    dims = 1 vs dims = 3 (any dims should behave the same)
  Boundaries (buffer_size trim: `>= buffer_size` keeps last buffer_size//2):
    buffer at size-1  -> untrimmed (just inside)
    buffer reaches size -> trimmed to exactly size//2
    cutoff just below Nyquist (fs/2) -> valid
    cutoff == Nyquist -> ValueError from scipy.signal.butter (just outside)
  Error/negative:
    sample with wrong dims -> ValueError (vstack shape mismatch)
    cutoff <= 0 -> ValueError
    non-numeric sample -> NotImplementedError (scipy lfilter dtype check)
External dependencies: scipy.signal (butter/lfilter) - deterministic pure
  math, used real; no I/O to mock.
"""

import numpy as np
import pytest

from LowPassFilter import LowPassFilter


def make_lpf(**kw):
    defaults = dict(cutoff_frequency=15.0, sampling_frequency=60.0, dims=3)
    defaults.update(kw)
    return LowPassFilter(**defaults)


# ---------- equivalence ----------

def test_output_shape_matches_dims():
    lpf = make_lpf()
    out = lpf.filter(np.array([1.0, 2.0, 3.0]))
    assert out.shape == (3,)


def test_constant_input_converges_to_input():
    lpf = make_lpf()
    sample = np.array([0.5, -1.0, 2.0])
    for _ in range(200):
        out = lpf.filter(sample)
    np.testing.assert_allclose(out, sample, atol=1e-3)


def test_single_dim_filter_works():
    lpf = make_lpf(dims=1)
    out = lpf.filter(np.array([1.0]))
    assert out.shape == (1,)


def test_attenuates_high_frequency_noise():
    lpf = make_lpf(cutoff_frequency=2.0)
    rng = np.random.default_rng(42)
    base = np.array([1.0, 1.0, 1.0])
    for _ in range(300):
        noisy = base + rng.normal(0, 0.5, 3)   # broadband noise
        out = lpf.filter(noisy)
    np.testing.assert_allclose(out, base, atol=0.35)


# ---------- boundaries: buffer trimming ----------

def test_buffer_just_inside_not_trimmed():
    lpf = make_lpf(buffer_size=10)
    for _ in range(9):
        lpf.filter(np.zeros(3))
    assert lpf.buffered_data.shape[0] == 9


def test_buffer_at_size_trimmed_to_half():
    lpf = make_lpf(buffer_size=10)
    for _ in range(10):
        lpf.filter(np.zeros(3))
    assert lpf.buffered_data.shape[0] == 10 // 2


def test_output_continuous_across_trim():
    """The value returned just after a trim should stay near steady state."""
    lpf = make_lpf(buffer_size=20)
    sample = np.array([1.0, 1.0, 1.0])
    outs = [lpf.filter(sample) for _ in range(40)]  # trims at 20 and 40
    np.testing.assert_allclose(outs[-1], sample, atol=0.1)


# ---------- boundaries: cutoff vs Nyquist ----------

def test_cutoff_just_below_nyquist_valid():
    lpf = make_lpf(cutoff_frequency=29.9, sampling_frequency=60.0)
    assert lpf.filter(np.ones(3)).shape == (3,)


def test_cutoff_at_nyquist_raises():
    with pytest.raises(ValueError):
        make_lpf(cutoff_frequency=30.0, sampling_frequency=60.0)


def test_cutoff_zero_raises():
    with pytest.raises(ValueError):
        make_lpf(cutoff_frequency=0.0)


# ---------- error / negative ----------

def test_wrong_dims_sample_raises():
    lpf = make_lpf(dims=3)
    with pytest.raises(ValueError):
        lpf.filter(np.array([1.0, 2.0]))       # 2 values into 3-dim filter


def test_non_numeric_sample_raises():
    lpf = make_lpf(dims=3)
    # scipy.signal.lfilter rejects string dtypes with NotImplementedError
    with pytest.raises((TypeError, ValueError, NotImplementedError)):
        lpf.filter(np.array(["a", "b", "c"]))
