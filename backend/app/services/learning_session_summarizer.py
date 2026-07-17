"""
Learning Session Summarizer
Extracts session state from learning conversations for continuity across sessions.
Uses hybrid trigger: >30min gap OR topic change.
Includes cognitive state tracking for David's Analogical Builder profile.
"""
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta, timezone
import logging
import json

logger = logging.getLogger(__name__)

# Gap threshold for session summarization (30 minutes)
SESSION_GAP_MINUTES = 30

# Maximum messages to pass to summarizer (tail of conversation)
MAX_MESSAGES_FOR_SUMMARIZATION = 20


class LearningSessionSummarizer:
    """Service for summarizing learning sessions and maintaining continuity"""

    def should_summarize(
        self,
        last_interaction_at: Optional[datetime],
        is_topic_change: bool = False
    ) -> bool:
        """
        Determine if we should summarize the previous session.

        Args:
            last_interaction_at: Timestamp of last interaction
            is_topic_change: Whether the user switched topics

        Returns:
            True if session should be summarized
        """
        # Always summarize on topic change
        if is_topic_change:
            return True

        # Check time gap
        if last_interaction_at is None:
            return False

        now = datetime.now(timezone.utc)

        # Handle timezone-naive datetime
        if last_interaction_at.tzinfo is None:
            last_interaction_at = last_interaction_at.replace(tzinfo=timezone.utc)

        gap = now - last_interaction_at
        return gap >= timedelta(minutes=SESSION_GAP_MINUTES)

    async def summarize_session(
        self,
        conversation_history: List[Dict[str, str]],
        topic_title: str = ""
    ) -> Dict[str, Any]:
        """
        Summarize a learning session using LLM.

        Args:
            conversation_history: List of {"role": "user"|"assistant", "content": "..."}
            topic_title: Title of the topic being studied

        Returns:
            Session state dict with summary, open_questions, concepts_in_progress,
            stuck_points, mastery_signals, and cognitive_state
        """
        if not conversation_history:
            return self._empty_session_state()

        try:
            from app.core.llm import llm_client

            # Take only the last N messages to stay within token budget
            messages_to_summarize = conversation_history[-MAX_MESSAGES_FOR_SUMMARIZATION:]

            # Build conversation text for summarization
            conversation_text = self._format_conversation(messages_to_summarize)

            prompt = f"""Extract from this learning conversation about "{topic_title}":

1. A 1-2 sentence summary of what was covered
2. Any questions that were asked but not fully resolved
3. Concepts the user was actively working through
4. Areas where the user seemed stuck or confused
5. Concepts the user demonstrated clear understanding of vs. remained uncertain about
6. The user's engagement level during the session
7. Any analogies or metaphors that resonated with the user
8. Moments where understanding clearly broke through ("click moments")
9. Any concepts the user tried to explain back and how well they did

Conversation:
{conversation_text}

Output as JSON matching this exact schema:
{{
  "summary": "string",
  "open_questions": ["string"],
  "concepts_in_progress": ["string"],
  "stuck_points": ["string"],
  "mastery_signals": {{
    "demonstrated": ["string"],
    "uncertain": ["string"]
  }},
  "cognitive_state": {{
    "engagement_level": "surface|transitioning|deep",
    "active_analogies": ["string - analogies that resonated"],
    "click_moments": ["string - concepts where understanding broke through"],
    "explanation_attempts": [{{"concept": "string", "quality": "weak|partial|strong"}}]
  }}
}}

Engagement levels:
- "surface": short responses, not connecting ideas, seems disengaged
- "transitioning": asking questions, starting to make connections
- "deep": making own analogies, explaining back, asking edge cases

Be concise. Return ONLY valid JSON."""

            response = await llm_client.generate(
                prompt=prompt,
                max_tokens=600
            )

            if not response:
                logger.warning("Empty response from LLM for session summarization")
                return self._empty_session_state()

            # Parse JSON response
            session_state = self._parse_session_state(response)
            return session_state

        except Exception as e:
            logger.error(f"Failed to summarize session: {e}")
            return self._empty_session_state()

    def _format_conversation(self, messages: List[Dict[str, str]]) -> str:
        """Format conversation history for the summarization prompt"""
        lines = []
        for msg in messages:
            role = msg.get("role", "user").upper()
            content = msg.get("content", "")
            # Truncate very long messages
            if len(content) > 500:
                content = content[:500] + "..."
            lines.append(f"{role}: {content}")
        return "\n\n".join(lines)

    def _parse_session_state(self, response: str) -> Dict[str, Any]:
        """Parse LLM response into session state dict"""
        try:
            # Try to extract JSON from response
            response = response.strip()

            # Handle markdown code blocks
            if response.startswith("```"):
                # Remove markdown code block markers
                lines = response.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                response = "\n".join(lines)

            # Find JSON object in response
            start_idx = response.find("{")
            end_idx = response.rfind("}") + 1
            if start_idx != -1 and end_idx > start_idx:
                json_str = response[start_idx:end_idx]
                parsed = json.loads(json_str)

                # Parse cognitive_state sub-object
                raw_cognitive = parsed.get("cognitive_state", {})
                cognitive_state = {
                    "engagement_level": raw_cognitive.get("engagement_level", "unknown"),
                    "active_analogies": raw_cognitive.get("active_analogies", []) or [],
                    "click_moments": raw_cognitive.get("click_moments", []) or [],
                    "explanation_attempts": raw_cognitive.get("explanation_attempts", []) or [],
                }
                # Normalize engagement_level
                if cognitive_state["engagement_level"] not in ("surface", "transitioning", "deep"):
                    cognitive_state["engagement_level"] = "unknown"

                # Validate and normalize structure
                return {
                    "summary": parsed.get("summary", ""),
                    "open_questions": parsed.get("open_questions", []) or [],
                    "concepts_in_progress": parsed.get("concepts_in_progress", []) or [],
                    "stuck_points": parsed.get("stuck_points", []) or [],
                    "mastery_signals": {
                        "demonstrated": parsed.get("mastery_signals", {}).get("demonstrated", []) or [],
                        "uncertain": parsed.get("mastery_signals", {}).get("uncertain", []) or []
                    },
                    "cognitive_state": cognitive_state
                }
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse session state JSON: {e}")
        except Exception as e:
            logger.warning(f"Error parsing session state: {e}")

        return self._empty_session_state()

    def _empty_session_state(self) -> Dict[str, Any]:
        """Return empty session state structure"""
        return {
            "summary": "",
            "open_questions": [],
            "concepts_in_progress": [],
            "stuck_points": [],
            "mastery_signals": {
                "demonstrated": [],
                "uncertain": []
            },
            "cognitive_state": {
                "engagement_level": "unknown",
                "active_analogies": [],
                "click_moments": [],
                "explanation_attempts": []
            }
        }

    def format_session_context(self, session_state: Dict[str, Any]) -> str:
        """
        Format session state for injection into system prompt.

        Args:
            session_state: The session state dict

        Returns:
            Formatted markdown string for the system prompt
        """
        if not session_state or not session_state.get("summary"):
            return ""

        lines = ["## Previous Session Context", ""]

        # Summary
        if session_state.get("summary"):
            lines.append(f"**Last time:** {session_state['summary']}")
            lines.append("")

        # Open questions
        if session_state.get("open_questions"):
            lines.append("**Open questions from last session:**")
            for q in session_state["open_questions"][:3]:  # Limit to 3
                lines.append(f"- {q}")
            lines.append("")

        # Concepts in progress
        if session_state.get("concepts_in_progress"):
            lines.append("**Concepts being worked on:**")
            for c in session_state["concepts_in_progress"][:3]:
                lines.append(f"- {c}")
            lines.append("")

        # Stuck points
        if session_state.get("stuck_points"):
            lines.append("**Areas that were challenging:**")
            for s in session_state["stuck_points"][:2]:
                lines.append(f"- {s}")
            lines.append("")

        # Mastery signals
        mastery = session_state.get("mastery_signals", {})
        if mastery.get("demonstrated"):
            lines.append("**Demonstrated understanding of:** " + ", ".join(mastery["demonstrated"][:3]))
        if mastery.get("uncertain"):
            lines.append("**Still uncertain about:** " + ", ".join(mastery["uncertain"][:3]))

        # Cognitive state
        cognitive = session_state.get("cognitive_state", {})
        if cognitive:
            engagement = cognitive.get("engagement_level", "unknown")
            if engagement != "unknown":
                lines.append("")
                lines.append(f"**Last session engagement:** {engagement}")

            analogies = cognitive.get("active_analogies", [])
            if analogies:
                lines.append(f"**Analogies that worked:** {', '.join(analogies[:4])}")

            clicks = cognitive.get("click_moments", [])
            if clicks:
                lines.append(f"**Click moments:** {', '.join(clicks[:4])}")

        return "\n".join(lines)


# Singleton instance
learning_session_summarizer = LearningSessionSummarizer()
