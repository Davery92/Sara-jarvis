"""
Manual Entry Service

Provides manual data entry capabilities for web and Android users who cannot
use HealthKit integration. Includes data validation, persistence, and 
baseline learning from manual entries.
"""

from typing import Dict, List, Any, Optional
from datetime import datetime, date, timedelta
import logging
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc, func

from app.models.fitness import ReadinessBaseline, MorningReadiness
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


class ManualEntryService:
    """Handles manual entry of health and readiness data for web/Android users"""
    
    def __init__(self):
        self.entry_types = {
            'readiness': {
                'required': ['energy', 'soreness', 'stress', 'time_available_min'],
                'optional': ['hrv_ms', 'rhr', 'sleep_hours', 'notes']
            },
            'health_metrics': {
                'required': ['date'],
                'optional': ['hrv_ms', 'rhr', 'sleep_hours', 'weight', 'notes']
            }
        }
    
    async def create_manual_entry(
        self, 
        user_id: str,
        entry_type: str,
        data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Create a manual entry for health/readiness data.
        
        entry_type: 'readiness' or 'health_metrics'
        """
        try:
            # Validate entry type
            if entry_type not in self.entry_types:
                return {
                    "success": False,
                    "error": f"Invalid entry type. Must be one of: {list(self.entry_types.keys())}"
                }
            
            # Validate required fields
            validation_result = self._validate_entry_data(entry_type, data)
            if not validation_result["valid"]:
                return {
                    "success": False,
                    "error": f"Validation failed: {', '.join(validation_result['errors'])}"
                }
            
            db = SessionLocal()
            try:
                if entry_type == 'readiness':
                    result = await self._create_readiness_entry(db, user_id, data)
                elif entry_type == 'health_metrics':
                    result = await self._create_health_metrics_entry(db, user_id, data)
                
                db.commit()
                return result
                
            except Exception as e:
                db.rollback()
                raise e
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Manual entry creation failed for user {user_id}: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def _create_readiness_entry(
        self, 
        db: Session, 
        user_id: str, 
        data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create a readiness entry with baseline updates"""
        
        # Check if user already submitted today's readiness
        today = datetime.utcnow().date()
        existing_entry = db.query(MorningReadiness).filter(
            and_(
                MorningReadiness.user_id == user_id,
                func.date(MorningReadiness.created_at) == today
            )
        ).first()
        
        if existing_entry:
            return {
                "success": False,
                "error": "Readiness already submitted for today. Use update endpoint to modify."
            }
        
        # Create readiness entry (scoring will be done by ReadinessEngine)
        readiness_entry = MorningReadiness(
            user_id=user_id,
            hrv_ms=data.get('hrv_ms'),
            rhr=data.get('rhr'),
            sleep_hours=data.get('sleep_hours'),
            energy=data['energy'],
            soreness=data['soreness'],
            stress=data['stress'],
            time_available_min=data['time_available_min'],
            score=0,  # Will be calculated by ReadinessEngine
            recommendation='keep',  # Will be updated by ReadinessEngine
            adjustments=[],
            message=data.get('notes', ''),
            data_source='manual'
        )
        db.add(readiness_entry)
        db.flush()
        
        # Update baselines if health metrics provided
        if any(data.get(k) is not None for k in ['hrv_ms', 'rhr', 'sleep_hours']):
            await self._update_baseline_from_manual(db, user_id, today, data)
        
        return {
            "success": True,
            "readiness_id": readiness_entry.id,
            "message": "Readiness entry created successfully",
            "baseline_updated": any(data.get(k) is not None for k in ['hrv_ms', 'rhr', 'sleep_hours'])
        }
    
    async def _create_health_metrics_entry(
        self, 
        db: Session, 
        user_id: str, 
        data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create or update health metrics baseline entry"""
        
        entry_date = datetime.strptime(data['date'], '%Y-%m-%d').date()
        
        # Check if entry already exists for this date
        existing_baseline = db.query(ReadinessBaseline).filter(
            and_(
                ReadinessBaseline.user_id == user_id,
                ReadinessBaseline.date == entry_date
            )
        ).first()
        
        if existing_baseline:
            # Update existing entry
            if data.get('hrv_ms') is not None:
                existing_baseline.hrv_ms = float(data['hrv_ms'])
            if data.get('rhr') is not None:
                existing_baseline.rhr = int(data['rhr'])
            if data.get('sleep_hours') is not None:
                existing_baseline.sleep_hours = float(data['sleep_hours'])
            
            existing_baseline.data_source = 'manual'
            existing_baseline.last_updated = datetime.utcnow()
            
            return {
                "success": True,
                "baseline_id": str(existing_baseline.id),
                "message": "Health metrics updated successfully",
                "action": "updated"
            }
        else:
            # Create new baseline entry
            baseline = ReadinessBaseline(
                user_id=user_id,
                date=entry_date,
                hrv_ms=float(data['hrv_ms']) if data.get('hrv_ms') is not None else None,
                rhr=int(data['rhr']) if data.get('rhr') is not None else None,
                sleep_hours=float(data['sleep_hours']) if data.get('sleep_hours') is not None else None,
                data_source='manual',
                confidence_score=0.7  # Lower confidence for manual entries
            )
            db.add(baseline)
            db.flush()
            
            return {
                "success": True,
                "baseline_id": str(baseline.id),
                "message": "Health metrics created successfully", 
                "action": "created"
            }
    
    async def _update_baseline_from_manual(
        self, 
        db: Session, 
        user_id: str, 
        entry_date: date,
        data: Dict[str, Any]
    ) -> None:
        """Update baseline data from manual readiness entry"""
        
        # Look for existing baseline for this date
        existing = db.query(ReadinessBaseline).filter(
            and_(
                ReadinessBaseline.user_id == user_id,
                ReadinessBaseline.date == entry_date
            )
        ).first()
        
        if existing:
            # Update existing
            if data.get('hrv_ms') is not None:
                existing.hrv_ms = float(data['hrv_ms'])
            if data.get('rhr') is not None:
                existing.rhr = int(data['rhr'])
            if data.get('sleep_hours') is not None:
                existing.sleep_hours = float(data['sleep_hours'])
            
            existing.data_source = 'manual'
            existing.last_updated = datetime.utcnow()
        else:
            # Create new baseline
            baseline = ReadinessBaseline(
                user_id=user_id,
                date=entry_date,
                hrv_ms=float(data['hrv_ms']) if data.get('hrv_ms') is not None else None,
                rhr=int(data['rhr']) if data.get('rhr') is not None else None,
                sleep_hours=float(data['sleep_hours']) if data.get('sleep_hours') is not None else None,
                data_source='manual',
                confidence_score=0.7
            )
            db.add(baseline)
    
    def _validate_entry_data(self, entry_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate manual entry data"""
        
        validation_result = {
            "valid": True,
            "errors": [],
            "warnings": []
        }
        
        entry_config = self.entry_types[entry_type]
        
        # Check required fields
        for field in entry_config['required']:
            if field not in data or data[field] is None:
                validation_result["errors"].append(f"Missing required field: {field}")
                validation_result["valid"] = False
        
        # Validate specific fields
        if entry_type == 'readiness':
            # Energy, soreness, stress should be 1-5
            for field in ['energy', 'soreness', 'stress']:
                if field in data:
                    value = data[field]
                    if not isinstance(value, int) or value < 1 or value > 5:
                        validation_result["errors"].append(f"{field} must be an integer between 1-5")
                        validation_result["valid"] = False
            
            # Time available should be reasonable
            if 'time_available_min' in data:
                value = data['time_available_min']
                if not isinstance(value, int) or value < 10 or value > 240:
                    validation_result["errors"].append("time_available_min must be between 10-240 minutes")
                    validation_result["valid"] = False
        
        # Validate optional health metrics
        if 'hrv_ms' in data and data['hrv_ms'] is not None:
            value = data['hrv_ms']
            if not isinstance(value, (int, float)) or value < 5 or value > 200:
                validation_result["warnings"].append(f"HRV value {value}ms outside typical range (5-200ms)")
        
        if 'rhr' in data and data['rhr'] is not None:
            value = data['rhr']
            if not isinstance(value, int) or value < 30 or value > 120:
                validation_result["warnings"].append(f"RHR value {value}bpm outside typical range (30-120bpm)")
        
        if 'sleep_hours' in data and data['sleep_hours'] is not None:
            value = data['sleep_hours']
            if not isinstance(value, (int, float)) or value < 0 or value > 16:
                validation_result["warnings"].append(f"Sleep duration {value}h outside typical range (0-16h)")
        
        # Validate date format for health_metrics
        if entry_type == 'health_metrics' and 'date' in data:
            try:
                datetime.strptime(data['date'], '%Y-%m-%d')
            except ValueError:
                validation_result["errors"].append("Date must be in YYYY-MM-DD format")
                validation_result["valid"] = False
        
        return validation_result
    
    async def get_manual_entry_template(self, entry_type: str) -> Dict[str, Any]:
        """Get template structure for manual entry forms"""
        
        if entry_type not in self.entry_types:
            return {
                "error": f"Invalid entry type. Must be one of: {list(self.entry_types.keys())}"
            }
        
        config = self.entry_types[entry_type]
        
        templates = {
            'readiness': {
                "title": "Daily Readiness Assessment",
                "description": "Rate your readiness for today's workout",
                "fields": [
                    {
                        "name": "energy",
                        "label": "Energy Level",
                        "type": "scale",
                        "required": True,
                        "min": 1,
                        "max": 5,
                        "labels": ["Very Low", "Low", "Moderate", "High", "Very High"]
                    },
                    {
                        "name": "soreness",
                        "label": "Muscle Soreness",
                        "type": "scale", 
                        "required": True,
                        "min": 1,
                        "max": 5,
                        "labels": ["None", "Minimal", "Moderate", "High", "Severe"]
                    },
                    {
                        "name": "stress",
                        "label": "Stress Level",
                        "type": "scale",
                        "required": True,
                        "min": 1,
                        "max": 5,
                        "labels": ["Very Low", "Low", "Moderate", "High", "Very High"]
                    },
                    {
                        "name": "time_available_min",
                        "label": "Time Available (minutes)",
                        "type": "number",
                        "required": True,
                        "min": 10,
                        "max": 240,
                        "placeholder": "60"
                    },
                    {
                        "name": "hrv_ms", 
                        "label": "Heart Rate Variability (optional)",
                        "type": "number",
                        "required": False,
                        "min": 5,
                        "max": 200,
                        "placeholder": "Enter HRV in milliseconds"
                    },
                    {
                        "name": "rhr",
                        "label": "Resting Heart Rate (optional)",
                        "type": "number", 
                        "required": False,
                        "min": 30,
                        "max": 120,
                        "placeholder": "Enter RHR in BPM"
                    },
                    {
                        "name": "sleep_hours",
                        "label": "Sleep Duration (optional)",
                        "type": "number",
                        "required": False,
                        "min": 0,
                        "max": 16,
                        "step": 0.5,
                        "placeholder": "Enter hours of sleep"
                    },
                    {
                        "name": "notes",
                        "label": "Additional Notes (optional)",
                        "type": "text",
                        "required": False,
                        "placeholder": "Any additional context..."
                    }
                ]
            },
            'health_metrics': {
                "title": "Health Metrics Entry",
                "description": "Log your health metrics for baseline tracking",
                "fields": [
                    {
                        "name": "date",
                        "label": "Date",
                        "type": "date",
                        "required": True
                    },
                    {
                        "name": "hrv_ms",
                        "label": "Heart Rate Variability", 
                        "type": "number",
                        "required": False,
                        "min": 5,
                        "max": 200,
                        "placeholder": "Enter HRV in milliseconds"
                    },
                    {
                        "name": "rhr",
                        "label": "Resting Heart Rate",
                        "type": "number",
                        "required": False,
                        "min": 30,
                        "max": 120,
                        "placeholder": "Enter RHR in BPM"
                    },
                    {
                        "name": "sleep_hours",
                        "label": "Sleep Duration",
                        "type": "number",
                        "required": False,
                        "min": 0,
                        "max": 16,
                        "step": 0.5,
                        "placeholder": "Enter hours of sleep"
                    },
                    {
                        "name": "notes",
                        "label": "Notes",
                        "type": "text", 
                        "required": False,
                        "placeholder": "Any relevant notes..."
                    }
                ]
            }
        }
        
        return {
            "template": templates[entry_type],
            "validation_rules": config
        }
    
    async def get_entry_history(
        self, 
        user_id: str, 
        entry_type: str, 
        days: int = 30
    ) -> Dict[str, Any]:
        """Get history of manual entries for the user"""
        
        db = SessionLocal()
        try:
            if entry_type == 'readiness':
                entries = db.query(MorningReadiness).filter(
                    MorningReadiness.user_id == user_id,
                    MorningReadiness.data_source == 'manual'
                ).order_by(desc(MorningReadiness.created_at)).limit(days).all()
                
                entry_data = []
                for entry in entries:
                    entry_data.append({
                        "id": entry.id,
                        "date": entry.created_at.date().isoformat(),
                        "energy": entry.energy,
                        "soreness": entry.soreness,
                        "stress": entry.stress,
                        "time_available_min": entry.time_available_min,
                        "hrv_ms": entry.hrv_ms,
                        "rhr": entry.rhr,
                        "sleep_hours": entry.sleep_hours,
                        "score": entry.score,
                        "recommendation": entry.recommendation
                    })
                
            elif entry_type == 'health_metrics':
                entries = db.query(ReadinessBaseline).filter(
                    ReadinessBaseline.user_id == user_id,
                    ReadinessBaseline.data_source == 'manual'
                ).order_by(desc(ReadinessBaseline.date)).limit(days).all()
                
                entry_data = []
                for entry in entries:
                    entry_data.append({
                        "id": str(entry.id),
                        "date": entry.date.isoformat(),
                        "hrv_ms": entry.hrv_ms,
                        "rhr": entry.rhr,
                        "sleep_hours": entry.sleep_hours,
                        "confidence_score": entry.confidence_score
                    })
            else:
                return {"error": f"Invalid entry type: {entry_type}"}
            
            return {
                "entry_type": entry_type,
                "entries": entry_data,
                "total_count": len(entry_data)
            }
            
        finally:
            db.close()