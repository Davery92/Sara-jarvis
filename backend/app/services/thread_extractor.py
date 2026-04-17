"""
Thread Extractor — LLM-based extraction of conversation threads.

Identifies actionable things David mentioned (plans, tasks, cooking, etc.)
and creates conversation_thread records for follow-up.

Runs as fire-and-forget after chat_stream completes.
"""

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm import get_background_llm_client

logger = logging.getLogger(__name__)

# Rate limit: one extraction per 5 minutes per user
_last_extraction: Dict[str, float] = {}
EXTRACTION_COOLDOWN = 300  # seconds

# Follow-up timing heuristics by category
CATEGORY_TIMING = {
    "cooking": {"after_hours": 2, "before_hours": 12, "max_mentions": 2},
    "project": {"after_hours": 4, "before_hours": 72, "max_mentions": 3},
    "errand": {"after_hours": 12, "before_hours": 48, "max_mentions": 2},
    "social": {"after_hours": 1, "before_hours": 24, "max_mentions": 2},
    "health": {"after_hours": 4, "before_hours": 24, "max_mentions": 1},
    "planning": {"after_hours": 24, "before_hours": 72, "max_mentions": 2},
    "learning": {"after_hours": 24, "before_hours": 168, "max_mentions": 3},
}
DEFAULT_TIMING = {"after_hours": 4, "before_hours": 48, "max_mentions": 2}

EXTRACTION_PROMPT = """You are analyzing a conversation between David (user) and Sara (assistant).

Identify any ACTIONABLE things David mentioned he is going to DO, is currently doing, or plans to do. These should be specific activities, NOT abstract discussion topics.

Good examples:
- "making chuck roast in the ninja foodi" → cooking
- "setting up the new monitor" → project
- "going to the gym later" → health
- "need to call the dentist" → errand
- "working on the API migration" → project

Bad examples (too abstract, don't extract):
- "thinking about life"
- "wondering about politics"
- General small talk
- Questions about factual information

For each thread found, output JSON:
{
  "threads": [
    {
      "topic": "short description of what David is doing/planning",
      "category": "cooking|project|errand|social|health|planning|learning",
      "suggested_followup": "A natural Sara-voice follow-up question",
      "priority": 0.0-1.0,
      "context_snippet": "the key sentence from the conversation"
    }
  ],
  "resolved_topics": ["topic text that matches an existing open thread that this conversation resolves"]
}

If nothing actionable was mentioned, return {"threads": [], "resolved_topics": []}.

Output ONLY valid JSON, no explanation."""

RESOLVE_CHECK_PROMPT = """Given these open conversation threads Sara is tracking:
{threads}

And this recent conversation:
{conversation}

Which threads, if any, have been implicitly resolved by the conversation?
(e.g., David mentioned finishing something, the topic came up and was completed, etc.)

Return ONLY a JSON array of thread IDs that are now resolved:
["uuid1", "uuid2"]

If none are resolved, return [].
Output ONLY valid JSON."""


