"""Memory and conversation schemas."""
from typing import Optional
from pydantic import BaseModel


class ConversationResponse(BaseModel):
    id: str
    title: str
    summary: str
    total_messages: int
    created_at: str
    updated_at: str


class ConversationTurnResponse(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    message_index: int
    created_at: str


# Episode-based conversation models
class EpisodeMessageResponse(BaseModel):
    id: str
    role: str
    content: str
    created_at: str
    importance: Optional[float] = None


class ConversationSummaryResponse(BaseModel):
    conversation_id: str
    first_message: str
    message_count: int
    last_activity: str
    created_at: str


class SetActiveConversationRequest(BaseModel):
    conversation_id: Optional[str] = None
