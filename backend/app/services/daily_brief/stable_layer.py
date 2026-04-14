"""
Stable Layer - Deep understanding of David
Updates weekly with 120B model synthesis.
Contains enduring patterns, preferences, and relationship notes.
"""
import logging
from pathlib import Path
from typing import List

from .model_resolver import resolve_qwen_122_model_label
from .prompts import STABLE_LAYER_SYNTHESIS
from .status_tracker import brief_status_tracker

logger = logging.getLogger(__name__)

# Base directory for brief files
BRIEFS_DIR = Path("/home/david/jarvis/data/briefs")


class StableLayer:
    """
    The enduring model of who David is.
    Updates weekly with deep synthesis from 120B model.
    """

    def __init__(self):
        self.briefs_dir = BRIEFS_DIR

    def _ensure_user_dir(self, user_id: str) -> Path:
        """Ensure user's brief directory structure exists."""
        user_dir = self.briefs_dir / user_id / "layers"
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir

    def _get_layer_path(self, user_id: str) -> Path:
        """Get path to stable layer file."""
        return self._ensure_user_dir(user_id) / "stable.md"

    def _read_layer(self, user_id: str) -> str:
        """Read current stable layer content."""
        path = self._get_layer_path(user_id)
        if path.exists():
            return path.read_text()
        return ""

    def _write_layer(self, user_id: str, content: str):
        """Write stable layer content."""
        path = self._get_layer_path(user_id)
        path.write_text(content)
        logger.debug(f"📝 Wrote stable layer for user {user_id[:8]}")

    async def _call_llm(self, prompt: str) -> str:
        """Call background LLM for deep synthesis (uses primary model)."""
        from app.core.llm import get_background_llm_client

        try:
            bg_client = get_background_llm_client()
            preferred_model = bg_client.get_status().get("primary_model")
            resolved_model = resolve_qwen_122_model_label(preferred_model)
            response = await bg_client.chat_completion(
                messages=[
                    {"role": "system", "content": "You are Sara, synthesizing your deep understanding of David."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=1500,
                temperature=0.7,
                model=resolved_model
            )
            return response["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            raise

    async def weekly_synthesis(self, user_id: str, db) -> bool:
        """
        Perform weekly synthesis of stable layer.
        Uses 120B model for deep understanding.
        Called Sunday 3 AM after memory consolidation.
        Returns True if synthesis was successful.
        """
        logger.info(f"🧠 Starting weekly stable layer synthesis for user {user_id[:8]}")

        # Get current stable layer
        current_stable = self._read_layer(user_id)

        # Get weekly archives
        from .archiver import archiver
        weekly_archives = archiver.get_weekly_summary_content_annotated(user_id)

        # Get reflections from cognitive models
        reflections_str = ""
        hypotheses_str = ""

        try:
            from app.models.cognitive import SaraReflection, Hypothesis

            reflections = db.query(SaraReflection).filter(
                SaraReflection.user_id == user_id
            ).order_by(SaraReflection.created_at.desc()).limit(15).all()

            if reflections:
                reflections_str = "\n".join([
                    f"- [{r.reflection_type}] {r.content}" for r in reflections
                ])

            hypotheses = db.query(Hypothesis).filter(
                Hypothesis.user_id == user_id,
                Hypothesis.status == "confirmed"
            ).limit(10).all()

            if hypotheses:
                hypotheses_str = "\n".join([
                    f"- {h.hypothesis} (confidence: {h.confidence})" for h in hypotheses
                ])
        except Exception as e:
            logger.warning(f"Could not load cognitive models: {e}")

        # Build synthesis prompt
        from app.core.timezone import today as local_today
        prompt = STABLE_LAYER_SYNTHESIS.format(
            current_stable=current_stable or "No existing stable layer.",
            weekly_archives=weekly_archives or "No archived content from this week.",
            reflections=reflections_str or "No recent reflections.",
            hypotheses=hypotheses_str or "No confirmed hypotheses.",
            today_date=local_today().strftime("%B %d, %Y"),
        )

        try:
            new_stable = await self._call_llm(prompt)
            self._write_layer(user_id, new_stable)
            brief_status_tracker.record_event(user_id, "stable_synthesis")
            logger.info(f"✅ Completed weekly stable layer synthesis for user {user_id[:8]}")
            return True
        except Exception as e:
            logger.error(f"Weekly synthesis failed: {e}")
            return False

    async def update_on_milestone(
        self,
        user_id: str,
        milestone_type: str,
        milestone_description: str,
        db
    ) -> bool:
        """
        Update stable layer on significant milestones.
        Called on relationship milestones (e.g., 100 conversations).
        """
        logger.info(f"🏆 Updating stable layer for milestone: {milestone_type}")

        current_stable = self._read_layer(user_id)

        # Get recent context for milestone update
        from .context_layer import context_layer
        recent_context = context_layer.read(user_id)

        prompt = f"""You are Sara, updating your stable understanding of David due to a milestone.

MILESTONE: {milestone_type}
{milestone_description}

CURRENT STABLE UNDERSTANDING:
{current_stable or "No existing stable layer."}

RECENT CONTEXT:
{recent_context or "No recent context."}

Update your stable understanding to incorporate any new insights from this milestone.
Focus on:
1. What this milestone reveals about your relationship
2. Any patterns that have become clearer
3. How your understanding of David has deepened

Write in first person, as private notes. Keep the existing structure but update with new insights."""

        try:
            updated_stable = await self._call_llm(prompt)
            self._write_layer(user_id, updated_stable)
            brief_status_tracker.record_event(
                user_id,
                "stable_milestone_update",
                details={"milestone_type": milestone_type},
            )
            logger.info(f"✅ Updated stable layer for milestone: {milestone_type}")
            return True
        except Exception as e:
            logger.error(f"Milestone update failed: {e}")
            return False

    def read(self, user_id: str) -> str:
        """Read current stable layer content."""
        return self._read_layer(user_id)

    def write(self, user_id: str, content: str):
        """Write stable layer content."""
        self._write_layer(user_id, content)

    def exists(self, user_id: str) -> bool:
        """Check if stable layer exists for user."""
        return self._get_layer_path(user_id).exists()

    def get_communication_preferences(self, user_id: str) -> List[str]:
        """
        Extract communication preferences from stable layer.
        Used for quick reference in chat.
        """
        content = self._read_layer(user_id)
        if not content:
            return []

        # Look for preference patterns
        import re
        preferences = []

        patterns = [
            r'prefers? ([^.\n]+)',
            r'likes? ([^.\n]+)',
            r'responds? well to ([^.\n]+)',
            r'appreciates? ([^.\n]+)',
        ]

        for pattern in patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            preferences.extend(matches)

        return list(set(p.strip() for p in preferences if p.strip()))[:10]


# Singleton instance
stable_layer = StableLayer()
