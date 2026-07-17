"""
Policy Candidate Service (Phase 3 — Cortana Evolution).

Generates reviewable policy candidates from dream insights and reflection outputs.
Candidates can be accepted (creating standing orders or automations) or rejected.

Guardrails:
  - Minimum confidence threshold 0.6 for candidate creation
  - Max 5 candidates per dream/reflection cycle
  - 24h cooldown per dedupe_key (title hash)
  - Candidates auto-expire after 14 days if not acted on (via retention task)
"""

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Guardrails
MIN_CONFIDENCE = 0.6
MAX_CANDIDATES_PER_CYCLE = 5
COOLDOWN_HOURS = 24

# Dream insight types that can generate candidates
CANDIDATE_INSIGHT_TYPES = {"behavioral_pattern", "emerging_pattern", "habit_pattern"}


class PolicyCandidateService:
    """Generates and manages policy candidates."""

    async def generate_from_dream_insights(
        self,
        db: AsyncSession,
        user_id: str,
        insights: List[Dict[str, Any]],
    ) -> List[str]:
        """
        Generate policy candidates from dream consolidation insights.

        Analyzes behavioral_pattern and emerging_pattern insights and maps them
        to standing_order or automation candidates.

        Returns list of created candidate IDs.
        """
        created_ids = []
        count = 0

        for insight in insights:
            if count >= MAX_CANDIDATES_PER_CYCLE:
                break

            insight_type = insight.get("insight_type") or insight.get("type", "")
            if insight_type not in CANDIDATE_INSIGHT_TYPES:
                continue

            confidence = insight.get("confidence", 0.5)
            if confidence < MIN_CONFIDENCE:
                continue

            title = insight.get("title") or insight.get("pattern", "")
            if not title:
                continue

            description = insight.get("description") or insight.get("content", "")
            source_id = insight.get("id") or insight.get("insight_id", "")

            # Determine candidate type based on insight
            candidate_type = "standing_order"
            proposed_config = self._map_insight_to_config(insight)

            dedupe_key = hashlib.sha256(title.encode()).hexdigest()[:32]

            # Check cooldown
            if await self._is_in_cooldown(db, user_id, dedupe_key):
                continue

            item_id = await self._create_candidate(
                db=db, user_id=user_id, title=title,
                description=description, candidate_type=candidate_type,
                source="dream", source_id=str(source_id),
                confidence=confidence, proposed_config=proposed_config,
                dedupe_key=dedupe_key,
            )
            if item_id:
                created_ids.append(item_id)
                count += 1

        if created_ids:
            logger.info(f"Generated {len(created_ids)} policy candidates from dream insights")
        return created_ids

    async def generate_from_reflection(
        self,
        db: AsyncSession,
        user_id: str,
        reflection_data: Dict[str, Any],
    ) -> List[str]:
        """
        Generate policy candidates from nightly reflection output.

        Returns list of created candidate IDs.
        """
        created_ids = []
        count = 0

        # Extract actionable suggestions from reflection
        suggestions = reflection_data.get("suggestions", [])
        patterns = reflection_data.get("patterns", [])
        items = suggestions + patterns

        for item in items:
            if count >= MAX_CANDIDATES_PER_CYCLE:
                break

            title = item.get("title") or item.get("suggestion", "")
            if not title:
                continue

            confidence = item.get("confidence", 0.5)
            if confidence < MIN_CONFIDENCE:
                continue

            description = item.get("description") or item.get("detail", "")
            dedupe_key = hashlib.sha256(title.encode()).hexdigest()[:32]

            if await self._is_in_cooldown(db, user_id, dedupe_key):
                continue

            candidate_type = item.get("candidate_type", "standing_order")
            proposed_config = item.get("proposed_config", {})

            item_id = await self._create_candidate(
                db=db, user_id=user_id, title=title,
                description=description, candidate_type=candidate_type,
                source="reflection", source_id=reflection_data.get("id", ""),
                confidence=confidence, proposed_config=proposed_config,
                dedupe_key=dedupe_key,
            )
            if item_id:
                created_ids.append(item_id)
                count += 1

        if created_ids:
            logger.info(f"Generated {len(created_ids)} policy candidates from reflection")
        return created_ids

    async def accept_candidate(
        self,
        db: AsyncSession,
        candidate_id: str,
        user_id: str,
    ) -> Dict[str, Any]:
        """
        Accept a candidate and create the corresponding standing order or automation.

        Returns dict with result info.
        """
        try:
            result = await db.execute(text("""
                SELECT id::text, title, description, candidate_type,
                       confidence, proposed_config, status
                FROM autonomy_policy_candidate
                WHERE id = :id::uuid AND user_id = :user_id
            """), {"id": candidate_id, "user_id": user_id})
            row = result.fetchone()
            if not row:
                return {"success": False, "error": "Candidate not found"}

            c_id, title, description, c_type, confidence, config, status = row
            if status != "new":
                return {"success": False, "error": f"Candidate already {status}"}

            result_id = None

            if c_type == "standing_order":
                result_id = await self._create_standing_order(db, user_id, title, description, config, confidence)
            elif c_type == "automation":
                result_id = await self._create_automation(db, user_id, title, description, config)

            # Mark as accepted
            await db.execute(text("""
                UPDATE autonomy_policy_candidate
                SET status = 'accepted', decided_at = NOW(), decided_action = 'accept',
                    result_id = :result_id, updated_at = NOW()
                WHERE id = :id::uuid
            """), {"id": candidate_id, "result_id": str(result_id) if result_id else None})

            return {"success": True, "candidate_id": c_id, "result_id": result_id, "type": c_type}
        except Exception as e:
            logger.error(f"Failed to accept candidate: {e}")
            return {"success": False, "error": str(e)}

    async def reject_candidate(
        self,
        db: AsyncSession,
        candidate_id: str,
        user_id: str,
    ) -> bool:
        """Reject a candidate."""
        try:
            result = await db.execute(text("""
                UPDATE autonomy_policy_candidate
                SET status = 'rejected', decided_at = NOW(), decided_action = 'reject',
                    updated_at = NOW()
                WHERE id = :id::uuid AND user_id = :user_id AND status = 'new'
            """), {"id": candidate_id, "user_id": user_id})
            return result.rowcount > 0
        except Exception as e:
            logger.error(f"Failed to reject candidate: {e}")
            return False

    async def list_candidates(
        self,
        db: AsyncSession,
        user_id: str,
        status: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """List policy candidates."""
        conditions = ["user_id = :user_id"]
        params: Dict[str, Any] = {"user_id": user_id, "limit": limit}

        if status:
            conditions.append("status = :status")
            params["status"] = status

        where = " AND ".join(conditions)

        try:
            result = await db.execute(text(f"""
                SELECT id::text, title, description, candidate_type, source,
                       source_id, status, confidence, proposed_config,
                       created_at, decided_at, decided_action, result_id
                FROM autonomy_policy_candidate
                WHERE {where}
                ORDER BY created_at DESC
                LIMIT :limit
            """), params)
            return [
                {
                    "id": r[0], "title": r[1], "description": r[2],
                    "candidate_type": r[3], "source": r[4], "source_id": r[5],
                    "status": r[6], "confidence": r[7], "proposed_config": r[8],
                    "created_at": r[9].isoformat() if r[9] else None,
                    "decided_at": r[10].isoformat() if r[10] else None,
                    "decided_action": r[11], "result_id": r[12],
                }
                for r in result.fetchall()
            ]
        except Exception as e:
            logger.error(f"Failed to list candidates: {e}")
            return []

    # ── Internal helpers ──

    async def _create_candidate(
        self,
        db: AsyncSession,
        user_id: str,
        title: str,
        description: str,
        candidate_type: str,
        source: str,
        source_id: str,
        confidence: float,
        proposed_config: Dict[str, Any],
        dedupe_key: str,
    ) -> Optional[str]:
        """Create a policy candidate with dedup."""
        try:
            result = await db.execute(text("""
                INSERT INTO autonomy_policy_candidate
                (user_id, title, description, candidate_type, source, source_id,
                 confidence, proposed_config, dedupe_key)
                VALUES (:user_id, :title, :description, :candidate_type, :source, :source_id,
                        :confidence, CAST(:proposed_config AS jsonb), :dedupe_key)
                ON CONFLICT (user_id, dedupe_key)
                    WHERE dedupe_key IS NOT NULL AND status = 'new'
                DO NOTHING
                RETURNING id::text
            """), {
                "user_id": user_id, "title": title, "description": description,
                "candidate_type": candidate_type, "source": source, "source_id": source_id,
                "confidence": confidence,
                "proposed_config": json.dumps(proposed_config, default=str),
                "dedupe_key": dedupe_key,
            })
            row = result.fetchone()
            return row[0] if row else None
        except Exception as e:
            logger.error(f"Failed to create policy candidate: {e}")
            return None

    async def _is_in_cooldown(self, db: AsyncSession, user_id: str, dedupe_key: str) -> bool:
        """Check if a candidate with this dedupe_key was created in the last 24 hours."""
        try:
            result = await db.execute(text("""
                SELECT 1 FROM autonomy_policy_candidate
                WHERE user_id = :user_id AND dedupe_key = :dedupe_key
                  AND created_at > NOW() - INTERVAL ':hours hours'
                LIMIT 1
            """.replace(":hours", str(COOLDOWN_HOURS))), {
                "user_id": user_id, "dedupe_key": dedupe_key,
            })
            return result.fetchone() is not None
        except Exception:
            return False

    def _map_insight_to_config(self, insight: Dict[str, Any]) -> Dict[str, Any]:
        """Map a dream insight to a standing order config."""
        pattern = insight.get("pattern", "") or insight.get("title", "")
        action = insight.get("suggested_action", "") or insight.get("recommendation", "")

        return {
            "description": pattern,
            "trigger_type": "pattern",
            "trigger_config": {
                "pattern": pattern,
                "source_insight": insight.get("insight_type", ""),
            },
            "action_type": "notification",
            "action_config": {
                "message": action or f"Pattern detected: {pattern}",
            },
        }

    async def _create_standing_order(
        self,
        db: AsyncSession,
        user_id: str,
        title: str,
        description: str,
        config: Dict[str, Any],
        confidence: float,
    ) -> Optional[int]:
        """Create a standing order from accepted candidate."""
        try:
            from app.services.standing_order_service import standing_order_service
            from app.db.session import SessionLocal
            sync_db = SessionLocal()
            try:
                result = standing_order_service.create_order(
                    db=sync_db,
                    user_id=user_id,
                    description=title,
                    trigger_type=config.get("trigger_type", "pattern"),
                    trigger_config=config.get("trigger_config", {}),
                    action_type=config.get("action_type", "notification"),
                    action_config=config.get("action_config", {}),
                    source="policy_candidate",
                )
                sync_db.commit()
                return result.get("id") if isinstance(result, dict) else None
            finally:
                sync_db.close()
        except Exception as e:
            logger.error(f"Failed to create standing order from candidate: {e}")
            return None

    async def _create_automation(
        self,
        db: AsyncSession,
        user_id: str,
        title: str,
        description: str,
        config: Dict[str, Any],
    ) -> Optional[str]:
        """Create an automation task from accepted candidate."""
        try:
            result = await db.execute(text("""
                INSERT INTO automation_task
                (user_id, name, description, schedule_definition,
                 actions, origin, risk_tier, status)
                VALUES (:user_id, :name, :description,
                        CAST(:schedule AS jsonb), CAST(:actions AS jsonb),
                        'policy_candidate', 1, 'draft')
                RETURNING id::text
            """), {
                "user_id": user_id,
                "name": title,
                "description": description,
                "schedule": json.dumps(config.get("schedule", {})),
                "actions": json.dumps(config.get("actions", [])),
            })
            row = result.fetchone()
            return row[0] if row else None
        except Exception as e:
            logger.error(f"Failed to create automation from candidate: {e}")
            return None


# Module-level singleton
policy_candidate_service = PolicyCandidateService()
