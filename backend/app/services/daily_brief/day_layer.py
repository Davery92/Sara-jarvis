"""
Day Layer - Daily conversation accumulation
Updates after conversation gaps and hourly during active hours.
Uses 20B model for summarization.
"""
import json
import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict

from app.core.timezone import now as local_now, USER_TIMEZONE

from .prompts import DAY_LAYER_SUMMARIZE, DAY_LAYER_CONSOLIDATE
from .status_tracker import brief_status_tracker

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
        from app.core.llm_config import llm_config
        self.fast_model = llm_config.fast_model
        # bg lane — OPENAI_BASE_URL is the 1-slot chat lane in the backend process.
        self.llm_base_url = llm_config.bg_primary_url

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

    def _write_layer(self, user_id: str, content: str, effective_date: Optional[datetime] = None):
        """Write day layer content and its freshness metadata sidecar.

        `effective_date` is the local calendar day this content describes
        (chat harness repair Phase 3). Defaults to "now" — callers that
        archive/reset for a new day should pass the new day's timestamp
        explicitly rather than relying on the default.
        """
        path = self._get_layer_path(user_id)
        path.write_text(content)
        self._write_meta(user_id, effective_date or local_now())
        logger.debug(f"📝 Wrote day layer for user {user_id[:8]}")

    def _get_meta_path(self, user_id: str) -> Path:
        return self._ensure_user_dir(user_id) / "day.meta.json"

    def _write_meta(self, user_id: str, effective_date: datetime):
        meta = {
            "effective_date": effective_date.strftime("%Y-%m-%d"),
            "generated_at": local_now().isoformat(),
            "timezone": str(USER_TIMEZONE),
        }
        try:
            self._get_meta_path(user_id).write_text(json.dumps(meta))
        except Exception as e:
            logger.warning(f"Failed to write day layer metadata for {user_id[:8]}: {e}")

    def _read_meta(self, user_id: str) -> Optional[Dict]:
        path = self._get_meta_path(user_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except Exception as e:
            logger.warning(f"Failed to read day layer metadata for {user_id[:8]}: {e}")
            return None

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
        timestamp = timestamp or local_now()
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
        timestamp = timestamp or local_now()
        time_str = timestamp.strftime("%H:%M")

        current_day = self._read_layer(user_id)
        date_header = self._get_date_header(timestamp)

        # Check if we need a new day (date changed). Prefer the structured
        # metadata sidecar; fall back to parsing the heading for files
        # written before it existed.
        is_new_day = self._is_new_day(user_id, current_day, timestamp)

        if not current_day:
            # Start fresh day layer
            new_content = f"{date_header}**{time_str}**\n{summary}\n"
        elif is_new_day:
            # New day - archive old and start fresh
            await self._archive_and_reset(user_id, current_day)
            new_content = f"{date_header}**{time_str}**\n{summary}\n"
        else:
            # Append to existing day
            new_content = f"{current_day}\n**{time_str}**\n{summary}\n"

        self._write_layer(user_id, new_content, effective_date=timestamp)
        brief_status_tracker.record_event(user_id, "day_append", timestamp=timestamp)
        logger.info(f"📅 Appended session summary to day layer for user {user_id[:8]}")

    def _is_new_day(self, user_id: str, current_day: str, timestamp: datetime) -> bool:
        """True when `current_day`'s content describes a calendar day other
        than `timestamp`'s. Structured metadata first; heading text as a
        back-compat fallback for files written before the sidecar existed."""
        if not current_day:
            return True

        meta = self._read_meta(user_id)
        if meta and meta.get("effective_date"):
            return meta["effective_date"] != timestamp.strftime("%Y-%m-%d")

        current_date_str = self._extract_date_from_content(current_day)
        new_date_str = timestamp.strftime('%A, %B %d')
        return bool(current_date_str) and current_date_str != new_date_str

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

            # Preserve the day this content actually describes, not "now" —
            # consolidation can run after the calendar day has rolled over.
            meta = self._read_meta(user_id)
            effective_date = local_now()
            if meta and meta.get("effective_date"):
                try:
                    effective_date = datetime.strptime(
                        meta["effective_date"], "%Y-%m-%d"
                    ).replace(tzinfo=effective_date.tzinfo)
                except ValueError:
                    pass

            date_header = self._get_date_header(effective_date)
            if not consolidated.startswith("##"):
                consolidated = f"{date_header}{consolidated}"

            self._write_layer(user_id, consolidated, effective_date=effective_date)
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
        """Read current day layer content, with no freshness check.

        Kept for callers that intentionally want the raw file (the archiver,
        the scheduler's own rollover logic). Chat/context consumption should
        use `read_fresh`/`read_fresh_text` instead so a stale "Today" heading
        never reaches the model (chat harness repair Phase 3).
        """
        return self._read_layer(user_id)

    def read_fresh(self, user_id: str, now: Optional[datetime] = None) -> Dict:
        """Freshness-checked read for chat/context consumption.

        Returns {"content", "is_stale", "effective_date", "label"}:
        - label="current": today's content, returned unchanged.
        - label="historical": content from an earlier day. The heading is
          rewritten to an explicit "As of <date> (historical)" label instead
          of ever presenting yesterday's "## Today (...)" as today's.
        - label="empty": nothing has been written yet.

        This never mutates files or archives anything — rollover/archival
        still happens lazily via append_session_summary when a new summary
        actually lands. A read must be safe to call any number of times
        without racing a concurrent writer.
        """
        now = now or local_now()
        content = self._read_layer(user_id)
        if not content:
            return {"content": "", "is_stale": False, "effective_date": None, "label": "empty"}

        meta = self._read_meta(user_id)
        today_str = now.strftime("%Y-%m-%d")

        if meta and meta.get("effective_date"):
            effective_date = meta["effective_date"]
            is_stale = effective_date != today_str
        else:
            # Back-compat: file predates the metadata sidecar. Fall back to
            # parsing the heading; if it can't be parsed, assume current
            # rather than mislabeling a file we can't actually date.
            current_date_str = self._extract_date_from_content(content)
            new_date_str = now.strftime('%A, %B %d')
            is_stale = bool(current_date_str) and current_date_str != new_date_str
            effective_date = None

        if not is_stale:
            return {
                "content": content,
                "is_stale": False,
                "effective_date": effective_date or today_str,
                "label": "current",
            }

        label_date = effective_date or "an earlier day"
        relabeled = re.sub(
            r'^##\s*Today\s*\([^)]*\)',
            f"## As of {label_date} (historical — not today)",
            content,
            count=1,
        )
        if relabeled == content:
            # No "## Today (...)" heading to rewrite; prefix an explicit
            # label instead so the content still can't read as today's.
            relabeled = f"*(As of {label_date} — historical, not today)*\n\n{content}"

        return {"content": relabeled, "is_stale": True, "effective_date": effective_date, "label": "historical"}

    def read_fresh_text(self, user_id: str, now: Optional[datetime] = None) -> str:
        """Convenience wrapper: just the freshness-corrected content string."""
        return self.read_fresh(user_id, now)["content"]

    def clear(self, user_id: str):
        """Clear day layer content after archival."""
        self._write_layer(user_id, "")

    def needs_consolidation(self, user_id: str) -> bool:
        """Check if day layer needs consolidation."""
        content = self._read_layer(user_id)
        return len(content) > CONSOLIDATION_THRESHOLD


# Singleton instance
day_layer = DayLayer()
