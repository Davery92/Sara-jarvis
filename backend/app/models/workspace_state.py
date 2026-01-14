"""
Workspace State Model
Stores the canvas/workspace state for each user (windows, positions, zoom level).
"""
from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base import Base
import uuid


class WorkspaceState(Base):
    """User's workspace/canvas state for cross-device sync"""
    __tablename__ = "workspace_states"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), unique=True, nullable=False)

    # Full canvas state as JSON
    # Structure:
    # {
    #     "transform": {"x": 0, "y": 0, "scale": 1},
    #     "windows": [
    #         {
    #             "id": "...",
    #             "type": "note|chat|fitness|...",
    #             "title": "...",
    #             "position": {"x": 100, "y": 100},
    #             "size": {"width": 500, "height": 400},
    #             "zIndex": 1,
    #             "data": {...}  # Window-specific data
    #         }
    #     ]
    # }
    state_data = Column(JSONB, default=dict)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User")

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "state_data": self.state_data or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
