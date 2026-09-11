"""Replay tests only run when pointed at the replay database.

A plain `pytest tests` run skips this directory rather than failing it: the
replay needs a provisioned sara_replay and a container that can reach it,
neither of which the ordinary unit suite has.
"""
import pytest

from tests.replay import harness


def pytest_collection_modifyitems(config, items):
    if harness.replay_enabled():
        return
    skip = pytest.mark.skip(reason="replay suite: run backend/tests/replay/run_replay.sh")
    for item in items:
        if "tests/replay/" in str(item.fspath).replace("\\", "/"):
            item.add_marker(skip)
