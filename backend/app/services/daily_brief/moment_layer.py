"""
Moment Layer - Real-time conversation state
Updates on every message, no LLM required (fast, template-based)
"""
import os
import re
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)

# Base directory for brief files
BRIEFS_DIR = Path("/home/david/jarvis/data/briefs")


class MomentLayer:
    """
    Tracks the "right now" state of conversation.
    Fast, no LLM - uses heuristics and templates.
    """

    def __init__(self):
        self.briefs_dir = BRIEFS_DIR

    def _ensure_user_dir(self, user_id: str) -> Path:
        """Ensure user's brief directory structure exists."""
        user_dir = self.briefs_dir / user_id / "layers"
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir

    def _get_layer_path(self, user_id: str) -> Path:
        """Get path to moment layer file."""
        return self._ensure_user_dir(user_id) / "moment.md"

    def _extract_keywords(self, message: str, max_keywords: int = 5) -> List[str]:
        """Extract topic keywords from message (simple heuristic)."""
        # Remove common words and extract significant terms
        stopwords = {
            'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
            'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
            'would', 'could', 'should', 'may', 'might', 'must', 'shall',
            'can', 'need', 'dare', 'ought', 'used', 'to', 'of', 'in',
            'for', 'on', 'with', 'at', 'by', 'from', 'as', 'into',
            'through', 'during', 'before', 'after', 'above', 'below',
            'between', 'under', 'again', 'further', 'then', 'once',
            'here', 'there', 'when', 'where', 'why', 'how', 'all',
            'each', 'few', 'more', 'most', 'other', 'some', 'such',
            'no', 'nor', 'not', 'only', 'own', 'same', 'so', 'than',
            'too', 'very', 'just', 'and', 'but', 'if', 'or', 'because',
            'until', 'while', 'although', 'though', 'after', 'before',
            'i', 'me', 'my', 'myself', 'we', 'our', 'ours', 'you',
            'your', 'yours', 'he', 'him', 'his', 'she', 'her', 'hers',
            'it', 'its', 'they', 'them', 'their', 'what', 'which',
            'who', 'whom', 'this', 'that', 'these', 'those', 'am',
            "i'm", "it's", "don't", "doesn't", "didn't", "won't",
            "can't", "couldn't", "wouldn't", "shouldn't", "let's",
            'yeah', 'yes', 'no', 'okay', 'ok', 'hey', 'hi', 'hello',
            'thanks', 'thank', 'please', 'sorry', 'like', 'think',
            'know', 'want', 'get', 'got', 'make', 'go', 'going',
            'see', 'look', 'come', 'take', 'give', 'tell', 'say',
            'said', 'something', 'anything', 'nothing', 'thing',
            'about', 'also', 'well', 'back', 'even', 'still', 'way',
            'actually', 'really', 'right', 'now', 'up', 'out'
        }

        # Extract words, lowercase, filter
        words = re.findall(r'\b[a-zA-Z]{3,}\b', message.lower())
        keywords = [w for w in words if w not in stopwords]

        # Count frequency
        freq = {}
        for w in keywords:
            freq[w] = freq.get(w, 0) + 1

        # Sort by frequency, return top N
        sorted_words = sorted(freq.items(), key=lambda x: x[1], reverse=True)
        return [w for w, _ in sorted_words[:max_keywords]]

    def _detect_energy(self, message: str) -> str:
        """Detect energy level from message characteristics."""
        # Length-based
        word_count = len(message.split())

        # Punctuation analysis
        exclamations = message.count('!')
        questions = message.count('?')
        caps_ratio = sum(1 for c in message if c.isupper()) / max(len(message), 1)

        # Determine energy
        if exclamations >= 2 or caps_ratio > 0.3:
            return "high (enthusiastic)"
        elif word_count > 100:
            return "high (detailed, thorough)"
        elif word_count < 10 and questions == 0:
            return "low (brief)"
        elif questions >= 2:
            return "curious (questioning)"
        elif word_count > 50:
            return "engaged (substantive)"
        else:
            return "moderate"

    def _format_time_gap(self, gap: Optional[timedelta]) -> str:
        """Format time gap into human-readable string."""
        if gap is None:
            return "This is our first conversation."

        total_seconds = gap.total_seconds()

        if total_seconds < 60:
            return "We were just talking moments ago."
        elif total_seconds < 3600:
            mins = int(total_seconds / 60)
            return f"It's been {mins} minute{'s' if mins != 1 else ''} since we last talked."
        elif total_seconds < 86400:
            hours = int(total_seconds / 3600)
            return f"It's been {hours} hour{'s' if hours != 1 else ''} since we last talked."
        else:
            days = int(total_seconds / 86400)
            return f"It's been {days} day{'s' if days != 1 else ''} since we last talked."

    async def update(
        self,
        user_id: str,
        current_message: str,
        conversation_id: Optional[str],
        db,  # SQLAlchemy session
        conversation_turn_count: int = 0
    ) -> str:
        """
        Update moment layer with current conversation state.
        Returns the updated moment content.
        """
        try:
            # Import Episode model here to avoid circular imports
            from app.main_simple import Episode

            # Get time since last interaction
            last_episode = db.query(Episode).filter(
                Episode.user_id == user_id
            ).order_by(Episode.created_at.desc()).first()

            time_gap = None
            if last_episode:
                time_gap = datetime.utcnow() - last_episode.created_at

            # Extract keywords from message
            keywords = self._extract_keywords(current_message)
            topic_str = ', '.join(keywords) if keywords else 'general conversation'

            # Detect energy
            energy = self._detect_energy(current_message)

            # Determine conversation depth
            if conversation_turn_count == 0:
                # Try to count from database
                if conversation_id:
                    turn_count = db.query(Episode).filter(
                        Episode.conversation_id == conversation_id,
                        Episode.user_id == user_id
                    ).count()
                else:
                    turn_count = 0
            else:
                turn_count = conversation_turn_count

            if turn_count <= 1:
                depth = "just starting"
            elif turn_count <= 3:
                depth = "warming up"
            elif turn_count <= 6:
                depth = "engaged"
            elif turn_count <= 10:
                depth = "deep conversation"
            else:
                depth = f"extended session ({turn_count} exchanges)"

            # Get current time context
            now = datetime.now()
            hour = now.hour
            if 5 <= hour < 12:
                time_of_day = "morning"
            elif 12 <= hour < 17:
                time_of_day = "afternoon"
            elif 17 <= hour < 21:
                time_of_day = "evening"
            else:
                time_of_day = "night"

            # Build moment content
            moment_content = f"""## Right Now

I'm in conversation with David this {time_of_day}. {self._format_time_gap(time_gap)}

**Current topic**: {topic_str}
**Energy level**: {energy}
**Conversation depth**: {depth}
"""

            # Write to file
            layer_path = self._get_layer_path(user_id)
            layer_path.write_text(moment_content)

            logger.debug(f"📝 Updated moment layer for user {user_id[:8]}")
            return moment_content

        except Exception as e:
            logger.error(f"Error updating moment layer: {e}")
            # Return minimal fallback
            return "## Right Now\n\nIn conversation with David.\n"

    def read(self, user_id: str) -> str:
        """Read current moment layer content."""
        layer_path = self._get_layer_path(user_id)
        if layer_path.exists():
            return layer_path.read_text()
        return ""

    def invalidate(self, user_id: str):
        """Mark moment layer as needing recompilation (handled by compiler)."""
        # The compiler checks file hashes, so just updating the file
        # automatically invalidates the cache
        pass


# Singleton instance
moment_layer = MomentLayer()
