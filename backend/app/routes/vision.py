"""
Vision API Routes - Screenshot analysis and vision model integration
Routes images to Ollama vision models (qwen3-vl, llava, etc.)
"""
import base64
import hashlib
import logging
import uuid
from datetime import datetime
from typing import Optional, List

import httpx
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.models.user import User
from app.db.session import get_db
from app.models.machine import ShadowScreenshot
from app.models.user_settings import UserSettings
from app.core.vision_formatters import OllamaVisionFormatter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vision", tags=["vision"])

# Default configuration - can be overridden by user settings
DEFAULT_VISION_ENDPOINT = "http://10.185.1.8:11434"
DEFAULT_VISION_MODEL = "qwen3-vl:latest"


class VisionAnalyzeRequest(BaseModel):
    """Request for vision analysis"""
    image_base64: str
    prompt: str
    model: Optional[str] = None  # Override default model


class VisionAnalyzeResponse(BaseModel):
    """Response from vision analysis"""
    response: str
    model: str
    tokens_used: Optional[int] = None


class ScreenshotUploadResponse(BaseModel):
    """Response from screenshot upload"""
    screenshot_id: str
    analysis: Optional[str] = None
    image_hash: str


async def get_user_vision_settings(user_id: str, db: Session) -> dict:
    """
    Get user's vision model settings.
    Returns defaults if not configured.
    """
    from sqlalchemy import select

    stmt = select(UserSettings).where(UserSettings.user_id == user_id)
    settings = db.execute(stmt).scalar_one_or_none()

    if settings:
        return {
            "vision_model": settings.vision_model or DEFAULT_VISION_MODEL,
            "vision_endpoint": settings.vision_endpoint or DEFAULT_VISION_ENDPOINT
        }

    return {
        "vision_model": DEFAULT_VISION_MODEL,
        "vision_endpoint": DEFAULT_VISION_ENDPOINT
    }


async def call_ollama_vision(
    image_base64: str,
    prompt: str,
    model: str,
    endpoint: str
) -> dict:
    """
    Call Ollama with a vision model.
    Uses the Ollama /api/chat endpoint with images.
    """
    formatter = OllamaVisionFormatter()

    # Format the message content
    content = [
        {"type": "image", "data": image_base64},
        {"type": "text", "text": prompt}
    ]
    formatted = formatter.format_message_content(content)

    # Build the request for Ollama chat API
    request_body = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": formatted["content"],
                "images": formatted["images"]
            }
        ],
        "stream": False
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            response = await client.post(
                f"{endpoint}/api/chat",
                json=request_body
            )
            response.raise_for_status()
            result = response.json()

            return {
                "response": result.get("message", {}).get("content", ""),
                "model": model,
                "tokens_used": result.get("eval_count")
            }
        except httpx.TimeoutException:
            logger.error(f"Vision model timeout: {model} at {endpoint}")
            raise HTTPException(status_code=504, detail="Vision model timeout")
        except httpx.HTTPStatusError as e:
            logger.error(f"Vision model error: {e.response.status_code} - {e.response.text}")
            raise HTTPException(
                status_code=e.response.status_code,
                detail=f"Vision model error: {e.response.text}"
            )
        except Exception as e:
            logger.exception(f"Vision model error: {e}")
            raise HTTPException(status_code=500, detail=str(e))


