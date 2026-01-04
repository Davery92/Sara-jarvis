"""
Daily Brief Service - Main orchestration
Provides the primary interface for the daily brief system.
"""
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List

from .compiler import BriefCompiler, BRIEFS_DIR
from .moment_layer import MomentLayer
from .prompts import BOOTSTRAP_STABLE_LAYER

logger = logging.getLogger(__name__)


class DailyBriefService:
    """
    Main service for the Daily Brief system.
    Orchestrates layer updates, compilation, and bootstrapping.
    """

    def __init__(self):
        self.briefs_dir = BRIEFS_DIR
        self.compiler = BriefCompiler()
        self.moment_layer = MomentLayer()

        # LLM settings - use LOCAL_LLM_URL for heavy synthesis, falls back to local Ollama
        self.fast_model = "gpt-oss:20b"
        self.full_model = "gpt-oss:120b"
        # Use dedicated local LLM for synthesis (not the configured OPENAI_BASE_URL which may be Gemini)
        self.llm_base_url = os.environ.get("LOCAL_LLM_URL", "http://100.104.68.115:11434/v1")

    def _ensure_user_dir(self, user_id: str) -> Path:
        """Ensure user's complete directory structure exists."""
        user_dir = self.briefs_dir / user_id
        (user_dir / "layers").mkdir(parents=True, exist_ok=True)
        (user_dir / "compiled").mkdir(parents=True, exist_ok=True)
        (user_dir / "archive").mkdir(parents=True, exist_ok=True)
        return user_dir

    def _get_layer_path(self, user_id: str, layer_name: str) -> Path:
        """Get path to a specific layer file."""
        return self.briefs_dir / user_id / "layers" / f"{layer_name}.md"

    def _read_layer(self, user_id: str, layer_name: str) -> str:
        """Read layer content."""
        path = self._get_layer_path(user_id, layer_name)
        if path.exists():
            return path.read_text()
        return ""

    def _write_layer(self, user_id: str, layer_name: str, content: str):
        """Write layer content."""
        self._ensure_user_dir(user_id)
        path = self._get_layer_path(user_id, layer_name)
        path.write_text(content)
        logger.debug(f"📝 Wrote {layer_name} layer for user {user_id[:8]}")

    async def _call_llm(self, prompt: str, model: str = None) -> str:
        """Call LLM for text generation."""
        import httpx

        model = model or self.fast_model
        url = f"{self.llm_base_url}/chat/completions"

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "You are Sara, a personal AI assistant."},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 2000,
            "temperature": 0.7
        }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            raise

    async def get_compiled_brief(self, user_id: str) -> str:
        """
        Get the compiled brief for injection into context.
        This is the main entry point for chat endpoints.
        """
        self._ensure_user_dir(user_id)

        # Check if we need to bootstrap (no stable layer)
        stable_path = self._get_layer_path(user_id, "stable")
        if not stable_path.exists():
            logger.info(f"No stable layer found for user {user_id[:8]}, attempting bootstrap")
            # We'll do lazy bootstrap during first request
            # For now, return minimal brief
            moment = self._read_layer(user_id, "moment")
            if moment:
                return f"---\n## My Understanding of David\n---\n\n{moment}"
            return ""

        # Compile the brief
        return self.compiler.compile(user_id)

    async def update_moment(
        self,
        user_id: str,
        current_message: str,
        conversation_id: Optional[str],
        db,
        conversation_turn_count: int = 0
    ):
        """
        Update the moment layer with current conversation state.
        Called at the start of every chat request.
        """
        await self.moment_layer.update(
            user_id=user_id,
            current_message=current_message,
            conversation_id=conversation_id,
            db=db,
            conversation_turn_count=conversation_turn_count
        )

    async def bootstrap_stable_layer(self, user_id: str, db) -> bool:
        """
        Bootstrap the stable layer from existing conversation history.
        Uses 120B model for deep synthesis.
        Returns True if successful.
        """
        try:
            # Import models here to avoid circular imports
            from app.main_simple import Episode

            logger.info(f"🚀 Bootstrapping stable layer for user {user_id[:8]}")

            # Get recent episodes (last 30 days or up to 200)
            thirty_days_ago = datetime.utcnow() - timedelta(days=30)
            episodes = db.query(Episode).filter(
                Episode.user_id == user_id,
                Episode.created_at >= thirty_days_ago,
                Episode.role.in_(["user", "assistant"])
            ).order_by(Episode.created_at.desc()).limit(200).all()

            if not episodes:
                logger.warning(f"No episodes found for user {user_id[:8]}, skipping bootstrap")
                return False

            # Format episodes for prompt
            episode_texts = []
            for ep in reversed(episodes):  # Chronological order
                role = "David" if ep.role == "user" else "Sara"
                timestamp = ep.created_at.strftime("%Y-%m-%d %H:%M")
                episode_texts.append(f"[{timestamp}] {role}: {ep.content[:500]}")

            episodes_str = "\n".join(episode_texts[-100:])  # Last 100 for context window

            # Try to get reflections and hypotheses if they exist
            reflections_str = ""
            hypotheses_str = ""

            try:
                from app.models.cognitive import SaraReflection, Hypothesis

                reflections = db.query(SaraReflection).filter(
                    SaraReflection.user_id == user_id
                ).order_by(SaraReflection.created_at.desc()).limit(10).all()

                if reflections:
                    reflections_str = "\n".join([
                        f"- {r.reflection_type}: {r.content}" for r in reflections
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

            # Build prompt
            prompt = BOOTSTRAP_STABLE_LAYER.format(
                episodes=episodes_str,
                reflections=reflections_str or "No reflections recorded yet.",
                hypotheses=hypotheses_str or "No confirmed hypotheses yet."
            )

            # Call 120B model for synthesis
            stable_content = await self._call_llm(prompt, model=self.full_model)

            # Write stable layer
            self._write_layer(user_id, "stable", stable_content)

            logger.info(f"✅ Successfully bootstrapped stable layer for user {user_id[:8]}")
            return True

        except Exception as e:
            logger.error(f"Bootstrap failed for user {user_id[:8]}: {e}")
            return False

    async def append_to_day_layer(
        self,
        user_id: str,
        summary: str,
        timestamp: Optional[datetime] = None
    ):
        """
        Append a conversation summary to the day layer.
        Called after conversation gaps or explicitly.
        """
        timestamp = timestamp or datetime.now()
        time_str = timestamp.strftime("%H:%M")

        current_day = self._read_layer(user_id, "day")

        # Get current date header
        date_header = f"## Today ({timestamp.strftime('%A, %B %d')})\n\n"

        if not current_day:
            # Start fresh day layer
            new_content = f"{date_header}**{time_str}**\n{summary}\n"
        else:
            # Check if we need a new date header (day rollover)
            if date_header not in current_day:
                # New day - archive old and start fresh
                await self._archive_day_layer(user_id)
                new_content = f"{date_header}**{time_str}**\n{summary}\n"
            else:
                # Append to existing day
                new_content = f"{current_day}\n**{time_str}**\n{summary}\n"

        self._write_layer(user_id, "day", new_content)

    async def _archive_day_layer(self, user_id: str):
        """Archive the current day layer before starting a new day."""
        current_day = self._read_layer(user_id, "day")
        if not current_day:
            return

        # Determine archive date from content or use yesterday
        archive_date = datetime.now() - timedelta(days=1)

        # Create archive path
        archive_dir = self.briefs_dir / user_id / "archive" / archive_date.strftime("%Y/%m/%d")
        archive_dir.mkdir(parents=True, exist_ok=True)

        archive_path = archive_dir / "day.md"
        archive_path.write_text(current_day)

        logger.info(f"📦 Archived day layer for user {user_id[:8]} to {archive_date.date()}")

    def get_brief_stats(self, user_id: str) -> Dict:
        """Get statistics about the user's brief system."""
        return self.compiler.get_stats(user_id)

    def has_stable_layer(self, user_id: str) -> bool:
        """Check if user has a stable layer (is bootstrapped)."""
        return self._get_layer_path(user_id, "stable").exists()

    async def ensure_initialized(self, user_id: str, db) -> bool:
        """
        Ensure the brief system is initialized for this user.
        Bootstraps if needed.
        Returns True if system is ready.
        """
        self._ensure_user_dir(user_id)

        # Check if we need to bootstrap
        if not self.has_stable_layer(user_id):
            return await self.bootstrap_stable_layer(user_id, db)

        return True


# Singleton instance
daily_brief_service = DailyBriefService()
