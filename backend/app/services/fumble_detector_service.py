"""Fumble detectors for skill minting (SARA_ALIVE §4/Arc 6.5, 2026-07-31).

Evidence-only, per the design artifact (published 2026-07-31,
https://claude.ai/code/artifact/aa35b186-8023-4991-9a37-dc0b5867c921):

  A. Same tool-error class >=3 times in a rolling 7-day window.
  B. Same >=2-tool sequence repeated >=3 times in a rolling 14-day window.

Both read `sara_activity_log` (kind='tool_result'), the same shape
kernel_hands._ledger() already writes and main_simple.execute_tool now
also writes (work-order item 4, same session) — no new retrieval path.
"""
import hashlib
import logging
from typing import Any, Dict, List

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_ERROR_WINDOW_DAYS = 7
_ERROR_THRESHOLD = 3
_SEQUENCE_WINDOW_DAYS = 14
_SEQUENCE_THRESHOLD = 3
_SEQUENCE_MIN_LEN = 2


def detect_error_fumbles(db: Session, window_days: int = _ERROR_WINDOW_DAYS,
                          threshold: int = _ERROR_THRESHOLD) -> List[Dict[str, Any]]:
    """Detector A. Returns [{tool, error_class, count, sample_error}]."""
    rows = db.execute(text("""
        SELECT metadata->>'tool' AS tool,
               split_part(COALESCE(metadata->>'error', 'Unknown'), ':', 1) AS error_class,
               COUNT(*) AS n,
               MAX(body) AS sample_error
        FROM sara_activity_log
        WHERE kind = 'tool_result'
          AND tags @> '["error"]'
          AND created_at > NOW() - (:days || ' days')::interval
          AND metadata->>'tool' IS NOT NULL
        GROUP BY 1, 2
        HAVING COUNT(*) >= :threshold
        ORDER BY n DESC
    """), {"days": window_days, "threshold": threshold}).mappings().fetchall()
    return [dict(r) for r in rows]


def detect_sequence_fumbles(db: Session, window_days: int = _SEQUENCE_WINDOW_DAYS,
                             threshold: int = _SEQUENCE_THRESHOLD) -> List[Dict[str, Any]]:
    """Detector B. Groups tool_result rows by conversation_id (the only
    thing linking calls that belong to "one manual workflow" — kernel_hands
    entries have no conversation_id and are capped at 1 call/turn anyway, so
    they never contribute a sequence), builds each conversation's ordered
    tool-call sequence, and counts how many distinct conversations produced
    the exact same sequence within the window. Returns
    [{sequence: [tool, ...], count, example_conversation_ids}]."""
    rows = db.execute(text("""
        SELECT metadata->>'conversation_id' AS conversation_id,
               metadata->>'tool' AS tool,
               created_at
        FROM sara_activity_log
        WHERE kind = 'tool_result'
          AND metadata->>'source' = 'chat'
          AND metadata->>'conversation_id' IS NOT NULL
          AND created_at > NOW() - (:days || ' days')::interval
        ORDER BY metadata->>'conversation_id', created_at
    """), {"days": window_days}).fetchall()

    by_conversation: Dict[str, List[str]] = {}
    for conv_id, tool, _created in rows:
        by_conversation.setdefault(conv_id, []).append(tool)

    by_fingerprint: Dict[str, Dict[str, Any]] = {}
    for conv_id, tools in by_conversation.items():
        if len(tools) < _SEQUENCE_MIN_LEN:
            continue
        fingerprint = hashlib.sha256("|".join(tools).encode()).hexdigest()[:16]
        entry = by_fingerprint.setdefault(fingerprint, {"sequence": tools, "conversation_ids": []})
        entry["conversation_ids"].append(conv_id)

    return [
        {
            "sequence": v["sequence"],
            "count": len(v["conversation_ids"]),
            "example_conversation_ids": v["conversation_ids"][:5],
        }
        for v in by_fingerprint.values()
        if len(v["conversation_ids"]) >= threshold
    ]
