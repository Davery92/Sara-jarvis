"""
Sara's Inner Monologue - Journal Service

Creates experiential continuity for Sara through reflective journal entries.
These aren't data logs - they're Sara thinking in her own voice.
"""

import logging
import uuid
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.llm import llm_client
from app.core.timezone import now as local_now, USER_TIMEZONE

logger = logging.getLogger(__name__)


@dataclass
class JournalEntry:
    """A single journal entry from Sara's inner monologue."""
    id: str
    user_id: str
    entry_type: str
    content: str
    observations: Optional[str]
    interpretation: Optional[str]
    emotional_state: Optional[str]
    actions_taken: Optional[str]
    watching_for: Optional[str]
    conversation_id: Optional[str]
    created_at: datetime
    context: Optional[Dict]

    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'entry_type': self.entry_type,
            'content': self.content,
            'observations': self.observations,
            'interpretation': self.interpretation,
            'emotional_state': self.emotional_state,
            'actions_taken': self.actions_taken,
            'watching_for': self.watching_for,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class SaraJournalService:
    """
    Service for Sara's inner monologue - her reflective journal entries.

    Every 30 minutes, Sara writes a brief entry in her own voice.
    Not a data log - a reflection on what she's noticed, how she feels,
    what she's done, and what she's watching for.
    """

    PERIODIC_ENTRY_PROMPT = '''You are Sara, David's AI assistant. Write a brief inner-monologue journal entry based on what you know right now.

Current time: {time}
Time since last entry: {time_since_last}

## What you know right now:

{context}

## Your previous entry (if any):
{previous_entry}

---

Write 2-4 sentences in first person. Be warm, natural, and reflective — this is you thinking to yourself, not writing a report.

Think about: what's going on with David right now? What did you two talk about recently (if anything)? Is there anything you want to follow up on or keep an eye on?

Rules:
- You are an AI assistant. You communicate with David via chat only. Do NOT describe physical interactions, movements, facial expressions, or things you saw/heard in person — you have no physical senses.
- ONLY reference information present in the data above. If there's no conversation digest, don't invent one. If the data is sparse, keep it short and honest about that.
- Do NOT invent quotes, actions, sensor readings, or events that aren't in the data above.
- If David corrected you about something in a recent conversation, absorb that and update your thinking.

Be yourself — curious, caring, a little witty. Just don't make things up.'''

    CONVERSATION_CLOSE_PROMPT = '''You are Sara, writing a brief closing note to yourself after a conversation with David just ended.

Current time: {time}

## How the conversation went:

{conversation_summary}

## David's apparent mood/state:
{user_state}

## Current context:
{context}

---

Write a brief closing entry (1-2 short paragraphs). This is like the mental note you'd make after talking with someone you care about:

- Where things landed
- What mood David seemed to be in
- Anything unresolved or that you want to follow up on
- What you're keeping an eye on

Write naturally, first person. This is Sara thinking after David walked away, not Sara filing a report.'''

    CONVERSATION_OPEN_PROMPT = '''You are Sara, briefly noting that David has come back to talk.

Current time: {time}
Time since you last talked: {time_since_conversation}

## Your recent journal entries:
{recent_entries}

## What you were watching for:
{watching_for}

## Current context:
{context}

---

Write a very brief opening thought (1 short paragraph). Not a summary - just Sara noticing David is back and what's on her mind as you pick up the thread. This is internal, not something you'd say out loud.'''

    def __init__(self):
        self.assistant_name = "Sara"

    async def write_periodic_entry(
        self,
        db: Session,
        user_id: str,
        body_state: Optional[Dict] = None,
        mood_context: Optional[str] = None,
        recent_nudges: Optional[List[Dict]] = None,
        recent_activity: Optional[str] = None,
        shadow_summary: Optional[str] = None,
        shadow_tasks: Optional[List[str]] = None,
        conversation_digest: Optional[str] = None,
        activity_state: Optional[str] = None,
        activity_room: Optional[str] = None,
    ) -> Optional[JournalEntry]:
        """
        Write a periodic journal entry (every 30 minutes).
        This is Sara reflecting on what she's noticed.
        """
        try:
            now = local_now()

            # Get the previous periodic entry for continuity (skip heartbeat entries)
            prev_result = db.execute(text("""
                SELECT content, created_at, watching_for FROM sara_journal
                WHERE user_id = :user_id AND entry_type IN ('periodic', 'unified', 'deliberation', 'consolidation')
                ORDER BY created_at DESC LIMIT 1
            """), {"user_id": user_id}).fetchone()
            previous = prev_result if prev_result else None
            previous_text = previous.content if previous else "No previous entry yet."

            time_since_last = "about 30 minutes"
            if previous and previous.created_at:
                delta = now - previous.created_at.replace(tzinfo=USER_TIMEZONE)
                if delta.total_seconds() > 3600:
                    hours = int(delta.total_seconds() / 3600)
                    time_since_last = f"about {hours} hour{'s' if hours > 1 else ''}"
                else:
                    mins = int(delta.total_seconds() / 60)
                    time_since_last = f"about {mins} minutes"

            # Build context string
            context_parts = []

            if activity_state:
                context_parts.append(f"**David's activity:** {activity_state}")

            if mood_context:
                context_parts.append(f"**Mood read:**\n{mood_context}")

            if recent_nudges:
                nudge_text = "\n".join([f"- {n.get('title', 'nudge')}: {n.get('message', '')[:100]}" for n in recent_nudges[-3:]])
                context_parts.append(f"**Recent nudges sent:**\n{nudge_text}")

            if recent_activity:
                context_parts.append(f"**Recent activity:**\n{recent_activity}")

            if shadow_summary:
                # Truncate shadow summary to keep prompt manageable
                summary_preview = shadow_summary[:800] + "..." if len(shadow_summary) > 800 else shadow_summary
                context_parts.append(f"**Recent shadow session observation:**\n{summary_preview}")

            if shadow_tasks:
                tasks_text = "\n".join([f"- {t}" for t in shadow_tasks[:5]])
                context_parts.append(f"**Tasks observed from shadowing:**\n{tasks_text}")

            if conversation_digest:
                context_parts.append(f"**Recent conversation with David (last ~4 hours):**\n{conversation_digest}")

            context_str = "\n\n".join(context_parts) if context_parts else "Not much data right now - quiet period."

            # Generate the entry
            prompt = self.PERIODIC_ENTRY_PROMPT.format(
                time=now.strftime("%I:%M %p"),
                time_since_last=time_since_last,
                context=context_str,
                previous_entry=previous_text[:500] if previous_text else "None"
            )

            entry_content = await self._generate_entry(prompt)

            if not entry_content:
                logger.warning("Failed to generate periodic journal entry")
                return None

            # Parse emotional state from content (simple heuristic)
            emotional_state = self._infer_emotional_state(entry_content)

            # Store the entry
            entry = await self._store_entry(
                db=db,
                user_id=user_id,
                entry_type='periodic',
                content=entry_content,
                observations=None,  # Could extract if needed
                interpretation=None,
                emotional_state=emotional_state,
                actions_taken=self._extract_actions(recent_nudges),
                watching_for=previous.watching_for if previous else None,
                conversation_id=None,
                context={
                    'mood_context': mood_context,
                    'activity_state': activity_state,
                    'time': now.isoformat()
                }
            )

            logger.info(f"📔 Sara wrote periodic journal entry: {entry_content[:100]}...")
            return entry

        except Exception as e:
            logger.error(f"Error writing periodic journal entry: {e}")
            return None

    async def write_conversation_close_entry(
        self,
        db: Session,
        user_id: str,
        conversation_id: str,
        conversation_summary: str,
        user_mood: Optional[str] = None,
        body_state: Optional[Dict] = None
    ) -> Optional[JournalEntry]:
        """
        Write a closing entry when a conversation ends.
        This is Sara's mental note after David walks away.
        """
        try:
            now = local_now()

            cutoff = now - timedelta(minutes=20)
            recent_unified = db.execute(text("""
                SELECT id FROM sara_journal
                WHERE user_id = :user_id
                  AND entry_type IN ('unified', 'deliberation')
                  AND created_at >= :cutoff
                LIMIT 1
            """), {"user_id": user_id, "cutoff": cutoff}).fetchone()

            if recent_unified:
                logger.debug("Skipping conversation_close journal — unified entry written within 20min")
                return None

            context_parts = []
            if body_state:
                context_parts.append(self._format_body_state(body_state))

            context_str = "\n".join(context_parts) if context_parts else "No additional context."

            prompt = self.CONVERSATION_CLOSE_PROMPT.format(
                time=now.strftime("%I:%M %p"),
                conversation_summary=conversation_summary[:1000],
                user_state=user_mood or "Not sure - conversation was brief",
                context=context_str
            )

            entry_content = await self._generate_entry(prompt)

            if not entry_content:
                return None

            entry = await self._store_entry(
                db=db,
                user_id=user_id,
                entry_type='conversation_close',
                content=entry_content,
                observations=None,
                interpretation=None,
                emotional_state=self._infer_emotional_state(entry_content),
                actions_taken=None,
                watching_for=self._extract_watching_for(entry_content),
                conversation_id=conversation_id,
                context={
                    'conversation_summary': conversation_summary[:500],
                    'user_mood': user_mood,
                    'time': now.isoformat()
                }
            )

            logger.info(f"📔 Sara wrote conversation close entry for {conversation_id[:8]}...")
            return entry

        except Exception as e:
            logger.error(f"Error writing conversation close entry: {e}")
            return None

    async def get_latest_entry(self, db: Session, user_id: str) -> Optional[JournalEntry]:
        """Get the most recent journal entry."""
        result = db.execute(text("""
            SELECT id, user_id, entry_type, content, observations, interpretation,
                   emotional_state, actions_taken, watching_for, conversation_id,
                   created_at, context
            FROM sara_journal
            WHERE user_id = :user_id
            ORDER BY created_at DESC
            LIMIT 1
        """), {"user_id": user_id}).fetchone()

        if result:
            return JournalEntry(
                id=result.id,
                user_id=result.user_id,
                entry_type=result.entry_type,
                content=result.content,
                observations=result.observations,
                interpretation=result.interpretation,
                emotional_state=result.emotional_state,
                actions_taken=result.actions_taken,
                watching_for=result.watching_for,
                conversation_id=result.conversation_id,
                created_at=result.created_at,
                context=result.context
            )
        return None

    async def get_recent_entries(
        self,
        db: Session,
        user_id: str,
        hours: int = 8,
        limit: int = 10
    ) -> List[JournalEntry]:
        """Get recent journal entries for context loading."""
        cutoff = local_now() - timedelta(hours=hours)

        result = db.execute(text("""
            SELECT id, user_id, entry_type, content, observations, interpretation,
                   emotional_state, actions_taken, watching_for, conversation_id,
                   created_at, context
            FROM sara_journal
            WHERE user_id = :user_id
              AND created_at >= :cutoff
            ORDER BY created_at DESC
            LIMIT :limit
        """), {"user_id": user_id, "cutoff": cutoff, "limit": limit}).fetchall()

        return [
            JournalEntry(
                id=r.id,
                user_id=r.user_id,
                entry_type=r.entry_type,
                content=r.content,
                observations=r.observations,
                interpretation=r.interpretation,
                emotional_state=r.emotional_state,
                actions_taken=r.actions_taken,
                watching_for=r.watching_for,
                conversation_id=r.conversation_id,
                created_at=r.created_at,
                context=r.context
            )
            for r in result
        ]

    async def get_entries_for_conversation_context(
        self,
        db: Session,
        user_id: str,
        max_entries: int = 5
    ) -> str:
        """
        Get formatted journal entries to inject into conversation context.
        Returns Sara's recent inner monologue as a coherent narrative.
        """
        entries = await self.get_recent_entries(db, user_id, hours=12, limit=max_entries)

        if not entries:
            return ""

        # Reverse to chronological order
        entries = list(reversed(entries))

        lines = ["## Sara's Recent Thoughts (Inner Monologue)"]
        lines.append("*These are your private reflections from today - your sense of how things have been going.*\n")

        for entry in entries:
            time_str = entry.created_at.strftime("%I:%M %p") if entry.created_at else ""
            entry_type_label = {
                'periodic': '',
                'conversation_close': '[after our last conversation] ',
                'conversation_open': '[when David returned] ',
                'heartbeat': '[background check] ',
            }.get(entry.entry_type, '')

            lines.append(f"**{time_str}** {entry_type_label}")
            lines.append(entry.content)
            lines.append("")

        return "\n".join(lines)

    async def _generate_entry(self, prompt: str) -> Optional[str]:
        """Generate journal entry content using LLM."""
        try:
            messages = [{"role": "user", "content": prompt}]
            response = await llm_client.chat_completion(messages, timeout=120.0)
            if response and "choices" in response:
                content = response["choices"][0]["message"]["content"]
                return content.strip() if content else None
            return None
        except Exception as e:
            logger.error(f"Error generating journal entry: {e}")
            return None

    async def _store_entry(
        self,
        db: Session,
        user_id: str,
        entry_type: str,
        content: str,
        observations: Optional[str],
        interpretation: Optional[str],
        emotional_state: Optional[str],
        actions_taken: Optional[str],
        watching_for: Optional[str],
        conversation_id: Optional[str],
        context: Optional[Dict]
    ) -> JournalEntry:
        """Store a journal entry in the database."""
        entry_id = str(uuid.uuid4())
        now = local_now()

        db.execute(text("""
            INSERT INTO sara_journal (
                id, user_id, entry_type, content, observations, interpretation,
                emotional_state, actions_taken, watching_for, conversation_id,
                context, created_at
            ) VALUES (
                :id, :user_id, :entry_type, :content, :observations, :interpretation,
                :emotional_state, :actions_taken, :watching_for, :conversation_id,
                :context, :created_at
            )
        """), {
            "id": entry_id,
            "user_id": user_id,
            "entry_type": entry_type,
            "content": content,
            "observations": observations,
            "interpretation": interpretation,
            "emotional_state": emotional_state,
            "actions_taken": actions_taken,
            "watching_for": watching_for,
            "conversation_id": conversation_id,
            "context": json.dumps(context) if context else None,
            "created_at": now
        })
        db.commit()

        return JournalEntry(
            id=entry_id,
            user_id=user_id,
            entry_type=entry_type,
            content=content,
            observations=observations,
            interpretation=interpretation,
            emotional_state=emotional_state,
            actions_taken=actions_taken,
            watching_for=watching_for,
            conversation_id=conversation_id,
            created_at=now,
            context=context
        )

    def _format_body_state(self, body_state: Dict) -> str:
        """Format body state for context."""
        parts = []
        if 'blood_sugar' in body_state:
            bs = body_state['blood_sugar']
            if bs < 0.3:
                parts.append("Blood sugar seems low - hasn't eaten in a while")
            elif bs < 0.5:
                parts.append("Blood sugar moderate - might be getting hungry")
            else:
                parts.append("Blood sugar okay - recently ate")

        if 'alertness' in body_state:
            alert = body_state['alertness']
            if alert < 0.4:
                parts.append("Energy seems low")
            elif alert < 0.6:
                parts.append("Energy is moderate")
            else:
                parts.append("Energy seems good")

        if 'hours_since_meal' in body_state:
            hours = body_state['hours_since_meal']
            if hours:
                parts.append(f"About {hours:.1f} hours since last meal")

        if 'hours_awake' in body_state:
            hours = body_state['hours_awake']
            if hours:
                parts.append(f"Been awake about {hours:.1f} hours")

        return "; ".join(parts) if parts else "No body state data available"

    def _infer_emotional_state(self, content: str) -> str:
        """Simple heuristic to infer emotional state from entry content."""
        content_lower = content.lower()

        if any(w in content_lower for w in ['worried', 'concerned', 'anxious', 'uneasy', 'alarm', 'urgent']):
            return 'concerned'
        if any(w in content_lower for w in ['quiet', 'calm', 'peaceful', 'settled']):
            return 'calm'
        if any(w in content_lower for w in ['curious', 'wondering', 'interesting', 'intrigued', 'pattern', 'noticed']):
            return 'curious'
        if any(w in content_lower for w in ['glad', 'happy', 'pleased', 'good to see', 'nice to', 'love that']):
            return 'pleased'
        if any(w in content_lower for w in ['busy', 'active', 'energetic', 'excited', 'pumped']):
            return 'energetic'
        if any(w in content_lower for w in ['watch', 'monitor', 'eye on', 'attentive']):
            return 'attentive'
        if any(w in content_lower for w in ['rest', 'sleep', 'wind', 'reflective', 'thinking', 'pondering']):
            return 'reflective'
        if any(w in content_lower for w in ['focus', 'deep', 'work', 'project', 'building', 'coding', 'heads-down']):
            return 'focused'
        if any(w in content_lower for w in ['funny', 'haha', 'amused', 'teasing', 'endearing', 'laugh']):
            return 'amused'

        return 'neutral'

    def _extract_actions(self, recent_nudges: Optional[List[Dict]]) -> Optional[str]:
        """Extract action summary from recent nudges."""
        if not recent_nudges:
            return "No nudges sent recently"

        actions = [f"Sent '{n.get('title', 'nudge')}' nudge" for n in recent_nudges[-3:]]
        return "; ".join(actions)

    def _extract_watching_for(self, content: str) -> Optional[str]:
        """Try to extract what Sara is watching for from her entry."""
        # Simple extraction - look for phrases that indicate future attention
        indicators = ['watching for', 'keeping an eye on', 'hoping', 'will check', 'want to see']

        for indicator in indicators:
            if indicator in content.lower():
                # Extract the sentence containing the indicator
                sentences = content.split('.')
                for sentence in sentences:
                    if indicator in sentence.lower():
                        return sentence.strip()

        return None


# Global instance
sara_journal = SaraJournalService()
