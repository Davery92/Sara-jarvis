"""
ConsolidationAuditor - Audits consolidation decisions.

Compares what consolidation kept vs. what was available,
assesses quality of decisions, and records findings.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .scratchpad import ReflectionScratchpad, ObservationType

logger = logging.getLogger(__name__)


@dataclass
class MissedItem:
    """An item that was discarded but turned out to be needed."""
    raw_entry_id: str
    content_preview: str
    relevance_score: float
    discard_reason: str
    action_that_needed_it: Optional[str] = None


@dataclass
class UnnecessaryKeep:
    """An item that was kept but never used."""
    segment_id: str
    content_preview: str
    relevance_score: float


@dataclass
class ConsolidationAuditResult:
    """Results of auditing a consolidation window."""
    window_start: datetime
    window_end: datetime
    total_raw: int = 0
    total_kept: int = 0
    total_discarded: int = 0
    missed_items: List[MissedItem] = field(default_factory=list)
    unnecessary_keeps: List[UnnecessaryKeep] = field(default_factory=list)
    accuracy_score: float = 1.0  # 0-1 score


class ConsolidationAuditor:
    """
    Audits consolidation decisions by comparing raw input to consolidated output.

    Identifies:
    - Missed items: Important things that were discarded
    - Unnecessary keeps: Things kept that were never used
    - Accuracy score: Overall consolidation quality
    """

    def __init__(self, db: AsyncSession, scratchpad: ReflectionScratchpad):
        self.db = db
        self.scratchpad = scratchpad

    async def audit_consolidation_window(
        self,
        window_start: datetime,
        window_end: datetime,
    ) -> ConsolidationAuditResult:
        """
        Audit a specific time window of consolidation.

        Compares what was in the raw buffer, what was kept, what was discarded,
        and what Sara actually needed during that time.
        """
        result = ConsolidationAuditResult(
            window_start=window_start,
            window_end=window_end,
        )

        # Get consolidation run stats for this window
        run_result = await self.db.execute(
            text("""
                SELECT
                    SUM(raw_entries_processed) as total_raw,
                    SUM(entries_kept) as total_kept,
                    SUM(entries_discarded) as total_discarded
                FROM consolidation_runs
                WHERE window_start >= :start AND window_end <= :end
                AND status = 'completed'
            """),
            {"start": window_start, "end": window_end}
        )
        run_row = run_result.fetchone()

        if run_row and run_row[0]:
            result.total_raw = int(run_row[0])
            result.total_kept = int(run_row[1] or 0)
            result.total_discarded = int(run_row[2] or 0)

        # Get discarded items
        discards_result = await self.db.execute(
            text("""
                SELECT raw_entry_id, content_preview, relevance_score, discard_reason
                FROM consolidation_discards
                WHERE created_at >= :start AND created_at <= :end
                ORDER BY relevance_score DESC
                LIMIT 100
            """),
            {"start": window_start, "end": window_end}
        )
        discards = discards_result.fetchall()

        # Get Sara's actions during this window to see what context was needed
        actions_result = await self.db.execute(
            text("""
                SELECT action_id, action_type, action_content, context_snapshot
                FROM action_log
                WHERE created_at >= :start AND created_at <= :end
                AND outcome_status IN ('success', 'partial')
                ORDER BY created_at
            """),
            {"start": window_start, "end": window_end}
        )
        actions = actions_result.fetchall()

        # Check for missed items - discards that were related to successful actions
        for discard in discards:
            raw_id, content, score, reason = discard
            content_lower = (content or "").lower()

            # Check if any action content overlaps with discarded content
            for action in actions:
                action_content = (action[2] or "").lower()
                action_context = action[3] or {}

                # Simple overlap check - could be made smarter with embeddings
                if self._content_overlaps(content_lower, action_content, action_context):
                    result.missed_items.append(MissedItem(
                        raw_entry_id=raw_id,
                        content_preview=content[:200] if content else "",
                        relevance_score=score or 0,
                        discard_reason=reason,
                        action_that_needed_it=str(action[0]),
                    ))
                    break

        # Calculate accuracy score
        if result.total_raw > 0:
            miss_penalty = len(result.missed_items) * 0.1
            result.accuracy_score = max(0, 1.0 - miss_penalty)
        else:
            result.accuracy_score = 1.0  # No data to audit

        return result

    def _content_overlaps(
        self,
        discarded_content: str,
        action_content: str,
        action_context: Dict,
    ) -> bool:
        """Check if discarded content was relevant to an action."""
        if not discarded_content or not action_content:
            return False

        # Simple keyword overlap check
        # Extract significant words (>3 chars, not common)
        discard_words = set(
            w for w in discarded_content.split()
            if len(w) > 3 and w not in {"the", "and", "for", "that", "with", "this", "from"}
        )
        action_words = set(
            w for w in action_content.split()
            if len(w) > 3
        )

        # Check for overlap
        overlap = discard_words & action_words
        if len(overlap) >= 2:  # At least 2 significant words in common
            return True

        # Check context references
        context_str = str(action_context).lower()
        for word in discard_words:
            if word in context_str:
                return True

        return False

    async def record_audit_observations(
        self,
        audit_result: ConsolidationAuditResult,
    ) -> None:
        """Record audit findings to reflection scratchpad."""
        # Record missed items as observations
        for missed in audit_result.missed_items:
            await self.scratchpad.add_observation(
                observation_type=ObservationType.CONSOLIDATION_AUDIT,
                subject_agent="consolidation",
                subject_dimension="accuracy",
                summary=f"Missed important item: {missed.content_preview[:100]}",
                details={
                    "action_that_needed_it": missed.action_that_needed_it,
                    "discard_reason": missed.discard_reason,
                    "relevance_score_was": missed.relevance_score,
                },
                confidence=0.8,
                evidence_refs={
                    "raw_entry_id": missed.raw_entry_id,
                    "action_id": missed.action_that_needed_it,
                }
            )

        # Record summary observation
        await self.scratchpad.add_observation(
            observation_type=ObservationType.CONSOLIDATION_AUDIT,
            subject_agent="consolidation",
            summary=f"Audit: {audit_result.total_kept}/{audit_result.total_raw} kept, "
                    f"{len(audit_result.missed_items)} misses, "
                    f"accuracy={audit_result.accuracy_score:.2f}",
            details={
                "window_start": audit_result.window_start.isoformat(),
                "window_end": audit_result.window_end.isoformat(),
                "total_raw": audit_result.total_raw,
                "total_kept": audit_result.total_kept,
                "total_discarded": audit_result.total_discarded,
                "missed_count": len(audit_result.missed_items),
                "accuracy_score": audit_result.accuracy_score,
            },
            confidence=0.9,
        )

        logger.info(
            f"Consolidation audit complete: {audit_result.total_raw} raw, "
            f"{len(audit_result.missed_items)} misses, "
            f"accuracy={audit_result.accuracy_score:.2f}"
        )

    async def get_recent_audit_summary(self, days: int = 7) -> Dict[str, Any]:
        """Get a summary of recent consolidation audits."""
        observations = await self.scratchpad.get_recent_observations(
            days=days,
            observation_type=ObservationType.CONSOLIDATION_AUDIT,
        )

        total_misses = 0
        total_audits = 0
        avg_accuracy = []

        for obs in observations:
            if obs.details:
                if "missed_count" in obs.details:
                    total_misses += obs.details["missed_count"]
                    total_audits += 1
                if "accuracy_score" in obs.details:
                    avg_accuracy.append(obs.details["accuracy_score"])

        return {
            "total_audits": total_audits,
            "total_misses": total_misses,
            "avg_accuracy": sum(avg_accuracy) / len(avg_accuracy) if avg_accuracy else 1.0,
            "observations": len(observations),
        }
