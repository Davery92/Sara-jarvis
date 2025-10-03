from sqlalchemy import Column, String, ForeignKey, Integer, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db.base import Base
import uuid


class Folder(Base):
    __tablename__ = "folder"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    parent_id = Column(String, ForeignKey("folder.id", ondelete="CASCADE"), nullable=True)
    
    # For ordering folders/files in UI
    sort_order = Column(Integer, default=0)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Relationships
    user = relationship("User")
    parent = relationship("Folder", remote_side=[id], back_populates="children")
    children = relationship("Folder", back_populates="parent", cascade="all, delete-orphan")
    notes = relationship("Note", back_populates="folder", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Folder(name='{self.name}')>"
    
    @property
    def full_path(self):
        """Get the full path of this folder like /folder1/folder2/folder3"""
        if self.parent:
            return f"{self.parent.full_path}/{self.name}"
        return f"/{self.name}"
    
    @property 
    def is_root(self):
        """Check if this is a root folder"""
        return self.parent_id is None