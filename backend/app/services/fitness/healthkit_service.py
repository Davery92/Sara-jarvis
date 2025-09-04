"""
HealthKit Integration Service

Handles iOS HealthKit data collection for fitness readiness metrics.
Provides endpoints for iOS app to submit HRV, RHR, and sleep data.
"""

from typing import Dict, List, Any, Optional
from datetime import datetime, date, timedelta
import json
import logging
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc

from app.models.fitness import ReadinessBaseline, WorkoutSession
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


class HealthKitService:
    """Handles HealthKit data ingestion and processing for iOS users"""
    
    def __init__(self):
        self.supported_metrics = {
            'hrv_ms': 'HKQuantityTypeIdentifierHeartRateVariabilitySDNN',
            'rhr': 'HKQuantityTypeIdentifierRestingHeartRate',
            'sleep_hours': 'HKCategoryTypeIdentifierSleepAnalysis',
            'active_energy': 'HKQuantityTypeIdentifierActiveEnergyBurned',
            'steps': 'HKQuantityTypeIdentifierStepCount',
            'workout_heart_rate': 'HKQuantityTypeIdentifierHeartRate'
        }
    
    async def process_healthkit_data(
        self, 
        user_id: str, 
        healthkit_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Process raw HealthKit data submission from iOS app.
        
        Expected format:
        {
            "date": "2025-09-02",
            "metrics": {
                "hrv_ms": 45.2,
                "rhr": 58,
                "sleep_hours": 7.3,
                "active_energy": 420.5,
                "steps": 8450
            },
            "samples": [
                {
                    "type": "HKQuantityTypeIdentifierHeartRateVariabilitySDNN",
                    "value": 45.2,
                    "unit": "ms",
                    "start_date": "2025-09-02T06:00:00Z",
                    "end_date": "2025-09-02T06:00:00Z",
                    "source": "Apple Watch"
                }
            ]
        }
        """
        try:
            data_date = datetime.strptime(healthkit_data["date"], "%Y-%m-%d").date()
            metrics = healthkit_data.get("metrics", {})
            samples = healthkit_data.get("samples", [])
            
            db = SessionLocal()
            try:
                # Store or update baseline data
                baseline = await self._upsert_baseline_data(
                    db, user_id, data_date, metrics
                )
                
                # Process detailed samples if provided
                processed_samples = await self._process_samples(
                    db, user_id, samples
                )
                
                # Calculate trend information
                trend_data = await self._calculate_trends(db, user_id, data_date)
                
                db.commit()
                
                return {
                    "success": True,
                    "date": data_date.isoformat(),
                    "metrics_processed": list(metrics.keys()),
                    "samples_processed": len(processed_samples),
                    "baseline_updated": baseline is not None,
                    "trends": trend_data
                }
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"HealthKit data processing failed for user {user_id}: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def _upsert_baseline_data(
        self, 
        db: Session, 
        user_id: str, 
        data_date: date, 
        metrics: Dict[str, Any]
    ) -> Optional[ReadinessBaseline]:
        """Update or create baseline data for the date"""
        
        # Look for existing baseline for this date
        existing = db.query(ReadinessBaseline).filter(
            and_(
                ReadinessBaseline.user_id == user_id,
                ReadinessBaseline.date == data_date
            )
        ).first()
        
        if existing:
            # Update existing baseline
            if "hrv_ms" in metrics:
                existing.hrv_ms = float(metrics["hrv_ms"])
            if "rhr" in metrics:
                existing.rhr = int(metrics["rhr"])
            if "sleep_hours" in metrics:
                existing.sleep_hours = float(metrics["sleep_hours"])
            
            existing.data_source = "healthkit"
            existing.last_updated = datetime.utcnow()
            
            return existing
        else:
            # Create new baseline
            baseline = ReadinessBaseline(
                user_id=user_id,
                date=data_date,
                hrv_ms=float(metrics.get("hrv_ms", 0)) if "hrv_ms" in metrics else None,
                rhr=int(metrics.get("rhr", 0)) if "rhr" in metrics else None,
                sleep_hours=float(metrics.get("sleep_hours", 0)) if "sleep_hours" in metrics else None,
                data_source="healthkit",
                confidence_score=0.9  # High confidence for HealthKit data
            )
            db.add(baseline)
            return baseline
    
    async def _process_samples(
        self, 
        db: Session, 
        user_id: str, 
        samples: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Process detailed HealthKit samples for additional insights"""
        
        processed = []
        
        for sample in samples:
            try:
                sample_type = sample.get("type")
                value = sample.get("value")
                unit = sample.get("unit")
                start_date = datetime.fromisoformat(
                    sample.get("start_date", "").replace("Z", "+00:00")
                )
                source = sample.get("source", "Unknown")
                
                # Store detailed sample data in metadata
                sample_data = {
                    "type": sample_type,
                    "value": value,
                    "unit": unit,
                    "start_date": start_date.isoformat(),
                    "source": source,
                    "processed_at": datetime.utcnow().isoformat()
                }
                
                processed.append(sample_data)
                
            except Exception as e:
                logger.warning(f"Failed to process HealthKit sample: {e}")
                continue
        
        return processed
    
    async def _calculate_trends(
        self, 
        db: Session, 
        user_id: str, 
        current_date: date
    ) -> Dict[str, Any]:
        """Calculate 7-day and 30-day trends for key metrics"""
        
        # Get baseline data for trend calculation
        week_ago = current_date - timedelta(days=7)
        month_ago = current_date - timedelta(days=30)
        
        recent_baselines = db.query(ReadinessBaseline).filter(
            and_(
                ReadinessBaseline.user_id == user_id,
                ReadinessBaseline.date >= month_ago,
                ReadinessBaseline.date <= current_date
            )
        ).order_by(desc(ReadinessBaseline.date)).all()
        
        if not recent_baselines:
            return {"trends_available": False}
        
        # Calculate averages
        week_data = [b for b in recent_baselines if b.date >= week_ago]
        month_data = recent_baselines
        
        trends = {
            "trends_available": True,
            "period_days": {
                "week": len(week_data),
                "month": len(month_data)
            }
        }
        
        # HRV trends
        week_hrv = [b.hrv_ms for b in week_data if b.hrv_ms is not None]
        month_hrv = [b.hrv_ms for b in month_data if b.hrv_ms is not None]
        
        if week_hrv and month_hrv:
            trends["hrv"] = {
                "week_avg": round(sum(week_hrv) / len(week_hrv), 1),
                "month_avg": round(sum(month_hrv) / len(month_hrv), 1),
                "trend": "improving" if sum(week_hrv) / len(week_hrv) > sum(month_hrv) / len(month_hrv) else "declining"
            }
        
        # RHR trends
        week_rhr = [b.rhr for b in week_data if b.rhr is not None]
        month_rhr = [b.rhr for b in month_data if b.rhr is not None]
        
        if week_rhr and month_rhr:
            trends["rhr"] = {
                "week_avg": round(sum(week_rhr) / len(week_rhr), 1),
                "month_avg": round(sum(month_rhr) / len(month_rhr), 1),
                "trend": "improving" if sum(week_rhr) / len(week_rhr) < sum(month_rhr) / len(month_rhr) else "declining"
            }
        
        # Sleep trends
        week_sleep = [b.sleep_hours for b in week_data if b.sleep_hours is not None]
        month_sleep = [b.sleep_hours for b in month_data if b.sleep_hours is not None]
        
        if week_sleep and month_sleep:
            trends["sleep"] = {
                "week_avg": round(sum(week_sleep) / len(week_sleep), 1),
                "month_avg": round(sum(month_sleep) / len(month_sleep), 1),
                "trend": "improving" if sum(week_sleep) / len(week_sleep) > sum(month_sleep) / len(month_sleep) else "declining"
            }
        
        return trends
    
    async def get_healthkit_config(self, user_id: str) -> Dict[str, Any]:
        """
        Return HealthKit configuration for iOS app.
        Specifies which metrics to request and collection preferences.
        """
        
        config = {
            "required_permissions": [
                {
                    "type": "HKQuantityTypeIdentifierHeartRateVariabilitySDNN",
                    "frequency": "daily",
                    "description": "Heart rate variability for readiness assessment"
                },
                {
                    "type": "HKQuantityTypeIdentifierRestingHeartRate", 
                    "frequency": "daily",
                    "description": "Resting heart rate for recovery tracking"
                },
                {
                    "type": "HKCategoryTypeIdentifierSleepAnalysis",
                    "frequency": "daily", 
                    "description": "Sleep duration and quality metrics"
                }
            ],
            "optional_permissions": [
                {
                    "type": "HKQuantityTypeIdentifierActiveEnergyBurned",
                    "frequency": "daily",
                    "description": "Activity level for load assessment"
                },
                {
                    "type": "HKQuantityTypeIdentifierStepCount",
                    "frequency": "daily",
                    "description": "Daily activity tracking"
                },
                {
                    "type": "HKQuantityTypeIdentifierHeartRate",
                    "frequency": "during_workouts",
                    "description": "Heart rate during exercise sessions"
                }
            ],
            "collection_settings": {
                "auto_sync": True,
                "sync_frequency": "daily_morning",  # 6-9 AM preferred
                "lookback_days": 7,  # How far back to sync initially
                "batch_size": 50  # Max samples per request
            },
            "data_quality": {
                "min_hrv_samples": 1,  # Minimum daily HRV readings
                "max_rhr_variance": 20,  # Flag RHR readings outside ±20 BPM
                "min_sleep_hours": 3,  # Flag sleep < 3 hours as potentially invalid
                "max_sleep_hours": 12  # Flag sleep > 12 hours for review
            }
        }
        
        return config
    
    async def validate_healthkit_data(
        self, 
        healthkit_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Validate incoming HealthKit data for quality and completeness"""
        
        validation_result = {
            "valid": True,
            "warnings": [],
            "errors": []
        }
        
        # Check required fields
        if "date" not in healthkit_data:
            validation_result["errors"].append("Missing required field: date")
            validation_result["valid"] = False
        
        if "metrics" not in healthkit_data:
            validation_result["errors"].append("Missing required field: metrics")
            validation_result["valid"] = False
            return validation_result
        
        metrics = healthkit_data["metrics"]
        
        # Validate HRV
        if "hrv_ms" in metrics:
            hrv = metrics["hrv_ms"]
            if not isinstance(hrv, (int, float)) or hrv < 5 or hrv > 200:
                validation_result["warnings"].append(f"HRV value {hrv}ms outside typical range (5-200ms)")
        
        # Validate RHR
        if "rhr" in metrics:
            rhr = metrics["rhr"]
            if not isinstance(rhr, (int, float)) or rhr < 30 or rhr > 120:
                validation_result["warnings"].append(f"RHR value {rhr}bpm outside typical range (30-120bpm)")
        
        # Validate sleep
        if "sleep_hours" in metrics:
            sleep = metrics["sleep_hours"]
            if not isinstance(sleep, (int, float)) or sleep < 0 or sleep > 16:
                validation_result["warnings"].append(f"Sleep duration {sleep}h outside typical range (0-16h)")
        
        return validation_result