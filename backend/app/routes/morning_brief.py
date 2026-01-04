"""
Morning Brief API Routes
Endpoints for generating and retrieving morning briefs with news, weather, and calendar.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import date, datetime, timezone
import json
import logging
from pathlib import Path

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.services.morning_brief_service import morning_brief_service
from app.services.weather_service import weather_service

logger = logging.getLogger(__name__)

router = APIRouter()


# Response Models
class WeatherCurrentResponse(BaseModel):
    temperature: float
    feels_like: float
    humidity: int
    description: str
    icon: str
    wind_speed: float


class WeatherForecastResponse(BaseModel):
    date: str
    temp_high: float
    temp_low: float
    description: str
    icon: str
    pop: float


class WeatherResponse(BaseModel):
    location: str
    current: WeatherCurrentResponse
    forecast: List[WeatherForecastResponse]
    fetched_at: str


class BriefSummaryResponse(BaseModel):
    id: str
    brief_date: str
    has_audio: bool
    audio_duration_seconds: Optional[float]
    generated_at: Optional[str]
    viewed_at: Optional[str]


class BriefDetailResponse(BaseModel):
    id: str
    brief_date: str
    news_summary: Optional[str]
    weather_summary: Optional[str]
    calendar_summary: Optional[str]
    full_text: Optional[str]
    has_audio: bool
    audio_duration_seconds: Optional[float]
    recovery_text: Optional[str]
    has_recovery_audio: bool
    generated_at: Optional[str]


class GenerateBriefResponse(BaseModel):
    success: bool
    message: str
    brief_id: Optional[str]


# Endpoints

@router.get("/weather", response_model=WeatherResponse)
async def get_weather(
    current_user: User = Depends(get_current_user)
):
    """Get current weather for Allentown, PA."""
    try:
        weather = await weather_service.get_weather()
        if not weather:
            raise HTTPException(status_code=503, detail="Weather service unavailable")

        return WeatherResponse(
            location=weather.location,
            current=WeatherCurrentResponse(
                temperature=weather.current.temperature,
                feels_like=weather.current.feels_like,
                humidity=weather.current.humidity,
                description=weather.current.description,
                icon=weather.current.icon,
                wind_speed=weather.current.wind_speed
            ),
            forecast=[
                WeatherForecastResponse(
                    date=f.date,
                    temp_high=f.temp_high,
                    temp_low=f.temp_low,
                    description=f.description,
                    icon=f.icon,
                    pop=f.pop
                )
                for f in weather.forecast[:5]
            ],
            fetched_at=weather.fetched_at
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting weather: {e}")
        raise HTTPException(status_code=500, detail="Failed to get weather")


@router.get("/today", response_model=BriefDetailResponse)
async def get_today_brief(
    include_recovery: bool = Query(False, description="Generate recovery section if not already present"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get today's morning brief."""
    try:
        today = date.today().strftime("%Y-%m-%d")

        result = db.execute(text("""
            SELECT id, brief_date, news_summary, weather_summary, calendar_summary,
                   full_text, audio_path, audio_duration_seconds, recovery_text,
                   recovery_audio_path, generated_at
            FROM morning_brief
            WHERE user_id = :user_id AND brief_date = :brief_date
        """), {"user_id": str(current_user.id), "brief_date": today}).fetchone()

        if not result:
            raise HTTPException(
                status_code=404,
                detail="No brief generated for today. Use POST /morning-brief/generate to create one."
            )

        brief = dict(result._mapping)

        # Generate recovery section on-demand if requested and not present
        if include_recovery and not brief.get("recovery_text"):
            recovery_text, recovery_audio_path = await morning_brief_service.generate_recovery_section(
                str(current_user.id), db
            )
            # Update the database
            db.execute(text("""
                UPDATE morning_brief
                SET recovery_text = :recovery_text, recovery_audio_path = :recovery_audio_path
                WHERE id = :id
            """), {
                "id": brief["id"],
                "recovery_text": recovery_text,
                "recovery_audio_path": recovery_audio_path
            })
            db.commit()
            brief["recovery_text"] = recovery_text
            brief["recovery_audio_path"] = recovery_audio_path

        # Mark as viewed
        db.execute(text("""
            UPDATE morning_brief SET viewed_at = :now WHERE id = :id AND viewed_at IS NULL
        """), {"id": brief["id"], "now": datetime.now(timezone.utc)})
        db.commit()

        return BriefDetailResponse(
            id=brief["id"],
            brief_date=str(brief["brief_date"]),
            news_summary=brief.get("news_summary"),
            weather_summary=brief.get("weather_summary"),
            calendar_summary=brief.get("calendar_summary"),
            full_text=brief.get("full_text"),
            has_audio=bool(brief.get("audio_path")),
            audio_duration_seconds=brief.get("audio_duration_seconds"),
            recovery_text=brief.get("recovery_text"),
            has_recovery_audio=bool(brief.get("recovery_audio_path")),
            generated_at=brief.get("generated_at").isoformat() if brief.get("generated_at") else None
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting today's brief: {e}")
        raise HTTPException(status_code=500, detail="Failed to get brief")


@router.get("/today/audio")
async def get_today_audio(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Stream today's pre-generated audio."""
    try:
        today = date.today().strftime("%Y-%m-%d")

        result = db.execute(text("""
            SELECT id, audio_path FROM morning_brief
            WHERE user_id = :user_id AND brief_date = :brief_date
        """), {"user_id": str(current_user.id), "brief_date": today}).fetchone()

        if not result or not result.audio_path:
            raise HTTPException(status_code=404, detail="No audio available for today's brief")

        audio_path = Path(result.audio_path)
        if not audio_path.exists():
            raise HTTPException(status_code=404, detail="Audio file not found")

        # Mark as listened
        db.execute(text("""
            UPDATE morning_brief SET listened_at = :now WHERE id = :id AND listened_at IS NULL
        """), {"id": result.id, "now": datetime.now(timezone.utc)})
        db.commit()

        return FileResponse(
            audio_path,
            media_type="audio/mpeg",
            filename=f"morning_brief_{today}.mp3"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error streaming audio: {e}")
        raise HTTPException(status_code=500, detail="Failed to stream audio")


@router.get("/today/recovery-audio")
async def get_recovery_audio(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Stream recovery section audio (generated on-demand)."""
    try:
        today = date.today().strftime("%Y-%m-%d")

        result = db.execute(text("""
            SELECT id, recovery_audio_path FROM morning_brief
            WHERE user_id = :user_id AND brief_date = :brief_date
        """), {"user_id": str(current_user.id), "brief_date": today}).fetchone()

        if not result:
            raise HTTPException(status_code=404, detail="No brief found for today")

        # Generate recovery audio if not present
        recovery_audio_path = result.recovery_audio_path
        if not recovery_audio_path:
            _, recovery_audio_path = await morning_brief_service.generate_recovery_section(
                str(current_user.id), db
            )
            if recovery_audio_path:
                db.execute(text("""
                    UPDATE morning_brief SET recovery_audio_path = :path WHERE id = :id
                """), {"id": result.id, "path": recovery_audio_path})
                db.commit()

        if not recovery_audio_path:
            raise HTTPException(status_code=404, detail="Unable to generate recovery audio")

        audio_path = Path(recovery_audio_path)
        if not audio_path.exists():
            raise HTTPException(status_code=404, detail="Recovery audio file not found")

        return FileResponse(
            audio_path,
            media_type="audio/mpeg",
            filename=f"recovery_brief_{today}.mp3"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error streaming recovery audio: {e}")
        raise HTTPException(status_code=500, detail="Failed to stream recovery audio")


@router.post("/generate", response_model=GenerateBriefResponse)
async def generate_brief(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Manually generate or regenerate today's morning brief."""
    try:
        brief = await morning_brief_service.generate_brief(str(current_user.id), db)

        return GenerateBriefResponse(
            success=True,
            message="Morning brief generated successfully",
            brief_id=brief.brief_date  # Using date as identifier
        )

    except Exception as e:
        logger.error(f"Error generating brief: {e}")
        return GenerateBriefResponse(
            success=False,
            message=f"Failed to generate brief: {str(e)}",
            brief_id=None
        )


@router.get("/history", response_model=List[BriefSummaryResponse])
async def get_brief_history(
    limit: int = Query(7, ge=1, le=30),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get recent morning briefs."""
    try:
        result = db.execute(text("""
            SELECT id, brief_date, audio_path, audio_duration_seconds, generated_at, viewed_at
            FROM morning_brief
            WHERE user_id = :user_id
            ORDER BY brief_date DESC
            LIMIT :limit
        """), {"user_id": str(current_user.id), "limit": limit})

        briefs = []
        for row in result.fetchall():
            brief = dict(row._mapping)
            briefs.append(BriefSummaryResponse(
                id=brief["id"],
                brief_date=str(brief["brief_date"]),
                has_audio=bool(brief.get("audio_path")),
                audio_duration_seconds=brief.get("audio_duration_seconds"),
                generated_at=brief.get("generated_at").isoformat() if brief.get("generated_at") else None,
                viewed_at=brief.get("viewed_at").isoformat() if brief.get("viewed_at") else None
            ))

        return briefs

    except Exception as e:
        logger.error(f"Error getting brief history: {e}")
        raise HTTPException(status_code=500, detail="Failed to get brief history")


@router.get("/{brief_date}/audio")
async def get_audio_by_date(
    brief_date: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Stream audio for a specific brief date."""
    try:
        # Validate date format
        try:
            date.fromisoformat(brief_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

        result = db.execute(text("""
            SELECT id, audio_path FROM morning_brief
            WHERE user_id = :user_id AND brief_date = :brief_date
        """), {"user_id": str(current_user.id), "brief_date": brief_date}).fetchone()

        if not result or not result.audio_path:
            raise HTTPException(status_code=404, detail=f"No audio available for brief on {brief_date}")

        audio_path = Path(result.audio_path)
        if not audio_path.exists():
            raise HTTPException(status_code=404, detail="Audio file not found")

        # Mark as listened
        db.execute(text("""
            UPDATE morning_brief SET listened_at = :now WHERE id = :id AND listened_at IS NULL
        """), {"id": result.id, "now": datetime.now(timezone.utc)})
        db.commit()

        return FileResponse(
            audio_path,
            media_type="audio/mpeg",
            filename=f"morning_brief_{brief_date}.mp3"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error streaming audio for {brief_date}: {e}")
        raise HTTPException(status_code=500, detail="Failed to stream audio")


@router.get("/{brief_date}/recovery-audio")
async def get_recovery_audio_by_date(
    brief_date: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Stream recovery audio for a specific brief date."""
    try:
        # Validate date format
        try:
            date.fromisoformat(brief_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

        result = db.execute(text("""
            SELECT id, recovery_audio_path FROM morning_brief
            WHERE user_id = :user_id AND brief_date = :brief_date
        """), {"user_id": str(current_user.id), "brief_date": brief_date}).fetchone()

        if not result:
            raise HTTPException(status_code=404, detail=f"No brief found for {brief_date}")

        recovery_audio_path = result.recovery_audio_path

        # Only generate recovery audio on-demand for today's brief
        today_str = date.today().strftime("%Y-%m-%d")
        if not recovery_audio_path and brief_date == today_str:
            _, recovery_audio_path = await morning_brief_service.generate_recovery_section(
                str(current_user.id), db
            )
            if recovery_audio_path:
                db.execute(text("""
                    UPDATE morning_brief SET recovery_audio_path = :path WHERE id = :id
                """), {"id": result.id, "path": recovery_audio_path})
                db.commit()

        if not recovery_audio_path:
            raise HTTPException(status_code=404, detail="No recovery audio available")

        audio_path = Path(recovery_audio_path)
        if not audio_path.exists():
            raise HTTPException(status_code=404, detail="Recovery audio file not found")

        return FileResponse(
            audio_path,
            media_type="audio/mpeg",
            filename=f"recovery_brief_{brief_date}.mp3"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error streaming recovery audio for {brief_date}: {e}")
        raise HTTPException(status_code=500, detail="Failed to stream recovery audio")


@router.get("/{brief_date}", response_model=BriefDetailResponse)
async def get_brief_by_date(
    brief_date: str,
    include_recovery: bool = Query(True, description="Generate recovery section if not already present"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific brief by date (YYYY-MM-DD)."""
    try:
        # Validate date format
        try:
            date.fromisoformat(brief_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

        result = db.execute(text("""
            SELECT id, brief_date, news_summary, weather_summary, calendar_summary,
                   full_text, audio_path, audio_duration_seconds, recovery_text,
                   recovery_audio_path, generated_at
            FROM morning_brief
            WHERE user_id = :user_id AND brief_date = :brief_date
        """), {"user_id": str(current_user.id), "brief_date": brief_date}).fetchone()

        if not result:
            raise HTTPException(status_code=404, detail=f"No brief found for {brief_date}")

        brief = dict(result._mapping)

        # Generate recovery section on-demand if requested and not present
        # Only for today's brief (recovery data is for today only)
        today_str = date.today().strftime("%Y-%m-%d")
        if include_recovery and not brief.get("recovery_text") and brief_date == today_str:
            logger.info(f"Generating recovery section for user {current_user.id}")
            recovery_text, recovery_audio_path = await morning_brief_service.generate_recovery_section(
                str(current_user.id), db
            )
            # Update the database
            db.execute(text("""
                UPDATE morning_brief
                SET recovery_text = :recovery_text, recovery_audio_path = :recovery_audio_path
                WHERE id = :id
            """), {
                "id": brief["id"],
                "recovery_text": recovery_text,
                "recovery_audio_path": recovery_audio_path
            })
            db.commit()
            brief["recovery_text"] = recovery_text
            brief["recovery_audio_path"] = recovery_audio_path

        return BriefDetailResponse(
            id=brief["id"],
            brief_date=str(brief["brief_date"]),
            news_summary=brief.get("news_summary"),
            weather_summary=brief.get("weather_summary"),
            calendar_summary=brief.get("calendar_summary"),
            full_text=brief.get("full_text"),
            has_audio=bool(brief.get("audio_path")),
            audio_duration_seconds=brief.get("audio_duration_seconds"),
            recovery_text=brief.get("recovery_text"),
            has_recovery_audio=bool(brief.get("recovery_audio_path")),
            generated_at=brief.get("generated_at").isoformat() if brief.get("generated_at") else None
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting brief for {brief_date}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="Failed to get brief")
