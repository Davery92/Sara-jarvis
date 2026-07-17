"""ProgressPhoto model — physique progress photos with inline VLM critique.

A user uploads a body/fitness progress photo (stored in MinIO like every other
binary, keyed by ``storage_key``). Tapping "Critique" in the app runs the image
through the configured vision model and stores the returned text on the row so
it renders inline next to the photo. See ``routes/progress_photos.py``.
"""
import uuid

from sqlalchemy import Column, String, Text, Integer, Float, DateTime, ForeignKey
from sqlalchemy.sql import func

from app.db.base import Base


class ProgressPhoto(Base):
    __tablename__ = "progress_photo"
    __table_args__ = {"extend_existing": True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)

    # MinIO object keys (single shared `sara-docs` bucket)
    storage_key = Column(String(500), nullable=False)
    thumbnail_key = Column(String(500))

    original_filename = Column(String(500))
    mime_type = Column(String(100))
    file_size = Column(Integer)
    width = Column(Integer)
    height = Column(Integer)

    # User-supplied context
    taken_at = Column(DateTime(timezone=True))
    notes = Column(Text)
    bodyweight = Column(Float)
    bodyweight_unit = Column(String(8), default="lbs")

    # Inline AI critique (populated on demand)
    critique = Column(Text)
    critique_model = Column(String(100))
    critiqued_at = Column(DateTime(timezone=True))

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<ProgressPhoto id={self.id} user={self.user_id} critiqued={self.critiqued_at is not None}>"