@router.post("/analyze", response_model=VisionAnalyzeResponse)
async def analyze_image(
    request: VisionAnalyzeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Analyze an image using the configured vision model.

    The image should be base64 encoded. The prompt describes what
    analysis to perform on the image.
    """
    user_id = current_user.id
    settings = await get_user_vision_settings(user_id, db)

    model = request.model or settings["vision_model"]
    endpoint = settings["vision_endpoint"]

    logger.info(f"Vision analysis requested by user {user_id} using {model}")

    result = await call_ollama_vision(
        image_base64=request.image_base64,
        prompt=request.prompt,
        model=model,
        endpoint=endpoint
    )

    return VisionAnalyzeResponse(**result)


@router.post("/analyze-file", response_model=VisionAnalyzeResponse)
async def analyze_image_file(
    file: UploadFile = File(...),
    prompt: str = Form(...),
    model: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Analyze an uploaded image file using the vision model.
    Accepts image files (JPEG, PNG, etc.) directly.
    """
    user_id = current_user.id
    settings = await get_user_vision_settings(user_id, db)

    use_model = model or settings["vision_model"]
    endpoint = settings["vision_endpoint"]

    # Read and encode the file
    content = await file.read()
    image_base64 = base64.b64encode(content).decode("utf-8")

    logger.info(f"Vision file analysis requested by user {user_id} using {use_model}")

    result = await call_ollama_vision(
        image_base64=image_base64,
        prompt=prompt,
        model=use_model,
        endpoint=endpoint
    )

    return VisionAnalyzeResponse(**result)


@router.post("/screenshot", response_model=ScreenshotUploadResponse)
async def upload_screenshot(
    file: UploadFile = File(...),
    device_id: str = Form(...),
    session_id: Optional[str] = Form(None),
    window_title: Optional[str] = Form(None),
    app_name: Optional[str] = Form(None),
    analyze: bool = Form(False),
    analyze_prompt: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Upload a screenshot from a desktop agent.

    Optionally analyzes the screenshot using the vision model.
    Stores the screenshot in MinIO for later reference.
    """
    user_id = current_user.id

    # Read the file content
    content = await file.read()
    file_size = len(content)

    # Calculate perceptual hash for change detection
    image_hash = hashlib.md5(content).hexdigest()

    # Generate unique ID
    screenshot_id = str(uuid.uuid4())

    # TODO: Store in MinIO
    # For now, we'll skip MinIO storage and just record metadata
    minio_key = f"screenshots/{user_id}/{device_id}/{screenshot_id}.png"

    # Create database record if we have a session
    if session_id:
        screenshot = ShadowScreenshot(
            id=screenshot_id,
            session_id=session_id,
            minio_key=minio_key,
            file_size_bytes=file_size,
            window_title=window_title,
            app_name=app_name,
            image_hash=image_hash
        )
        db.add(screenshot)
        db.commit()

    # Optionally analyze the screenshot
    analysis = None
    if analyze:
        settings = await get_user_vision_settings(user_id, db)
        image_base64 = base64.b64encode(content).decode("utf-8")

        prompt = analyze_prompt or "Describe what's happening on this screen. What application is being used? What is the user doing?"

        try:
            result = await call_ollama_vision(
                image_base64=image_base64,
                prompt=prompt,
                model=settings["vision_model"],
                endpoint=settings["vision_endpoint"]
            )
            analysis = result["response"]
        except Exception as e:
            logger.error(f"Screenshot analysis failed: {e}")
            # Don't fail the upload if analysis fails

    logger.info(f"Screenshot uploaded: {screenshot_id} from device {device_id}")

    return ScreenshotUploadResponse(
        screenshot_id=screenshot_id,
        analysis=analysis,
        image_hash=image_hash
    )


@router.get("/models")
async def list_vision_models(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List available vision models from Ollama.
    """
    settings = await get_user_vision_settings(current_user.id, db)
    endpoint = settings["vision_endpoint"]

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{endpoint}/api/tags")
            response.raise_for_status()
            models = response.json().get("models", [])

            # Filter to likely vision models
            vision_keywords = ["llava", "bakllava", "moondream", "qwen", "vl", "vision"]
            vision_models = [
                m for m in models
                if any(kw in m.get("name", "").lower() for kw in vision_keywords)
            ]

            return {
                "models": vision_models,
                "current_model": settings["vision_model"],
                "endpoint": endpoint
            }
    except Exception as e:
        logger.error(f"Failed to list vision models: {e}")
        return {
            "models": [],
            "current_model": settings["vision_model"],
            "endpoint": endpoint,
            "error": str(e)
        }


@router.get("/status")
async def vision_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Check vision service status.
    """
    settings = await get_user_vision_settings(current_user.id, db)
    endpoint = settings["vision_endpoint"]
    model = settings["vision_model"]

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{endpoint}/api/tags")
            response.raise_for_status()

            return {
                "status": "available",
                "endpoint": endpoint,
                "model": model
            }
    except Exception as e:
        return {
            "status": "unavailable",
            "endpoint": endpoint,
            "model": model,
            "error": str(e)
        }
