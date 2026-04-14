"""
Daily Brief Service - Main orchestration
Provides the primary interface for the daily brief system.
"""
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict

from .compiler import BriefCompiler, BRIEFS_DIR
from .model_resolver import resolve_qwen_122_model_label
from .moment_layer import MomentLayer
from .prompts import BOOTSTRAP_STABLE_LAYER
from .status_tracker import brief_status_tracker

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

    async def _call_llm(self, prompt: str) -> str:
        """Call background LLM for stable-layer synthesis tasks."""
        from app.core.llm import get_background_llm_client

        try:
            bg_client = get_background_llm_client()
            preferred_model = bg_client.get_status().get("primary_model")
            resolved_model = resolve_qwen_122_model_label(preferred_model)
            response = await bg_client.chat_completion(
                messages=[
                    {"role": "system", "content": "You are Sara, a personal AI assistant."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=2000,
                temperature=0.7,
                model=resolved_model,
            )
            return response["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            raise

    async def get_compiled_brief(self, user_id: str) -> str:
        """
        Get the compiled brief for injection into context.
        This is the main entry point for chat endpoints.
        """
        self._ensure_user_dir(user_id)
        from .stable_layer import stable_layer

        # Check if we need to bootstrap (no stable layer)
        if not stable_layer.exists(user_id):
            logger.info(f"No stable layer found for user {user_id[:8]}, attempting bootstrap")
            # Guard: skip if recently attempted (check Redis flag with 1h TTL)
            should_bootstrap = True
            try:
                import redis as _redis
                r = _redis.from_url(
                    os.environ.get("REDIS_URL", "redis://redis:6379/0"),
                    decode_responses=True,
                )
                flag_key = f"brief:bootstrap_attempted:{user_id}"
                if r.get(flag_key):
                    should_bootstrap = False
                else:
                    r.setex(flag_key, 3600, "1")  # 1h cooldown
            except Exception:
                pass  # Redis unavailable — allow bootstrap

            if should_bootstrap:
                try:
                    from app.db.session import get_db
                    db_gen = get_db()
                    db = next(db_gen)
                    try:
                        success = await self.bootstrap_stable_layer(user_id, db)
                        if success and stable_layer.exists(user_id):
                            return self.compiler.compile(user_id)
                    finally:
                        db.close()
                except Exception as e:
                    logger.warning(f"Bootstrap failed for {user_id[:8]}: {e}")

            # Fallback: return moment text or empty
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

            # Call background synthesis model (Qwen 3.5 122 label resolver)
            stable_content = await self._call_llm(prompt)

            # Canonical stable write path
            from .stable_layer import stable_layer
            stable_layer.write(user_id, stable_content)
            brief_status_tracker.record_event(user_id, "stable_bootstrap")

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
        from .day_layer import day_layer
        await day_layer.append_session_summary(user_id, summary, timestamp)

    def get_brief_stats(self, user_id: str) -> Dict:
        """Get statistics about the user's brief system."""
        return self.compiler.get_stats(user_id)

    @staticmethod
    def _mtime_iso(path: Optional[Path]) -> Optional[str]:
        """Convert file mtime to UTC ISO timestamp."""
        if not path or not path.exists():
            return None
        return datetime.utcfromtimestamp(path.stat().st_mtime).isoformat() + "Z"

    def _latest_archive_day_path(self, user_id: str) -> Optional[Path]:
        """Return the newest archived day file by mtime."""
        archive_root = self.briefs_dir / user_id / "archive"
        if not archive_root.exists():
            return None

        latest_path = None
        latest_mtime = -1.0
        for day_path in archive_root.rglob("day.md"):
            try:
                mtime = day_path.stat().st_mtime
            except OSError:
                continue
            if mtime > latest_mtime:
                latest_path = day_path
                latest_mtime = mtime
        return latest_path

    def get_debug_report(self, user_id: str) -> Dict:
        """Operational debug report for day/stable layers and background model resolution."""
        self._ensure_user_dir(user_id)
        user_dir = self.briefs_dir / user_id
        layers_dir = user_dir / "layers"

        status = brief_status_tracker.read_status(user_id)
        events = status.get("events", {}) if isinstance(status.get("events"), dict) else {}

        day_path = layers_dir / "day.md"
        stable_path = layers_dir / "stable.md"
        archive_day_path = self._latest_archive_day_path(user_id)
        status_path = brief_status_tracker.get_status_path(user_id)

        from app.core.llm import get_background_llm_client
        bg_client = get_background_llm_client()
        bg_status = bg_client.get_status()
        resolved_model = resolve_qwen_122_model_label(bg_status.get("primary_model"))

        return {
            "user_id": user_id,
            "events": {
                "last_day_append_at": events.get("day_append") or self._mtime_iso(day_path),
                "last_archive_at": events.get("day_archive") or self._mtime_iso(archive_day_path),
                "last_stable_synthesis_at": events.get("stable_synthesis") or self._mtime_iso(stable_path),
                "last_stable_bootstrap_at": events.get("stable_bootstrap"),
                "last_stable_milestone_update_at": events.get("stable_milestone_update"),
            },
            "models": {
                "resolved_qwen_122_label": resolved_model,
                "bg_primary_model": bg_status.get("primary_model"),
                "bg_fallback_model": bg_status.get("fallback_model"),
            },
            "paths": {
                "day_layer": str(day_path),
                "stable_layer": str(stable_path),
                "latest_archive_day": str(archive_day_path) if archive_day_path else None,
                "status_file": str(status_path),
            },
            "status": status,
        }

    def has_stable_layer(self, user_id: str) -> bool:
        """Check if user has a stable layer (is bootstrapped)."""
        from .stable_layer import stable_layer
        return stable_layer.exists(user_id)

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
