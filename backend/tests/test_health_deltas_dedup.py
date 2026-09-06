"""
gotcha_chat_amnesia_brief_clip_2026_09_06 Phase 5 §1: 15 near-identical
"Weight 240 / RHR / sleep" health_deltas lines piled up under 15 different
keys because the existing dedup only compared text for the SAME key.
"""
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_apply_brief_patch_drops_identical_text_under_a_different_key():
    from app.services.appraisal import _apply_brief_patch

    state = {
        "sections": {
            "health_deltas": [
                {"key": "health-2026-09-02", "text": "Weight 240.00. Resting HR 63 bpm. Recovery: sleep 7.6h (HRV 75)."},
            ]
        }
    }
    patch_dict = {
        "op": "add", "section": "health_deltas", "item_key": "health-2026-09-03",
        "content": {"text": "Weight 240.00. Resting HR 63 bpm. Recovery: sleep 7.6h (HRV 75)."},
    }

    mock_brief_patch = AsyncMock()
    with patch("app.services.world_brief.get_brief_row", AsyncMock(return_value=state)), \
         patch("app.services.world_brief.brief_patch", mock_brief_patch), \
         patch("app.services.world_brief.SECTIONS", {"health_deltas"}):
        await _apply_brief_patch(db=None, user_id="u1", patch=patch_dict)

    mock_brief_patch.assert_not_awaited()


@pytest.mark.asyncio
async def test_apply_brief_patch_keeps_genuinely_new_text():
    from app.services.appraisal import _apply_brief_patch

    state = {
        "sections": {
            "health_deltas": [
                {"key": "health-2026-09-02", "text": "Weight 240.00. Resting HR 63 bpm. Recovery: sleep 7.6h (HRV 75)."},
            ]
        }
    }
    patch_dict = {
        "op": "add", "section": "health_deltas", "item_key": "health-2026-09-04",
        "content": {"text": "Weight 238.00. Resting HR 58 bpm. Recovery: sleep 8.1h (HRV 82)."},
    }

    mock_brief_patch = AsyncMock()
    with patch("app.services.world_brief.get_brief_row", AsyncMock(return_value=state)), \
         patch("app.services.world_brief.brief_patch", mock_brief_patch), \
         patch("app.services.world_brief.SECTIONS", {"health_deltas"}):
        await _apply_brief_patch(db=None, user_id="u1", patch=patch_dict)

    mock_brief_patch.assert_awaited_once()
