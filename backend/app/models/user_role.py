from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.sql import func

from app.db.base import Base


class UserRole(Base):
    """
    Role mapping for app users.

    Kept as a separate table to allow backward-compatible rollout without
    modifying existing app_user columns.
    """

    __tablename__ = "app_user_role"

    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True)
    role = Column(String(32), nullable=False, default="user")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

