"""
Nightly Reflection Service
Manages daily reflection routines and insight generation
"""

import json
import uuid
from datetime import datetime, date, timedelta, timezone
from typing import Dict, List, Optional, Tuple, Any
from sqlalchemy.orm import Session
from sqlalchemy import desc, and_
from app.models.profile import DailyReflection, ReflectionSettings, UserActivityLog
from app.core.llm import llm_client
import logging

logger = logging.getLogger(__name__)


class ReflectionService:
    """Service for managing nightly reflection routines"""
    
    # Default reflection questions
    DEFAULT_QUESTIONS = [
        {
            "id": "went_well",
            "question": "What went well today?",
            "type": "text",
            "required": False,
            "follow_up": True
        },
        {
            "id": "challenges",
            "question": "What was challenging or difficult today?",
            "type": "text", 
            "required": False,
            "follow_up": True
        },
        {
            "id": "grateful_for",
            "question": "What are you grateful for today?",
            "type": "text",
            "required": False,
            "follow_up": False
        },
        {
            "id": "learned",
            "question": "Did you learn anything new or interesting today?",
            "type": "text",
            "required": False,
            "follow_up": True
        },
        {
            "id": "tomorrow_focus",
            "question": "What's the most important thing for tomorrow?",
            "type": "text",
            "required": False,
            "follow_up": True
        },
        {
            "id": "mood_scale",
            "question": "How would you rate your overall mood today?",
            "type": "scale",
            "scale": {"min": 1, "max": 10, "labels": {"1": "Very low", "5": "Neutral", "10": "Excellent"}},
            "required": False,
            "follow_up": False
        }
    ]
    
    def __init__(self, db: Session):
        self.db = db
    
    async def start_reflection(self, user_id: str, reflection_date: date = None) -> Dict[str, Any]:
        """Start a new daily reflection"""
        
        if reflection_date is None:
            reflection_date = date.today()
        
        # Check if reflection already exists for today
        existing_reflection = self.db.query(DailyReflection).filter(
            DailyReflection.user_id == user_id,
            DailyReflection.reflection_date == reflection_date
        ).first()
        
        if existing_reflection:
            return {
                "status": "existing",
                "reflection_id": str(existing_reflection.id),
                "message": "You've already reflected today! You can update your reflection or view your insights.",
                "reflection_date": reflection_date.isoformat(),
                "responses": existing_reflection.responses,
                "insights_generated": existing_reflection.insights_generated,
                "mood_score": existing_reflection.mood_score,
                "can_update": True
            }
        
        # Create new reflection
        reflection = DailyReflection(
            user_id=user_id,
            reflection_date=reflection_date,
            responses={},
            insights_generated={}
        )
        
        self.db.add(reflection)
        self.db.commit()
        
        # Get user's reflection settings for personalization
        settings = self.db.query(ReflectionSettings).filter(
            ReflectionSettings.user_id == user_id
        ).first()
        
        # Get first question
        first_question = self.DEFAULT_QUESTIONS[0]
        
        # Log activity
        await self._log_activity(user_id, "reflection_started", {
            "reflection_id": str(reflection.id),
            "reflection_date": reflection_date.isoformat()
        })
        
        return {
            "status": "started",
            "reflection_id": str(reflection.id),
            "reflection_date": reflection_date.isoformat(),
            "current_question_index": 0,
            "total_questions": len(self.DEFAULT_QUESTIONS),
            "question": first_question,
            "progress": "1 of 6 questions",
            "estimated_time": "3-5 minutes"
        }
    
    async def respond_to_question(
        self,
        reflection_id: str,
        user_id: str,
        question_id: str,
        response: Any,
        question_index: int
    ) -> Dict[str, Any]:
        """Process response to a reflection question"""
        
        reflection = self.db.query(DailyReflection).filter(
            DailyReflection.id == reflection_id,
            DailyReflection.user_id == user_id
        ).first()
        
        if not reflection:
            raise ValueError("Reflection not found")
        
        # Validate question
        if question_index >= len(self.DEFAULT_QUESTIONS):
            raise ValueError("Invalid question index")
        
        current_question = self.DEFAULT_QUESTIONS[question_index]
        if current_question["id"] != question_id:
            raise ValueError("Question ID mismatch")
        
        # Store the response
        responses = reflection.responses.copy()
        responses[question_id] = {
            "value": response,
            "timestamp": datetime.utcnow().isoformat(),
            "question": current_question["question"]
        }
        reflection.responses = responses
        
        # Update mood score if this is the mood question
        if question_id == "mood_scale" and isinstance(response, (int, float)):
            reflection.mood_score = int(response)
        
        # Generate follow-up if needed
        follow_up = None
        if current_question.get("follow_up") and response:
            follow_up = await self._generate_follow_up(
                current_question,
                response,
                reflection.reflection_date
            )
        
        # Check if we have more questions
        next_index = question_index + 1
        
        if next_index < len(self.DEFAULT_QUESTIONS):
            # More questions
            next_question = self.DEFAULT_QUESTIONS[next_index]
            
            self.db.commit()
            
            return {
                "status": "continue",
                "question": next_question,
                "follow_up": follow_up,
                "progress": f"{next_index + 1} of {len(self.DEFAULT_QUESTIONS)} questions",
                "current_question_index": next_index
            }
        else:
            # All questions complete - generate insights
            reflection.reflection_duration_minutes = self._calculate_duration(reflection)
            
            insights = await self._generate_insights(user_id, reflection)
            reflection.insights_generated = insights
            
            self.db.commit()
            
            # Update reflection streak
            await self._update_reflection_streak(user_id)
            
            # Log completion
            await self._log_activity(user_id, "reflection_completed", {
                "reflection_id": str(reflection.id),
                "total_responses": len(responses),
                "insights_generated": len(insights.get("insights", [])),
                "mood_score": reflection.mood_score
            })
            
            return {
                "status": "complete",
                "message": "Thank you for reflecting! I've generated some insights for tomorrow.",
                "insights": insights,
                "reflection_summary": self._create_reflection_summary(reflection),
                "mood_score": reflection.mood_score,
                "next_steps": [
                    "Your insights are saved for future reference",
                    "Check tomorrow's suggestions in your dashboard",
                    "Your reflection streak has been updated"
                ]
            }
    
    async def get_reflection_history(
        self,
        user_id: str,
        limit: int = 30,
        offset: int = 0
    ) -> Dict[str, Any]:
        """Get user's reflection history"""
        
        reflections = self.db.query(DailyReflection).filter(
            DailyReflection.user_id == user_id
        ).order_by(desc(DailyReflection.reflection_date)).offset(offset).limit(limit).all()
        
        total_count = self.db.query(DailyReflection).filter(
            DailyReflection.user_id == user_id
        ).count()
        
        history = []
        for reflection in reflections:
            history.append({
                "id": str(reflection.id),
                "reflection_date": reflection.reflection_date.isoformat(),
                "mood_score": reflection.mood_score,
                "response_count": len(reflection.responses),
                "insights_count": len(reflection.insights_generated.get("insights", [])),
                "duration_minutes": reflection.reflection_duration_minutes,
                "created_at": reflection.created_at.isoformat()
            })
        
        # Get streak information
        settings = self.db.query(ReflectionSettings).filter(
            ReflectionSettings.user_id == user_id
        ).first()
        
        streak_count = settings.streak_count if settings else 0
        
        return {
            "history": history,
            "total_count": total_count,
            "current_streak": streak_count,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "has_more": offset + len(history) < total_count
            }
        }
    
    async def get_reflection_insights(
        self,
        reflection_id: str,
        user_id: str
    ) -> Dict[str, Any]:
        """Get insights for a specific reflection"""
        
        reflection = self.db.query(DailyReflection).filter(
            DailyReflection.id == reflection_id,
            DailyReflection.user_id == user_id
        ).first()
        
        if not reflection:
            raise ValueError("Reflection not found")
        
        return {
            "reflection_id": str(reflection.id),
            "reflection_date": reflection.reflection_date.isoformat(),
            "insights": reflection.insights_generated,
            "responses": reflection.responses,
            "mood_score": reflection.mood_score,
            "summary": self._create_reflection_summary(reflection)
        }
    
    async def update_reflection_settings(
        self,
        user_id: str,
        settings_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Update user's reflection settings"""
        
        settings = self.db.query(ReflectionSettings).filter(
            ReflectionSettings.user_id == user_id
        ).first()
        
        if not settings:
            settings = ReflectionSettings(user_id=user_id)
            self.db.add(settings)
        
        # Update settings
        if "enabled" in settings_data:
            settings.enabled = settings_data["enabled"]
        
        if "preferred_time" in settings_data:
            # Parse time string (HH:MM format)
            time_str = settings_data["preferred_time"]
            try:
                from datetime import time
                hour, minute = map(int, time_str.split(":"))
                settings.preferred_time = time(hour=hour, minute=minute)
            except (ValueError, AttributeError):
                raise ValueError("Invalid time format. Use HH:MM format")
        
        if "timezone" in settings_data:
            settings.timezone = settings_data["timezone"]
        
        if "quiet_hours" in settings_data:
            settings.quiet_hours = settings_data["quiet_hours"]
        
        if "reminder_channels" in settings_data:
            settings.reminder_channels = settings_data["reminder_channels"]
        
        settings.updated_at = datetime.utcnow()
        self.db.commit()
        
        return {
            "message": "Reflection settings updated successfully",
            "settings": {
                "enabled": settings.enabled,
                "preferred_time": settings.preferred_time.strftime("%H:%M") if settings.preferred_time else "21:00",
                "timezone": settings.timezone,
                "quiet_hours": settings.quiet_hours,
                "reminder_channels": settings.reminder_channels,
                "streak_count": settings.streak_count
            }
        }
    
    def _calculate_duration(self, reflection: DailyReflection) -> int:
        """Calculate reflection duration in minutes"""
        
        if not reflection.responses:
            return 0
        
        timestamps = []
        for response in reflection.responses.values():
            if isinstance(response, dict) and "timestamp" in response:
                try:
                    ts = datetime.fromisoformat(response["timestamp"])
                    timestamps.append(ts)
                except (ValueError, TypeError):
                    continue
        
        if len(timestamps) < 2:
            return 1  # Default minimum
        
        start_time = min(timestamps)
        end_time = max(timestamps)
        duration = (end_time - start_time).total_seconds() / 60
        
        return max(1, int(duration))  # At least 1 minute
    
    async def _generate_follow_up(
        self,
        question: Dict[str, Any],
        response: Any,
        reflection_date: date
    ) -> Optional[str]:
        """Generate contextual follow-up comment"""
        
        try:
            prompt = f"""You are Sara, a thoughtful AI assistant providing gentle follow-up comments during a daily reflection.

Today is {reflection_date.strftime('%A, %B %d, %Y')}.

The user just answered: "{question['question']}"
Their response: "{response}"

Generate a brief, warm follow-up comment that:
- Acknowledges their response with empathy
- Shows you understood what they shared
- Might offer a gentle insight or encouraging word
- Stays supportive and non-judgmental
- Is 1-2 sentences max

Examples of good follow-ups:
- For challenges: "That sounds really difficult. It's great that you're reflecting on it thoughtfully."
- For gratitude: "It's wonderful that you noticed that. Gratitude can really shift our perspective."
- For learning: "How exciting! Learning something new always feels good."

Follow-up:"""

            response_obj = await llm_client.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=100
            )
            
            follow_up = response_obj["choices"][0]["message"]["content"].strip()
            return follow_up if len(follow_up) > 10 else None
            
        except Exception as e:
            logger.error(f"Failed to generate follow-up: {e}")
            return None
    
    async def _generate_insights(
        self,
        user_id: str,
        reflection: DailyReflection
    ) -> Dict[str, Any]:
        """Generate insights and suggestions for tomorrow"""
        
        try:
            # Get recent reflections for context
            recent_reflections = self.db.query(DailyReflection).filter(
                DailyReflection.user_id == user_id,
                DailyReflection.reflection_date >= reflection.reflection_date - timedelta(days=7)
            ).order_by(desc(DailyReflection.reflection_date)).limit(7).all()
            
            # Build context
            responses_text = []
            for q_id, response_data in reflection.responses.items():
                if isinstance(response_data, dict):
                    question = response_data.get("question", q_id)
                    value = response_data.get("value", "")
                    responses_text.append(f"Q: {question}\nA: {value}")
            
            context = "\n\n".join(responses_text)
            
            # Get mood trend
            mood_trend = ""
            if len(recent_reflections) > 1:
                recent_moods = [r.mood_score for r in recent_reflections if r.mood_score is not None]
                if len(recent_moods) >= 2:
                    avg_recent = sum(recent_moods[:3]) / len(recent_moods[:3])  # Last 3 days
                    current_mood = reflection.mood_score or 5
                    if current_mood > avg_recent + 1:
                        mood_trend = "Your mood seems to be improving recently."
                    elif current_mood < avg_recent - 1:
                        mood_trend = "Your mood has been lower than usual lately."
            
            prompt = f"""You are Sara, a thoughtful AI assistant analyzing today's reflection to provide helpful insights and suggestions for tomorrow.

Today's reflection ({reflection.reflection_date.strftime('%A, %B %d, %Y')}):

{context}

{f"Mood trend: {mood_trend}" if mood_trend else ""}

Generate helpful insights in JSON format with these sections:

{{
  "insights": [
    "2-3 thoughtful observations about patterns, growth, or things to appreciate"
  ],
  "tomorrow_suggestions": [
    "2-3 specific, actionable suggestions for tomorrow based on their responses"
  ],
  "appreciation": "One thing to acknowledge or appreciate about their reflection",
  "gentle_reminder": "Optional gentle reminder or encouragement (only if appropriate)"
}}

Guidelines:
- Be supportive and encouraging, not prescriptive
- Focus on what they shared, not generic advice
- Suggestions should be specific and actionable
- Keep insights positive while acknowledging challenges
- Don't repeat what they already said, add new perspective

Response:"""

            response_obj = await llm_client.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=400
            )
            
            insights_text = response_obj["choices"][0]["message"]["content"].strip()
            
            try:
                insights = json.loads(insights_text)
            except json.JSONDecodeError:
                # Fallback if JSON parsing fails
                insights = {
                    "insights": ["Thank you for taking time to reflect today."],
                    "tomorrow_suggestions": ["Focus on what matters most to you."],
                    "appreciation": "Your thoughtfulness in reflection shows great self-awareness."
                }
            
            return insights
            
        except Exception as e:
            logger.error(f"Failed to generate insights: {e}")
            return {
                "insights": ["Thank you for reflecting today. Every moment of self-awareness matters."],
                "tomorrow_suggestions": ["Take things one step at a time tomorrow."],
                "appreciation": "Your commitment to reflection shows wonderful self-care."
            }
    
    def _create_reflection_summary(self, reflection: DailyReflection) -> str:
        """Create a brief summary of the reflection"""
        
        responses = reflection.responses
        if not responses:
            return "No responses recorded."
        
        summary_parts = []
        
        # Add mood if available
        if reflection.mood_score:
            mood_desc = "great" if reflection.mood_score >= 8 else "good" if reflection.mood_score >= 6 else "challenging"
            summary_parts.append(f"Had a {mood_desc} day")
        
        # Add key highlights from responses
        if "went_well" in responses and responses["went_well"].get("value"):
            summary_parts.append("noted positive moments")
        
        if "challenges" in responses and responses["challenges"].get("value"):
            summary_parts.append("reflected on challenges")
        
        if "grateful_for" in responses and responses["grateful_for"].get("value"):
            summary_parts.append("practiced gratitude")
        
        if "tomorrow_focus" in responses and responses["tomorrow_focus"].get("value"):
            summary_parts.append("set intentions for tomorrow")
        
        if not summary_parts:
            return "Completed reflection."
        
        return " • ".join(summary_parts).capitalize() + "."
    
    async def _update_reflection_streak(self, user_id: str):
        """Update user's reflection streak"""
        
        settings = self.db.query(ReflectionSettings).filter(
            ReflectionSettings.user_id == user_id
        ).first()
        
        if not settings:
            settings = ReflectionSettings(user_id=user_id, streak_count=1)
            self.db.add(settings)
        else:
            # Check if yesterday had a reflection
            yesterday = date.today() - timedelta(days=1)
            yesterday_reflection = self.db.query(DailyReflection).filter(
                DailyReflection.user_id == user_id,
                DailyReflection.reflection_date == yesterday
            ).first()
            
            if yesterday_reflection:
                # Continue streak
                settings.streak_count += 1
            else:
                # Check if there's a gap - reset streak if more than 1 day gap
                latest_reflection = self.db.query(DailyReflection).filter(
                    DailyReflection.user_id == user_id,
                    DailyReflection.reflection_date < date.today()
                ).order_by(desc(DailyReflection.reflection_date)).first()
                
                if not latest_reflection or (date.today() - latest_reflection.reflection_date).days > 1:
                    settings.streak_count = 1  # Reset streak
                else:
                    settings.streak_count += 1
        
        self.db.commit()
    
    async def _log_activity(self, user_id: str, action_type: str, data: Dict[str, Any]):
        """Log user activity for transparency"""
        
        try:
            log_entry = UserActivityLog(
                user_id=user_id,
                action_type=action_type,
                action_description=f"Reflection: {action_type}",
                data_accessed=data
            )
            
            self.db.add(log_entry)
            self.db.commit()
            
        except Exception as e:
            logger.error(f"Failed to log activity: {e}")