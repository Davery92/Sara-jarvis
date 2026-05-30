"""Git/GitHub-based triggers. Reads tables populated by /api/webhooks/github."""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.narrator.triggers.base import (
    Trigger,
    TriggerContext,
    register_trigger,
)

logger = logging.getLogger(__name__)


# Minimum age before a PR is considered "stale" enough to roast.
STALE_PR_MIN_AGE_DAYS = 7

# Anything merged after sitting open this long is a "long merge" worth a
# (grudging) acknowledgment.
LONG_MERGE_MIN_DAYS = 30

# How recently we look for a merge to consider it "fresh enough to narrate."
LONG_MERGE_LOOKBACK_DAYS = 2

# Damned commit messages — empty, single-char, or stock placeholders.
DAMNED_COMMIT_MESSAGES = ("wip", "fix", "asdf", "test", ".", "..", "", "stuff", "tmp")

# Window over which to count damned-message commits.
DAMNED_COMMIT_WINDOW_DAYS = 7

# Minimum count before it crosses from "happens" to "pattern."
DAMNED_COMMIT_MIN_COUNT = 3


@register_trigger("stale_pr", cooldown_seconds=24 * 60 * 60)
class StalePRTrigger(Trigger):
    """Open PRs that have been sitting for a while.

    Fires when at least one open PR is older than STALE_PR_MIN_AGE_DAYS.
    Facts include the count of open stale PRs and the oldest one's
    branch + age, which is everything the persona needs to be specific.
    """

    async def check(
        self, db: AsyncSession, user_id: str
    ) -> Optional[TriggerContext]:
        row = (
            await db.execute(
                text(
                    """
                    SELECT
                        COUNT(*) AS pr_count,
                        MAX(EXTRACT(EPOCH FROM (NOW() - opened_at)) / 86400)::int
                            AS oldest_age_days
                    FROM pull_request
                    WHERE status = 'open'
                      AND opened_at IS NOT NULL
                      AND opened_at < NOW() - make_interval(days => :min_age)
                    """
                ),
                {"min_age": STALE_PR_MIN_AGE_DAYS},
            )
        ).mappings().first()

        if not row or not row["pr_count"]:
            return None

        pr_count = int(row["pr_count"])
        oldest_age_days = int(row["oldest_age_days"] or 0)

        # Fetch the oldest branch name for specificity.
        oldest = (
            await db.execute(
                text(
                    """
                    SELECT source_branch, pr_number, title
                    FROM pull_request
                    WHERE status = 'open' AND opened_at IS NOT NULL
                    ORDER BY opened_at ASC
                    LIMIT 1
                    """
                )
            )
        ).mappings().first()

        oldest_branch = (oldest and oldest["source_branch"]) or "unknown"
        oldest_pr_number = oldest and oldest["pr_number"]
        oldest_title = oldest and oldest["title"]

        facts = {
            "pr_count": pr_count,
            "oldest_branch": oldest_branch,
            "oldest_age_days": oldest_age_days,
            "oldest_pr_number": oldest_pr_number,
            "oldest_pr_title": oldest_title,
        }
        summary = (
            f"{pr_count} open PR{'s' if pr_count != 1 else ''}, "
            f"oldest is {oldest_age_days} day"
            f"{'s' if oldest_age_days != 1 else ''} old ({oldest_branch})"
        )

        return TriggerContext(
            trigger_name="stale_pr",
            severity="roast",
            facts=facts,
            summary=summary,
            # Same oldest branch within the cooldown → don't re-fire. If the
            # set churns (one PR merges, another goes stale), this re-fires.
            dedup_key=f"stale_pr:{oldest_branch}:{pr_count}",
        )


