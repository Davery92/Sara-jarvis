"""
Tests for the Arc 1.5 write-freeze flags (SARA_ALIVE_BUILD_PLAN, per review:
"wire each sender to the mouth with its legacy path disabled-not-deleted").

Each sender gets its own flag so a regression on one (e.g. calendar_prep's
35-55min timing window) reverts independently of the others. All default
OFF — legacy sends stay live until each is individually verified.
"""
from app.core.feature_flags import Flag, ALL_FLAGS


class TestWriteFreezeFlagsExist:
    def test_all_seven_sender_flags_registered(self):
        expected = [
            "MOUTH_ONLY_CALENDAR_PREP",
            "MOUTH_ONLY_TASK_RESULT_DELIVERY",
            "MOUTH_ONLY_MORNING_PROACTIVE",
            "MOUTH_ONLY_PREDICTIVE_ENGINE",
            "MOUTH_ONLY_BEDTIME_INTELLIGENCE",
            "MOUTH_ONLY_TRAVEL_NUDGE",
            "MOUTH_ONLY_LEARNING_DIGEST",
        ]
        for name in expected:
            assert name in ALL_FLAGS, f"{name} not registered"

    def test_flags_default_off(self):
        from unittest.mock import patch
        # is_enabled reads app_settings; with no row (fresh env), must be False.
        with patch("app.core.feature_flags._read_flags", return_value={}):
            from app.core.feature_flags import is_enabled
            assert is_enabled(Flag.MOUTH_ONLY_CALENDAR_PREP) is False
            assert is_enabled(Flag.MOUTH_ONLY_TRAVEL_NUDGE) is False
