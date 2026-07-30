"""ACS2 Gap A backoff logic — pure unit tests, no live daemon/network needed.

Verifies the sleep-pressure backoff (interval doubles on non-productive
turns, resets to base the moment a turn produces something, never exceeds
the 120-minute ceiling) without requiring live idle time on the VM. The
"looping x127 doing nothing" failure mode this guards against is a matter
of code correctness, not something that needs staged production idle time
to prove — see daemon.py's _adjust_after_turn/_backoff/_reset_backoff.
"""
import os

os.environ.setdefault("ACS_BACKEND_URL", "http://localhost:8000")
os.environ.setdefault("ACS_DAEMON_TOKEN", "test-token")

from daemon import Daemon  # noqa: E402


def _fresh_daemon() -> Daemon:
    return Daemon()


def test_base_interval_is_config_default():
    d = _fresh_daemon()
    assert d.think_interval_ticks == d._base_think_ticks


def test_produced_true_resets_to_base():
    d = _fresh_daemon()
    d.think_interval_ticks = d._base_think_ticks * 4
    d._adjust_after_turn({"produced": True})
    assert d.think_interval_ticks == d._base_think_ticks


def test_produced_false_doubles_interval():
    d = _fresh_daemon()
    base = d.think_interval_ticks
    d._adjust_after_turn({"produced": False})
    assert d.think_interval_ticks == base * 2


def test_none_result_treated_as_unproductive():
    d = _fresh_daemon()
    base = d.think_interval_ticks
    d._adjust_after_turn(None)
    assert d.think_interval_ticks == base * 2


def test_repeated_non_production_stretches_interval():
    d = _fresh_daemon()
    base = d.think_interval_ticks
    for _ in range(3):
        d._adjust_after_turn({"produced": False})
    assert d.think_interval_ticks == base * 8


def test_backoff_never_exceeds_max():
    d = _fresh_daemon()
    for _ in range(20):
        d._adjust_after_turn({"produced": False})
    assert d.think_interval_ticks == d._max_think_ticks
    assert d.think_interval_ticks <= d._max_think_ticks


def test_production_after_backoff_resets_fully_not_partially():
    d = _fresh_daemon()
    for _ in range(5):
        d._adjust_after_turn({"produced": False})
    assert d.think_interval_ticks > d._base_think_ticks
    d._adjust_after_turn({"produced": True})
    assert d.think_interval_ticks == d._base_think_ticks


def test_missing_produced_key_treated_as_unproductive():
    d = _fresh_daemon()
    base = d.think_interval_ticks
    d._adjust_after_turn({"some_other_field": True})
    assert d.think_interval_ticks == base * 2