@register_trigger("the_long_merge", cooldown_seconds=24 * 60 * 60)
class TheLongMergeTrigger(Trigger):
    """A PR that sat open >30 days finally merged.

    Grudging acknowledgment — the persona acknowledges the lift without
    pretending to be impressed. Fires once per merged PR (dedup key includes
    the PR number) and only if the merge happened in the last 2 days.
    """

    async def check(
        self, db: AsyncSession, user_id: str
    ) -> Optional[TriggerContext]:
        row = (
            await db.execute(
                text(
                    """
                    SELECT
                        pr_number, source_branch, title,
                        EXTRACT(DAY FROM (merged_at - opened_at))::int
                            AS days_open,
                        EXTRACT(EPOCH FROM (NOW() - merged_at)) / 3600
                            AS hours_since_merge
                    FROM pull_request
                    WHERE status = 'merged'
                      AND opened_at IS NOT NULL
                      AND merged_at IS NOT NULL
                      AND merged_at > NOW() - make_interval(days => :lookback)
                      AND merged_at - opened_at > make_interval(days => :min_days)
                    ORDER BY merged_at DESC
                    LIMIT 1
                    """
                ),
                {
                    "lookback": LONG_MERGE_LOOKBACK_DAYS,
                    "min_days": LONG_MERGE_MIN_DAYS,
                },
            )
        ).mappings().first()

        if not row:
            return None

        pr_number = row["pr_number"]
        branch = row["source_branch"] or "unknown"
        days_open = int(row["days_open"])
        facts = {
            "pr_number": pr_number,
            "source_branch": branch,
            "title": row["title"],
            "days_open": days_open,
            "hours_since_merge": round(float(row["hours_since_merge"] or 0), 1),
        }
        summary = (
            f"PR #{pr_number} ({branch}) merged after sitting open "
            f"for {days_open} days"
        )
        return TriggerContext(
            trigger_name="the_long_merge",
            severity="grudging",
            facts=facts,
            summary=summary,
            # One acknowledgment per PR.
            dedup_key=f"the_long_merge:pr_{pr_number}",
        )


@register_trigger("damned_commit_message", cooldown_seconds=24 * 60 * 60)
class DamnedCommitMessageTrigger(Trigger):
    """A pattern of placeholder commit messages over the last week.

    Single 'wip' commits are fine. Three or more 'wip'/'fix'/'.' messages in
    a week is a pattern — and patterns are the System AI's home turf.
    """

    async def check(
        self, db: AsyncSession, user_id: str
    ) -> Optional[TriggerContext]:
        rows = (
            await db.execute(
                text(
                    """
                    SELECT LOWER(TRIM(message)) AS msg, COUNT(*) AS n
                    FROM git_commit
                    WHERE committed_at > NOW() - make_interval(days => :win)
                      AND LOWER(TRIM(message)) = ANY(:bad)
                    GROUP BY 1
                    ORDER BY n DESC
                    """
                ),
                {
                    "win": DAMNED_COMMIT_WINDOW_DAYS,
                    "bad": list(DAMNED_COMMIT_MESSAGES),
                },
            )
        ).mappings().all()

        total = sum(int(r["n"]) for r in rows)
        if total < DAMNED_COMMIT_MIN_COUNT:
            return None

        breakdown = {r["msg"] or "<empty>": int(r["n"]) for r in rows}
        top_msg = rows[0]["msg"] or "<empty>"
        top_n = int(rows[0]["n"])

        facts = {
            "total_count": total,
            "window_days": DAMNED_COMMIT_WINDOW_DAYS,
            "breakdown": breakdown,
            "top_message": top_msg,
            "top_count": top_n,
        }
        summary = (
            f"{total} placeholder commit message"
            f"{'s' if total != 1 else ''} in the last "
            f"{DAMNED_COMMIT_WINDOW_DAYS} days; most common: "
            f"{top_msg!r} ({top_n})"
        )
        return TriggerContext(
            trigger_name="damned_commit_message",
            severity="roast",
            facts=facts,
            summary=summary,
            # Refires when the count crosses a new threshold (3, 5, 10, …).
            dedup_key=f"damned_commit:{_bucket(total)}",
        )


def _bucket(n: int) -> str:
    """Coarse buckets so dedup ignores n+1 vs n+2 jitters."""
    if n < 5:
        return "lt5"
    if n < 10:
        return "lt10"
    if n < 25:
        return "lt25"
    return "ge25"