class ThreadExtractor:
    def __init__(self):
        self.llm_client = get_background_llm_client()

    async def extract_threads(
        self, messages: List, user_id: str, db: AsyncSession
    ) -> List[str]:
        """Extract actionable threads from a conversation. Returns list of created thread IDs."""
        # Rate limit
        now = time.time()
        last = _last_extraction.get(user_id, 0)
        if (now - last) < EXTRACTION_COOLDOWN:
            return []
        _last_extraction[user_id] = now

        # Need at least 3 user messages for meaningful extraction
        user_messages = [
            m for m in messages
            if (m.get("role") if isinstance(m, dict) else getattr(m, "role", None)) == "user"
        ]
        if len(user_messages) < 3:
            return []

        # Build conversation text (last ~8 messages)
        recent = messages[-8:] if len(messages) > 8 else messages
        conversation_text = self._format_messages(recent)

        # Call LLM for extraction
        try:
            response = await self.llm_client.chat_completion(
                messages=[
                    {"role": "system", "content": EXTRACTION_PROMPT},
                    {"role": "user", "content": conversation_text},
                ],
                temperature=0.3,
                max_tokens=500,
            )

            content = response["choices"][0]["message"].get("content", "")
            parsed = self._parse_json_response(content)
            if not parsed or "threads" not in parsed:
                return []

            # Get existing threads for dedup
            from app.services.thread_manager import get_all_open_threads, create_thread
            existing = await get_all_open_threads(user_id, db)
            existing_topics = [t["topic"].lower() for t in existing]

            created_ids = []
            for thread_data in parsed["threads"]:
                topic = thread_data.get("topic", "").strip()
                if not topic:
                    continue

                # Simple dedup: skip if very similar topic already exists
                if any(self._topics_similar(topic, et) for et in existing_topics):
                    logger.debug(f"Thread dedup: skipping '{topic}' (similar exists)")
                    continue

                category = thread_data.get("category", "project")
                timing = CATEGORY_TIMING.get(category, DEFAULT_TIMING)
                now_dt = datetime.now(timezone.utc)

                thread_id = await create_thread(
                    user_id=user_id,
                    topic=topic,
                    category=category,
                    follow_up_after=now_dt + timedelta(hours=timing["after_hours"]),
                    follow_up_before=now_dt + timedelta(hours=timing["before_hours"]),
                    max_mentions=timing["max_mentions"],
                    original_context=thread_data.get("context_snippet", "")[:500],
                    suggested_followup=thread_data.get("suggested_followup", "")[:300],
                    priority=min(1.0, max(0.0, thread_data.get("priority", 0.5))),
                    db=db,
                )
                if thread_id:
                    created_ids.append(thread_id)
                    logger.info(f"Thread created: [{category}] {topic}")

            return created_ids

        except Exception as e:
            logger.debug(f"Thread extraction LLM call failed: {e}")
            return []

    async def resolve_threads_from_conversation(
        self, messages: List, user_id: str, db: AsyncSession
    ) -> List[str]:
        """Check if the conversation implicitly resolves any open threads."""
        from app.services.thread_manager import get_all_open_threads, resolve_thread

        existing = await get_all_open_threads(user_id, db)
        if not existing:
            return []

        # Format threads for the prompt
        threads_text = "\n".join(
            f"- ID: {t['id']} | Topic: {t['topic']} ({t['category']})"
            for t in existing
        )

        recent = messages[-8:] if len(messages) > 8 else messages
        conversation_text = self._format_messages(recent)

        try:
            prompt = RESOLVE_CHECK_PROMPT.format(
                threads=threads_text,
                conversation=conversation_text,
            )

            response = await self.llm_client.chat_completion(
                messages=[
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=200,
            )

            content = response["choices"][0]["message"].get("content", "")
            resolved_ids = self._parse_json_response(content)
            if not isinstance(resolved_ids, list):
                return []

            resolved = []
            valid_ids = {t["id"] for t in existing}
            for tid in resolved_ids:
                if isinstance(tid, str) and tid in valid_ids:
                    if await resolve_thread(tid, db):
                        resolved.append(tid)
                        logger.info(f"Thread resolved from conversation: {tid}")

            return resolved

        except Exception as e:
            logger.debug(f"Thread resolution check failed: {e}")
            return []

    def _format_messages(self, messages: List) -> str:
        """Format messages into readable conversation text."""
        lines = []
        for msg in messages:
            if isinstance(msg, dict):
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
            else:
                role = getattr(msg, "role", "unknown")
                content = getattr(msg, "content", "")
            if content:
                name = "David" if role == "user" else "Sara"
                lines.append(f"{name}: {str(content)[:300]}")
        return "\n".join(lines)

    def _parse_json_response(self, content: str):
        """Parse JSON from LLM response, handling markdown code blocks."""
        content = content.strip()
        # Strip markdown code fences
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:])
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            # Try to find JSON within the text
            for start_char in ["{", "["]:
                idx = content.find(start_char)
                if idx >= 0:
                    try:
                        return json.loads(content[idx:])
                    except json.JSONDecodeError:
                        pass
            return None

    def _topics_similar(self, new_topic: str, existing_topic: str) -> bool:
        """Simple word-overlap similarity check."""
        new_words = set(new_topic.lower().split())
        existing_words = set(existing_topic.lower().split())
        # Remove common stop words
        stop = {"the", "a", "an", "to", "in", "on", "for", "of", "is", "it", "and", "or", "my", "i"}
        new_words -= stop
        existing_words -= stop
        if not new_words or not existing_words:
            return False
        overlap = len(new_words & existing_words)
        return overlap >= min(2, len(new_words))


# Module-level singleton
thread_extractor = ThreadExtractor()
