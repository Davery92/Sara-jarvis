"""
Get-to-Know-You Interview Service
Manages the conversational interview process to learn about users
"""

import json
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
from sqlalchemy.orm import Session
from app.models.profile import UserProfile, GTKYSession, UserActivityLog
from app.core.llm import llm_client
import logging

logger = logging.getLogger(__name__)


class GTKYService:
    """Service for managing Get-to-Know-You interviews"""
    
    # Question packs for structured interview
    QUESTION_PACKS = {
        "identity": {
            "name": "Getting to Know You",
            "description": "Let's start with the basics about who you are",
            "questions": [
                {
                    "id": "name_preference",
                    "question": "What should I call you? Your name, nickname, or however you'd prefer I address you?",
                    "type": "text",
                    "follow_up": True
                },
                {
                    "id": "timezone_location", 
                    "question": "What timezone are you in? This helps me understand when you're active.",
                    "type": "timezone",
                    "follow_up": False
                },
                {
                    "id": "work_schedule",
                    "question": "What's your typical daily schedule like? Early bird, night owl, or somewhere in between?",
                    "type": "text",
                    "follow_up": True
                },
                {
                    "id": "communication_style",
                    "question": "How do you prefer I communicate? Should I be more chatty and conversational, or brief and to the point?",
                    "type": "choice",
                    "options": ["chatty", "balanced", "brief"],
                    "follow_up": False
                }
            ]
        },
        "preferences": {
            "name": "Your Preferences",
            "description": "Help me understand how you like to work and be supported",
            "questions": [
                {
                    "id": "notification_style",
                    "question": "How should I notify you about important things? Through the app, push notifications, or other channels?",
                    "type": "multi_choice",
                    "options": ["app_only", "push_notifications", "ntfy", "email"],
                    "follow_up": True
                },
                {
                    "id": "autonomy_level",
                    "question": "How proactive should I be? Should I wait for you to ask, offer gentle suggestions, or actively help manage your tasks?",
                    "type": "choice", 
                    "options": ["minimal", "moderate", "high"],
                    "labels": ["Wait for me to ask", "Offer suggestions when helpful", "Actively help manage tasks"],
                    "follow_up": True
                },
                {
                    "id": "focus_areas",
                    "question": "What areas of your life would you most like my help with?",
                    "type": "multi_choice",
                    "options": ["productivity", "health", "learning", "relationships", "creativity", "organization"],
                    "follow_up": True
                },
                {
                    "id": "quiet_hours",
                    "question": "When should I avoid interrupting you? Any quiet hours or do not disturb times?",
                    "type": "time_range",
                    "follow_up": False
                }
            ]
        },
        "goals": {
            "name": "Your Goals & Aspirations", 
            "description": "Let's talk about what you're working toward",
            "questions": [
                {
                    "id": "current_goals",
                    "question": "What are your top 1-3 goals for the next 90 days? These could be work, personal, health, or anything important to you.",
                    "type": "text",
                    "follow_up": True
                },
                {
                    "id": "habits_interests",
                    "question": "Are there any habits you're trying to build or interests you're exploring?",
                    "type": "text", 
                    "follow_up": True
                },
                {
                    "id": "challenges",
                    "question": "What's something you find challenging or would like support with?",
                    "type": "text",
                    "follow_up": True
                },
                {
                    "id": "motivation_style",
                    "question": "How do you prefer to be motivated? Gentle encouragement, accountability, celebrating wins, or something else?",
                    "type": "text",
                    "follow_up": False
                }
            ]
        }
    }
    
    def __init__(self, db: Session):
        self.db = db
    
    async def start_interview(self, user_id: str, personality_mode: str = "companion") -> Dict[str, Any]:
        """Start a new GTKY interview session"""
        
        # Check if user already has a complete profile
        existing_profile = self.db.query(UserProfile).filter(
            UserProfile.user_id == user_id,
            UserProfile.gtky_completed_at.isnot(None)
        ).first()
        
        if existing_profile:
            return {
                "status": "already_completed",
                "message": "You've already completed the get-to-know-you interview! You can update your preferences in Settings.",
                "completed_at": existing_profile.gtky_completed_at.isoformat(),
                "can_retake": True
            }
        
        # Create new session for identity pack
        session = GTKYSession(
            user_id=user_id,
            question_pack="identity",
            session_metadata={
                "personality_mode": personality_mode,
                "started_at": datetime.utcnow().isoformat(),
                "current_question_index": 0
            }
        )
        
        self.db.add(session)
        self.db.commit()
        
        # Get first question
        first_question = self.QUESTION_PACKS["identity"]["questions"][0]
        
        # Log activity
        await self._log_activity(user_id, "gtky_started", {
            "session_id": str(session.id),
            "personality_mode": personality_mode
        })
        
        return {
            "status": "started",
            "session_id": str(session.id),
            "pack_info": {
                "name": self.QUESTION_PACKS["identity"]["name"],
                "description": self.QUESTION_PACKS["identity"]["description"],
                "progress": "1 of 4 sections"
            },
            "question": first_question,
            "sprite_state": "interviewing"
        }
    
    async def respond_to_question(
        self,
        session_id: str,
        user_id: str,
        response: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Process user response and return next question or completion"""
        
        session = self.db.query(GTKYSession).filter(
            GTKYSession.id == session_id,
            GTKYSession.user_id == user_id
        ).first()
        
        if not session:
            raise ValueError("Session not found")
        
        # Store the response
        current_index = session.session_metadata.get("current_question_index", 0)
        question_pack = self.QUESTION_PACKS[session.question_pack]
        current_question = question_pack["questions"][current_index]
        
        # Debug logging
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"📊 GTKY: Current index: {current_index}, Question: {current_question['id']}")
        
        # Update responses
        responses = session.responses.copy()
        responses[current_question["id"]] = response
        session.responses = responses
        
        # Generate follow-up if needed
        follow_up = None
        if current_question.get("follow_up") and response.get("value"):
            follow_up = await self._generate_follow_up(
                current_question,
                response,
                session.session_metadata.get("personality_mode", "companion")
            )
        
        # Check if we need next question in current pack
        next_index = current_index + 1
        
        if next_index < len(question_pack["questions"]):
            # More questions in current pack
            metadata = session.session_metadata.copy()
            metadata["current_question_index"] = next_index
            session.session_metadata = metadata
            self.db.commit()
            
            next_question = question_pack["questions"][next_index]
            logger.info(f"📈 GTKY: Updated to index: {next_index}, Next question: {next_question['id']}")
            
            return {
                "status": "continue",
                "question": next_question,
                "follow_up": follow_up,
                "progress": f"Question {next_index + 1} of {len(question_pack['questions'])} in {question_pack['name']}"
            }
        else:
            # Finished current pack
            session.completed_at = datetime.utcnow()
            self.db.commit()
            
            # Determine next pack
            next_pack = self._get_next_pack(session.question_pack)
            
            if next_pack:
                return {
                    "status": "pack_complete",
                    "completed_pack": question_pack["name"],
                    "next_pack": {
                        "id": next_pack,
                        "name": self.QUESTION_PACKS[next_pack]["name"],
                        "description": self.QUESTION_PACKS[next_pack]["description"]
                    },
                    "follow_up": follow_up,
                    "can_continue": True
                }
            else:
                # All packs complete - create profile
                profile = await self._create_user_profile(user_id)
                
                return {
                    "status": "complete",
                    "message": "Thanks for taking the time to get to know each other! I've created your personalized profile.",
                    "profile_summary": await self._generate_profile_summary(profile),
                    "follow_up": follow_up,
                    "next_steps": [
                        "Your preferences are now saved",
                        "I'll start learning from our interactions", 
                        "You can update your profile anytime in Settings"
                    ]
                }
    
    async def continue_with_pack(self, user_id: str, pack_id: str) -> Dict[str, Any]:
        """Continue interview with next question pack"""
        
        if pack_id not in self.QUESTION_PACKS:
            raise ValueError(f"Invalid pack ID: {pack_id}")
        
        # Create new session for this pack
        session = GTKYSession(
            user_id=user_id,
            question_pack=pack_id,
            session_metadata={
                "started_at": datetime.utcnow().isoformat(),
                "current_question_index": 0
            }
        )
        
        self.db.add(session)
        self.db.commit()
        
        # Get first question
        first_question = self.QUESTION_PACKS[pack_id]["questions"][0]
        
        result = {
            "status": "pack_started",
            "session_id": str(session.id),
            "pack_info": {
                "name": self.QUESTION_PACKS[pack_id]["name"],
                "description": self.QUESTION_PACKS[pack_id]["description"]
            },
            "question": first_question
        }
        
        # Debug logging
        logger.info(f"📦 GTKY: Continue pack response: {result}")
        return result
    
    async def get_profile_summary(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user's profile summary if GTKY is complete"""
        
        profile = self.db.query(UserProfile).filter(
            UserProfile.user_id == user_id
        ).first()
        
        if not profile or not profile.gtky_completed_at:
            return None
        
        return {
            "completed_at": profile.gtky_completed_at.isoformat(),
            "communication_style": profile.communication_style,
            "autonomy_level": profile.autonomy_level,
            "profile_data": profile.profile_data,
            "notification_channels": profile.notification_channels
        }
    
    def _get_next_pack(self, current_pack: str) -> Optional[str]:
        """Get the next question pack in sequence"""
        pack_order = ["identity", "preferences", "goals"]
        
        try:
            current_index = pack_order.index(current_pack)
            if current_index + 1 < len(pack_order):
                return pack_order[current_index + 1]
        except ValueError:
            pass
        
        return None
    
    async def _generate_follow_up(
        self,
        question: Dict[str, Any],
        response: Dict[str, Any],
        personality_mode: str
    ) -> Optional[str]:
        """Generate a contextual follow-up comment using LLM"""
        
        try:
            prompt = f"""You are Sara, an AI assistant in {personality_mode} mode conducting a get-to-know-you interview.

The user just answered: "{question['question']}"
Their response: "{response.get('value', '')}"

Generate a brief, warm follow-up comment that:
- Acknowledges their response naturally
- Shows you understood what they shared
- Might ask a quick clarifying question if helpful
- Stays conversational and friendly
- Is 1-2 sentences max

Mode context:
- companion: warm, encouraging, personal
- analyst: thoughtful, insightful, structured  
- coach: supportive, goal-focused
- guardian: protective, caring
- concierge: helpful, accommodating
- librarian: knowledgeable, organized

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
    
    async def _create_user_profile(self, user_id: str) -> UserProfile:
        """Create user profile from completed GTKY sessions"""
        
        # Get all completed sessions for user
        sessions = self.db.query(GTKYSession).filter(
            GTKYSession.user_id == user_id,
            GTKYSession.completed_at.isnot(None)
        ).all()
        
        # Aggregate responses
        all_responses = {}
        for session in sessions:
            all_responses.update(session.responses)
        
        # Extract key settings
        communication_style = all_responses.get("communication_style", {}).get("value", "balanced")
        autonomy_level = all_responses.get("autonomy_level", {}).get("value", "moderate")
        
        # Build notification channels
        notification_prefs = all_responses.get("notification_style", {}).get("value", ["app_only"])
        if isinstance(notification_prefs, str):
            notification_prefs = [notification_prefs]
        
        notification_channels = {
            "app_notifications": True,
            "push_notifications": "push_notifications" in notification_prefs,
            "ntfy_enabled": "ntfy" in notification_prefs,
            "email_enabled": "email" in notification_prefs,
            "quiet_hours": all_responses.get("quiet_hours", {}).get("value", {})
        }
        
        # Create or update profile
        profile = self.db.query(UserProfile).filter(
            UserProfile.user_id == user_id
        ).first()
        
        if not profile:
            profile = UserProfile(user_id=user_id)
            self.db.add(profile)
        
        profile.profile_data = all_responses
        profile.communication_style = communication_style
        profile.autonomy_level = autonomy_level
        profile.notification_channels = notification_channels
        profile.gtky_completed_at = datetime.utcnow()
        profile.updated_at = datetime.utcnow()
        
        self.db.commit()
        
        # Log completion
        await self._log_activity(user_id, "gtky_completed", {
            "communication_style": communication_style,
            "autonomy_level": autonomy_level,
            "total_responses": len(all_responses)
        })
        
        return profile
    
    async def _generate_profile_summary(self, profile: UserProfile) -> str:
        """Generate a friendly summary of the user's profile"""
        
        try:
            prompt = f"""Create a warm, personalized summary of this user's profile from their get-to-know-you interview responses.

User Profile Data:
{json.dumps(profile.profile_data, indent=2)}

Communication Style: {profile.communication_style}
Autonomy Level: {profile.autonomy_level}

Generate a 2-3 sentence summary that:
- Feels personal and warm
- Highlights their main goals or interests
- Shows Sara understands them
- Uses their preferred communication style

Summary:"""

            response_obj = await llm_client.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=150
            )
            
            return response_obj["choices"][0]["message"]["content"].strip()
            
        except Exception as e:
            logger.error(f"Failed to generate profile summary: {e}")
            return "I'm excited to learn more about you and help with your goals!"
    
    async def _log_activity(self, user_id: str, action_type: str, data: Dict[str, Any]):
        """Log user activity for transparency"""
        
        try:
            log_entry = UserActivityLog(
                user_id=user_id,
                action_type=action_type,
                action_description=f"GTKY: {action_type}",
                data_accessed=data
            )
            
            self.db.add(log_entry)
            self.db.commit()
            
        except Exception as e:
            logger.error(f"Failed to log activity: {e}")