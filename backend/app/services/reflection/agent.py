"""
ReflectionAgent - The meta-cognitive agent that audits and improves the system.

Orchestrates all reflection components:
- Consolidation auditing
- Pattern detection
- Proposal generation
- Uncertainty handling
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .scratchpad import ReflectionScratchpad, ObservationType, get_reflection_scratchpad
from .consolidation_auditor import ConsolidationAuditor, ConsolidationAuditResult
from .pattern_detector import PatternDetector, DetectedPattern
from .proposal_generator import PromptProposalGenerator, PromptProposal

logger = logging.getLogger(__name__)

# Single-user system — same default every other reflection-adjacent service
# (prediction_engine._DAVID, kernel.DEFAULT_USER_ID) uses.
_DAVID_USER_ID = "64f37c56-85cb-4590-8de9-adfc17d343ed"


@dataclass
class ReflectionCycleResult:
    """Results of a complete reflection cycle."""
    cycle_start: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    consolidation_audit: Optional[ConsolidationAuditResult] = None
    outcomes_assessed: int = 0
    patterns_detected: List[DetectedPattern] = field(default_factory=list)
    proposals_generated: List[PromptProposal] = field(default_factory=list)
    uncertainties_flagged: int = 0
    # Arc 4.1: "dreaming scores every resolved prediction nightly and
    # updates per-domain confidence" — compute_calibration's report
    # (total_resolved, overall_by_bucket, by_domain_bucket), not a new
    # store. None if the prediction table has nothing resolved yet.
    prediction_calibration: Optional[Dict[str, Any]] = None
    # Arc 4.2: the rolling consolidated self-story dreaming just wrote this
    # cycle (None if nothing happened yet to consolidate). The persisted
    # story lives in sara_journal (entry_type='self_story'); this is just
    # this cycle's copy for the caller/logs.
    self_story: Optional[str] = None
    # Arc 4.5: the rolling consolidated understanding of David dreaming
    # just updated this cycle. Persisted in sara_journal
    # (entry_type='theory_of_david'); this is this cycle's copy for the
    # caller/logs.
    theory_of_david: Optional[str] = None
    duration_seconds: float = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "cycle_start": self.cycle_start.isoformat(),
            "consolidation_audit": {
                "total_raw": self.consolidation_audit.total_raw,
                "total_kept": self.consolidation_audit.total_kept,
                "missed_items": len(self.consolidation_audit.missed_items),
                "accuracy_score": self.consolidation_audit.accuracy_score,
            } if self.consolidation_audit else None,
            "outcomes_assessed": self.outcomes_assessed,
            "patterns_detected": len(self.patterns_detected),
            "proposals_generated": len(self.proposals_generated),
            "uncertainties_flagged": self.uncertainties_flagged,
            "prediction_calibration": self.prediction_calibration,
            "self_story": self.self_story,
            "theory_of_david": self.theory_of_david,
            "duration_seconds": self.duration_seconds,
        }


class ReflectionAgent:
    """
    The meta-cognitive agent that audits and improves Sara's system.

    Responsibilities:
    1. AUDIT: Compare what consolidation kept vs. what was available
    2. ANALYZE: Review actions and their outcomes
    3. DETECT: Look for patterns - recurring errors, successful approaches
    4. PROPOSE: When confident, propose specific fixes
    5. LEARN: Flag uncertainties for David's input
    """

    def __init__(
        self,
        db: AsyncSession,
        scratchpad: ReflectionScratchpad,
        consolidation_auditor: ConsolidationAuditor,
        pattern_detector: PatternDetector,
        proposal_generator: PromptProposalGenerator,
    ):
        self.db = db
        self.scratchpad = scratchpad
        self.consolidation_auditor = consolidation_auditor
        self.pattern_detector = pattern_detector
        self.proposal_generator = proposal_generator

    async def run_reflection_cycle(self) -> ReflectionCycleResult:
        """
        Run a complete reflection cycle.

        Called periodically by the Celery worker.
        """
        cycle_start = datetime.now(timezone.utc)
        result = ReflectionCycleResult(cycle_start=cycle_start)

        logger.info("Starting reflection cycle")

        try:
            # 1. Audit recent consolidation
            audit_window_start = cycle_start - timedelta(hours=4)
            consolidation_audit = await self.consolidation_auditor.audit_consolidation_window(
                audit_window_start, cycle_start
            )
            await self.consolidation_auditor.record_audit_observations(consolidation_audit)
            result.consolidation_audit = consolidation_audit
            logger.info(f"Consolidation audit complete: {consolidation_audit.total_raw} raw, "
                       f"{len(consolidation_audit.missed_items)} misses")

            # 2. Review pending action outcomes
            pending_outcomes = await self._get_pending_outcome_assessments()
            for pending in pending_outcomes:
                outcome = await self._assess_outcome(pending)
                await self._record_outcome(pending["action_id"], outcome)
            result.outcomes_assessed = len(pending_outcomes)
            logger.info(f"Assessed {len(pending_outcomes)} pending outcomes")

            # 3. Detect patterns
            patterns = await self.pattern_detector.detect_patterns()
            for pattern in patterns:
                await self._record_or_update_pattern(pattern)
            result.patterns_detected = patterns
            logger.info(f"Detected {len(patterns)} patterns")

            # 4. Generate proposals for significant patterns
            high_confidence_patterns = [p for p in patterns if p.confidence >= 0.7]
            proposals = await self.proposal_generator.generate_proposals_from_patterns(
                high_confidence_patterns
            )
            for proposal in proposals:
                await self.proposal_generator.submit_proposal(proposal)
            result.proposals_generated = proposals
            logger.info(f"Generated {len(proposals)} proposals")

            # 5. Check for situations needing clarification
            uncertain_items = await self._identify_uncertain_items()
            for item in uncertain_items:
                await self._flag_uncertainty(item)
            result.uncertainties_flagged = len(uncertain_items)
            logger.info(f"Flagged {len(uncertain_items)} uncertainties")

            # 6. Score prediction calibration (Arc 4.1) — grades whether
            # stated confidence matched actual hit-rate, per domain and
            # confidence bucket, over predictions resolved since the last
            # cycle window. Read-only scoring; compute_calibration doesn't
            # write anything itself, so a failure here can't corrupt state —
            # still isolated so it never blocks the rest of the cycle.
            try:
                from app.services.prediction_engine import compute_calibration
                result.prediction_calibration = await compute_calibration(self.db)
                logger.info(
                    f"Prediction calibration: {result.prediction_calibration['total_resolved']} "
                    f"resolved, {result.prediction_calibration['overall_by_bucket']}"
                )
            except Exception as e:
                logger.warning(f"Prediction calibration scoring failed (non-critical): {e}")

            # 7. Fold today's chapter into the rolling self-story (Arc 4.2)
            # — "yesterday's self constrains today's." sara_journal_service
            # uses a sync Session (db.execute without await) throughout,
            # unlike self.db here (an AsyncSession, needed for compute_
            # calibration above) — a separate sync session for just this
            # step, matching the pattern other services already use when
            # they need to call a sync-session service from async code.
            try:
                from app.db.session import SessionLocal
                from app.services.sara_journal_service import sara_journal
                with SessionLocal() as sync_db:
                    result.self_story = await sara_journal.write_self_story(sync_db, _DAVID_USER_ID)
                if result.self_story:
                    logger.info(f"Self-story updated ({len(result.self_story)} chars)")
            except Exception as e:
                logger.warning(f"Self-story consolidation failed (non-critical): {e}")

            # 8. Fold fresh substrate into the theory-of-David document
            # (Arc 4.5) — same sync-session shape as step 7, since it's the
            # same sara_journal_service.
            try:
                from app.db.session import SessionLocal
                from app.services.sara_journal_service import sara_journal
                with SessionLocal() as sync_db:
                    result.theory_of_david = await sara_journal.write_theory_of_david(sync_db, _DAVID_USER_ID)
                if result.theory_of_david:
                    logger.info(f"Theory-of-David updated ({len(result.theory_of_david)} chars)")
            except Exception as e:
                logger.warning(f"Theory-of-David consolidation failed (non-critical): {e}")

            # 9. Self-assess this reflection cycle
            await self._self_assess(result)

        except Exception as e:
            logger.error(f"Reflection cycle failed: {e}", exc_info=True)
            raise

        result.duration_seconds = (datetime.now(timezone.utc) - cycle_start).total_seconds()
        logger.info(f"Reflection cycle complete in {result.duration_seconds:.1f}s")

        return result

    async def _get_pending_outcome_assessments(self) -> List[Dict]:
        """Get actions that need outcome assessment."""
        result = await self.db.execute(
            text("""
                SELECT action_id, user_id, action_type, action_content,
                       context_snapshot, created_at
                FROM action_log
                WHERE outcome_status = 'pending'
                AND created_at < NOW() - INTERVAL '30 minutes'
                ORDER BY created_at
                LIMIT 50
            """)
        )

        return [
            {
                "action_id": str(row[0]),
                "user_id": row[1],
                "action_type": row[2],
                "action_content": row[3],
                "context_snapshot": row[4],
                "created_at": row[5],
            }
            for row in result.fetchall()
        ]

    async def _assess_outcome(self, pending: Dict) -> Dict:
        """
        Assess the outcome of an action.

        Uses heuristics based on:
        - Subsequent user interactions
        - Error signals
        - Time since action
        """
        action_id = pending["action_id"]
        created_at = pending["created_at"]

        # Check for follow-up user messages that might indicate success/failure
        followup_result = await self.db.execute(
            text("""
                SELECT COUNT(*) as count,
                       MIN(created_at) as first_followup
                FROM episode
                WHERE user_id = :user_id
                AND created_at > :action_time
                AND created_at < :action_time + INTERVAL '1 hour'
                AND (content ILIKE '%thank%' OR content ILIKE '%great%' OR content ILIKE '%perfect%')
            """),
            {
                "user_id": pending["user_id"],
                "action_time": created_at,
            }
        )
        positive_signals = followup_result.fetchone()[0] or 0

        # Check for negative signals
        negative_result = await self.db.execute(
            text("""
                SELECT COUNT(*)
                FROM episode
                WHERE user_id = :user_id
                AND created_at > :action_time
                AND created_at < :action_time + INTERVAL '1 hour'
                AND (content ILIKE '%wrong%' OR content ILIKE '%error%' OR
                     content ILIKE '%not what%' OR content ILIKE '%incorrect%')
            """),
            {
                "user_id": pending["user_id"],
                "action_time": created_at,
            }
        )
        negative_signals = negative_result.fetchone()[0] or 0

        # Determine outcome
        if positive_signals > 0 and negative_signals == 0:
            return {
                "status": "success",
                "details": f"Positive user signals detected ({positive_signals})",
                "source": "implicit"
            }
        elif negative_signals > 0:
            return {
                "status": "failure",
                "details": f"Negative user signals detected ({negative_signals})",
                "source": "implicit"
            }
        else:
            # After timeout, assume partial success if no negative signals.
            # created_at comes from a naive `timestamp` column (naive UTC); compare
            # naive-to-naive to avoid offset-naive/aware subtraction errors.
            if created_at is not None and created_at.tzinfo is not None:
                created_at = created_at.astimezone(timezone.utc).replace(tzinfo=None)
            hours_elapsed = (datetime.now(timezone.utc).replace(tzinfo=None) - created_at).total_seconds() / 3600
            if hours_elapsed > 24:
                return {
                    "status": "unknown",
                    "details": "No signals detected within timeout",
                    "source": "timeout"
                }
            else:
                # Keep as pending for now
                return None

    async def _record_outcome(self, action_id: str, outcome: Optional[Dict]) -> None:
        """Record the assessed outcome of an action."""
        if not outcome:
            return

        await self.db.execute(
            text("""
                UPDATE action_log
                SET outcome_status = :status,
                    outcome_details = :details,
                    outcome_recorded_at = NOW(),
                    feedback_source = :source
                WHERE action_id = :action_id
            """),
            {
                "action_id": action_id,
                "status": outcome["status"],
                "details": outcome["details"],
                "source": outcome["source"],
            }
        )
        await self.db.commit()

        # Record observation
        await self.scratchpad.add_observation(
            observation_type=ObservationType.ACTION_OUTCOME,
            subject_agent="sara",
            summary=f"Action outcome: {outcome['status']}",
            details={
                "action_id": action_id,
                "outcome": outcome["status"],
                "outcome_details": outcome["details"],
                "source": outcome["source"],
            },
            confidence=0.7 if outcome["source"] == "implicit" else 0.5,
            evidence_refs={"action_id": action_id},
        )

    async def _record_or_update_pattern(self, pattern: DetectedPattern) -> None:
        """Record a new pattern or update an existing one."""
        # Check for similar existing patterns
        existing = await self.scratchpad.get_active_patterns(
            pattern_type=pattern.pattern_type,
        )

        for existing_pattern in existing:
            if self._patterns_match(pattern, existing_pattern):
                # Update existing pattern
                await self.pattern_detector.update_existing_pattern(
                    existing_pattern.pattern_id,
                    pattern.supporting_observations,
                )
                return

        # Create new pattern
        await self.pattern_detector.persist_pattern(pattern)

    def _patterns_match(self, new: DetectedPattern, existing) -> bool:
        """Check if a new pattern matches an existing one."""
        # Same type and affected agent/dimension
        if new.affected_agent != existing.affected_agent:
            return False
        if new.affected_dimension != existing.affected_dimension:
            return False

        # Similar description (simple word overlap)
        new_words = set(new.description.lower().split())
        existing_words = set(existing.description.lower().split())
        overlap = len(new_words & existing_words) / min(len(new_words), len(existing_words))

        return overlap > 0.5

    async def _identify_uncertain_items(self) -> List[Dict]:
        """Identify situations that need David's clarification."""
        uncertain_items = []

        # Look for low-confidence observations
        low_confidence = await self.scratchpad.get_recent_observations(
            days=3,
        )

        for obs in low_confidence:
            if obs.confidence < 0.3 and not obs.resolved:
                uncertain_items.append({
                    "context": obs.summary,
                    "what_happened": obs.details.get("outcome_details", "") if obs.details else "",
                    "possible_causes": ["Unknown - needs clarification"],
                    "question_for_david": f"What should I learn from this observation: {obs.summary}?",
                    "observation_id": obs.observation_id,
                })

        return uncertain_items[:3]  # Limit to 3 per cycle

    async def _flag_uncertainty(self, item: Dict) -> None:
        """Flag an uncertain situation for David."""
        await self.scratchpad.add_observation(
            observation_type=ObservationType.UNCERTAINTY_FLAG,
            summary=f"Need clarification: {item['question_for_david'][:100]}",
            details={
                "context": item["context"],
                "what_happened": item["what_happened"],
                "possible_causes": item["possible_causes"],
                "question": item["question_for_david"],
            },
            confidence=0.0,  # Explicitly uncertain
        )

        # Send notification to David
        try:
            from app.services.notification_service import get_notification_service
            notification_service = get_notification_service()
            await notification_service.notify_uncertainty(item)
        except Exception as e:
            logger.warning(f"Failed to notify about uncertainty: {e}")

        logger.info(f"Flagged uncertainty: {item['question_for_david'][:50]}")

    async def _self_assess(self, result: ReflectionCycleResult) -> None:
        """The reflection agent reflects on its own performance."""
        meaningful_patterns = [p for p in result.patterns_detected if p.confidence >= 0.6]

        if meaningful_patterns:
            logger.info(f"Identified {len(meaningful_patterns)} meaningful patterns")

        if result.proposals_generated:
            logger.info(f"Generated {len(result.proposals_generated)} proposals for review")


# Factory function for creating ReflectionAgent
async def get_reflection_agent(db: AsyncSession) -> ReflectionAgent:
    """Create and return a configured ReflectionAgent."""
    scratchpad = await get_reflection_scratchpad(db)
    auditor = ConsolidationAuditor(db, scratchpad)
    detector = PatternDetector(db, scratchpad)
    generator = PromptProposalGenerator(db)

    return ReflectionAgent(
        db=db,
        scratchpad=scratchpad,
        consolidation_auditor=auditor,
        pattern_detector=detector,
        proposal_generator=generator,
    )
