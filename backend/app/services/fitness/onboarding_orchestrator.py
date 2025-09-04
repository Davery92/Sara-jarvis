from typing import Dict, Any, List, Optional, Tuple
import redis
import json
from datetime import datetime, timedelta
from app.models.fitness_onboarding import FitnessOnboardingSession
from app.services.fitness.generator_service import FitnessPlanGenerator
import uuid

class OnboardingOrchestrator:
    """Manages conversational fitness onboarding flow"""
    
    def __init__(self, db_session=None, redis_client: redis.Redis = None):
        self.db = db_session
        self.redis = redis_client or self._get_redis_client()
        self.generator = FitnessPlanGenerator()
        # Conversation flow definition (was previously unreachable due to indentation)
        self.stages = {
            "profile": {
                "fields": ["age", "sex", "height", "weight"],
                "next_stage": "history"
            },
            "history": {
                "fields": ["training_age", "injuries", "experience_level"],
                "next_stage": "context"
            },
            "context": {
                "fields": ["equipment", "days_per_week", "time_availability"],
                "next_stage": "goals"
            },
            "goals": {
                "fields": ["goal_type", "target_metrics", "timeframe"],
                "next_stage": "preferences"
            },
            "preferences": {
                "fields": ["style", "session_length_cap", "dislikes"],
                "next_stage": "preview"
            },
            "preview": {
                "fields": ["plan_preview_approval"],
                "next_stage": "confirm"
            },
            "confirm": {
                "fields": ["final_confirmation"],
                "next_stage": "completed"
            }
        }
    
    def _get_redis_client(self):
        """Get Redis client with fallback"""
        try:
            return redis.Redis(host='redis', port=6379, db=0, decode_responses=True)
        except Exception:
            return redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
        # Note: flow definition is set in __init__
        
    def get_redis_key(self, session_id: str) -> str:
        return f"fitness:onboarding:{session_id}"
    
    def get_session_state(self, session_id: str) -> Optional[Dict]:
        """Get ephemeral session state from Redis"""
        key = self.get_redis_key(session_id)
        state = self.redis.get(key)
        return json.loads(state) if state else None
    
    def update_session_state(self, session_id: str, state: Dict, ttl: int = 3600):
        """Update ephemeral session state in Redis"""
        key = self.get_redis_key(session_id)
        self.redis.setex(key, ttl, json.dumps(state, default=str))
    
    def get_next_question(self, session: FitnessOnboardingSession) -> Dict[str, Any]:
        """Determine the next question based on current stage and collected answers"""
        stage = session.stage
        collected = session.collected_answers or {}
        
        if stage == "profile":
            return self._get_profile_question(collected)
        elif stage == "history":
            return self._get_history_question(collected)
        elif stage == "context":
            return self._get_context_question(collected)
        elif stage == "goals":
            return self._get_goals_question(collected)
        elif stage == "preferences":
            return self._get_preferences_question(collected)
        elif stage == "preview":
            return self._get_preview_question(session)
        elif stage == "confirm":
            return self._get_confirmation_question(session)
        else:
            return {"prompt": "Let's get started with your fitness journey!", "chips": [], "can_commit": False}
    
    def _get_profile_question(self, collected: Dict) -> Dict[str, Any]:
        """Profile stage questions"""
        if "age" not in collected:
            return {
                "prompt": "Let's start with the basics! How old are you?",
                "chips": ["18-25", "26-35", "36-45", "46-55", "55+"],
                "field": "age",
                "can_commit": False
            }
        elif "sex" not in collected:
            return {
                "prompt": "What's your biological sex? (This helps with metabolism calculations)",
                "chips": ["Male", "Female", "Other"],
                "field": "sex",
                "can_commit": False
            }
        elif "height" not in collected:
            return {
                "prompt": "What's your height? (e.g., '5'8\"' or '173cm')",
                "chips": [],
                "field": "height",
                "can_commit": False
            }
        elif "weight" not in collected:
            return {
                "prompt": "What's your current weight? (e.g., '165lbs' or '75kg')",
                "chips": [],
                "field": "weight",
                "can_commit": False
            }
        return {"prompt": "Profile complete!", "can_commit": False}
    
    def _get_history_question(self, collected: Dict) -> Dict[str, Any]:
        """Training history questions"""
        if "training_age" not in collected:
            return {
                "prompt": "How long have you been training consistently?",
                "chips": ["Beginner (0-6 months)", "Novice (6-18 months)", "Intermediate (1.5-3 years)", "Advanced (3+ years)"],
                "field": "training_age",
                "can_commit": False
            }
        elif "injuries" not in collected:
            return {
                "prompt": "Do you have any current injuries or movement restrictions?",
                "chips": ["None", "Shoulder issues", "Lower back", "Knee problems", "Other"],
                "field": "injuries",
                "can_commit": False
            }
        elif "experience_level" not in collected:
            return {
                "prompt": "How would you rate your exercise form and technique knowledge?",
                "chips": ["Learning basics", "Comfortable with fundamentals", "Advanced technique"],
                "field": "experience_level",
                "can_commit": False
            }
        return {"prompt": "History complete!", "can_commit": False}
    
    def _get_context_question(self, collected: Dict) -> Dict[str, Any]:
        """Context and availability questions"""
        if "equipment" not in collected:
            return {
                "prompt": "What equipment do you have access to?",
                "chips": ["Home - minimal", "Home - dumbbells", "Home - full gym", "Commercial gym"],
                "field": "equipment",
                "can_commit": False
            }
        elif "days_per_week" not in collected:
            return {
                "prompt": "How many days per week can you realistically train?",
                "chips": ["2 days", "3 days", "4 days", "5+ days"],
                "field": "days_per_week", 
                "can_commit": False
            }
        elif "time_availability" not in collected:
            return {
                "prompt": "How much time do you have per session?",
                "chips": ["30-45 min", "45-60 min", "60-90 min", "90+ min"],
                "field": "time_availability",
                "can_commit": False
            }
        return {"prompt": "Context complete!", "can_commit": False}
    
    def _get_goals_question(self, collected: Dict) -> Dict[str, Any]:
        """Goals and objectives questions"""
        if "goal_type" not in collected:
            return {
                "prompt": "What's your primary fitness goal?",
                "chips": ["Build muscle", "Lose fat", "Get stronger", "Improve endurance", "General health"],
                "field": "goal_type",
                "can_commit": False
            }
        elif "timeframe" not in collected:
            return {
                "prompt": "What's your target timeframe?",
                "chips": ["3 months", "6 months", "1 year", "Long-term lifestyle"],
                "field": "timeframe",
                "can_commit": False
            }
        return {"prompt": "Goals complete!", "can_commit": False}
    
    def _get_preferences_question(self, collected: Dict) -> Dict[str, Any]:
        """Style and preference questions"""
        if "style" not in collected:
            days = collected.get("days_per_week", 3)
            if days <= 3:
                chips = ["Full body", "Upper/Lower", "Push/Pull/Legs"]
            else:
                chips = ["Push/Pull/Legs", "Upper/Lower", "Body part split", "Functional"]
            
            return {
                "prompt": "What training style appeals to you?",
                "chips": chips,
                "field": "style",
                "can_commit": False
            }
        elif "session_length_cap" not in collected:
            return {
                "prompt": "Any hard limit on session length?",
                "chips": ["No limit", "45 min max", "60 min max", "30 min max"],
                "field": "session_length_cap",
                "can_commit": False
            }
        return {"prompt": "Preferences complete!", "can_commit": False}
    
    def _get_preview_question(self, session: FitnessOnboardingSession) -> Dict[str, Any]:
        """Generate and show plan preview"""
        if not session.proposed_plan_draft_id:
            # Generate preview
            preview = self._generate_plan_preview(session.collected_answers)
            return {
                "prompt": "Here's your personalized plan preview:",
                "preview": preview,
                "chips": ["Looks great!", "Change days/week", "Different style", "Adjust time"],
                "field": "plan_approval",
                "can_review_plan": True,
                "can_commit": False
            }
        else:
            return {
                "prompt": "How does this plan look?",
                "chips": ["Perfect, let's do it!", "Make some tweaks"],
                "field": "plan_approval",
                "can_review_plan": True,
                "can_commit": True
            }
    
    def _get_confirmation_question(self, session: FitnessOnboardingSession) -> Dict[str, Any]:
        """Final confirmation before committing"""
        return {
            "prompt": "Ready to create your workout plan and schedule? This will add workouts to your calendar.",
            "chips": ["Yes, create my plan!", "Let me review once more"],
            "field": "final_confirmation",
            "can_commit": True
        }
    
    def _generate_plan_preview(self, answers: Dict) -> Dict[str, Any]:
        """Generate a compact plan preview for chat display"""
        # Map answers to plan generator format
        payload = {
            "profile": {
                "age": answers.get("age"),
                "sex": answers.get("sex"),
                "height": answers.get("height"),
                "weight": answers.get("weight")
            },
            "goals": {
                "goal_type": answers.get("goal_type", "general"),
                "timeframe": answers.get("timeframe", "6 months")
            },
            "equipment": self._map_equipment(answers.get("equipment", [])),
            "days_per_week": answers.get("days_per_week", 3),
            "session_len_min": self._map_time_availability(answers.get("time_availability", "60 min")),
            "preferences": {
                "style": answers.get("style", "")
            }
        }
        
        # Use existing generator to create template
        template = self.generator._select_template(payload)
        days = self.generator._substitute_exercises(template.get("days", []), payload.get("equipment"))
        
        return {
            "split": answers.get("style", "Custom"),
            "days_per_week": payload["days_per_week"],
            "phases": template.get("phases", ["Build", "Intensify"]),
            "estimated_session_length": f"{payload['session_len_min']} min",
            "sample_workouts": [day.get("title", f"Day {i+1}") for i, day in enumerate(days[:3])]
        }
    
    def _map_equipment(self, equipment_choice: str) -> List[str]:
        """Map equipment choice to equipment list"""
        mapping = {
            "Home - minimal": ["bodyweight", "resistance_bands"],
            "Home - dumbbells": ["dumbbells", "adjustable_bench", "resistance_bands"],
            "Home - full gym": ["barbell", "dumbbells", "rack", "bench", "plates"],
            "Commercial gym": ["barbell", "dumbbells", "rack", "bench", "plates", "machines", "cables"]
        }
        return mapping.get(equipment_choice, ["bodyweight"])
    
    def _map_time_availability(self, time_choice: str) -> int:
        """Map time choice to minutes"""
        mapping = {
            "30-45 min": 40,
            "45-60 min": 55,
            "60-90 min": 75,
            "90+ min": 90
        }
        return mapping.get(time_choice, 60)
    
    def process_user_input(self, session: FitnessOnboardingSession, message: str, intent: str = None) -> Dict[str, Any]:
        """Process user input and determine next response"""
        
        # Get current question context
        next_question = self.get_next_question(session)
        current_field = next_question.get("field")
        
        if not current_field:
            return next_question
        
        # Validate and normalize the answer
        validation_result = self._validate_answer(current_field, message, session.collected_answers)
        
        if not validation_result["valid"]:
            return {
                "prompt": validation_result["error_message"],
                "chips": next_question.get("chips", []),
                "field": current_field,
                "can_commit": False
            }
        
        # Store the validated answer
        session.collected_answers[current_field] = validation_result["normalized_value"]
        if not session.raw_answers:
            session.raw_answers = {}
        session.raw_answers[current_field] = message
        
        # Check if stage is complete
        stage_complete = self._is_stage_complete(session.stage, session.collected_answers)
        
        if stage_complete:
            # Move to next stage
            session.stage = self.stages[session.stage]["next_stage"]
        
        # Generate next question
        return self.get_next_question(session)
    
    def _validate_answer(self, field: str, value: str, context: Dict) -> Dict[str, Any]:
        """Validate and normalize user answer"""
        
        validators = {
            "age": self._validate_age,
            "sex": self._validate_sex,
            "height": self._validate_height,
            "weight": self._validate_weight,
            "training_age": self._validate_training_age,
            "equipment": self._validate_equipment,
            "days_per_week": self._validate_days_per_week,
            "goal_type": self._validate_goal_type,
            # Add more as needed
        }
        
        validator = validators.get(field, self._validate_generic)
        return validator(value, context)
    
    def _validate_age(self, value: str, context: Dict) -> Dict[str, Any]:
        """Validate age input"""
        try:
            # Handle chip selections
            age_mapping = {
                "18-25": 22,
                "26-35": 30, 
                "36-45": 40,
                "46-55": 50,
                "55+": 60
            }
            
            if value in age_mapping:
                return {"valid": True, "normalized_value": age_mapping[value]}
            
            # Handle direct number input
            age = int(value)
            if 13 <= age <= 100:
                return {"valid": True, "normalized_value": age}
            else:
                return {"valid": False, "error_message": "Please enter an age between 13 and 100."}
                
        except ValueError:
            return {"valid": False, "error_message": "Please enter a valid age or select from the options."}
    
    def _validate_sex(self, value: str, context: Dict) -> Dict[str, Any]:
        """Validate biological sex"""
        valid_options = {"male", "female", "other", "m", "f"}
        normalized = value.lower().strip()
        
        if normalized in valid_options:
            if normalized in ["m", "male"]:
                return {"valid": True, "normalized_value": "male"}
            elif normalized in ["f", "female"]:
                return {"valid": True, "normalized_value": "female"}
            else:
                return {"valid": True, "normalized_value": "other"}
        
        return {"valid": False, "error_message": "Please select Male, Female, or Other."}
    
    def _validate_height(self, value: str, context: Dict) -> Dict[str, Any]:
        """Validate height input in various formats"""
        import re
        
        # Handle feet/inches: 5'8", 5'8, 5ft 8in, etc.
        feet_inches_pattern = r"(\d+)['\s]*(?:ft)?['\s]*(\d+)(?:\"|\s*in)?"
        match = re.search(feet_inches_pattern, value)
        
        if match:
            feet = int(match.group(1))
            inches = int(match.group(2)) if match.group(2) else 0
            cm = round((feet * 12 + inches) * 2.54, 1)
            return {"valid": True, "normalized_value": cm}
        
        # Handle cm: 180cm, 180
        cm_pattern = r"(\d+(?:\.\d+)?)\s*cm?"
        match = re.search(cm_pattern, value)
        if match:
            cm = float(match.group(1))
            if 100 <= cm <= 250:
                return {"valid": True, "normalized_value": cm}
        
        return {"valid": False, "error_message": "Please enter height like '5\\'8\"' or '173cm'."}
    
    def _validate_weight(self, value: str, context: Dict) -> Dict[str, Any]:
        """Validate weight input"""
        import re
        
        # Handle lbs: 165lbs, 165 lbs, 165
        lbs_pattern = r"(\d+(?:\.\d+)?)\s*(?:lbs?|pounds?)?"
        match = re.search(lbs_pattern, value)
        
        if match:
            lbs = float(match.group(1))
            if 50 <= lbs <= 500:  # Reasonable range
                kg = round(lbs * 0.453592, 1)
                return {"valid": True, "normalized_value": {"lbs": lbs, "kg": kg}}
        
        # Handle kg: 75kg, 75
        kg_pattern = r"(\d+(?:\.\d+)?)\s*kg"
        match = re.search(kg_pattern, value)
        if match:
            kg = float(match.group(1))
            if 25 <= kg <= 200:
                lbs = round(kg * 2.20462, 1)
                return {"valid": True, "normalized_value": {"kg": kg, "lbs": lbs}}
        
        return {"valid": False, "error_message": "Please enter weight like '165lbs' or '75kg'."}
    
    def _validate_training_age(self, value: str, context: Dict) -> Dict[str, Any]:
        """Validate training experience"""
        mapping = {
            "Beginner (0-6 months)": "beginner",
            "Novice (6-18 months)": "novice", 
            "Intermediate (1.5-3 years)": "intermediate",
            "Advanced (3+ years)": "advanced"
        }
        
        if value in mapping:
            return {"valid": True, "normalized_value": mapping[value]}
        
        # Handle free text
        lower_val = value.lower()
        if any(word in lower_val for word in ["beginner", "new", "start"]):
            return {"valid": True, "normalized_value": "beginner"}
        elif any(word in lower_val for word in ["intermediate", "year", "experienced"]):
            return {"valid": True, "normalized_value": "intermediate"}
        elif any(word in lower_val for word in ["advanced", "expert", "competitive"]):
            return {"valid": True, "normalized_value": "advanced"}
        else:
            return {"valid": True, "normalized_value": "novice"}  # Default
    
    def _validate_equipment(self, value: str, context: Dict) -> Dict[str, Any]:
        """Validate equipment selection"""
        valid_options = ["Home - minimal", "Home - dumbbells", "Home - full gym", "Commercial gym"]
        
        if value in valid_options:
            return {"valid": True, "normalized_value": value}
        
        # Handle free text mapping
        lower_val = value.lower()
        if any(word in lower_val for word in ["gym", "commercial", "fitness center"]):
            return {"valid": True, "normalized_value": "Commercial gym"}
        elif any(word in lower_val for word in ["dumbbell", "weights", "home gym"]):
            return {"valid": True, "normalized_value": "Home - dumbbells"}
        elif any(word in lower_val for word in ["minimal", "bodyweight", "none"]):
            return {"valid": True, "normalized_value": "Home - minimal"}
        else:
            return {"valid": True, "normalized_value": "Home - dumbbells"}  # Safe default
    
    def _validate_days_per_week(self, value: str, context: Dict) -> Dict[str, Any]:
        """Validate days per week"""
        import re
        
        # Extract number from text
        number_match = re.search(r'(\d+)', value)
        if number_match:
            days = int(number_match.group(1))
            if 1 <= days <= 7:
                return {"valid": True, "normalized_value": days}
        
        return {"valid": False, "error_message": "Please enter a number between 1 and 7 days per week."}
    
    def _validate_goal_type(self, value: str, context: Dict) -> Dict[str, Any]:
        """Validate goal type"""
        mapping = {
            "Build muscle": "hypertrophy",
            "Lose fat": "fat_loss",
            "Get stronger": "strength", 
            "Improve endurance": "endurance",
            "General health": "general"
        }
        
        if value in mapping:
            return {"valid": True, "normalized_value": mapping[value]}
        
        # Handle free text
        lower_val = value.lower()
        if any(word in lower_val for word in ["muscle", "mass", "size", "hypertrophy"]):
            return {"valid": True, "normalized_value": "hypertrophy"}
        elif any(word in lower_val for word in ["strength", "strong", "power"]):
            return {"valid": True, "normalized_value": "strength"}
        elif any(word in lower_val for word in ["fat", "lose", "cut", "lean"]):
            return {"valid": True, "normalized_value": "fat_loss"}
        elif any(word in lower_val for word in ["endurance", "cardio", "stamina"]):
            return {"valid": True, "normalized_value": "endurance"}
        else:
            return {"valid": True, "normalized_value": "general"}
    
    def _validate_generic(self, value: str, context: Dict) -> Dict[str, Any]:
        """Generic validator for simple text fields"""
        return {"valid": True, "normalized_value": value}
    
    def _is_stage_complete(self, stage: str, collected: Dict) -> bool:
        """Check if current stage has all required fields"""
        required_fields = self.stages.get(stage, {}).get("fields", [])
        return all(field in collected for field in required_fields)
    
    async def start_conversation(self, user_id: uuid.UUID, flow_type: str = "chat_onboarding", context: Dict = None) -> Dict[str, Any]:
        """Start a new conversational onboarding session"""
        try:
            from sqlalchemy.orm import sessionmaker
            
            # Create new session
            session_uuid = uuid.uuid4()
            session = FitnessOnboardingSession(
                id=session_uuid,
                user_id=user_id,
                stage="profile",
                collected_answers={},
                raw_answers={},
                status="active",
                current_question=None
            )
            
            # Save to database
            self.db.add(session)
            self.db.commit()
            
            # Initialize session state in Redis
            initial_state = {
                "conversation_history": [],
                "current_stage": "profile",
                "context": context or {}
            }
            self.update_session_state(str(session_uuid), initial_state)
            
            # Get first question
            question_data = self.get_next_question(session)
            
            # Create initial response
            message = question_data.get("prompt", "Let's start your fitness journey!")
            
            return {
                "session_id": str(session_uuid),
                "stage": session.stage,
                "message": message,
                "progress": 0.0,
                "can_go_back": False,
                "completed": False,
                "conversation_history": []
            }
            
        except Exception as e:
            return {"error": f"Failed to start conversation: {str(e)}"}
    
    async def process_message(self, session_id: str, user_message: str, user_id: str, context: Dict = None) -> Dict[str, Any]:
        """Process user message and advance conversation"""
        try:
            # Get session state from Redis
            session_state = self.get_session_state(session_id)
            if not session_state:
                return {"error": "Session not found or expired"}
            
            # Add user message to history
            conversation_history = session_state.get("conversation_history", [])
            conversation_history.append({
                "role": "user",
                "content": user_message,
                "timestamp": datetime.utcnow().isoformat()
            })
            
            # Load actual session from database
            from uuid import UUID
            session = self.db.query(FitnessOnboardingSession).filter(
                FitnessOnboardingSession.id == UUID(session_id)
            ).first()
            
            if not session:
                return {"error": "Session not found in database"}
            
            # Update session with current state
            session.stage = session_state.get("current_stage", session.stage)
            session.collected_answers = session_state.get("collected_answers", {})
            session.raw_answers = session_state.get("raw_answers", {})
            
            # Validate and process the user's answer
            current_question = self.get_next_question(session)
            field_name = current_question.get("field")
            
            if field_name:
                # Validate the user's response
                validation = self._validate_answer(field_name, user_message, session_state.get("collected_answers", {}))
                
                if validation["valid"]:
                    # Store the validated answer
                    collected_answers = session_state.get("collected_answers", {})
                    raw_answers = session_state.get("raw_answers", {})
                    
                    collected_answers[field_name] = validation["normalized_value"]
                    raw_answers[field_name] = user_message
                    
                    session_state["collected_answers"] = collected_answers
                    session_state["raw_answers"] = raw_answers
                    
                    # Check if stage is complete and advance if needed
                    current_stage = session_state.get("current_stage", "profile")
                    if self._is_stage_complete(current_stage, collected_answers):
                        next_stage = self.stages.get(current_stage, {}).get("next_stage")
                        if next_stage:
                            session_state["current_stage"] = next_stage
                            session.stage = next_stage
                    # Keep session object in sync for next question resolution
                    session.collected_answers = collected_answers
                    session.raw_answers = raw_answers
                    
                    # Get next question
                    next_question = self.get_next_question(session)
                    assistant_message = next_question.get("prompt", "Great! Let's continue...")
                    
                else:
                    assistant_message = validation.get("error_message", "I didn't understand that. Could you try again?")
            else:
                assistant_message = "I understand. Let's continue with your fitness journey!"
            
            # Add assistant response to history
            conversation_history.append({
                "role": "assistant", 
                "content": assistant_message,
                "timestamp": datetime.utcnow().isoformat()
            })
            
            session_state["conversation_history"] = conversation_history
            
            # Calculate progress
            total_fields = sum(len(stage_info["fields"]) for stage_info in self.stages.values())
            completed_fields = len(session_state.get("collected_answers", {}))
            progress = (completed_fields / total_fields) * 100
            
            # Check if completed
            completed = session_state.get("current_stage") == "completed"
            
            # Save session to database
            self.db.add(session)
            self.db.commit()
            
            # Update session state in Redis
            self.update_session_state(session_id, session_state)
            
            return {
                "session_id": session_id,
                "stage": session_state.get("current_stage", "profile"),
                "message": assistant_message,
                "progress": progress,
                "can_go_back": len(conversation_history) > 2,
                "completed": completed,
                "conversation_history": conversation_history
            }
            
        except Exception as e:
            return {"error": f"Failed to process message: {str(e)}"}
    
    async def get_session_status(self, session_id: str, user_id: str) -> Dict[str, Any]:
        """Get current session status"""
        try:
            session_state = self.get_session_state(session_id)
            if not session_state:
                return {"error": "Session not found or expired"}
            
            return {
                "session_id": session_id,
                "stage": session_state.get("current_stage", "profile"),
                "progress": len(session_state.get("collected_answers", {})) * 10,  # Rough estimate
                "conversation_history": session_state.get("conversation_history", []),
                "completed": session_state.get("current_stage") == "completed"
            }
            
        except Exception as e:
            return {"error": f"Failed to get session status: {str(e)}"}
    
    async def go_back(self, session_id: str, user_id: str) -> Dict[str, Any]:
        """Go back to previous stage in conversation"""
        try:
            session_state = self.get_session_state(session_id)
            if not session_state:
                return {"error": "Session not found or expired"}
            
            # Simple go back - remove last exchange from history
            conversation_history = session_state.get("conversation_history", [])
            if len(conversation_history) >= 2:
                conversation_history = conversation_history[:-2]  # Remove last user + assistant messages
                session_state["conversation_history"] = conversation_history
            
            self.update_session_state(session_id, session_state)
            
            return {
                "session_id": session_id,
                "stage": session_state.get("current_stage", "profile"),
                "message": "Let's go back. What would you like to change?",
                "progress": len(session_state.get("collected_answers", {})) * 10,
                "can_go_back": len(conversation_history) > 2,
                "completed": False,
                "conversation_history": conversation_history
            }
            
        except Exception as e:
            return {"error": f"Failed to go back: {str(e)}"}
    
    async def complete_onboarding(self, session_id: str, user_id: str) -> Dict[str, Any]:
        """Complete onboarding and create fitness plan"""
        try:
            session_state = self.get_session_state(session_id)
            if not session_state:
                return {"error": "Session not found or expired"}
            
            collected_answers = session_state.get("collected_answers", {})
            
            # Generate fitness plan using the collected data
            plan_data = {
                "profile": {
                    "age": collected_answers.get("age"),
                    "sex": collected_answers.get("sex"),
                    "height": collected_answers.get("height"),
                    "weight": collected_answers.get("weight")
                },
                "goals": {
                    "goal_type": collected_answers.get("goal_type", "general"),
                    "target_metrics": collected_answers.get("target_metrics"),
                    "timeframe": collected_answers.get("timeframe")
                },
                "constraints": {
                    "equipment": collected_answers.get("equipment", "Home - minimal"),
                    "days_per_week": collected_answers.get("days_per_week", 3),
                    "time_availability": collected_answers.get("time_availability", 60)
                },
                "preferences": {
                    "style": collected_answers.get("style"),
                    "session_length_cap": collected_answers.get("session_length_cap", 60),
                    "dislikes": collected_answers.get("dislikes", [])
                }
            }
            
            # Generate plan draft
            try:
                draft = self.generator.propose_plan(plan_data)
                plan_draft_id = str(uuid.uuid4())
                
                # In a real implementation, save this to database
                
                # Clean up session state
                self.redis.delete(self.get_redis_key(session_id))
                
                return {
                    "success": True,
                    "message": "Onboarding completed successfully!",
                    "plan_draft_id": plan_draft_id,
                    "plan_summary": {
                        "phases": draft.get("phases", []),
                        "weeks": draft.get("weeks", 4),
                        "days_per_week": collected_answers.get("days_per_week", 3)
                    }
                }
                
            except Exception as e:
                return {"error": f"Failed to generate fitness plan: {str(e)}"}
            
        except Exception as e:
            return {"error": f"Failed to complete onboarding: {str(e)}"}
