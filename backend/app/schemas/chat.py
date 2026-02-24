"""Chat and messaging schemas."""
from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel


class UserSettings(BaseModel):
    theme: Optional[str] = "dark"
    notifications_enabled: Optional[bool] = True
    language: Optional[str] = "en"
    timezone: Optional[str] = "America/New_York"


class ImageContent(BaseModel):
    """Image content for multimodal messages"""
    type: str = "image"
    data: str  # Base64 encoded image data
    media_type: str = "image/jpeg"  # e.g., "image/jpeg", "image/png"


class TextContent(BaseModel):
    """Text content for multimodal messages"""
    type: str = "text"
    text: str


class ChatMessage(BaseModel):
    role: str
    content: Union[str, List[Dict[str, Any]]]  # Support both text-only and multimodal


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    conversation_id: Optional[str] = None
    model: Optional[str] = None  # Override default model (e.g., "claude-opus-4-5-20250514")
    ephemeral: Optional[bool] = False  # If true, chat won't be saved to memory
    source: Optional[str] = None  # "workspace" | "webapp" | "ios" - determines available tools
    inbox_item_id: Optional[str] = None  # Pre-load inbox item content for discussion
    notify_on_complete: Optional[bool] = False  # Send push notification when response is ready
    current_screen: Optional[str] = None  # iOS current screen name for context-aware tool loading
    workspace_context: Optional[dict] = None  # Canvas workspace context (open windows, active scene)


class ChatResponse(BaseModel):
    message: ChatMessage
