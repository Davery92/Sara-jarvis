"""
Fitness Onboarding Service

Manages stateful chat-based onboarding flow for fitness profiles and goals.
Uses Redis for session state management and implements branching question logic.
"""

from typing import Dict, List, Any, Optional, Tuple
import json
import uuid
from datetime import datetime, timedelta

import redis
from app.core.config import settings
from app.models.fitness import FitnessProfile, FitnessGoal
from app.db.session import SessionLocal


class FitnessOnboardingService:
    """Handles fitness onboarding chat flow with Redis state management"""
    
    def __init__(self):
        # Connect to Redis
        self.redis_client = redis.Redis(
            host=getattr(settings, 'redis_host', 'localhost'),
            port=getattr(settings, 'redis_port', 6379),
            decode_responses=True
        )
        self.session_ttl = 3600  # 1 hour session timeout
        
        # Define onboarding flow
        self.onboarding_flow = self._define_onboarding_flow()
    
    def _define_onboarding_flow(self) -> Dict[str, Any]:
        """Define the complete onboarding question flow"""
        return {
            "start": {
                "type": "greeting",
                "message": "Hi! I'm Sara, and I'm excited to help you create a personalized fitness plan. This will take about 5 minutes. Ready to get started?",
                "options": ["Yes, let's do this!", "I have questions first"],
                "next": {
                    "Yes, let's do this!": "demographics",
                    "I have questions first": "questions"
                }
            },
            
            "questions": {
                "type": "info",
                "message": "No problem! I'll ask about your fitness background, goals, available equipment, and schedule preferences. This helps me create a plan that's perfect for you. Ready now?",
                "options": ["Ready!", "Maybe later"],
                "next": {
                    "Ready!": "demographics", 
                    "Maybe later": "exit"
                }
            },
            
            "demographics": {
                "type": "form",
                "message": "First, let me learn about you. What's your age and biological sex? (This helps with exercise selection and recovery needs)",
                "fields": [
                    {"name": "age", "type": "number", "required": True, "min": 13, "max": 100},
                    {"name": "sex", "type": "choice", "required": True, "options": ["Male", "Female", "Other"]}
                ],
                "next": "experience"
            },
            
            "experience": {
                "type": "choice",
                "message": "What's your training experience?",
                "options": [
                    "Complete beginner (never trained regularly)",
                    "Some experience (trained on/off for <1 year)", 
                    "Intermediate (1-3 years consistent training)",
                    "Advanced (3+ years, know what I'm doing)"
                ],
                "field": "experience",
                "next": {
                    "Complete beginner (never trained regularly)": "goals_beginner",
                    "Some experience (trained on/off for <1 year)": "goals_beginner", 
                    "Intermediate (1-3 years consistent training)": "goals_intermediate",
                    "Advanced (3+ years, know what I'm doing)": "goals_advanced"
                }
            },
            
            "goals_beginner": {
                "type": "choice",
                "message": "What's your primary fitness goal?",
                "options": [
                    "General health and fitness",
                    "Lose weight and tone up",
                    "Build some muscle",
                    "Get stronger for daily activities"
                ],
                "field": "primary_goal",
                "next": "schedule"
            },
            
            "goals_intermediate": {
                "type": "choice", 
                "message": "What's your primary goal?",
                "options": [
                    "Build muscle (hypertrophy)",
                    "Get stronger (strength focus)", 
                    "Lose fat while maintaining muscle",
                    "Improve athletic performance",
                    "General fitness maintenance"
                ],
                "field": "primary_goal",
                "next": "schedule"
            },
            
            "goals_advanced": {
                "type": "multi_choice",
                "message": "What are your goals? (Select all that apply)",
                "options": [
                    "Powerlifting/max strength",
                    "Bodybuilding/physique", 
                    "Athletic performance",
                    "Powerbuilding (strength + size)",
                    "Body recomposition",
                    "Sport-specific training"
                ],
                "field": "goals_list",
                "min_selections": 1,
                "max_selections": 3,
                "next": "schedule"
            },
            
            "schedule": {
                "type": "form",
                "message": "Let's talk schedule. How many days per week can you realistically train, and how long per session?",
                "fields": [
                    {"name": "days_per_week", "type": "number", "required": True, "min": 1, "max": 7},
                    {"name": "session_length", "type": "choice", "required": True, "options": ["30 min", "45 min", "60 min", "75 min", "90+ min"]}
                ],
                "next": "equipment"
            },
            
            "equipment": {
                "type": "multi_choice",
                "message": "What equipment do you have access to? (Select all that apply)",
                "options": [
                    "Full commercial gym",
                    "Home gym with barbell/plates",
                    "Dumbbells (adjustable or set)",
                    "Kettlebells", 
                    "Resistance bands",
                    "Pull-up bar",
                    "Bench",
                    "Cable machine/TRX",
                    "Just bodyweight"
                ],
                "field": "equipment",
                "min_selections": 1,
                "next": "constraints"
            },
            
            "constraints": {
                "type": "multi_choice",
                "message": "Any injuries, limitations, or exercises you want to avoid? (Optional - select if applicable)",
                "options": [
                    "Lower back issues",
                    "Knee problems", 
                    "Shoulder/neck issues",
                    "No overhead pressing",
                    "No jumping/plyometrics",
                    "Previous surgery/injury",
                    "None of these apply"
                ],
                "field": "constraints",
                "min_selections": 0,
                "next": "preferences"
            },
            
            "preferences": {
                "type": "form",
                "message": "Last questions! What style do you prefer, and any exercises you particularly love or hate?",
                "fields": [
                    {"name": "style", "type": "choice", "required": False, "options": ["Full body", "Upper/Lower split", "Push/Pull/Legs", "No preference"]},
                    {"name": "loves", "type": "text", "required": False, "placeholder": "Exercises you love (optional)"},
                    {"name": "hates", "type": "text", "required": False, "placeholder": "Exercises you avoid (optional)"}
                ],
                "next": "review"
            },
            
            "review": {
                "type": "review",
                "message": "Perfect! Let me create your personalized plan...",
                "next": "complete"
            },
            
            "complete": {
                "type": "completion",
                "message": "Your plan is ready! I've created a program that matches your goals, schedule, and equipment. You can review and modify it before we schedule your workouts. Ready to see it?",
                "next": "exit"
            },
            
            "exit": {
                "type": "exit",
                "message": "Thanks for using Sara Fitness! You can restart onboarding anytime from Settings.",
                "next": None
            }
        }
    
    def start_onboarding(self, user_id: str, flow_type: str = "new_journey") -> Dict[str, Any]:
        """Start a new onboarding session"""
        session_id = str(uuid.uuid4())
        
        # Initialize session state
        session_state = {
            "session_id": session_id,
            "user_id": user_id,
            "flow_type": flow_type,
            "current_step": "start",
            "collected_data": {},
            "step_history": [],
            "created_at": datetime.utcnow().isoformat(),
            "last_activity": datetime.utcnow().isoformat()
        }
        
        # Store in Redis
        self.redis_client.setex(
            f"fitness_onboarding:{session_id}",
            self.session_ttl,
            json.dumps(session_state)
        )
        
        # Return first step
        return self._get_current_step_data(session_state)
    
    def continue_onboarding(self, session_id: str, response: Dict[str, Any]) -> Dict[str, Any]:
        """Continue onboarding with user response"""
        # Get session state
        session_state = self._get_session_state(session_id)
        if not session_state:
            return {"error": "Session not found or expired"}
        
        # Process response and update state
        session_state = self._process_response(session_state, response)
        
        # Determine next step
        session_state = self._advance_to_next_step(session_state, response)
        
        # Update session in Redis
        session_state["last_activity"] = datetime.utcnow().isoformat()
        self.redis_client.setex(
            f"fitness_onboarding:{session_id}",
            self.session_ttl,
            json.dumps(session_state)
        )
        
        # Return current step data
        return self._get_current_step_data(session_state)
    
    def get_session_status(self, session_id: str) -> Dict[str, Any]:
        """Get current session status"""
        session_state = self._get_session_state(session_id)
        if not session_state:
            return {"error": "Session not found"}
        
        return {
            "session_id": session_id,
            "current_step": session_state["current_step"],
            "progress": len(session_state["step_history"]) / len(self.onboarding_flow) * 100,
            "collected_data": session_state["collected_data"]
        }
    
    def complete_onboarding(self, session_id: str) -> Dict[str, Any]:
        """Complete onboarding and persist data to database"""
        session_state = self._get_session_state(session_id)
        if not session_state:
            return {"error": "Session not found"}
        
        # Extract collected data
        data = session_state["collected_data"]
        user_id = session_state["user_id"]
        
        # Save to database
        db = SessionLocal()
        try:
            # Create or update fitness profile
            profile_data = {
                "demographics": {
                    "age": data.get("age"),
                    "sex": data.get("sex"),
                    "experience": data.get("experience")
                },
                "equipment": data.get("equipment", []),
                "preferences": {
                    "style": data.get("style"),
                    "loves": data.get("loves"),
                    "hates": data.get("hates"),
                    "session_length": data.get("session_length"),
                    "days_per_week": data.get("days_per_week")
                },
                "constraints": {
                    "injuries": data.get("constraints", []),
                    "limitations": data.get("limitations", [])
                }
            }
            
            # Upsert profile
            existing_profile = db.query(FitnessProfile).filter(
                FitnessProfile.user_id == user_id
            ).first()
            
            if existing_profile:
                existing_profile.demographics = profile_data["demographics"]
                existing_profile.equipment = profile_data["equipment"]
                existing_profile.preferences = profile_data["preferences"] 
                existing_profile.constraints = profile_data["constraints"]
            else:
                profile = FitnessProfile(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    demographics=profile_data["demographics"],
                    equipment=profile_data["equipment"],
                    preferences=profile_data["preferences"],
                    constraints=profile_data["constraints"]
                )
                db.add(profile)
            
            # Create fitness goal
            goal_data = self._extract_goals(data)
            fitness_goal = FitnessGoal(
                id=str(uuid.uuid4()),
                user_id=user_id,
                goal_type=goal_data["goal_type"],
                targets=goal_data["targets"],
                timeframe=goal_data["timeframe"],
                status="active"
            )
            db.add(fitness_goal)
            
            db.commit()
            
            # Clean up session
            self.redis_client.delete(f"fitness_onboarding:{session_id}")
            
            return {
                "success": True,
                "profile_data": profile_data,
                "goal_data": goal_data,
                "message": "Onboarding completed successfully!"
            }
            
        except Exception as e:
            db.rollback()
            return {"error": f"Failed to save onboarding data: {str(e)}"}
        finally:
            db.close()
    
    def _get_session_state(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session state from Redis"""
        state_json = self.redis_client.get(f"fitness_onboarding:{session_id}")
        if state_json:
            return json.loads(state_json)
        return None
    
    def _get_current_step_data(self, session_state: Dict[str, Any]) -> Dict[str, Any]:
        """Get data for current step"""
        current_step = session_state["current_step"]
        step_config = self.onboarding_flow[current_step]
        
        return {
            "session_id": session_state["session_id"],
            "step": current_step,
            "type": step_config["type"],
            "message": step_config["message"],
            "options": step_config.get("options"),
            "fields": step_config.get("fields"),
            "progress": len(session_state["step_history"]) / len(self.onboarding_flow) * 100,
            "can_go_back": len(session_state["step_history"]) > 0
        }
    
    def _process_response(self, session_state: Dict[str, Any], response: Dict[str, Any]) -> Dict[str, Any]:
        """Process user response and update collected data"""
        current_step = session_state["current_step"]
        step_config = self.onboarding_flow[current_step]
        
        # Add current step to history
        session_state["step_history"].append({
            "step": current_step,
            "response": response,
            "timestamp": datetime.utcnow().isoformat()
        })
        
        # Extract data based on step type
        if step_config["type"] == "choice":
            field = step_config.get("field")
            if field:
                session_state["collected_data"][field] = response.get("choice")
        
        elif step_config["type"] == "multi_choice":
            field = step_config.get("field")
            if field:
                session_state["collected_data"][field] = response.get("choices", [])
        
        elif step_config["type"] == "form":
            for field in step_config.get("fields", []):
                field_name = field["name"]
                if field_name in response:
                    session_state["collected_data"][field_name] = response[field_name]
        
        return session_state
    
    def _advance_to_next_step(self, session_state: Dict[str, Any], response: Dict[str, Any]) -> Dict[str, Any]:
        """Determine and advance to next step"""
        current_step = session_state["current_step"]
        step_config = self.onboarding_flow[current_step]
        
        next_step = None
        
        # Determine next step based on response
        if "next" in step_config:
            if isinstance(step_config["next"], str):
                # Simple next step
                next_step = step_config["next"]
            elif isinstance(step_config["next"], dict):
                # Conditional next step
                if step_config["type"] == "choice":
                    choice = response.get("choice")
                    next_step = step_config["next"].get(choice)
                else:
                    # Default to first option if no specific mapping
                    next_step = list(step_config["next"].values())[0]
        
        if next_step and next_step in self.onboarding_flow:
            session_state["current_step"] = next_step
        
        return session_state
    
    def _extract_goals(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract and normalize goal data"""
        primary_goal = data.get("primary_goal", "general")
        goals_list = data.get("goals_list", [])
        
        # Map user-friendly goals to system goals
        goal_mapping = {
            "General health and fitness": "general",
            "Lose weight and tone up": "fat_loss", 
            "Build some muscle": "hypertrophy",
            "Get stronger for daily activities": "strength",
            "Build muscle (hypertrophy)": "hypertrophy",
            "Get stronger (strength focus)": "strength",
            "Lose fat while maintaining muscle": "recomposition",
            "Improve athletic performance": "performance",
            "General fitness maintenance": "maintenance"
        }
        
        goal_type = goal_mapping.get(primary_goal, "general")
        
        # Set targets based on goals
        targets = {}
        if goal_type == "fat_loss":
            targets = {"target_type": "fat_loss", "timeline_weeks": 12}
        elif goal_type == "hypertrophy":
            targets = {"target_type": "muscle_gain", "timeline_weeks": 16}
        elif goal_type == "strength":
            targets = {"target_type": "strength_gain", "timeline_weeks": 12}
        
        return {
            "goal_type": goal_type,
            "targets": targets,
            "timeframe": f"{targets.get('timeline_weeks', 12)} weeks"
        }