# ── Branch / commit-pattern triggers (PR 8) ──────────────────────────────────


@register_trigger("ghost_branch", cooldown_seconds=24 * 60 * 60)
class GhostBranchTrigger(Trigger):
    """A branch older than 30 days, never merged, never deleted.

    Quiet observation, not a roast — branches like this often hold
    abandoned ideas the user might want to remember exist.
    """

    async def check(
        self, db: AsyncSession, user_id: str
    ) -> Optional[TriggerContext]:
        row = (
            await db.execute(
                text(
                    """
                    SELECT b.name, p.name AS project_name,
                           EXTRACT(DAY FROM (NOW() - b.last_activity_at))::int
                               AS age_days,
                           (SELECT COUNT(*) FROM git_branch
                            WHERE NOT is_merged AND NOT is_deleted
                              AND NOT is_default
                              AND last_activity_at IS NOT NULL
                              AND last_activity_at < NOW() - INTERVAL '30 days')
                            AS total_ghosts
                    FROM git_branch b
                    JOIN dev_project p ON p.id = b.project_id
                    WHERE NOT b.is_merged
                      AND NOT b.is_deleted
                      AND NOT b.is_default
                      AND b.last_activity_at IS NOT NULL
                      AND b.last_activity_at < NOW() - INTERVAL '30 days'
                    ORDER BY b.last_activity_at ASC
                    LIMIT 1
                    """
                )
            )
        ).mappings().first()

        if not row or not row["total_ghosts"]:
            return None

        facts = {
            "oldest_branch": row["name"],
            "project_name": row["project_name"],
            "age_days": int(row["age_days"] or 0),
            "total_ghost_count": int(row["total_ghosts"]),
        }
        summary = (
            f"{facts['total_ghost_count']} abandoned branch"
            f"{'es' if facts['total_ghost_count'] != 1 else ''}; "
            f"oldest is {facts['oldest_branch']} in {facts['project_name']} "
            f"({facts['age_days']} days)"
        )
        return TriggerContext(
            trigger_name="ghost_branch",
            severity="observation",
            facts=facts,
            summary=summary,
            dedup_key=f"ghost_branch:{row['name']}:{_bucket(facts['total_ghost_count'])}",
        )


@register_trigger("readme_neglect", cooldown_seconds=7 * 24 * 60 * 60)
class ReadmeNeglectTrigger(Trigger):
    """100+ commits have landed in a project whose README hasn't been touched
    in 90+ days. The codebase has drifted from its documentation."""

    async def check(
        self, db: AsyncSession, user_id: str
    ) -> Optional[TriggerContext]:
        # Find projects where any README was touched once, and many commits
        # have landed since without touching the README again.
        row = (
            await db.execute(
                text(
                    """
                    WITH readme_touches AS (
                        SELECT c.project_id,
                               MAX(c.committed_at) AS last_readme_touch
                        FROM git_commit c
                        WHERE c.files_changed IS NOT NULL
                          AND EXISTS (
                              SELECT 1 FROM jsonb_array_elements_text(c.files_changed) f
                              WHERE LOWER(f.value) LIKE '%readme%'
                          )
                        GROUP BY c.project_id
                    ),
                    commits_since AS (
                        SELECT c.project_id, COUNT(*) AS n
                        FROM git_commit c
                        JOIN readme_touches r ON r.project_id = c.project_id
                        WHERE c.committed_at > r.last_readme_touch
                        GROUP BY c.project_id
                    )
                    SELECT p.name AS project_name,
                           cs.n AS commits_since,
                           rt.last_readme_touch,
                           EXTRACT(DAY FROM (NOW() - rt.last_readme_touch))::int
                               AS days_since
                    FROM commits_since cs
                    JOIN readme_touches rt ON rt.project_id = cs.project_id
                    JOIN dev_project p ON p.id = cs.project_id
                    WHERE cs.n >= 100
                      AND rt.last_readme_touch < NOW() - INTERVAL '90 days'
                    ORDER BY cs.n DESC
                    LIMIT 1
                    """
                )
            )
        ).mappings().first()

        if not row:
            return None

        facts = {
            "project_name": row["project_name"],
            "commits_since_readme": int(row["commits_since"]),
            "days_since_readme": int(row["days_since"] or 0),
        }
        summary = (
            f"{facts['project_name']}: {facts['commits_since_readme']} commits "
            f"since the README was last touched {facts['days_since_readme']} days ago"
        )
        return TriggerContext(
            trigger_name="readme_neglect",
            severity="observation",
            facts=facts,
            summary=summary,
            dedup_key=f"readme_neglect:{row['project_name']}",
        )


