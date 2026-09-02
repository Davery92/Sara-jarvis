"""
Recovery Log Tools
Tools for tracking daily recovery metrics: HRV, heart rate, sleep, soreness, body weight
"""
from typing import Dict, Any, List
from app.tools.base import BaseTool, ToolResult
from sqlalchemy import text
from datetime import datetime, timezone, timedelta, date
import uuid


def get_fitness_db():
    """Get database session"""
    from app.db.session import get_db
    return next(get_db())


class RecoveryLogCreateTool(BaseTool):
    """Create or update daily recovery log with HRV, sleep, soreness, and other metrics"""

    @property
    def name(self) -> str:
        return "recovery_log_create"

    @property
    def description(self) -> str:
        return "Create or update daily recovery log with metrics like HRV, heart rate, sleep hours, soreness level (1-10), and body weight. Use this when the user shares recovery data or morning metrics."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "log_date": {
                    "type": "string",
                    "description": "Date for the recovery log (YYYY-MM-DD format, defaults to today)"
                },
                "hrv": {
                    "type": "integer",
                    "description": "Heart Rate Variability in milliseconds (optional)"
                },
                "heart_rate": {
                    "type": "integer",
                    "description": "Resting heart rate in BPM (optional)"
                },
                "sleep_hours": {
                    "type": "number",
                    "description": "Hours of sleep (can include decimals like 7.5)"
                },
                "soreness_level": {
                    "type": "integer",
                    "description": "Muscle soreness on 1-10 scale (1=none, 10=extremely sore)"
                },
                "body_weight": {
                    "type": "number",
                    "description": "Body weight (optional)"
                },
                "weight_unit": {
                    "type": "string",
                    "description": "Unit for body weight",
                    "enum": ["lbs", "kg"]
                },
                "notes": {
                    "type": "string",
                    "description": "Additional notes about recovery, how you feel, injuries, etc."
                }
            },
            "required": []
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Create or update recovery log entry"""
        log_date_str = kwargs.get("log_date")
        hrv = kwargs.get("hrv")
        heart_rate = kwargs.get("heart_rate")
        sleep_hours = kwargs.get("sleep_hours")
        soreness_level = kwargs.get("soreness_level")
        body_weight = kwargs.get("body_weight")
        weight_unit = kwargs.get("weight_unit", "lbs")
        notes = kwargs.get("notes", "")

        # Parse or default to today
        if log_date_str:
            try:
                log_date = datetime.strptime(log_date_str, "%Y-%m-%d").date()
            except ValueError:
                return ToolResult(
                    success=False,
                    data={"error": "Invalid date format. Use YYYY-MM-DD"}
                )
        else:
            log_date = date.today()

        # Validate soreness level if provided
        if soreness_level is not None:
            if soreness_level < 1 or soreness_level > 10:
                return ToolResult(
                    success=False,
                    data={"error": "Soreness level must be between 1 and 10"}
                )

        db = get_fitness_db()

        try:
            # Check if entry exists for this date
            existing = db.execute(
                text("""
                    SELECT id FROM daily_recovery_log
                    WHERE user_id = :user_id AND log_date = :log_date
                """),
                {"user_id": user_id, "log_date": log_date}
            ).first()

            if existing:
                # Update existing entry (only update provided fields)
                update_fields = []
                params = {"user_id": user_id, "log_date": log_date}

                if hrv is not None:
                    update_fields.append("hrv = :hrv")
                    params["hrv"] = hrv
                if heart_rate is not None:
                    update_fields.append("heart_rate = :heart_rate")
                    params["heart_rate"] = heart_rate
                if sleep_hours is not None:
                    update_fields.append("sleep_hours = :sleep_hours")
                    params["sleep_hours"] = sleep_hours
                if soreness_level is not None:
                    update_fields.append("soreness_level = :soreness_level")
                    params["soreness_level"] = soreness_level
                if body_weight is not None:
                    update_fields.append("body_weight = :body_weight")
                    params["body_weight"] = body_weight
                if weight_unit:
                    update_fields.append("weight_unit = :weight_unit")
                    params["weight_unit"] = weight_unit
                if notes:
                    update_fields.append("notes = :notes")
                    params["notes"] = notes

                update_fields.append("updated_at = NOW()")

                if update_fields:
                    query = text(f"""
                        UPDATE daily_recovery_log
                        SET {', '.join(update_fields)}
                        WHERE user_id = :user_id AND log_date = :log_date
                        RETURNING id, log_date, hrv, heart_rate, sleep_hours, soreness_level,
                                  body_weight, weight_unit, notes
                    """)
                    result = db.execute(query, params).first()
                    db.commit()

                    return ToolResult(
                        success=True,
                        data={
                            "message": f"Updated recovery log for {log_date}",
                            "id": result.id,
                            "log_date": str(result.log_date),
                            "hrv": result.hrv,
                            "heart_rate": result.heart_rate,
                            "sleep_hours": float(result.sleep_hours) if result.sleep_hours else None,
                            "soreness_level": result.soreness_level,
                            "body_weight": float(result.body_weight) if result.body_weight else None,
                            "weight_unit": result.weight_unit,
                            "notes": result.notes
                        }
                    )
            else:
                # Create new entry
                log_id = str(uuid.uuid4())
                db.execute(
                    text("""
                        INSERT INTO daily_recovery_log
                        (id, user_id, log_date, hrv, heart_rate, sleep_hours, soreness_level,
                         body_weight, weight_unit, notes, created_at, updated_at)
                        VALUES (:id, :user_id, :log_date, :hrv, :heart_rate, :sleep_hours,
                                :soreness_level, :body_weight, :weight_unit, :notes, NOW(), NOW())
                    """),
                    {
                        "id": log_id,
                        "user_id": user_id,
                        "log_date": log_date,
                        "hrv": hrv,
                        "heart_rate": heart_rate,
                        "sleep_hours": sleep_hours,
                        "soreness_level": soreness_level,
                        "body_weight": body_weight,
                        "weight_unit": weight_unit,
                        "notes": notes
                    }
                )
                db.commit()

                return ToolResult(
                    success=True,
                    data={
                        "message": f"Created recovery log for {log_date}",
                        "id": log_id,
                        "log_date": str(log_date),
                        "hrv": hrv,
                        "heart_rate": heart_rate,
                        "sleep_hours": sleep_hours,
                        "soreness_level": soreness_level,
                        "body_weight": body_weight,
                        "weight_unit": weight_unit,
                        "notes": notes
                    }
                )

        except Exception as e:
            db.rollback()
            return ToolResult(
                success=False,
                data={"error": f"Failed to create/update recovery log: {str(e)}"}
            )


class RecoveryLogGetTool(BaseTool):
    """Get recovery log for a specific date"""

    @property
    def name(self) -> str:
        return "recovery_log_get"

    @property
    def description(self) -> str:
        return "Get recovery log for a specific date to see HRV, sleep, soreness, and other metrics from that day."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "log_date": {
                    "type": "string",
                    "description": "Date to retrieve (YYYY-MM-DD format, defaults to today)"
                }
            },
            "required": []
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Get recovery log for a specific date"""
        log_date_str = kwargs.get("log_date")

        # Parse or default to today
        if log_date_str:
            try:
                log_date = datetime.strptime(log_date_str, "%Y-%m-%d").date()
            except ValueError:
                return ToolResult(
                    success=False,
                    data={"error": "Invalid date format. Use YYYY-MM-DD"}
                )
        else:
            log_date = date.today()

        db = get_fitness_db()

        try:
            # Debug logging
            import logging
            logger = logging.getLogger("app.main_simple")
            logger.info(f"🔍 RecoveryLogGetTool: user_id={user_id}, log_date={log_date}")

            result = db.execute(
                text("""
                    SELECT id, user_id, log_date, hrv, heart_rate, sleep_hours, soreness_level,
                           body_weight, weight_unit, notes, created_at, updated_at
                    FROM daily_recovery_log
                    WHERE user_id = :user_id AND log_date = :log_date
                """),
                {"user_id": user_id, "log_date": log_date}
            ).first()

            logger.info(f"🔍 RecoveryLogGetTool: result={result}")

            if not result:
                return ToolResult(
                    success=True,
                    data={"message": f"No recovery log found for {log_date}"}
                )

            return ToolResult(
                success=True,
                data={
                    "id": result.id,
                    "log_date": str(result.log_date),
                    "hrv": result.hrv,
                    "heart_rate": result.heart_rate,
                    "sleep_hours": float(result.sleep_hours) if result.sleep_hours else None,
                    "soreness_level": result.soreness_level,
                    "body_weight": float(result.body_weight) if result.body_weight else None,
                    "weight_unit": result.weight_unit,
                    "notes": result.notes,
                    "created_at": result.created_at.isoformat() if result.created_at else None,
                    "updated_at": result.updated_at.isoformat() if result.updated_at else None
                }
            )

        except Exception as e:
            return ToolResult(
                success=False,
                data={"error": f"Failed to retrieve recovery log: {str(e)}"}
            )


