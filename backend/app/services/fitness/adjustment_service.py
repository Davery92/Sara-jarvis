"""
Automated Workout Adjustment Service

Implements intelligent workout modification based on readiness scores.
Provides four main adjustment strategies: keep, reduce, swap, move.
Considers user preferences, equipment availability, and schedule constraints.
"""

from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, date, timedelta
import logging
import json
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc, func

from app.models.fitness import Workout, ReadinessAdjustment, FitnessEvent

logger = logging.getLogger(__name__)


class WorkoutAdjustmentService:
    """Handles automated workout adjustments based on readiness assessment"""
    
    def __init__(self):
        # Adjustment thresholds
        self.thresholds = {
            'green': 80,    # Keep workout as planned
            'yellow': 60,   # Reduce intensity/volume
            'red': 40       # Swap or move workout
        }
        
        # Adjustment strategies by readiness score
        self.strategies = {
            'keep': {
                'min_score': 80,
                'description': 'Proceed with workout as planned'
            },
            'reduce': {
                'min_score': 60,
                'max_score': 79,
                'description': 'Reduce intensity or volume'
            },
            'swap': {
                'min_score': 40,
                'max_score': 59,
                'description': 'Swap to easier workout or active recovery'
            },
            'move': {
                'max_score': 39,
                'description': 'Move workout to later date'
            }
        }
        
        # Load exercise substitution catalog
        self.exercise_catalog = self._load_exercise_catalog()
    
    def _load_exercise_catalog(self) -> Dict[str, Any]:
        """Load exercise catalog with difficulty ratings and substitutions"""
        
        # Simplified catalog - in production this would be loaded from database
        return {
            "barbell_squat": {
                "difficulty": 8,
                "pattern": "squat",
                "equipment": ["barbell", "rack"],
                "easier_alternatives": ["goblet_squat", "bodyweight_squat"],
                "recovery_alternatives": ["leg_stretches", "foam_roll"]
            },
            "deadlift": {
                "difficulty": 9,
                "pattern": "hinge",
                "equipment": ["barbell"],
                "easier_alternatives": ["romanian_deadlift", "kettlebell_swing"],
                "recovery_alternatives": ["hip_flexor_stretch", "cat_cow"]
            },
            "bench_press": {
                "difficulty": 7,
                "pattern": "horizontal_push",
                "equipment": ["barbell", "bench"],
                "easier_alternatives": ["dumbbell_press", "pushup"],
                "recovery_alternatives": ["chest_stretch", "arm_circles"]
            },
            "pull_up": {
                "difficulty": 8,
                "pattern": "vertical_pull",
                "equipment": ["pull_up_bar"],
                "easier_alternatives": ["assisted_pull_up", "lat_pulldown"],
                "recovery_alternatives": ["shoulder_rolls", "upper_trap_stretch"]
            },
            "overhead_press": {
                "difficulty": 7,
                "pattern": "vertical_push", 
                "equipment": ["barbell"],
                "easier_alternatives": ["dumbbell_press", "pike_pushup"],
                "recovery_alternatives": ["shoulder_mobility", "neck_stretch"]
            }
        }
    
    async def generate_adjustments(
        self,
        db: Session,
        user_id: str,
        readiness_score: int,
        time_available_min: int,
        today_workout: Optional[Workout] = None
    ) -> Dict[str, Any]:
        """
        Generate workout adjustments based on readiness score and constraints.
        Returns detailed adjustment recommendations with specific modifications.
        """
        try:
            # Determine adjustment strategy
            strategy = self._determine_strategy(readiness_score)
            
            # Get today's workout if not provided
            if not today_workout:
                today_workout = await self._find_todays_workout(db, user_id)
            
            if not today_workout:
                return {
                    "strategy": "no_workout",
                    "message": "No workout scheduled for today",
                    "adjustments": []
                }
            
            # Generate specific adjustments based on strategy
            adjustments = await self._generate_strategy_adjustments(
                db, user_id, strategy, today_workout, readiness_score, time_available_min
            )
            
            # Create adjustment record
            adjustment_record = ReadinessAdjustment(
                user_id=user_id,
                workout_id=today_workout.id,
                readiness_score=readiness_score,
                strategy=strategy,
                original_workout=today_workout.prescription or [],
                proposed_adjustments=adjustments,
                status="proposed",
                created_at=datetime.utcnow()
            )
            db.add(adjustment_record)
            db.flush()
            
            return {
                "adjustment_id": str(adjustment_record.id),
                "strategy": strategy,
                "readiness_score": readiness_score,
                "original_workout": today_workout.prescription,
                "adjustments": adjustments,
                "message": self._get_adjustment_message(strategy, readiness_score),
                "auto_apply": self._should_auto_apply(strategy, readiness_score)
            }
            
        except Exception as e:
            logger.error(f"Failed to generate adjustments for user {user_id}: {e}")
            return {
                "strategy": "error",
                "message": f"Failed to generate adjustments: {str(e)}",
                "adjustments": []
            }
    
    def _determine_strategy(self, readiness_score: int) -> str:
        """Determine adjustment strategy based on readiness score"""
        
        if readiness_score >= self.thresholds['green']:
            return 'keep'
        elif readiness_score >= self.thresholds['yellow']:
            return 'reduce'
        elif readiness_score >= self.thresholds['red']:
            return 'swap'
        else:
            return 'move'
    
    async def _generate_strategy_adjustments(
        self,
        db: Session,
        user_id: str,
        strategy: str,
        workout: Workout,
        readiness_score: int,
        time_available_min: int
    ) -> List[Dict[str, Any]]:
        """Generate specific adjustments based on strategy"""
        
        adjustments = []
        original_blocks = workout.prescription or []
        
        if strategy == 'keep':
            # Minor time-based adjustments only
            if time_available_min < (workout.duration_min or 60):
                adjustments.append({
                    "type": "time_cap",
                    "description": f"Reduce session to fit {time_available_min} minutes",
                    "details": {
                        "target_duration": time_available_min,
                        "adjustment": "trim_accessories"
                    }
                })
        
        elif strategy == 'reduce':
            # Reduce intensity and/or volume
            adjustments.extend(self._generate_reduction_adjustments(
                original_blocks, readiness_score, time_available_min
            ))
        
        elif strategy == 'swap':
            # Swap to easier exercises or active recovery
            adjustments.extend(self._generate_swap_adjustments(
                original_blocks, readiness_score
            ))
        
        elif strategy == 'move':
            # Suggest rescheduling
            next_slot = await self._find_next_available_slot(db, user_id, workout)
            adjustments.append({
                "type": "reschedule",
                "description": "Move workout to when you're feeling better",
                "details": {
                    "suggested_date": next_slot.isoformat() if next_slot else None,
                    "reason": f"Low readiness score ({readiness_score})"
                }
            })
        
        return adjustments
    
    def _generate_reduction_adjustments(
        self, 
        blocks: List[Dict[str, Any]], 
        readiness_score: int,
        time_available_min: int
    ) -> List[Dict[str, Any]]:
        """Generate intensity/volume reduction adjustments"""
        
        adjustments = []
        reduction_factor = self._calculate_reduction_factor(readiness_score)
        
        for i, block in enumerate(blocks):
            block_adjustments = []
            
            # Reduce sets
            original_sets = int(block.get('sets', 3))
            reduced_sets = max(1, int(original_sets * reduction_factor))
            
            if reduced_sets < original_sets:
                block_adjustments.append(f"Reduce sets from {original_sets} to {reduced_sets}")
            
            # Reduce intensity
            if 'intensity' in block:
                block_adjustments.append("Reduce load by 10-15% from planned intensity")
            
            # Extend rest periods
            original_rest = block.get('rest', 60)
            extended_rest = min(180, int(original_rest * 1.2))
            
            if extended_rest > original_rest:
                block_adjustments.append(f"Extend rest from {original_rest}s to {extended_rest}s")
            
            if block_adjustments:
                adjustments.append({
                    "type": "reduce_volume",
                    "block_index": i,
                    "description": f"Block {i+1}: " + ", ".join(block_adjustments),
                    "details": {
                        "original_sets": original_sets,
                        "reduced_sets": reduced_sets,
                        "load_reduction": "10-15%",
                        "rest_extension": extended_rest
                    }
                })
        
        # Time-based adjustments
        if time_available_min < 60:
            adjustments.append({
                "type": "time_cap",
                "description": "Remove accessory exercises to fit available time",
                "details": {
                    "target_duration": time_available_min,
                    "priority": "keep_main_lifts"
                }
            })
        
        return adjustments
    
    def _generate_swap_adjustments(
        self, 
        blocks: List[Dict[str, Any]], 
        readiness_score: int
    ) -> List[Dict[str, Any]]:
        """Generate exercise swap adjustments for easier alternatives"""
        
        adjustments = []
        
        for i, block in enumerate(blocks):
            exercises = block.get('exercises', [])
            swapped_exercises = []
            
            for exercise in exercises:
                if exercise in self.exercise_catalog:
                    catalog_entry = self.exercise_catalog[exercise]
                    
                    # Choose alternative based on readiness score
                    if readiness_score < 50:
                        # Very low readiness - use recovery alternatives
                        alternatives = catalog_entry.get('recovery_alternatives', [])
                    else:
                        # Moderate readiness - use easier alternatives
                        alternatives = catalog_entry.get('easier_alternatives', [])
                    
                    if alternatives:
                        swapped_exercise = alternatives[0]  # Take first alternative
                        swapped_exercises.append({
                            "from": exercise,
                            "to": swapped_exercise,
                            "reason": f"Easier alternative due to readiness score {readiness_score}"
                        })
            
            if swapped_exercises:
                adjustments.append({
                    "type": "exercise_swap",
                    "block_index": i,
                    "description": f"Block {i+1}: Swap to easier exercises",
                    "details": {
                        "swaps": swapped_exercises
                    }
                })
        
        # If very low readiness, suggest full active recovery
        if readiness_score < 45:
            adjustments.append({
                "type": "full_swap",
                "description": "Replace entire workout with active recovery session",
                "details": {
                    "recovery_session": {
                        "duration_min": 20,
                        "exercises": ["light_stretching", "foam_rolling", "walking"],
                        "intensity": "very_light"
                    }
                }
            })
        
        return adjustments
    
    def _calculate_reduction_factor(self, readiness_score: int) -> float:
        """Calculate how much to reduce volume based on readiness score"""
        
        # Scale reduction factor based on readiness score
        # Score 60-79: reduce by 10-30%
        # Score 40-59: reduce by 30-50%
        
        if readiness_score >= 70:
            return 0.9  # 10% reduction
        elif readiness_score >= 60:
            return 0.8  # 20% reduction
        elif readiness_score >= 50:
            return 0.7  # 30% reduction
        else:
            return 0.6  # 40% reduction
    
    async def _find_todays_workout(self, db: Session, user_id: str) -> Optional[Workout]:
        """Find today's scheduled workout"""
        
        today = datetime.utcnow().date()
        
        # Look for workouts scheduled for today
        workout = db.query(Workout).filter(
            and_(
                Workout.user_id == user_id,
                Workout.status == "scheduled"
            )
        ).first()  # Simplified - in production would need proper date filtering
        
        return workout
    
    async def _find_next_available_slot(
        self, 
        db: Session, 
        user_id: str, 
        workout: Workout
    ) -> Optional[datetime]:
        """Find next available slot to reschedule workout"""
        
        # Simple implementation - find next day without conflicts
        current_date = datetime.utcnow().date()
        
        for days_ahead in range(1, 8):  # Look up to 7 days ahead
            target_date = current_date + timedelta(days=days_ahead)
            
            # Check if date has conflicts (simplified check)
            conflicts = db.query(FitnessEvent).filter(
                and_(
                    FitnessEvent.user_id == user_id,
                    func.date(FitnessEvent.starts_at) == target_date
                )
            ).count()
            
            if conflicts == 0:
                # Return suggested time (default 6 PM)
                return datetime.combine(target_date, datetime.min.time().replace(hour=18))
        
        return None
    
    def _get_adjustment_message(self, strategy: str, readiness_score: int) -> str:
        """Get user-friendly message explaining the adjustment strategy"""
        
        messages = {
            'keep': f"Great readiness score ({readiness_score})! Proceed with your planned workout.",
            'reduce': f"Moderate readiness ({readiness_score}). Consider reducing intensity to optimize recovery.",
            'swap': f"Lower readiness ({readiness_score}). Swap to easier exercises or active recovery to avoid overreaching.",
            'move': f"Very low readiness ({readiness_score}). Consider moving workout to tomorrow when you're feeling better."
        }
        
        return messages.get(strategy, "Workout adjustment recommended based on readiness assessment.")
    
    def _should_auto_apply(self, strategy: str, readiness_score: int) -> bool:
        """Determine if adjustments should be auto-applied or require user confirmation"""
        
        # Auto-apply minor adjustments, require confirmation for major changes
        auto_apply_strategies = {
            'keep': True,      # No changes needed
            'reduce': False,   # User should confirm volume reductions
            'swap': False,     # User should confirm exercise swaps  
            'move': False      # User should confirm rescheduling
        }
        
        return auto_apply_strategies.get(strategy, False)
    
    async def apply_adjustments(
        self,
        db: Session,
        adjustment_id: str,
        user_confirmation: bool = True
    ) -> Dict[str, Any]:
        """Apply approved adjustments to the workout"""
        
        try:
            # Get adjustment record
            adjustment = db.query(ReadinessAdjustment).filter(
                ReadinessAdjustment.id == adjustment_id
            ).first()
            
            if not adjustment:
                return {
                    "success": False,
                    "error": "Adjustment record not found"
                }
            
            # Get associated workout
            workout = db.query(Workout).filter(
                Workout.id == adjustment.workout_id
            ).first()
            
            if not workout:
                return {
                    "success": False,
                    "error": "Associated workout not found"
                }
            
            # Apply adjustments to workout
            applied_changes = []
            
            for adj in adjustment.proposed_adjustments:
                change = await self._apply_single_adjustment(workout, adj)
                if change:
                    applied_changes.append(change)
            
            # Update adjustment status
            adjustment.status = "applied"
            adjustment.applied_at = datetime.utcnow()
            adjustment.user_confirmed = user_confirmation
            
            db.add(adjustment)
            db.add(workout)
            db.commit()
            
            return {
                "success": True,
                "adjustment_id": adjustment_id,
                "changes_applied": applied_changes,
                "message": f"Applied {len(applied_changes)} adjustments to workout"
            }
            
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to apply adjustments {adjustment_id}: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def _apply_single_adjustment(
        self, 
        workout: Workout, 
        adjustment: Dict[str, Any]
    ) -> Optional[str]:
        """Apply a single adjustment to the workout"""
        
        adj_type = adjustment.get("type")
        details = adjustment.get("details", {})
        
        if adj_type == "reduce_volume":
            # Reduce sets in specified block
            block_index = adjustment.get("block_index", 0)
            if workout.prescription and block_index < len(workout.prescription):
                block = workout.prescription[block_index]
                original_sets = block.get("sets", 3)
                new_sets = details.get("reduced_sets", max(1, original_sets - 1))
                block["sets"] = new_sets
                return f"Reduced sets from {original_sets} to {new_sets} in block {block_index + 1}"
        
        elif adj_type == "exercise_swap":
            # Swap exercises in specified block
            block_index = adjustment.get("block_index", 0)
            if workout.prescription and block_index < len(workout.prescription):
                block = workout.prescription[block_index]
                swaps = details.get("swaps", [])
                
                for swap in swaps:
                    from_ex = swap.get("from")
                    to_ex = swap.get("to")
                    
                    if "exercises" in block:
                        exercises = block["exercises"]
                        for i, ex in enumerate(exercises):
                            if ex == from_ex:
                                exercises[i] = to_ex
                
                return f"Swapped exercises in block {block_index + 1}"
        
        elif adj_type == "time_cap":
            # Reduce workout duration
            target_duration = details.get("target_duration", 45)
            workout.duration_min = target_duration
            return f"Capped workout duration to {target_duration} minutes"
        
        elif adj_type == "full_swap":
            # Replace with recovery session
            recovery_session = details.get("recovery_session", {})
            workout.prescription = [{
                "exercises": recovery_session.get("exercises", ["stretching"]),
                "sets": 1,
                "duration_min": recovery_session.get("duration_min", 20)
            }]
            workout.duration_min = recovery_session.get("duration_min", 20)
            return "Replaced workout with active recovery session"
        
        return None