@register_trigger("readme_resurrection", cooldown_seconds=24 * 60 * 60)
class ReadmeResurrectionTrigger(Trigger):
    """The README was finally updated after >90 days of neglect.

    Grudging acknowledgment — the user did the thing the System has been
    quietly observing they were not doing.
    """

    async def check(
        self, db: AsyncSession, user_id: str
    ) -> Optional[TriggerContext]:
        row = (
            await db.execute(
                text(
                    """
                    WITH readme_commits AS (
                        SELECT c.project_id, c.committed_at, c.message,
                               LAG(c.committed_at) OVER (
                                   PARTITION BY c.project_id
                                   ORDER BY c.committed_at
                               ) AS prev_touch
                        FROM git_commit c
                        WHERE c.files_changed IS NOT NULL
                          AND EXISTS (
                              SELECT 1 FROM jsonb_array_elements_text(c.files_changed) f
                              WHERE LOWER(f.value) LIKE '%readme%'
                          )
                    )
                    SELECT p.name AS project_name,
                           rc.committed_at,
                           EXTRACT(DAY FROM (rc.committed_at - rc.prev_touch))::int
                               AS gap_days
                    FROM readme_commits rc
                    JOIN dev_project p ON p.id = rc.project_id
                    WHERE rc.prev_touch IS NOT NULL
                      AND rc.committed_at > NOW() - INTERVAL '2 days'
                      AND rc.committed_at - rc.prev_touch > INTERVAL '90 days'
                    ORDER BY rc.committed_at DESC
                    LIMIT 1
                    """
                )
            )
        ).mappings().first()

        if not row:
            return None

        facts = {
            "project_name": row["project_name"],
            "gap_days": int(row["gap_days"] or 0),
        }
        summary = (
            f"{facts['project_name']}'s README updated after "
            f"{facts['gap_days']} days of silence"
        )
        return TriggerContext(
            trigger_name="readme_resurrection",
            severity="grudging",
            facts=facts,
            summary=summary,
            dedup_key=f"readme_resurrection:{row['project_name']}",
        )


@register_trigger("hyperfocus_achieved", cooldown_seconds=4 * 60 * 60)
class HyperfocusAchievedTrigger(Trigger):
    """Same file shows up in 5+ commits within a 2-hour window.

    The classic 'staring at the same problem until it submits' pattern.
    The spec says 20 edits/2h but our commit cadence is sparser than the
    spec's assumption — 5 is the equivalent signal here.
    """

    async def check(
        self, db: AsyncSession, user_id: str
    ) -> Optional[TriggerContext]:
        row = (
            await db.execute(
                text(
                    """
                    SELECT f.value AS file_path, COUNT(*) AS n,
                           MIN(c.committed_at) AS first_commit,
                           MAX(c.committed_at) AS last_commit
                    FROM git_commit c,
                         LATERAL jsonb_array_elements_text(c.files_changed) f
                    WHERE c.files_changed IS NOT NULL
                      AND c.committed_at > NOW() - INTERVAL '2 hours'
                    GROUP BY f.value
                    HAVING COUNT(*) >= 5
                    ORDER BY n DESC
                    LIMIT 1
                    """
                )
            )
        ).mappings().first()

        if not row:
            return None

        # Pull just the filename for readability — full paths get noisy.
        file_path = row["file_path"]
        short = file_path.rsplit("/", 1)[-1] if "/" in file_path else file_path

        facts = {
            "file_path": file_path,
            "file_name": short,
            "edit_count": int(row["n"]),
            "window_minutes": 120,
        }
        summary = (
            f"{short} edited {facts['edit_count']} times in the last 2 hours"
        )
        return TriggerContext(
            trigger_name="hyperfocus_achieved",
            severity="achievement",
            facts=facts,
            summary=summary,
            dedup_key=f"hyperfocus:{file_path}",
        )