class RecoveryLogRecentTool(BaseTool):
    """Get recent recovery logs to see trends over time"""

    @property
    def name(self) -> str:
        return "recovery_log_recent"

    @property
    def description(self) -> str:
        return "Get recent recovery logs (default: last 7 days) to analyze trends in HRV, sleep quality, soreness patterns, and overall recovery status."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Number of days to retrieve (default: 7, max: 90)"
                }
            },
            "required": []
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Get recent recovery logs"""
        days = kwargs.get("days", 7)

        # Validate days range
        if days < 1:
            days = 7
        if days > 90:
            days = 90

        db = get_fitness_db()

        try:
            results = db.execute(
                text("""
                    SELECT id, user_id, log_date, hrv, heart_rate, sleep_hours, soreness_level,
                           body_weight, weight_unit, notes, created_at, updated_at
                    FROM daily_recovery_log
                    WHERE user_id = :user_id
                      AND log_date >= CURRENT_DATE - make_interval(days => :days)
                    ORDER BY log_date DESC
                """),
                {"user_id": user_id, "days": days}
            ).fetchall()

            if not results:
                return ToolResult(
                    success=True,
                    data={
                        "message": f"No recovery logs found in the last {days} days",
                        "logs": []
                    }
                )

            logs = []
            for row in results:
                logs.append({
                    "id": row.id,
                    "log_date": str(row.log_date),
                    "hrv": row.hrv,
                    "heart_rate": row.heart_rate,
                    "sleep_hours": float(row.sleep_hours) if row.sleep_hours is not None else None,
                    "soreness_level": row.soreness_level,
                    "body_weight": float(row.body_weight) if row.body_weight is not None else None,
                    "weight_unit": row.weight_unit,
                    "notes": row.notes
                })

            # Name the days with no log at all. A short list of 3 rows for a
            # 7-day request looks like a complete answer to a model that can't
            # see what's missing, and it will fill the rest in.
            from app.core.timezone import today as local_today
            end_day = local_today()
            logged = {log["log_date"] for log in logs}
            missing_dates = [
                str(end_day - timedelta(days=offset))
                for offset in range(days)
                if str(end_day - timedelta(days=offset)) not in logged
            ]
            # Per-field gaps too: a logged day with hrv=NULL is not an HRV reading.
            missing_by_field = {
                field: [log["log_date"] for log in logs if log[field] is None]
                for field in ("hrv", "heart_rate", "sleep_hours", "soreness_level")
            }

            # Calculate simple averages for trend analysis
            hrv_values = [log["hrv"] for log in logs if log["hrv"] is not None]
            hr_values = [log["heart_rate"] for log in logs if log["heart_rate"] is not None]
            sleep_values = [log["sleep_hours"] for log in logs if log["sleep_hours"] is not None]
            soreness_values = [log["soreness_level"] for log in logs if log["soreness_level"] is not None]

            averages = {
                "avg_hrv": round(sum(hrv_values) / len(hrv_values), 1) if hrv_values else None,
                "avg_heart_rate": round(sum(hr_values) / len(hr_values), 1) if hr_values else None,
                "avg_sleep_hours": round(sum(sleep_values) / len(sleep_values), 2) if sleep_values else None,
                "avg_soreness": round(sum(soreness_values) / len(soreness_values), 1) if soreness_values else None
            }

            return ToolResult(
                success=True,
                data={
                    "message": (
                        f"Retrieved {len(logs)} recovery logs from the last {days} days. "
                        + (f"No log at all on: {', '.join(missing_dates)}. " if missing_dates else "")
                        + "Report missing days as missing — do not estimate or interpolate values."
                    ),
                    "logs": logs,
                    "averages": averages,
                    "days_requested": days,
                    "days_with_logs": len(logs),
                    "missing_dates": missing_dates,
                    "missing_by_field": missing_by_field,
                }
            )

        except Exception as e:
            return ToolResult(
                success=False,
                data={"error": f"Failed to retrieve recovery logs: {str(e)}"}
            )
