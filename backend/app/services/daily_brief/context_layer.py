"""
Context Layer - Active threads, predictions, and questions
Updates daily with analysis of active projects and Sara's questions about David.
Uses 20B model for analysis.
"""
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List

from .prompts import CONTEXT_LAYER_UPDATE

logger = logging.getLogger(__name__)

# Base directory for brief files
BRIEFS_DIR = Path("/home/david/jarvis/data/briefs")


class ContextLayer:
    """
    Tracks active threads, predictions, and questions Sara has about David.
    Updates daily at end of day and after dream processing.
    """

    def __init__(self):
        self.briefs_dir = BRIEFS_DIR
        # Background LLM settings are now managed by BackgroundLLMClient

    def _ensure_user_dir(self, user_id: str) -> Path:
        """Ensure user's brief directory structure exists."""
        user_dir = self.briefs_dir / user_id / "layers"
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir

    def _get_layer_path(self, user_id: str) -> Path:
        """Get path to context layer file."""
        return self._ensure_user_dir(user_id) / "context.md"

    def _read_layer(self, user_id: str) -> str:
        """Read current context layer content."""
        path = self._get_layer_path(user_id)
        if path.exists():
            return path.read_text()
        return ""

    def _write_layer(self, user_id: str, content: str):
        """Write context layer content."""
        path = self._get_layer_path(user_id)
        path.write_text(content)
        logger.debug(f"📝 Wrote context layer for user {user_id[:8]}")

    async def _call_llm(self, prompt: str) -> str:
        """Call background LLM for context analysis (uses fallback/fast model)."""
        from app.core.llm import get_background_llm_client

        try:
            bg_client = get_background_llm_client()
            # Use the fallback model (faster) for context analysis
            response = await bg_client.chat_completion(
                messages=[
                    {"role": "system", "content": "You are Sara, analyzing your active context about David."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=800,
                temperature=0.7,
                model="qwen3-coder-next"
            )
            return response["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            raise

    async def daily_update(self, user_id: str, day_content: str) -> bool:
        """
        Update context layer based on today's activity.
        Called at end of day (11 PM) after day layer consolidation.
        Returns True if update was successful.
        """
        previous_context = self._read_layer(user_id)

        from datetime import datetime
        from zoneinfo import ZoneInfo
        today_str = datetime.now(ZoneInfo("America/New_York")).strftime("%B %d, %Y")

        prompt = CONTEXT_LAYER_UPDATE.format(
            day_content=day_content or "No conversations today.",
            previous_context=previous_context or "No previous context.",
            dream_insights="No recent dream insights.",
            today_date=today_str,
        )

        try:
            new_context = await self._call_llm(prompt)
            self._write_layer(user_id, new_context)
            logger.info(f"📋 Updated context layer for user {user_id[:8]}")
            return True
        except Exception as e:
            logger.error(f"Failed to update context layer: {e}")
            return False

    async def update_from_dream_insights(
        self,
        user_id: str,
        daily_summary: str,
        themes: Optional[List[str]] = None,
        key_outcomes: Optional[List[str]] = None
    ) -> bool:
        """
        Update context layer with insights from dream processing.
        Called after nightly dream service completes.
        """
        previous_context = self._read_layer(user_id)

        # Format dream insights
        dream_insights_parts = []
        if themes:
            dream_insights_parts.append(f"**Themes identified:** {', '.join(themes)}")
        if key_outcomes:
            dream_insights_parts.append(f"**Key outcomes:** {', '.join(key_outcomes)}")
        if daily_summary:
            dream_insights_parts.append(f"**Summary:** {daily_summary}")

        dream_insights = "\n".join(dream_insights_parts) if dream_insights_parts else "No specific insights."

        # Get today's day layer for context
        from .day_layer import day_layer
        day_content = day_layer.read(user_id)

        prompt = CONTEXT_LAYER_UPDATE.format(
            day_content=day_content or "No day layer content.",
            previous_context=previous_context or "No previous context.",
            dream_insights=dream_insights
        )

        try:
            new_context = await self._call_llm(prompt)
            self._write_layer(user_id, new_context)
            logger.info(f"🌙 Updated context layer with dream insights for user {user_id[:8]}")
            return True
        except Exception as e:
            logger.error(f"Failed to update context layer from dreams: {e}")
            return False

    async def add_significant_event(
        self,
        user_id: str,
        event_description: str,
        event_type: str = "decision"
    ):
        """
        Add a significant event to the context layer immediately.
        Called when major decisions or events happen mid-conversation.
        """
        current_context = self._read_layer(user_id)

        # Simple append for immediate events
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        event_note = f"\n\n**[{event_type.upper()} - {timestamp}]** {event_description}"

        if current_context:
            new_content = current_context + event_note
        else:
            new_content = f"## Active Context\n\n{event_note}"

        self._write_layer(user_id, new_content)
        logger.info(f"⚡ Added significant event to context layer for user {user_id[:8]}")

    def read(self, user_id: str) -> str:
        """Read current context layer content."""
        return self._read_layer(user_id)

    def get_active_projects(self, user_id: str) -> List[str]:
        """
        Extract active project names from context layer.
        Simple pattern matching for common project indicators.
        """
        content = self._read_layer(user_id)
        if not content:
            return []

        # Look for project-like patterns
        import re
        projects = []

        # Match "working on X", "project: X", "active: X" patterns
        patterns = [
            r'working on ([^,\n.]+)',
            r'project[:\s]+([^,\n.]+)',
            r'Active project[s]?[:\s]+([^,\n.]+)',
            r'\*\*([^*]+)\*\* (?:project|work|feature)',
        ]

        for pattern in patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            projects.extend(matches)

        # Deduplicate and clean
        cleaned = list(set(p.strip() for p in projects if p.strip()))
        return cleaned[:10]  # Limit to 10

    def get_predictions(self, user_id: str) -> List[str]:
        """
        Extract predictions from context layer.
        """
        content = self._read_layer(user_id)
        if not content:
            return []

        # Look for prediction patterns
        import re
        predictions = []

        patterns = [
            r'predict[s]?[:\s]+([^.\n]+)',
            r'might need[:\s]+([^.\n]+)',
            r'probably[:\s]+([^.\n]+)',
            r'expect[s]?[:\s]+([^.\n]+)',
        ]

        for pattern in patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            predictions.extend(matches)

        return list(set(p.strip() for p in predictions if p.strip()))[:5]


# Singleton instance
context_layer = ContextLayer()
