"""
Day Layer - Daily conversation accumulation
Updates after conversation gaps and hourly during active hours.
Uses 20B model for summarization.
"""
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict

from .prompts import DAY_LAYER_SUMMARIZE, DAY_LAYER_CONSOLIDATE

logger = logging.getLogger(__name__)

# Base directory for brief files
BRIEFS_DIR = Path("/home/david/jarvis/data/briefs")

# Token/char limits
MAX_DAY_LAYER_CHARS = 4000  # ~1000 tokens
CONSOLIDATION_THRESHOLD = 3000  # Trigger consolidation above this


class DayLayer:
    """
    Accumulates today's conversation context.
    Updates after session gaps and consolidates hourly.
    """

    def __init__(self):
        self.briefs_dir = BRIEFS_DIR
        self.fast_model = "qwen3-coder-next"
        self.llm_base_url = os.environ.get("OPENAI_BASE_URL", "http://100.104.68.115:11434/v1")

    def _ensure_user_dir(self, user_id: str) -> Path:
        """Ensure user's brief directory structure exists."""
        user_dir = self.briefs_dir / user_id / "layers"
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir

    def _get_layer_path(self, user_id: str) -> Path:
        """Get path to day layer file."""
        return self._ensure_user_dir(user_id) / "day.md"

    def _read_layer(self, user_id: str) -> str:
        """Read current day layer content."""
        path = self._get_layer_path(user_id)
        if path.exists():
            return path.read_text()
        return ""

    def _write_layer(self, user_id: str, content: str):
        """Write day layer content."""
        path = self._get_layer_path(user_id)
        path.write_text(content)
        logger.debug(f"📝 Wrote day layer for user {user_id[:8]}")

    async def _call_llm(self, prompt: str) -> str:
        """Call 20B model for summarization."""
        import httpx

        url = f"{self.llm_base_url}/chat/completions"

        payload = {
            "model": self.fast_model,
            "messages": [
                {"role": "system", "content": "You are Sara, writing private notes about your conversations with David."},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 500,
            "temperature": 0.7
        }

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            raise

    def _get_date_header(self, timestamp: Optional[datetime] = None) -> str:
        """Get date header for day layer."""
        timestamp = timestamp or datetime.now()
        return f"## Today ({timestamp.strftime('%A, %B %d')})\n\n"

    def _extract_date_from_content(self, content: str) -> Optional[str]:
        """Extract date from day layer header if present."""
        # Look for "## Today (Wednesday, November 27)" pattern
        import re
        match = re.search(r'## Today \(([^)]+)\)', content)
        if match:
            return match.group(1)
        return None

    async def append_session_summary(
        self,
        user_id: str,
        summary: str,
        timestamp: Optional[datetime] = None
    ):
        """
        Append a conversation summary to the day layer.
        Called after session gaps are detected.
        """
        timestamp = timestamp or datetime.now()
        time_str = timestamp.strftime("%H:%M")

        current_day = self._read_layer(user_id)
        date_header = self._get_date_header(timestamp)

        # Check if we need a new day (date changed)
        current_date_str = self._extract_date_from_content(current_day)
        new_date_str = timestamp.strftime('%A, %B %d')

        if not current_day:
            # Start fresh day layer
            new_content = f"{date_header}**{time_str}**\n{summary}\n"
        elif current_date_str and current_date_str != new_date_str:
            # New day - archive old and start fresh
            await self._archive_and_reset(user_id, current_day)
            new_content = f"{date_header}**{time_str}**\n{summary}\n"
        else:
            # Append to existing day
            new_content = f"{current_day}\n**{time_str}**\n{summary}\n"

        self._write_layer(user_id, new_content)
        logger.info(f"📅 Appended session summary to day layer for user {user_id[:8]}")

        # Check if consolidation needed
        if len(new_content) > CONSOLIDATION_THRESHOLD:
            logger.info(f"📦 Day layer exceeds threshold, scheduling consolidation")
            # Don't block - let consolidation happen in background
            # The hourly scheduler will handle it

    async def summarize_conversation(
        self,
        user_id: str,
        conversation_episodes: List[Dict],
        timestamp: Optional[datetime] = None
    ) -> str:
        """
        Generate a summary of conversation episodes using 20B model.
        Returns the summary text.
        """
        if not conversation_episodes:
            return ""

        # Format conversation for prompt
        conversation_text = []
        for ep in conversation_episodes:
            role = "David" if ep.get("role") == "user" else "Sara"
            content = ep.get("content", "")[:500]  # Limit each message
            conversation_text.append(f"{role}: {content}")

        conversation_str = "\n".join(conversation_text[-20:])  # Last 20 messages

        prompt = DAY_LAYER_SUMMARIZE.format(conversation=conversation_str)

        try:
            summary = await self._call_llm(prompt)
            return summary.strip()
        except Exception as e:
            logger.error(f"Failed to summarize conversation: {e}")
            # Return a basic fallback
            topic_hint = conversation_text[0][:100] if conversation_text else "general discussion"
            return f"Had a conversation about {topic_hint}..."

    async def consolidate(self, user_id: str) -> bool:
        """
        Consolidate the day layer if it's getting too long.
        Uses 20B model to compress while preserving key information.
        Returns True if consolidation was performed.
        """
        current_day = self._read_layer(user_id)

        if len(current_day) <= CONSOLIDATION_THRESHOLD:
            logger.debug(f"Day layer for {user_id[:8]} doesn't need consolidation")
            return False

        logger.info(f"📦 Consolidating day layer for user {user_id[:8]} ({len(current_day)} chars)")

        prompt = DAY_LAYER_CONSOLIDATE.format(current_day=current_day)

        try:
            consolidated = await self._call_llm(prompt)

            # Preserve the date header
            date_header = self._get_date_header()
            if not consolidated.startswith("##"):
                consolidated = f"{date_header}{consolidated}"

            self._write_layer(user_id, consolidated)
            logger.info(f"✅ Consolidated day layer: {len(current_day)} -> {len(consolidated)} chars")
            return True

        except Exception as e:
            logger.error(f"Failed to consolidate day layer: {e}")
            return False

    async def _archive_and_reset(self, user_id: str, content: str):
        """Archive the current day layer and reset for new day."""
        from .archiver import archiver
        await archiver.archive_day_layer(user_id, content)
        logger.info(f"📦 Archived day layer for user {user_id[:8]}")

    async def end_of_day_summary(self, user_id: str) -> str:
        """
        Generate an end-of-day summary for the context layer.
        Called at 11 PM by scheduler.
        """
        current_day = self._read_layer(user_id)

        if not current_day:
            return ""

        # The day layer already contains summaries, just return it
        # The context layer will use this to update active threads
        return current_day

    def read(self, user_id: str) -> str:
        """Read current day layer content."""
        return self._read_layer(user_id)

    def needs_consolidation(self, user_id: str) -> bool:
        """Check if day layer needs consolidation."""
        content = self._read_layer(user_id)
        return len(content) > CONSOLIDATION_THRESHOLD


# Singleton instance
day_layer = DayLayer()
