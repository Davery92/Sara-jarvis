"""Activity digests for scheduled narrator broadcasts.

Patch notes (daily / weekly) need *facts*, not just severity. This module
gathers them from the same tables individual triggers use, but as aggregates
over a time window. The output is a plain dict that goes into
TriggerContext.facts so the LLM can ground bullet points in real data.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def collect_activity_digest(
    db: AsyncSession,
    user_id: str,
    hours: int,
) -> Dict[str, Any]:
    """Aggregate David's activity over the last `hours` hours.

    All inner queries swallow their own errors so one missing table doesn't
    blank the whole digest — patch notes should still fire on a partial
    picture rather than fail silently.

    Returned dict has stable keys; the LLM can pick the ones that matter.
    """
    digest: Dict[str, Any] = {
        "window_hours": hours,
    }

    # ── git commits ──
    try:
        r = await db.execute(
            text(
                """
                SELECT COUNT(*) AS total,
                       COUNT(DISTINCT branch) AS branches
                FROM git_commit
                WHERE committed_at > NOW() - make_interval(hours => :h)
                """
            ),
            {"h": hours},
        )
        row = r.mappings().first()
        digest["commits"] = {
            "total": int(row["total"] or 0),
            "branches_touched": int(row["branches"] or 0),
        }

        # Top branches by commit count
        r = await db.execute(
            text(
                """
                SELECT branch, COUNT(*) AS n FROM git_commit
                WHERE committed_at > NOW() - make_interval(hours => :h)
                  AND branch IS NOT NULL AND branch != ''
                GROUP BY branch ORDER BY n DESC LIMIT 3
                """
            ),
            {"h": hours},
        )
        digest["commits"]["top_branches"] = [
            {"branch": x["branch"], "count": int(x["n"])}
            for x in r.mappings().all()
        ]

        # Damned commit messages in the window
        r = await db.execute(
            text(
                """
                SELECT COUNT(*) FROM git_commit
                WHERE committed_at > NOW() - make_interval(hours => :h)
                  AND LOWER(TRIM(message)) IN
                      ('wip','fix','asdf','test','.','..','','stuff','tmp')
                """
            ),
            {"h": hours},
        )
        digest["commits"]["damned_count"] = int(r.scalar_one() or 0)
    except Exception as exc:
        logger.warning("digest: commit query failed: %s", exc)

    # ── pull requests ──
    try:
        r = await db.execute(
            text(
                """
                SELECT
                    COUNT(*) FILTER (WHERE status = 'open'
                        AND opened_at > NOW() - make_interval(hours => :h))
                        AS opened_in_window,
                    COUNT(*) FILTER (WHERE status = 'merged'
                        AND merged_at > NOW() - make_interval(hours => :h))
                        AS merged_in_window,
                    COUNT(*) FILTER (WHERE status = 'open')
                        AS open_total,
                    COUNT(*) FILTER (WHERE status = 'open'
                        AND opened_at < NOW() - INTERVAL '7 days')
                        AS open_stale
                FROM pull_request
                """
            ),
            {"h": hours},
        )
        row = r.mappings().first()
        digest["pull_requests"] = {
            "opened_in_window": int(row["opened_in_window"] or 0),
            "merged_in_window": int(row["merged_in_window"] or 0),
            "open_total": int(row["open_total"] or 0),
            "open_stale": int(row["open_stale"] or 0),
        }
    except Exception as exc:
        logger.warning("digest: PR query failed: %s", exc)

    # ── errors ──
    try:
        r = await db.execute(
            text(
                """
                SELECT COUNT(*) FROM agent_run_log
                WHERE error_message IS NOT NULL AND error_message != ''
                  AND run_at > NOW() - make_interval(hours => :h)
                """
            ),
            {"h": hours},
        )
        digest["errors"] = {"count": int(r.scalar_one() or 0)}
    except Exception as exc:
        logger.warning("digest: error query failed: %s", exc)

    # ── workouts ──
    try:
        r = await db.execute(
            text(
                """
                SELECT COUNT(*) FROM external_workout
                WHERE user_id = :uid
                  AND started_at > NOW() - make_interval(hours => :h)
                """
            ),
            {"uid": user_id, "h": hours},
        )
        digest["workouts"] = {"count": int(r.scalar_one() or 0)}
    except Exception as exc:
        logger.warning("digest: workout query failed: %s", exc)

    # ── narrator self-broadcast count ──
    # How many times the System AI spoke up in this window. Self-aware
    # patch-note line: "[META] The System broadcast 4 times in the last 24h."
    try:
        r = await db.execute(
            text(
                """
                SELECT COUNT(*) FILTER (WHERE NOT suppressed) AS spoken,
                       COUNT(*) FILTER (WHERE suppressed) AS silent
                FROM system_event
                WHERE user_id = :uid
                  AND created_at > NOW() - make_interval(hours => :h)
                """
            ),
            {"uid": user_id, "h": hours},
        )
        row = r.mappings().first()
        digest["narrator_self"] = {
            "spoken": int(row["spoken"] or 0),
            "silent": int(row["silent"] or 0),
        }
    except Exception as exc:
        logger.warning("digest: narrator self-count failed: %s", exc)

    return digest
