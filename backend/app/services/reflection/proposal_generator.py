"""
PromptProposalGenerator - Generates prompt modification proposals.

Translates detected patterns into actionable prompt/config changes
with approval workflow.
"""

import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .scratchpad import PatternType
from .pattern_detector import DetectedPattern
from app.services.karma import get_karma_service, KarmaEvent

logger = logging.getLogger(__name__)


@dataclass
class PromptProposal:
    """A proposal to modify a prompt or configuration."""
    proposal_id: Optional[int] = None
    target_agent: str = ""
    target_prompt_section: Optional[str] = None
    current_content: Optional[str] = None
    proposed_content: Optional[str] = None
    reasoning: str = ""
    supporting_pattern_ids: List[str] = None
    expected_improvement: Optional[str] = None
    status: str = "pending"
    karma_state_at_proposal: Optional[Dict] = None

    def __post_init__(self):
        if self.supporting_pattern_ids is None:
            self.supporting_pattern_ids = []


class PromptProposalGenerator:
    """
    Generates prompt modification proposals based on detected patterns.

    For each pattern type, generates appropriate changes:
    - Consolidation issues -> Adjust thresholds
    - Recurring errors -> Add guidance
    - Timing patterns -> Adjust schedules
    """

    # Minimum confidence to generate a proposal
    MIN_CONFIDENCE = 0.7

    def __init__(self, db: AsyncSession):
        self.db = db

    async def generate_proposals_from_patterns(
        self,
        patterns: List[DetectedPattern],
    ) -> List[PromptProposal]:
        """Convert patterns into concrete prompt modification proposals."""
        proposals = []

        for pattern in patterns:
            if pattern.confidence < self.MIN_CONFIDENCE:
                continue

            proposal = None

            if pattern.pattern_type == PatternType.RECURRING_ERROR:
                proposal = await self._propose_error_prevention(pattern)
            elif pattern.pattern_type == PatternType.TIMING_PATTERN:
                proposal = await self._propose_timing_adjustment(pattern)
            elif pattern.pattern_type == PatternType.CONSOLIDATION_ISSUE:
                proposal = await self._propose_consolidation_change(pattern)
            elif pattern.pattern_type == PatternType.CALIBRATION_ISSUE:
                proposal = await self._propose_calibration_fix(pattern)

            if proposal:
                proposals.append(proposal)

        return proposals

    async def _propose_error_prevention(
        self,
        pattern: DetectedPattern,
    ) -> Optional[PromptProposal]:
        """Propose changes to prevent recurring errors."""
        # Extract action type from description
        action_type = "unknown"
        if "'" in pattern.description:
            start = pattern.description.index("'") + 1
            end = pattern.description.index("'", start)
            action_type = pattern.description[start:end]

        return PromptProposal(
            target_agent="sara",
            target_prompt_section=f"action_guidance.{action_type}",
            current_content=None,  # New guidance
            proposed_content=f"When performing '{action_type}' actions, be especially careful. "
                           f"This action type has had {pattern.observation_count} failures recently. "
                           f"Consider: verifying prerequisites, providing clearer feedback, "
                           f"and handling edge cases explicitly.",
            reasoning=f"Pattern detected: {pattern.description}\n"
                     f"Based on {pattern.observation_count} observations "
                     f"with {pattern.confidence:.0%} confidence.\n"
                     f"Proposed fix: Add explicit guidance to reduce error rate.",
            supporting_pattern_ids=[],  # Will be filled by persist
            expected_improvement=f"Reduce failures in '{action_type}' actions",
        )

    async def _propose_timing_adjustment(
        self,
        pattern: DetectedPattern,
    ) -> Optional[PromptProposal]:
        """Propose timing-related configuration changes."""
        # Extract hour from description
        hour = "unknown"
        if ":" in pattern.description:
            for part in pattern.description.split():
                if ":" in part and part[:2].isdigit():
                    hour = part.split(":")[0]
                    break

        return PromptProposal(
            target_agent="sara",
            target_prompt_section=f"timing.quiet_hours",
            current_content=None,
            proposed_content=f"Consider hour {hour}:00 as a potentially problematic time. "
                           f"Adjust notification thresholds or defer non-urgent actions.",
            reasoning=f"Pattern detected: {pattern.description}\n"
                     f"Based on {pattern.observation_count} observations "
                     f"with {pattern.confidence:.0%} confidence.\n"
                     f"Proposed fix: Adjust behavior during this time period.",
            supporting_pattern_ids=[],
            expected_improvement=f"Reduce issues during hour {hour}:00",
        )

    async def _propose_consolidation_change(
        self,
        pattern: DetectedPattern,
    ) -> Optional[PromptProposal]:
        """Propose changes to consolidation configuration."""
        # Get current consolidation config
        config_result = await self.db.execute(
            text("""
                SELECT config_value FROM consolidation_config
                WHERE config_key = 'consolidation_settings'
                LIMIT 1
            """)
        )
        config_row = config_result.fetchone()
        current_config = config_row[0] if config_row else {}

        current_threshold = current_config.get("relevance_threshold", 0.3)

        # Determine adjustment direction
        if "missing" in pattern.description.lower() or "misses" in pattern.description.lower():
            # Too aggressive, lower threshold
            new_threshold = max(0.1, current_threshold - 0.05)
            change_description = "Lower threshold to catch more potentially important items"
        else:
            # Default: raise threshold slightly
            new_threshold = min(0.8, current_threshold + 0.05)
            change_description = "Raise threshold to reduce noise"

        return PromptProposal(
            target_agent="consolidation",
            target_prompt_section="config.relevance_threshold",
            current_content=str(current_threshold),
            proposed_content=str(new_threshold),
            reasoning=f"Pattern detected: {pattern.description}\n"
                     f"Based on {pattern.observation_count} observations "
                     f"with {pattern.confidence:.0%} confidence.\n"
                     f"Proposed fix: {change_description}",
            supporting_pattern_ids=[],
            expected_improvement=f"Improve consolidation accuracy by adjusting threshold from {current_threshold} to {new_threshold}",
        )

    async def _propose_calibration_fix(
        self,
        pattern: DetectedPattern,
    ) -> Optional[PromptProposal]:
        """Propose changes to address calibration issues."""
        return PromptProposal(
            target_agent="sara",
            target_prompt_section="calibration_guidance",
            current_content=None,
            proposed_content="When uncertain, express that uncertainty explicitly. "
                           "Avoid overconfident statements. "
                           "Consider using phrases like 'I think' or 'It seems' when appropriate.",
            reasoning=f"Pattern detected: {pattern.description}\n"
                     f"Based on {pattern.observation_count} observations "
                     f"with {pattern.confidence:.0%} confidence.\n"
                     f"Proposed fix: Add guidance for better calibration.",
            supporting_pattern_ids=[],
            expected_improvement="Improve calibration and reduce overconfidence",
        )

    async def submit_proposal(self, proposal: PromptProposal) -> int:
        """Submit a proposal for approval and notify David."""
        # Get current karma state
        karma_service = await get_karma_service(self.db)
        sara_karma = await karma_service.get_agent_karma("sara")
        karma_state = {
            "composite_score": sara_karma.composite_score if sara_karma else 50,
            "dimensions": {
                d.dimension_name: d.current_score
                for d in (sara_karma.dimensions if sara_karma else [])
            }
        }

        # Save proposal to database
        result = await self.db.execute(
            text("""
                INSERT INTO prompt_proposals
                (target_agent, target_prompt_section, current_content, proposed_content,
                 reasoning, supporting_pattern_ids, expected_improvement,
                 karma_state_at_proposal)
                VALUES
                (:agent, :section, :current, :proposed, :reasoning, :patterns,
                 :expected, :karma)
                RETURNING proposal_id
            """),
            {
                "agent": proposal.target_agent,
                "section": proposal.target_prompt_section,
                "current": proposal.current_content,
                "proposed": proposal.proposed_content,
                "reasoning": proposal.reasoning,
                "patterns": proposal.supporting_pattern_ids,
                "expected": proposal.expected_improvement,
                "karma": karma_state,
            }
        )
        await self.db.commit()

        proposal_id = result.fetchone()[0]
        proposal.proposal_id = proposal_id

        logger.info(f"Submitted proposal {proposal_id}: {proposal.target_agent}/{proposal.target_prompt_section}")

        # Send notification to David about new proposal
        try:
            from app.services.notification_service import get_notification_service
            notification_service = get_notification_service()
            await notification_service.notify_new_proposal(proposal)
        except Exception as e:
            logger.warning(f"Failed to notify about proposal {proposal_id}: {e}")

        return proposal_id

    async def process_approval(
        self,
        proposal_id: int,
        decision: str,  # "approved" or "rejected"
        notes: Optional[str] = None,
    ) -> None:
        """Process David's decision on a proposal."""
        await self.db.execute(
            text("""
                UPDATE prompt_proposals
                SET status = :status, reviewed_by = 'david',
                    reviewed_at = NOW(), review_notes = :notes
                WHERE proposal_id = :proposal_id
            """),
            {
                "status": decision,
                "proposal_id": proposal_id,
                "notes": notes,
            }
        )
        await self.db.commit()

        # Update reflection karma
        karma_service = await get_karma_service(self.db)

        if decision == "approved":
            await self._implement_proposal(proposal_id)
            await karma_service.record_event(KarmaEvent(
                agent_id="reflection",
                dimension_name="proposal_acceptance",
                delta=3.0,
                reason=f"Proposal {proposal_id} approved",
                evidence_type="feedback",
                evidence_ids=[str(proposal_id)],
            ))
        else:
            await karma_service.record_event(KarmaEvent(
                agent_id="reflection",
                dimension_name="proposal_acceptance",
                delta=-2.0,
                reason=f"Proposal {proposal_id} rejected: {notes}",
                evidence_type="feedback",
                evidence_ids=[str(proposal_id)],
            ))

    async def _implement_proposal(self, proposal_id: int) -> None:
        """Implement an approved proposal."""
        # Get proposal details
        result = await self.db.execute(
            text("""
                SELECT target_agent, target_prompt_section, proposed_content,
                       current_content, karma_state_at_proposal
                FROM prompt_proposals
                WHERE proposal_id = :proposal_id
            """),
            {"proposal_id": proposal_id}
        )
        row = result.fetchone()
        if not row:
            return

        agent, section, proposed, current, karma_at_proposal = row

        # Save version history
        await self.db.execute(
            text("""
                INSERT INTO prompt_versions
                (agent, section, content, reason, proposal_id)
                VALUES (:agent, :section, :content, :reason, :proposal_id)
            """),
            {
                "agent": agent,
                "section": section or "unknown",
                "content": current or "",
                "reason": f"Before proposal {proposal_id}",
                "proposal_id": proposal_id,
            }
        )

        # Implement the change based on target
        if agent == "consolidation" and section == "config.relevance_threshold":
            # Update consolidation config
            await self.db.execute(
                text("""
                    UPDATE consolidation_config
                    SET config_value = jsonb_set(
                        config_value,
                        '{relevance_threshold}',
                        :new_value::jsonb
                    ),
                    updated_at = NOW(),
                    updated_by = 'reflection'
                    WHERE config_key = 'consolidation_settings'
                """),
                {"new_value": proposed}
            )

        # Mark proposal as implemented
        karma_service = await get_karma_service(self.db)
        current_karma = await karma_service.get_agent_karma(agent)

        await self.db.execute(
            text("""
                UPDATE prompt_proposals
                SET status = 'implemented', implemented_at = NOW(),
                    karma_state_at_implementation = :karma
                WHERE proposal_id = :proposal_id
            """),
            {
                "proposal_id": proposal_id,
                "karma": {
                    "composite_score": current_karma.composite_score if current_karma else 50,
                }
            }
        )

        await self.db.commit()
        logger.info(f"Implemented proposal {proposal_id}")

    async def get_pending_proposals(self) -> List[Dict]:
        """Get all pending proposals for review."""
        result = await self.db.execute(
            text("""
                SELECT proposal_id, target_agent, target_prompt_section,
                       current_content, proposed_content, reasoning,
                       expected_improvement, created_at
                FROM prompt_proposals
                WHERE status = 'pending'
                ORDER BY created_at
            """)
        )

        proposals = []
        for row in result.fetchall():
            proposals.append({
                "proposal_id": row[0],
                "target_agent": row[1],
                "target_prompt_section": row[2],
                "current_content": row[3],
                "proposed_content": row[4],
                "reasoning": row[5],
                "expected_improvement": row[6],
                "created_at": row[7].isoformat() if row[7] else None,
            })

        return proposals
