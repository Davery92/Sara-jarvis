from datetime import datetime

from app.tasks.delivery_flush import _waiting_for_morning_anchor


def test_waiting_for_morning_anchor_window_boundaries():
    assert _waiting_for_morning_anchor(datetime(2026, 8, 23, 3, 59)) is False
    assert _waiting_for_morning_anchor(datetime(2026, 8, 23, 4, 0)) is True
    assert _waiting_for_morning_anchor(datetime(2026, 8, 23, 6, 9)) is True
    assert _waiting_for_morning_anchor(datetime(2026, 8, 23, 6, 10)) is False
    assert _waiting_for_morning_anchor(datetime(2026, 8, 23, 8, 0)) is False
