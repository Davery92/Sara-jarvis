"""
Fitness Plan Generation Service

Generates personalized workout plans based on user profile, goals, and constraints.
Uses plan templates and applies equipment substitutions and time constraints.
"""

from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
import json
import uuid
from sqlalchemy.orm import Session

from app.models.fitness import PlanTemplate, ExerciseLibrary, MovementPattern
from app.db.session import SessionLocal


class FitnessPlanGenerator:
    """Generates personalized fitness plans from templates"""
    
    def __init__(self):
        self.templates = self._load_built_in_templates()
        self.exercise_catalog = self._load_exercise_catalog()
    
    def _load_built_in_templates(self) -> List[Dict[str, Any]]:
        """Load built-in plan templates"""
        return [
            {
                "id": "3day_full_body",
                "name": "3-Day Full Body",
                "template_type": "full_body",
                "days_per_week": 3,
                "weeks_per_phase": 4,
                "difficulty_level": 2,
                "primary_goals": ["strength", "hypertrophy", "general"],
                "phases": [
                    {"name": "Base", "weeks": 4, "rpe_range": [6, 7]},
                    {"name": "Build", "weeks": 4, "rpe_range": [7, 8]},
                    {"name": "Peak", "weeks": 2, "rpe_range": [8, 9]},
                    {"name": "Deload", "weeks": 1, "rpe_range": [5, 6]}
                ],
                "workout_templates": [
                    {
                        "title": "Full Body A",
                        "duration_min": 60,
                        "blocks": [
                            {
                                "type": "main",
                                "exercises": [
                                    {
                                        "id": "squat",
                                        "name": "Back Squat",
                                        "movement_pattern": "squat",
                                        "sets": 4,
                                        "reps": "5-8",
                                        "rpe": 8,
                                        "rest_sec": 120
                                    },
                                    {
                                        "id": "bench_press", 
                                        "name": "Bench Press",
                                        "movement_pattern": "horizontal_push",
                                        "sets": 4,
                                        "reps": "5-8", 
                                        "rpe": 8,
                                        "rest_sec": 120
                                    },
                                    {
                                        "id": "bent_row",
                                        "name": "Bent-Over Row", 
                                        "movement_pattern": "horizontal_pull",
                                        "sets": 3,
                                        "reps": "8-12",
                                        "rpe": 7,
                                        "rest_sec": 90
                                    }
                                ]
                            },
                            {
                                "type": "accessory",
                                "exercises": [
                                    {
                                        "id": "overhead_press",
                                        "name": "Overhead Press",
                                        "movement_pattern": "vertical_push", 
                                        "sets": 3,
                                        "reps": "8-12",
                                        "rpe": 7,
                                        "rest_sec": 90
                                    },
                                    {
                                        "id": "plank",
                                        "name": "Plank",
                                        "movement_pattern": "core",
                                        "sets": 3,
                                        "reps": "30-60s",
                                        "rpe": 6,
                                        "rest_sec": 60
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        "title": "Full Body B", 
                        "duration_min": 60,
                        "blocks": [
                            {
                                "type": "main",
                                "exercises": [
                                    {
                                        "id": "deadlift",
                                        "name": "Deadlift",
                                        "movement_pattern": "hinge",
                                        "sets": 3,
                                        "reps": "3-5",
                                        "rpe": 8,
                                        "rest_sec": 180
                                    },
                                    {
                                        "id": "pullup",
                                        "name": "Pull-up",
                                        "movement_pattern": "vertical_pull",
                                        "sets": 4,
                                        "reps": "5-10",
                                        "rpe": 7,
                                        "rest_sec": 120
                                    },
                                    {
                                        "id": "dumbbell_press",
                                        "name": "Dumbbell Press",
                                        "movement_pattern": "horizontal_push",
                                        "sets": 3,
                                        "reps": "8-12",
                                        "rpe": 7,
                                        "rest_sec": 90
                                    }
                                ]
                            },
                            {
                                "type": "accessory",
                                "exercises": [
                                    {
                                        "id": "lunges",
                                        "name": "Lunges",
                                        "movement_pattern": "single_leg",
                                        "sets": 3,
                                        "reps": "10-15",
                                        "rpe": 6,
                                        "rest_sec": 60
                                    },
                                    {
                                        "id": "side_plank",
                                        "name": "Side Plank",
                                        "movement_pattern": "core",
                                        "sets": 3,
                                        "reps": "20-45s",
                                        "rpe": 6,
                                        "rest_sec": 60
                                    }
                                ]
                            }
                        ]
                    }
                ],
                "equipment_required": ["barbell", "dumbbells", "bench", "pullup_bar"],
                "substitution_rules": {
                    "no_barbell": {
                        "squat": "goblet_squat",
                        "bench_press": "pushup",
                        "deadlift": "kettlebell_deadlift",
                        "bent_row": "dumbbell_row"
                    },
                    "no_pullup_bar": {
                        "pullup": "lat_pulldown"
                    }
                },
                "progression_rules": {
                    "strength": "increase_weight",
                    "hypertrophy": "increase_reps_then_weight",
                    "endurance": "increase_reps"
                }
            }
        ]
    
    def _load_exercise_catalog(self) -> Dict[str, Dict[str, Any]]:
        """Load exercise substitution catalog"""
        return {
            "goblet_squat": {
                "name": "Goblet Squat",
                "movement_pattern": "squat",
                "equipment_required": ["dumbbell"],
                "difficulty_level": 1
            },
            "pushup": {
                "name": "Push-up",
                "movement_pattern": "horizontal_push", 
                "equipment_required": [],
                "difficulty_level": 1
            },
            "kettlebell_deadlift": {
                "name": "Kettlebell Deadlift",
                "movement_pattern": "hinge",
                "equipment_required": ["kettlebell"],
                "difficulty_level": 2
            },
            "dumbbell_row": {
                "name": "Dumbbell Row",
                "movement_pattern": "horizontal_pull",
                "equipment_required": ["dumbbell"],
                "difficulty_level": 2
            },
            "lat_pulldown": {
                "name": "Lat Pulldown",
                "movement_pattern": "vertical_pull",
                "equipment_required": ["cable_machine"],
                "difficulty_level": 2
            }
        }
    
    def _select_template(self, requirements: Dict[str, Any]) -> Dict[str, Any]:
        """Select the best template based on requirements"""
        goal_type = requirements.get("goals", {}).get("goal_type", "general")
        days_per_week = requirements.get("days_per_week", 3)
        experience = requirements.get("profile", {}).get("experience", "beginner")
        
        # Simple template selection logic
        if days_per_week <= 3:
            return self.templates[0]  # 3-day full body
        else:
            # For now, just return the 3-day template
            return self.templates[0]
    
    def _substitute_exercises(self, workout_templates: List[Dict[str, Any]], available_equipment: List[str]) -> List[Dict[str, Any]]:
        """Apply equipment-based exercise substitutions"""
        if not available_equipment:
            available_equipment = []
            
        substituted_templates = []
        
        for template in workout_templates:
            new_template = template.copy()
            new_blocks = []
            
            for block in template.get("blocks", []):
                new_block = block.copy()
                new_exercises = []
                
                for exercise in block.get("exercises", []):
                    # Check if we need to substitute this exercise
                    if self._needs_substitution(exercise, available_equipment):
                        substitute = self._find_substitute(exercise, available_equipment)
                        if substitute:
                            new_exercises.append(substitute)
                        else:
                            new_exercises.append(exercise)  # Keep original if no substitute
                    else:
                        new_exercises.append(exercise)
                
                new_block["exercises"] = new_exercises
                new_blocks.append(new_block)
            
            new_template["blocks"] = new_blocks
            substituted_templates.append(new_template)
        
        return substituted_templates
    
    def _needs_substitution(self, exercise: Dict[str, Any], available_equipment: List[str]) -> bool:
        """Check if exercise needs equipment substitution"""
        exercise_id = exercise.get("id", "")
        
        # Simple rules - could be made more sophisticated
        if exercise_id in ["squat", "bench_press", "deadlift", "bent_row"] and "barbell" not in available_equipment:
            return True
        if exercise_id == "pullup" and "pullup_bar" not in available_equipment:
            return True
            
        return False
    
    def _find_substitute(self, exercise: Dict[str, Any], available_equipment: List[str]) -> Optional[Dict[str, Any]]:
        """Find a suitable substitute exercise"""
        exercise_id = exercise.get("id", "")
        
        substitutes = {
            "squat": "goblet_squat" if "dumbbell" in available_equipment else None,
            "bench_press": "pushup",
            "deadlift": "kettlebell_deadlift" if "kettlebell" in available_equipment else "dumbbell_row",
            "bent_row": "dumbbell_row" if "dumbbell" in available_equipment else None,
            "pullup": "lat_pulldown" if "cable_machine" in available_equipment else "dumbbell_row"
        }
        
        substitute_id = substitutes.get(exercise_id)
        if substitute_id and substitute_id in self.exercise_catalog:
            substitute_info = self.exercise_catalog[substitute_id]
            new_exercise = exercise.copy()
            new_exercise.update({
                "id": substitute_id,
                "name": substitute_info["name"],
                "movement_pattern": substitute_info["movement_pattern"]
            })
            return new_exercise
            
        return None
    
    def _apply_time_cap(self, workout_template: Dict[str, Any], session_len_min: int, catalog: Dict[str, Any]) -> Dict[str, Any]:
        """Apply time constraints to workout"""
        if not session_len_min:
            return workout_template
            
        # Estimate current workout duration
        estimated_duration = self._estimate_duration(workout_template)
        
        if estimated_duration <= session_len_min:
            return workout_template  # No changes needed
            
        # Need to trim the workout
        new_template = workout_template.copy()
        new_blocks = []
        
        # Priority: keep main lifts, trim accessories first
        for block in workout_template.get("blocks", []):
            if block.get("type") == "main":
                new_blocks.append(block)
            elif block.get("type") == "accessory" and len(new_blocks) == 1:
                # Keep some accessories if we have room
                trimmed_block = self._trim_block(block, session_len_min - estimated_duration + 10)
                if trimmed_block.get("exercises"):
                    new_blocks.append(trimmed_block)
        
        new_template["blocks"] = new_blocks
        new_template["duration_min"] = session_len_min
        
        return new_template
    
    def _estimate_duration(self, workout_template: Dict[str, Any]) -> int:
        """Estimate workout duration in minutes"""
        total_minutes = 10  # warmup/cooldown
        
        for block in workout_template.get("blocks", []):
            for exercise in block.get("exercises", []):
                sets = exercise.get("sets", 3)
                rest_sec = exercise.get("rest_sec", 60)
                work_time = 30  # assume 30 seconds per set
                
                total_minutes += (sets * (work_time + rest_sec)) / 60
                
        return int(total_minutes)
    
    def _trim_block(self, block: Dict[str, Any], target_reduction_min: int) -> Dict[str, Any]:
        """Trim exercises from a block to reduce duration"""
        new_block = block.copy()
        exercises = block.get("exercises", [])
        
        # Remove the last exercise first (usually least important)
        if len(exercises) > 1 and target_reduction_min > 5:
            new_block["exercises"] = exercises[:-1]
        else:
            new_block["exercises"] = exercises
            
        return new_block
    
    def _load_catalog(self) -> Dict[str, Any]:
        """Load exercise catalog for duration calculations"""
        return self.exercise_catalog
    
    def generate_plan(self, requirements: Dict[str, Any]) -> Dict[str, Any]:
        """Generate a complete fitness plan"""
        # Select template
        template = self._select_template(requirements)
        
        # Apply substitutions
        available_equipment = requirements.get("equipment", [])
        workout_templates = self._substitute_exercises(
            template["workout_templates"], 
            available_equipment
        )
        
        # Apply time constraints
        session_len_min = requirements.get("session_len_min", 60)
        time_capped_templates = []
        for template in workout_templates:
            time_capped = self._apply_time_cap(template, session_len_min, self.exercise_catalog)
            time_capped_templates.append(time_capped)
        
        # Generate plan structure
        plan_id = str(uuid.uuid4())
        return {
            "plan_id": plan_id,
            "name": template["name"],
            "phases": template["phases"],
            "weeks": template.get("weeks_per_phase", 4) * len(template["phases"]),
            "days_per_week": template["days_per_week"],
            "workout_templates": time_capped_templates,
            "meta": {
                "template_id": template["id"],
                "equipment_used": available_equipment,
                "difficulty_level": template["difficulty_level"],
                "primary_goals": template["primary_goals"]
            }
        }