@register_trigger("parallel_universes", cooldown_seconds=12 * 60 * 60)
class ParallelUniversesTrigger(Trigger):
    """3+ distinct projects received commits in the same hour.

    Context-switching as a lifestyle. Quiet roast — the System has watched
    other engineers do this and observed the pattern's consequences.
    """

    async def check(
        self, db: AsyncSession, user_id: str
    ) -> Optional[TriggerContext]:
        row = (
            await db.execute(
                text(
                    """
                    SELECT
                        COUNT(DISTINCT c.project_id) AS project_count,
                        ARRAY_AGG(DISTINCT p.name ORDER BY p.name) AS project_names,
                        COUNT(*) AS commit_count
                    FROM git_commit c
                    JOIN dev_project p ON p.id = c.project_id
                    WHERE c.committed_at > NOW() - INTERVAL '1 hour'
                    """
                )
            )
        ).mappings().first()

        if not row or int(row["project_count"] or 0) < 3:
            return None

        names = list(row["project_names"] or [])
        facts = {
            "project_count": int(row["project_count"]),
            "project_names": names,
            "commit_count": int(row["commit_count"]),
        }
        summary = (
            f"{facts['project_count']} projects touched in the last hour: "
            f"{', '.join(names)}"
        )
        # Dedup by the sorted project tuple — same set within cooldown is
        # the same pattern.
        proj_sig = ",".join(names)
        return TriggerContext(
            trigger_name="parallel_universes",
            severity="observation",
            facts=facts,
            summary=summary,
            dedup_key=f"parallel_universes:{proj_sig}",
        )


@register_trigger("revert_cascade", cooldown_seconds=24 * 60 * 60)
class RevertCascadeTrigger(Trigger):
    """A Revert commit followed within 24h by another commit on the same
    branch — a tell that the revert was a tactical retreat, not a final word."""

    async def check(
        self, db: AsyncSession, user_id: str
    ) -> Optional[TriggerContext]:
        row = (
            await db.execute(
                text(
                    """
                    WITH reverts AS (
                        SELECT id, project_id, branch, sha, committed_at, message
                        FROM git_commit
                        WHERE message ILIKE 'revert%'
                          AND committed_at > NOW() - INTERVAL '3 days'
                    )
                    SELECT r.sha AS revert_sha,
                           r.branch,
                           r.committed_at AS revert_at,
                           r.message AS revert_msg,
                           p.name AS project_name,
                           f.sha AS followup_sha,
                           f.message AS followup_msg,
                           EXTRACT(EPOCH FROM (f.committed_at - r.committed_at))/3600
                               AS hours_after
                    FROM reverts r
                    JOIN dev_project p ON p.id = r.project_id
                    JOIN git_commit f
                      ON f.project_id = r.project_id
                     AND f.branch = r.branch
                     AND f.committed_at > r.committed_at
                     AND f.committed_at < r.committed_at + INTERVAL '24 hours'
                    ORDER BY r.committed_at DESC
                    LIMIT 1
                    """
                )
            )
        ).mappings().first()

        if not row:
            return None

        facts = {
            "project_name": row["project_name"],
            "branch": row["branch"],
            "revert_message": (row["revert_msg"] or "")[:120],
            "followup_message": (row["followup_msg"] or "")[:120],
            "hours_between": round(float(row["hours_after"] or 0), 1),
        }
        summary = (
            f"{facts['project_name']}/{facts['branch']}: revert followed by "
            f"another commit {facts['hours_between']}h later"
        )
        return TriggerContext(
            trigger_name="revert_cascade",
            severity="roast",
            facts=facts,
            summary=summary,
            dedup_key=f"revert_cascade:{row['revert_sha'][:12]}",
        )
