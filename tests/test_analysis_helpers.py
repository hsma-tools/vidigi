"""Tests for shared internal helpers in `vidigi.analysis`.

These are exercised directly because later phases (resource utilisation, queue
size over time) call them, but no public function does yet.
"""

import pandas as pd
import pytest

from vidigi.analysis import _resolve_window


@pytest.fixture
def log():
    return pd.DataFrame({"time": [0, 5, 12, 30]})


def test_resolve_window_uses_explicit_limit_duration(log):
    assert _resolve_window(log, limit_duration=100, warm_up=0) == (0, 100)


def test_resolve_window_defaults_to_trial_max_time(log):
    assert _resolve_window(log, limit_duration=None, warm_up=0) == (0, 30)


def test_resolve_window_negative_warm_up_raises(log):
    with pytest.raises(ValueError, match="must not be negative"):
        _resolve_window(log, limit_duration=100, warm_up=-1)


def test_resolve_window_warm_up_after_end_raises(log):
    with pytest.raises(ValueError, match="is empty"):
        _resolve_window(log, limit_duration=10, warm_up=20)
