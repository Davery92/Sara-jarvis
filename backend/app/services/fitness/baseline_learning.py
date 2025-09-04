"""
Baseline Learning Algorithm

Implements personal baseline learning for fitness readiness metrics using
exponentially weighted moving averages (EWMA) and statistical analysis.
Establishes individual baselines for HRV, RHR, and sleep patterns.
"""

from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, date, timedelta
# import numpy as np  # Using pure Python statistics instead
import logging
from statistics import mean, stdev
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc, func

from app.models.fitness import ReadinessBaseline, MorningReadiness

logger = logging.getLogger(__name__)


class BaselineLearningEngine:
    """Learns and maintains personal baselines for readiness metrics"""
    
    def __init__(self):
        # EWMA parameters for different metrics
        self.ewma_params = {
            'hrv_ms': {
                'alpha': 0.1,  # Slower learning for HRV (more variable)
                'min_samples': 7,  # Need at least 7 days
                'confidence_threshold': 14  # Full confidence after 2 weeks
            },
            'rhr': {
                'alpha': 0.15,  # Medium learning rate for RHR
                'min_samples': 5,  # Need at least 5 days
                'confidence_threshold': 10  # Full confidence after 10 days
            },
            'sleep_hours': {
                'alpha': 0.2,  # Faster learning for sleep (more stable)
                'min_samples': 3,  # Need at least 3 nights
                'confidence_threshold': 7  # Full confidence after 1 week
            }
        }
        
        # Outlier detection parameters
        self.outlier_thresholds = {
            'hrv_ms': 3.0,  # 3 standard deviations
            'rhr': 2.5,     # 2.5 standard deviations  
            'sleep_hours': 2.0  # 2 standard deviations
        }
    
    async def update_user_baselines(
        self, 
        db: Session, 
        user_id: str,
        date_value: date,
        metrics: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Update user's personal baselines with new data point.
        Returns updated baselines and confidence scores.
        """
        try:
            # Get or create baseline record for the user
            baseline = await self._get_or_create_baseline(db, user_id)
            
            # Get historical data for learning
            historical_data = await self._get_historical_data(db, user_id, days=30)
            
            # Update each metric baseline
            updates = {}
            for metric, value in metrics.items():
                if value is not None and metric in self.ewma_params:
                    result = await self._update_metric_baseline(
                        metric, value, baseline, historical_data
                    )
                    updates[metric] = result
            
            # Calculate overall confidence
            confidence = self._calculate_overall_confidence(baseline, updates)
            
            # Save updated baseline
            baseline.sample_count += 1
            baseline.last_updated = datetime.utcnow()
            db.add(baseline)
            db.flush()
            
            return {
                "success": True,
                "baseline_id": str(baseline.id),
                "updates": updates,
                "confidence": confidence,
                "sample_count": baseline.sample_count
            }
            
        except Exception as e:
            logger.error(f"Baseline update failed for user {user_id}: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def _get_or_create_baseline(
        self, 
        db: Session, 
        user_id: str
    ) -> ReadinessBaseline:
        """Get existing baseline or create new one"""
        
        baseline = db.query(ReadinessBaseline).filter(
            ReadinessBaseline.user_id == user_id
        ).order_by(desc(ReadinessBaseline.last_updated)).first()
        
        if not baseline:
            # Create new baseline
            baseline = ReadinessBaseline(
                user_id=user_id,
                date=datetime.utcnow().date(),
                hrv_baseline=None,
                rhr_baseline=None,
                sleep_baseline=None,
                sample_count=0,
                confidence_score=0.0,
                data_source="learning"
            )
            db.add(baseline)
            db.flush()
        
        return baseline
    
    async def _get_historical_data(
        self, 
        db: Session, 
        user_id: str, 
        days: int = 30
    ) -> List[Dict[str, Any]]:
        """Get historical data for baseline learning"""
        
        cutoff_date = datetime.utcnow().date() - timedelta(days=days)
        
        # Get data from both ReadinessBaseline and MorningReadiness
        baseline_data = db.query(ReadinessBaseline).filter(
            and_(
                ReadinessBaseline.user_id == user_id,
                ReadinessBaseline.date >= cutoff_date
            )
        ).order_by(ReadinessBaseline.date).all()
        
        readiness_data = db.query(MorningReadiness).filter(
            and_(
                MorningReadiness.user_id == user_id,
                func.date(MorningReadiness.created_at) >= cutoff_date
            )
        ).order_by(MorningReadiness.created_at).all()
        
        # Combine and format data
        historical_points = []
        
        # Add baseline data points
        for baseline in baseline_data:
            if any(getattr(baseline, f) is not None for f in ['hrv_ms', 'rhr', 'sleep_hours']):
                historical_points.append({
                    'date': baseline.date,
                    'hrv_ms': baseline.hrv_ms,
                    'rhr': baseline.rhr,
                    'sleep_hours': baseline.sleep_hours,
                    'source': 'baseline'
                })
        
        # Add readiness data points
        for readiness in readiness_data:
            if any(getattr(readiness, f) is not None for f in ['hrv_ms', 'rhr', 'sleep_hours']):
                historical_points.append({
                    'date': readiness.created_at.date(),
                    'hrv_ms': readiness.hrv_ms,
                    'rhr': readiness.rhr,
                    'sleep_hours': readiness.sleep_hours,
                    'source': 'readiness'
                })
        
        # Sort by date and remove duplicates (prefer baseline over readiness)
        historical_points.sort(key=lambda x: x['date'])
        
        # Remove duplicates, keeping most recent source per date
        seen_dates = set()
        unique_points = []
        for point in reversed(historical_points):  # Process newest first
            if point['date'] not in seen_dates:
                unique_points.append(point)
                seen_dates.add(point['date'])
        
        return list(reversed(unique_points))  # Return chronological order
    
    async def _update_metric_baseline(
        self,
        metric: str,
        new_value: float,
        baseline: ReadinessBaseline,
        historical_data: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Update baseline for a specific metric using EWMA"""
        
        params = self.ewma_params[metric]
        alpha = params['alpha']
        
        # Get current baseline value
        current_baseline = getattr(baseline, f"{metric.split('_')[0]}_baseline")
        
        # Get historical values for this metric
        historical_values = [
            point[metric] for point in historical_data 
            if point[metric] is not None
        ]
        
        # Check for outliers
        is_outlier = self._detect_outlier(metric, new_value, historical_values)
        
        if is_outlier:
            logger.warning(f"Outlier detected for {metric}: {new_value}")
            return {
                "metric": metric,
                "new_value": new_value,
                "baseline": current_baseline,
                "updated": False,
                "reason": "outlier_detected"
            }
        
        # Calculate new baseline
        if current_baseline is None:
            # First time - initialize with current value
            new_baseline = float(new_value)
        else:
            # EWMA update: new_baseline = alpha * new_value + (1 - alpha) * old_baseline
            new_baseline = alpha * new_value + (1 - alpha) * current_baseline
        
        # Update the baseline
        setattr(baseline, f"{metric.split('_')[0]}_baseline", new_baseline)
        
        # Calculate metric confidence
        sample_count = len(historical_values) + 1  # +1 for new value
        metric_confidence = min(1.0, sample_count / params['confidence_threshold'])
        
        # Calculate recent trend
        trend = self._calculate_trend(metric, historical_values + [new_value])
        
        return {
            "metric": metric,
            "new_value": new_value,
            "previous_baseline": current_baseline,
            "new_baseline": round(new_baseline, 2),
            "updated": True,
            "confidence": metric_confidence,
            "sample_count": sample_count,
            "trend": trend
        }
    
    def _detect_outlier(
        self, 
        metric: str, 
        value: float, 
        historical_values: List[float]
    ) -> bool:
        """Detect if value is an outlier based on historical data"""
        
        if len(historical_values) < 3:
            return False  # Need at least 3 points for outlier detection
        
        try:
            hist_mean = mean(historical_values)
            hist_std = stdev(historical_values)
            threshold = self.outlier_thresholds[metric]
            
            # Check if value is more than N standard deviations from mean
            z_score = abs(value - hist_mean) / hist_std if hist_std > 0 else 0
            return z_score > threshold
            
        except Exception:
            return False  # If calculation fails, don't reject the value
    
    def _calculate_trend(self, metric: str, values: List[float]) -> str:
        """Calculate trend direction for the metric"""
        
        if len(values) < 5:
            return "insufficient_data"
        
        try:
            # Use last 7 days vs previous 7 days for trend
            recent_values = values[-7:] if len(values) >= 7 else values[-len(values)//2:]
            older_values = values[:-len(recent_values)] if len(recent_values) < len(values) else values[:len(values)//2]
            
            if not older_values:
                return "insufficient_data"
            
            recent_avg = mean(recent_values)
            older_avg = mean(older_values)
            
            # Define trend thresholds based on metric
            thresholds = {
                'hrv_ms': 2.0,      # 2ms change
                'rhr': 1.0,         # 1 bpm change
                'sleep_hours': 0.3   # 18 minutes change
            }
            
            threshold = thresholds.get(metric, 1.0)
            
            if recent_avg > older_avg + threshold:
                return "increasing"
            elif recent_avg < older_avg - threshold:
                return "decreasing"
            else:
                return "stable"
                
        except Exception:
            return "unknown"
    
    def _calculate_overall_confidence(
        self, 
        baseline: ReadinessBaseline, 
        updates: Dict[str, Any]
    ) -> float:
        """Calculate overall confidence in baseline accuracy"""
        
        confidences = []
        
        # Check each metric that has data
        for metric in ['hrv_ms', 'rhr', 'sleep_hours']:
            if metric in updates and updates[metric].get('updated'):
                confidences.append(updates[metric]['confidence'])
            else:
                # Check if we have existing baseline for this metric
                baseline_value = getattr(baseline, f"{metric.split('_')[0]}_baseline")
                if baseline_value is not None:
                    # Use sample count to estimate confidence
                    params = self.ewma_params[metric]
                    metric_confidence = min(1.0, baseline.sample_count / params['confidence_threshold'])
                    confidences.append(metric_confidence)
        
        if not confidences:
            return 0.0
        
        # Average confidence across available metrics
        return sum(confidences) / len(confidences)
    
    async def get_baseline_status(
        self, 
        db: Session, 
        user_id: str
    ) -> Dict[str, Any]:
        """Get current baseline status and recommendations"""
        
        try:
            # Get current baseline
            baseline = db.query(ReadinessBaseline).filter(
                ReadinessBaseline.user_id == user_id
            ).order_by(desc(ReadinessBaseline.last_updated)).first()
            
            if not baseline:
                return {
                    "status": "not_initialized",
                    "message": "No baseline data found. Start logging health metrics to establish baselines.",
                    "recommendations": [
                        "Log daily readiness for at least 7 days",
                        "Include HRV, RHR, and sleep data when possible",
                        "Be consistent with data collection times"
                    ]
                }
            
            # Calculate days since last update
            days_since_update = (datetime.utcnow().date() - baseline.date).days
            
            # Check metric availability and confidence
            metrics_status = {}
            for metric in ['hrv', 'rhr', 'sleep']:
                baseline_value = getattr(baseline, f"{metric}_baseline")
                metrics_status[metric] = {
                    "available": baseline_value is not None,
                    "baseline": baseline_value,
                    "confidence": baseline.confidence_score if baseline_value else 0.0
                }
            
            # Generate status and recommendations
            if baseline.confidence_score >= 0.8:
                status = "well_established"
                message = "Baselines are well established and reliable."
            elif baseline.confidence_score >= 0.5:
                status = "developing" 
                message = "Baselines are developing. Continue consistent data collection."
            else:
                status = "insufficient_data"
                message = "More data needed to establish reliable baselines."
            
            recommendations = self._generate_baseline_recommendations(
                baseline, metrics_status, days_since_update
            )
            
            return {
                "status": status,
                "message": message,
                "overall_confidence": baseline.confidence_score,
                "sample_count": baseline.sample_count,
                "days_since_update": days_since_update,
                "metrics": metrics_status,
                "recommendations": recommendations
            }
            
        except Exception as e:
            logger.error(f"Failed to get baseline status for user {user_id}: {e}")
            return {
                "status": "error",
                "message": f"Failed to retrieve baseline status: {str(e)}"
            }
    
    def _generate_baseline_recommendations(
        self, 
        baseline: ReadinessBaseline, 
        metrics_status: Dict[str, Any], 
        days_since_update: int
    ) -> List[str]:
        """Generate personalized recommendations for improving baselines"""
        
        recommendations = []
        
        # Check for stale data
        if days_since_update > 3:
            recommendations.append("Update your health data - it's been a few days since your last entry")
        
        # Check missing metrics
        missing_metrics = [
            metric for metric, status in metrics_status.items() 
            if not status["available"]
        ]
        
        if missing_metrics:
            metric_names = {"hrv": "HRV", "rhr": "Resting Heart Rate", "sleep": "Sleep Duration"}
            missing_names = [metric_names[m] for m in missing_metrics]
            recommendations.append(f"Start tracking {', '.join(missing_names)} for better readiness assessment")
        
        # Check confidence levels
        if baseline.confidence_score < 0.5:
            needed_samples = max(14 - baseline.sample_count, 0)
            if needed_samples > 0:
                recommendations.append(f"Continue daily entries for {needed_samples} more days to improve baseline accuracy")
        
        # Check for HealthKit integration
        if baseline.data_source == "manual":
            recommendations.append("Consider connecting HealthKit (iOS) for automatic and more accurate data collection")
        
        return recommendations