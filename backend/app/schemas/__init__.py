"""Pydantic schemas for API request/response models."""
from .auth import UserCreate, UserLogin, UserResponse
from .notes import (
    NoteCreate, NoteResponse,
    NoteConnectionCreate, NoteConnectionResponse,
    FolderCreate, FolderUpdate, FolderResponse,
    TreeNodeResponse
)
from .reminders import (
    ReminderCreate, ReminderUpdate, ReminderResponse,
    TimerCreate, TimerResponse
)
from .calendar import (
    CalendarEventCreate, CalendarEventUpdate, CalendarEventResponse,
    IOSCalendarEventSync, IOSCalendarSyncRequest, IOSCalendarSyncResponse
)
from .chat import (
    UserSettings, ImageContent, TextContent,
    ChatMessage, ChatRequest, ChatResponse
)
from .documents import DocumentResponse, Model3DResponse, DocumentChunkResponse
from .memory import (
    ConversationResponse, ConversationTurnResponse,
    EpisodeMessageResponse, ConversationSummaryResponse,
    SetActiveConversationRequest
)
from .habits import (
    HabitCreate, HabitResponse,
    HabitItemCreate, HabitItemResponse,
    HabitInstanceResponse, HabitTodayStats, HabitTodayResponse,
    HabitInsightsOverview, HabitInsightsWeeklyStats,
    HabitInsightsPerformance, HabitInsightsPatterns, HabitInsightsResponse,
    HabitLogCreate, HabitLogResponse,
    HabitStreakResponse, HabitLinkCreate, HabitLinkResponse,
    HabitPauseRequest
)
from .insights import (
    UserProfileCreate, UserProfileResponse,
    AutonomousInsightResponse, InsightFeedbackRequest,
    ActivitySessionResponse, BackgroundSweepResponse
)

__all__ = [
    # Auth
    "UserCreate", "UserLogin", "UserResponse",
    # Notes
    "NoteCreate", "NoteResponse",
    "NoteConnectionCreate", "NoteConnectionResponse",
    "FolderCreate", "FolderUpdate", "FolderResponse",
    "TreeNodeResponse",
    # Reminders
    "ReminderCreate", "ReminderUpdate", "ReminderResponse",
    "TimerCreate", "TimerResponse",
    # Calendar
    "CalendarEventCreate", "CalendarEventUpdate", "CalendarEventResponse",
    "IOSCalendarEventSync", "IOSCalendarSyncRequest", "IOSCalendarSyncResponse",
    # Chat
    "UserSettings", "ImageContent", "TextContent",
    "ChatMessage", "ChatRequest", "ChatResponse",
    # Documents
    "DocumentResponse", "Model3DResponse", "DocumentChunkResponse",
    # Memory
    "ConversationResponse", "ConversationTurnResponse",
    "EpisodeMessageResponse", "ConversationSummaryResponse",
    "SetActiveConversationRequest",
    # Habits
    "HabitCreate", "HabitResponse",
    "HabitItemCreate", "HabitItemResponse",
    "HabitInstanceResponse", "HabitTodayStats", "HabitTodayResponse",
    "HabitInsightsOverview", "HabitInsightsWeeklyStats",
    "HabitInsightsPerformance", "HabitInsightsPatterns", "HabitInsightsResponse",
    "HabitLogCreate", "HabitLogResponse",
    "HabitStreakResponse", "HabitLinkCreate", "HabitLinkResponse",
    "HabitPauseRequest",
    # Insights
    "UserProfileCreate", "UserProfileResponse",
    "AutonomousInsightResponse", "InsightFeedbackRequest",
    "ActivitySessionResponse", "BackgroundSweepResponse",
]
