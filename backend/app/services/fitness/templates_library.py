"""
Fitness Plan Templates Library

Comprehensive library of workout plan templates for different goals, experience levels,
and equipment availability. Supports progression rules and substitution matrices.
"""

from typing import Dict, List, Any, Optional
import json


class FitnessTemplatesLibrary:
    """Library of fitness plan templates with progression and substitution rules"""
    
    def __init__(self):
        self.templates = self._load_all_templates()
        self.exercise_database = self._load_exercise_database()
        self.substitution_matrix = self._load_substitution_matrix()
    
    def get_templates_by_criteria(
        self, 
        goal_type: str = None,
        days_per_week: int = None, 
        experience: str = None,
        equipment: List[str] = None
    ) -> List[Dict[str, Any]]:
        """Get templates matching specified criteria"""
        matching_templates = []
        
        for template in self.templates:
            if goal_type and goal_type not in template.get("primary_goals", []):
                continue
            if days_per_week and template.get("days_per_week") != days_per_week:
                continue
            if experience and not self._matches_experience(template, experience):
                continue
            if equipment and not self._has_required_equipment(template, equipment):
                continue
                
            matching_templates.append(template)
        
        return matching_templates
    
    def get_template_by_id(self, template_id: str) -> Optional[Dict[str, Any]]:
        """Get specific template by ID"""
        for template in self.templates:
            if template.get("id") == template_id:
                return template
        return None
    
    def _load_all_templates(self) -> List[Dict[str, Any]]:
        """Load all available plan templates"""
        return [
            self._create_3day_full_body_beginner(),
            self._create_3day_full_body_intermediate(),
            self._create_4day_upper_lower(),
            self._create_5day_ppl(),
            self._create_bodyweight_only(),
            self._create_kettlebell_focused(),
            self._create_strength_focused(),
            self._create_hypertrophy_focused()
        ]
    
    def _create_3day_full_body_beginner(self) -> Dict[str, Any]:
        """3-day full body template for beginners"""
        return {
            "id": "3day_fb_beginner",
            "name": "3-Day Full Body (Beginner)",
            "description": "Perfect starter program focusing on compound movements and proper form",
            "template_type": "full_body",
            "days_per_week": 3,
            "weeks_per_phase": 4,
            "difficulty_level": 1,
            "experience_levels": ["beginner"],
            "primary_goals": ["general", "strength", "hypertrophy"],
            "equipment_required": ["barbell", "dumbbells", "bench"],
            "phases": [
                {"name": "Foundation", "weeks": 4, "rpe_range": [6, 7], "focus": "form and consistency"},
                {"name": "Progress", "weeks": 4, "rpe_range": [6, 8], "focus": "gradual loading"},
                {"name": "Develop", "weeks": 4, "rpe_range": [7, 8], "focus": "strength building"}
            ],
            "workout_templates": [
                {
                    "day": 1,
                    "title": "Full Body A",
                    "duration_min": 45,
                    "blocks": [
                        {
                            "type": "warmup",
                            "duration_min": 5,
                            "exercises": [
                                {"name": "Dynamic Warmup", "sets": 1, "reps": "5-10 min", "rpe": 3}
                            ]
                        },
                        {
                            "type": "main",
                            "exercises": [
                                {
                                    "id": "squat",
                                    "name": "Goblet Squat", 
                                    "movement_pattern": "squat",
                                    "sets": 3,
                                    "reps": "8-12",
                                    "rpe": 7,
                                    "rest_sec": 90,
                                    "progression": "reps_then_weight",
                                    "notes": "Focus on depth and control"
                                },
                                {
                                    "id": "pushup",
                                    "name": "Push-up (knee or full)",
                                    "movement_pattern": "horizontal_push",
                                    "sets": 3, 
                                    "reps": "5-10",
                                    "rpe": 7,
                                    "rest_sec": 90,
                                    "progression": "reps_then_progression",
                                    "notes": "Knee version OK for beginners"
                                },
                                {
                                    "id": "bent_row",
                                    "name": "Bent-Over Dumbbell Row",
                                    "movement_pattern": "horizontal_pull", 
                                    "sets": 3,
                                    "reps": "8-12",
                                    "rpe": 7,
                                    "rest_sec": 90,
                                    "progression": "reps_then_weight"
                                }
                            ]
                        },
                        {
                            "type": "accessory",
                            "exercises": [
                                {
                                    "id": "plank",
                                    "name": "Plank Hold",
                                    "movement_pattern": "core",
                                    "sets": 3,
                                    "reps": "20-45s",
                                    "rpe": 6,
                                    "rest_sec": 60,
                                    "progression": "duration"
                                }
                            ]
                        }
                    ]
                },
                {
                    "day": 2,
                    "title": "Full Body B", 
                    "duration_min": 45,
                    "blocks": [
                        {
                            "type": "warmup",
                            "duration_min": 5,
                            "exercises": [
                                {"name": "Dynamic Warmup", "sets": 1, "reps": "5-10 min", "rpe": 3}
                            ]
                        },
                        {
                            "type": "main",
                            "exercises": [
                                {
                                    "id": "hinge",
                                    "name": "Romanian Deadlift",
                                    "movement_pattern": "hinge",
                                    "sets": 3,
                                    "reps": "8-12", 
                                    "rpe": 7,
                                    "rest_sec": 90,
                                    "progression": "reps_then_weight",
                                    "notes": "Focus on hip hinge pattern"
                                },
                                {
                                    "id": "vertical_push",
                                    "name": "Dumbbell Shoulder Press",
                                    "movement_pattern": "vertical_push",
                                    "sets": 3,
                                    "reps": "8-12",
                                    "rpe": 7,
                                    "rest_sec": 90,
                                    "progression": "reps_then_weight"
                                },
                                {
                                    "id": "lunge",
                                    "name": "Reverse Lunge",
                                    "movement_pattern": "single_leg",
                                    "sets": 3,
                                    "reps": "8-10 each leg",
                                    "rpe": 6,
                                    "rest_sec": 90,
                                    "progression": "reps_then_weight"
                                }
                            ]
                        },
                        {
                            "type": "accessory", 
                            "exercises": [
                                {
                                    "id": "side_plank",
                                    "name": "Side Plank",
                                    "movement_pattern": "core",
                                    "sets": 3,
                                    "reps": "15-30s each side",
                                    "rpe": 6,
                                    "rest_sec": 60,
                                    "progression": "duration"
                                }
                            ]
                        }
                    ]
                },
                {
                    "day": 3,
                    "title": "Full Body C",
                    "duration_min": 45,
                    "blocks": [
                        {
                            "type": "warmup",
                            "duration_min": 5,
                            "exercises": [
                                {"name": "Dynamic Warmup", "sets": 1, "reps": "5-10 min", "rpe": 3}
                            ]
                        },
                        {
                            "type": "main",
                            "exercises": [
                                {
                                    "id": "step_up",
                                    "name": "Step-up or Box Step",
                                    "movement_pattern": "single_leg",
                                    "sets": 3,
                                    "reps": "8-10 each leg",
                                    "rpe": 6,
                                    "rest_sec": 90,
                                    "progression": "reps_then_height"
                                },
                                {
                                    "id": "incline_push",
                                    "name": "Incline Push-up",
                                    "movement_pattern": "horizontal_push",
                                    "sets": 3,
                                    "reps": "6-12",
                                    "rpe": 7,
                                    "rest_sec": 90,
                                    "progression": "reps_then_decline_angle"
                                },
                                {
                                    "id": "assisted_pullup",
                                    "name": "Assisted Pull-up or Lat Pulldown",
                                    "movement_pattern": "vertical_pull",
                                    "sets": 3,
                                    "reps": "5-10", 
                                    "rpe": 7,
                                    "rest_sec": 90,
                                    "progression": "reps_then_less_assistance"
                                }
                            ]
                        },
                        {
                            "type": "accessory",
                            "exercises": [
                                {
                                    "id": "dead_bug",
                                    "name": "Dead Bug",
                                    "movement_pattern": "core",
                                    "sets": 3,
                                    "reps": "8-12 each side",
                                    "rpe": 5,
                                    "rest_sec": 60,
                                    "progression": "reps"
                                }
                            ]
                        }
                    ]
                }
            ],
            "progression_rules": {
                "reps_then_weight": "Increase reps first, then add weight when hitting top of range",
                "reps_then_progression": "Master current progression before advancing to harder variant",
                "duration": "Increase hold time by 5-10s each week"
            },
            "substitution_rules": {
                "no_dumbbells": {
                    "goblet_squat": "bodyweight_squat",
                    "bent_row": "inverted_row"
                },
                "no_bench": {
                    "incline_pushup": "wall_pushup"
                }
            }
        }
    
    def _create_4day_upper_lower(self) -> Dict[str, Any]:
        """4-day upper/lower split for intermediate trainees"""
        return {
            "id": "4day_upper_lower",
            "name": "4-Day Upper/Lower Split",
            "description": "Classic upper/lower split for balanced development",
            "template_type": "upper_lower",
            "days_per_week": 4,
            "weeks_per_phase": 4,
            "difficulty_level": 2,
            "experience_levels": ["intermediate", "advanced"],
            "primary_goals": ["hypertrophy", "strength"],
            "equipment_required": ["barbell", "dumbbells", "bench", "pullup_bar"],
            "phases": [
                {"name": "Base", "weeks": 3, "rpe_range": [7, 8]},
                {"name": "Intensify", "weeks": 3, "rpe_range": [8, 9]},
                {"name": "Peak", "weeks": 2, "rpe_range": [8, 9]},
                {"name": "Deload", "weeks": 1, "rpe_range": [6, 7]}
            ],
            "workout_templates": [
                {
                    "day": 1,
                    "title": "Upper Body A",
                    "duration_min": 75,
                    "blocks": [
                        {
                            "type": "main",
                            "exercises": [
                                {
                                    "id": "bench_press",
                                    "name": "Barbell Bench Press", 
                                    "movement_pattern": "horizontal_push",
                                    "sets": 4,
                                    "reps": "6-8",
                                    "rpe": 8,
                                    "rest_sec": 180
                                },
                                {
                                    "id": "bent_row",
                                    "name": "Barbell Bent Row",
                                    "movement_pattern": "horizontal_pull",
                                    "sets": 4,
                                    "reps": "6-8", 
                                    "rpe": 8,
                                    "rest_sec": 180
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
                                    "rest_sec": 120
                                },
                                {
                                    "id": "pullup",
                                    "name": "Pull-ups",
                                    "movement_pattern": "vertical_pull", 
                                    "sets": 3,
                                    "reps": "6-12",
                                    "rpe": 7,
                                    "rest_sec": 120
                                },
                                {
                                    "id": "dips",
                                    "name": "Dips",
                                    "movement_pattern": "vertical_push",
                                    "sets": 3,
                                    "reps": "8-15",
                                    "rpe": 7,
                                    "rest_sec": 90
                                }
                            ]
                        }
                    ]
                }
                # Additional days would be defined here...
            ]
        }
    
    def _create_bodyweight_only(self) -> Dict[str, Any]:
        """Bodyweight-only template for home training"""
        return {
            "id": "bodyweight_only",
            "name": "Bodyweight Mastery",
            "description": "Complete bodyweight program requiring no equipment",
            "template_type": "bodyweight", 
            "days_per_week": 3,
            "weeks_per_phase": 6,
            "difficulty_level": 1,
            "experience_levels": ["beginner", "intermediate"],
            "primary_goals": ["general", "strength", "endurance"],
            "equipment_required": [],
            "phases": [
                {"name": "Foundation", "weeks": 6, "rpe_range": [6, 7]},
                {"name": "Progression", "weeks": 6, "rpe_range": [7, 8]}
            ],
            "workout_templates": [
                {
                    "day": 1,
                    "title": "Push Focus",
                    "duration_min": 40,
                    "blocks": [
                        {
                            "type": "main",
                            "exercises": [
                                {
                                    "id": "pushup_progression",
                                    "name": "Push-up Progression",
                                    "movement_pattern": "horizontal_push",
                                    "sets": 4,
                                    "reps": "5-15",
                                    "rpe": 7,
                                    "rest_sec": 90,
                                    "progressions": ["wall", "incline", "knee", "full", "decline", "one_arm"]
                                },
                                {
                                    "id": "pike_pushup",
                                    "name": "Pike Push-up",
                                    "movement_pattern": "vertical_push",
                                    "sets": 3,
                                    "reps": "5-12",
                                    "rpe": 7,
                                    "rest_sec": 90
                                }
                            ]
                        }
                    ]
                }
            ]
        }
    
    # Simplified stubs for other templates - in real implementation these would be fully defined
    def _create_3day_full_body_intermediate(self) -> Dict[str, Any]:
        return {"id": "3day_fb_intermediate", "name": "3-Day Full Body (Intermediate)"}
    
    def _create_5day_ppl(self) -> Dict[str, Any]:
        return {"id": "5day_ppl", "name": "5-Day Push/Pull/Legs"}
        
    def _create_kettlebell_focused(self) -> Dict[str, Any]:
        return {"id": "kettlebell_focused", "name": "Kettlebell Focused"}
        
    def _create_strength_focused(self) -> Dict[str, Any]:
        return {"id": "strength_focused", "name": "Strength Focused"}
        
    def _create_hypertrophy_focused(self) -> Dict[str, Any]:
        return {"id": "hypertrophy_focused", "name": "Hypertrophy Focused"}
    
    def _load_exercise_database(self) -> Dict[str, Dict[str, Any]]:
        """Load comprehensive exercise database"""
        return {
            "squat": {
                "name": "Back Squat",
                "movement_pattern": "squat",
                "equipment": ["barbell"],
                "muscle_groups": ["quadriceps", "glutes", "core"],
                "difficulty": 3
            },
            "goblet_squat": {
                "name": "Goblet Squat", 
                "movement_pattern": "squat",
                "equipment": ["dumbbell", "kettlebell"],
                "muscle_groups": ["quadriceps", "glutes", "core"],
                "difficulty": 2
            },
            # ... many more exercises would be defined
        }
    
    def _load_substitution_matrix(self) -> Dict[str, Dict[str, str]]:
        """Load exercise substitution matrix"""
        return {
            "equipment_substitutions": {
                "no_barbell": {
                    "back_squat": "goblet_squat",
                    "bench_press": "dumbbell_press",
                    "deadlift": "dumbbell_deadlift", 
                    "bent_row": "dumbbell_row"
                },
                "no_dumbbells": {
                    "dumbbell_press": "pushup",
                    "dumbbell_row": "inverted_row"
                },
                "no_pullup_bar": {
                    "pullup": "lat_pulldown",
                    "chinup": "bicep_curls"
                }
            },
            "injury_substitutions": {
                "lower_back": {
                    "deadlift": "trap_bar_deadlift",
                    "bent_row": "chest_supported_row"
                },
                "knee_issues": {
                    "back_squat": "box_squat", 
                    "lunges": "step_ups"
                },
                "shoulder_issues": {
                    "overhead_press": "incline_press",
                    "pullups": "lat_pulldown"
                }
            }
        }
    
    def _matches_experience(self, template: Dict[str, Any], experience: str) -> bool:
        """Check if template matches experience level"""
        template_levels = template.get("experience_levels", [])
        return experience in template_levels
    
    def _has_required_equipment(self, template: Dict[str, Any], available_equipment: List[str]) -> bool:
        """Check if user has required equipment for template"""
        required = template.get("equipment_required", [])
        if not required:  # No equipment required (bodyweight)
            return True
        return all(eq in available_equipment for eq in required)