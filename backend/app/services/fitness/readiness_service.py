"""
Readiness Assessment Service

Analyzes daily readiness inputs (HRV, sleep, subjective metrics) and provides 
workout adjustments (keep, reduce, swap, move) with personalized baselines.
"""

from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
import json
import uuid
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from app.models.fitness import MorningReadiness, ReadinessBaseline, ReadinessAdjustment, Workout
from app.services.fitness.baseline_learning import BaselineLearningEngine
import math


class ReadinessEngine:
    """Processes daily readiness data and generates workout adjustments"""
    
    def __init__(self):
        self.baseline_period_days = 14
        self.ewma_alpha = 0.3  # Exponential weighted moving average factor
        self.baseline_engine = BaselineLearningEngine()
    
    async def score_and_adjust(self, db: Session, user_id: str, readiness_input: Dict[str, Any]) -> Dict[str, Any]:
        """Main method to score readiness and generate adjustments"""
        
        # Get or create user baseline
        baseline = self._get_or_create_baseline(db, user_id)
        
        # Update baselines with new data using advanced learning algorithm
        today = datetime.utcnow().date()
        health_metrics = {
            k: v for k, v in readiness_input.items() 
            if k in ['hrv_ms', 'rhr', 'sleep_hours'] and v is not None
        }
        
        baseline_update_result = None
        if health_metrics:
            baseline_update_result = await self.baseline_engine.update_user_baselines(
                db, user_id, today, health_metrics
            )
        
        # Calculate readiness score
        score = self._calculate_readiness_score(readiness_input, baseline)
        
        # Determine recommendation
        recommendation = self._get_recommendation(score)
        
        # Create readiness record
        readiness_record = MorningReadiness(
            id=str(uuid.uuid4()),
            user_id=str(user_id),
            hrv_ms=readiness_input.get("hrv_ms"),
            rhr=readiness_input.get("rhr"),
            sleep_hours=readiness_input.get("sleep_hours"),
            energy=readiness_input["energy"],
            soreness=readiness_input["soreness"],
            stress=readiness_input["stress"],
            time_available_min=readiness_input["time_available_min"],
            score=score,
            recommendation=recommendation,
            message=self._generate_message(score, recommendation)
        )
        
        db.add(readiness_record)
        db.flush()
        
        # Apply adjustments to today's workout if found
        adjustments = []
        today_workout = self._find_today_workout(db, user_id)
        
        if today_workout:
            adjustments = self._apply_workout_adjustments(
                db, today_workout, readiness_record, readiness_input
            )
        
        # Update baseline with new data
        self._update_baseline(db, baseline, readiness_input)
        
        db.commit()
        
        return {
            "readiness_id": readiness_record.id,
            "score": score,
            "recommendation": recommendation, 
            "message": readiness_record.message,
            "adjustments": adjustments,
            "baseline_confidence": self._get_baseline_confidence(baseline)
        }
    
    def _get_or_create_baseline(self, db: Session, user_id: str) -> ReadinessBaseline:
        """Get existing baseline or create new one"""
        baseline = db.query(ReadinessBaseline).filter(
            ReadinessBaseline.user_id == str(user_id)
        ).first()
        
        if not baseline:
            baseline = ReadinessBaseline(
                id=str(uuid.uuid4()),
                user_id=str(user_id),
                sample_count=0,
                created_at=datetime.utcnow()
            )
            db.add(baseline)
            db.flush()
            
        return baseline
    
    def _calculate_readiness_score(self, inputs: Dict[str, Any], baseline: ReadinessBaseline) -> int:
        """Calculate composite readiness score (0-100)"""
        
        # Extract inputs
        hrv_ms = inputs.get("hrv_ms")
        rhr = inputs.get("rhr") 
        sleep_hours = inputs.get("sleep_hours")
        energy = inputs["energy"]  # 1-5 scale
        soreness = inputs["soreness"]  # 1-5 scale  
        stress = inputs["stress"]  # 1-5 scale
        
        # Component scores (0-100 each)
        hrv_score = self._score_hrv(hrv_ms, baseline) if hrv_ms else 50
        rhr_score = self._score_rhr(rhr, baseline) if rhr else 50
        sleep_score = self._score_sleep(sleep_hours) if sleep_hours else 50
        subjective_score = self._score_subjective(energy, soreness, stress)
        
        # Weighted composite (matches spec: 40% HRV, 20% RHR, 20% sleep, 20% subjective)
        if baseline.sample_count >= 7:  # Have enough data for HRV/RHR baselines
            composite_score = (
                0.4 * hrv_score + 
                0.2 * rhr_score + 
                0.2 * sleep_score + 
                0.2 * subjective_score
            )
        else:
            # Fall back to more subjective weighting when lacking baseline data
            composite_score = (
                0.1 * hrv_score + 
                0.1 * rhr_score + 
                0.3 * sleep_score + 
                0.5 * subjective_score
            )
        
        return int(max(0, min(100, composite_score)))
    
    def _score_hrv(self, hrv_ms: int, baseline: ReadinessBaseline) -> float:
        """Score HRV relative to baseline (higher = better)"""
        if not baseline.hrv_baseline or baseline.sample_count < 3:
            return 50  # Neutral score without baseline
            
        # Calculate z-score
        std_dev = baseline.hrv_std_dev or (baseline.hrv_baseline * 0.2)  # 20% if no std dev
        z_score = (hrv_ms - baseline.hrv_baseline) / std_dev
        
        # Convert z-score to 0-100 scale (clamped at ±2 std devs)
        normalized = max(-2, min(2, z_score))  
        return 50 + (normalized * 25)  # 50 ± 50 range
    
    def _score_rhr(self, rhr: int, baseline: ReadinessBaseline) -> float:
        """Score RHR relative to baseline (lower = better)"""
        if not baseline.rhr_baseline or baseline.sample_count < 3:
            return 50  # Neutral score without baseline
            
        # Calculate inverse z-score (lower RHR = better score)
        std_dev = baseline.rhr_std_dev or (baseline.rhr_baseline * 0.1)  # 10% if no std dev
        z_score = (baseline.rhr_baseline - rhr) / std_dev  # Note: inverted
        
        # Convert to 0-100 scale
        normalized = max(-2, min(2, z_score))
        return 50 + (normalized * 25)
    
    def _score_sleep(self, sleep_hours: float) -> float:
        """Score sleep duration against 7.5h target"""
        target_hours = 7.5
        
        if sleep_hours >= target_hours:
            return 100  # Full score for adequate sleep
        elif sleep_hours >= 6:
            # Linear scaling from 6-7.5h: 60-100 points
            return 60 + (40 * (sleep_hours - 6) / 1.5)
        else:
            # Penalty for < 6h sleep: 0-60 points
            return max(0, 60 * (sleep_hours / 6))
    
    def _score_subjective(self, energy: int, soreness: int, stress: int) -> float:
        """Score subjective metrics (1-5 scales)"""
        # Energy: 1=terrible, 5=excellent (linear 0-100)
        energy_score = (energy - 1) * 25
        
        # Soreness: 1=none, 5=severe (inverted: 1=100, 5=0)
        soreness_score = (5 - soreness) * 25
        
        # Stress: 1=none, 5=high (inverted: 1=100, 5=0)
        stress_score = (5 - stress) * 25
        
        # Average the three components
        return (energy_score + soreness_score + stress_score) / 3
    
    def _get_recommendation(self, score: int) -> str:
        """Get recommendation based on score thresholds"""
        if score >= 80:
            return "keep"  # Green zone
        elif score >= 60:
            return "reduce"  # Yellow zone
        else:
            return "swap"  # Red zone (could also be "move")
    
    def _generate_message(self, score: int, recommendation: str) -> str:
        """Generate human-readable message"""
        if recommendation == "keep":
            return f"Readiness: Green ({score}). Normal progression recommended."
        elif recommendation == "reduce":
            return f"Readiness: Yellow ({score}). Reduce volume by 20-30% and cap intensity at RPE 8."
        else:
            return f"Readiness: Red ({score}). Consider recovery session or rescheduling."
    
    def _find_today_workout(self, db: Session, user_id: str) -> Optional[Workout]:
        """Find today's scheduled workout"""
        today = datetime.utcnow().date()
        
        # Look for workouts scheduled for today (this is simplified - real implementation 
        # would check calendar events or workout scheduling)
        workout = db.query(Workout).filter(
            Workout.user_id == str(user_id),
            Workout.status == "scheduled",
            func.date(Workout.created_at) == today
        ).first()
        
        return workout
    
    def _apply_workout_adjustments(
        self, 
        db: Session, 
        workout: Workout, 
        readiness_record: MorningReadiness,
        readiness_input: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Apply readiness-based adjustments to workout"""
        
        adjustments = []
        original_prescription = workout.prescription or {}
        adjusted_prescription = original_prescription.copy()
        
        recommendation = readiness_record.recommendation
        time_available = readiness_input["time_available_min"]
        
        if recommendation == "keep":
            # Green zone - minimal adjustments
            if time_available < workout.duration_min:
                adjustments.append({
                    "type": "time_cap",
                    "description": f"Trimmed to fit {time_available} minutes"
                })
                adjusted_prescription = self._apply_time_cap(adjusted_prescription, time_available)
                
        elif recommendation == "reduce":
            # Yellow zone - reduce volume
            adjustments.extend([
                {"type": "volume_reduction", "description": "Reduced accessory volume by 30%"},
                {"type": "intensity_cap", "description": "Capped top sets at RPE 8"}
            ])
            adjusted_prescription = self._reduce_volume(adjusted_prescription)
            adjusted_prescription = self._cap_intensity(adjusted_prescription, max_rpe=8)
            
        elif recommendation == "swap":
            # Red zone - swap to recovery session
            adjustments.append({
                "type": "session_swap", 
                "description": "Swapped to recovery session (mobility/core/zone-2)"
            })
            adjusted_prescription = self._create_recovery_session()
        
        # Create adjustment record
        if adjustments:
            adjustment_record = ReadinessAdjustment(
                id=str(uuid.uuid4()),
                user_id=str(workout.user_id),
                readiness_id=readiness_record.id,
                workout_id=str(workout.id),
                adjustment_type=recommendation,
                original_prescription=original_prescription,
                adjusted_prescription=adjusted_prescription,
                reasoning=f"Score: {readiness_record.score}, Time: {time_available}min"
            )
            
            db.add(adjustment_record)
            
            # Update workout prescription
            workout.prescription = adjusted_prescription
        
        return adjustments
    
    def _apply_time_cap(self, prescription: Dict[str, Any], time_limit_min: int) -> Dict[str, Any]:
        """Trim workout to fit time limit"""
        adjusted = prescription.copy()
        blocks = adjusted.get("blocks", [])
        
        # Remove accessories first, keep main lifts
        filtered_blocks = []
        for block in blocks:
            if block.get("type") == "main":
                filtered_blocks.append(block)
            elif block.get("type") == "accessory" and len(filtered_blocks) <= 1:
                # Keep some accessories if we have room
                filtered_blocks.append(block)
        
        adjusted["blocks"] = filtered_blocks
        return adjusted
    
    def _reduce_volume(self, prescription: Dict[str, Any]) -> Dict[str, Any]:
        """Reduce workout volume by ~30%"""
        adjusted = prescription.copy()
        blocks = adjusted.get("blocks", [])
        
        for block in blocks:
            if block.get("type") == "accessory":
                exercises = block.get("exercises", [])
                # Keep only first 70% of accessory exercises
                keep_count = max(1, int(len(exercises) * 0.7))
                block["exercises"] = exercises[:keep_count]
        
        adjusted["blocks"] = blocks
        return adjusted
    
    def _cap_intensity(self, prescription: Dict[str, Any], max_rpe: int = 8) -> Dict[str, Any]:
        """Cap exercise intensity at specified RPE"""
        adjusted = prescription.copy()
        blocks = adjusted.get("blocks", [])
        
        for block in blocks:
            for exercise in block.get("exercises", []):
                current_rpe = exercise.get("rpe", 6)
                exercise["rpe"] = min(current_rpe, max_rpe)
        
        adjusted["blocks"] = blocks
        return adjusted
    
    def _create_recovery_session(self) -> Dict[str, Any]:
        """Create a recovery-focused session"""
        return {
            "blocks": [
                {
                    "type": "recovery",
                    "exercises": [
                        {
                            "id": "dynamic_warmup",
                            "name": "Dynamic Warm-up",
                            "sets": 1,
                            "reps": "10-15 min",
                            "rpe": 3
                        },
                        {
                            "id": "mobility_flow", 
                            "name": "Mobility Flow",
                            "sets": 2,
                            "reps": "5-10 min",
                            "rpe": 4
                        },
                        {
                            "id": "core_stability",
                            "name": "Core Stability",
                            "sets": 2,
                            "reps": "30-60s holds",
                            "rpe": 5
                        }
                    ]
                }
            ]
        }
    
    def _update_baseline(self, db: Session, baseline: ReadinessBaseline, inputs: Dict[str, Any]):
        """Update user's readiness baseline with new data"""
        hrv_ms = inputs.get("hrv_ms")
        rhr = inputs.get("rhr")
        sleep_hours = inputs.get("sleep_hours")
        
        if hrv_ms:
            if baseline.hrv_baseline is None:
                baseline.hrv_baseline = float(hrv_ms)
                baseline.hrv_std_dev = float(hrv_ms) * 0.2  # Initial estimate
            else:
                # EWMA update
                old_baseline = baseline.hrv_baseline
                baseline.hrv_baseline = (1 - self.ewma_alpha) * old_baseline + self.ewma_alpha * hrv_ms
                
                # Update standard deviation (simple running estimate)
                variance_contribution = (hrv_ms - old_baseline) ** 2
                old_variance = (baseline.hrv_std_dev or 0) ** 2
                new_variance = (1 - self.ewma_alpha) * old_variance + self.ewma_alpha * variance_contribution
                baseline.hrv_std_dev = math.sqrt(new_variance)
        
        if rhr:
            if baseline.rhr_baseline is None:
                baseline.rhr_baseline = float(rhr)
                baseline.rhr_std_dev = float(rhr) * 0.1
            else:
                old_baseline = baseline.rhr_baseline
                baseline.rhr_baseline = (1 - self.ewma_alpha) * old_baseline + self.ewma_alpha * rhr
                
                variance_contribution = (rhr - old_baseline) ** 2
                old_variance = (baseline.rhr_std_dev or 0) ** 2
                new_variance = (1 - self.ewma_alpha) * old_variance + self.ewma_alpha * variance_contribution
                baseline.rhr_std_dev = math.sqrt(new_variance)
        
        if sleep_hours:
            if baseline.sleep_baseline is None:
                baseline.sleep_baseline = float(sleep_hours)
            else:
                baseline.sleep_baseline = (1 - self.ewma_alpha) * baseline.sleep_baseline + self.ewma_alpha * sleep_hours
        
        baseline.sample_count += 1
        baseline.last_calculated = datetime.utcnow()
    
    def _get_baseline_confidence(self, baseline: ReadinessBaseline) -> float:
        """Calculate confidence in baseline (0-1 scale)"""
        if baseline.sample_count == 0:
            return 0.0
        elif baseline.sample_count >= self.baseline_period_days:
            return 1.0
        else:
            return baseline.sample_count / self.baseline_period_days