from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text, text
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from app.db.base import Base
from app.core.config import settings
import uuid


class Recipe(Base):
    """Recipe model.

    Aligned with the existing `recipe` table created by
    `migrations/add_recovery_recipes_workout_enhancements.py`, which is also
    used by `routes/fitness.py` recipe endpoints. New columns (tags, embedding,
    starred, etc.) are added via `migrations/add_recipe_table.py`.
    """
    __tablename__ = "recipe"
    __table_args__ = {"extend_existing": True}

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)

    name = Column(String, nullable=False)
    description = Column(Text, default="")
    category = Column(String, nullable=True)

    ingredients = Column(JSON, nullable=False, default=list, server_default=text("'[]'"))
    instructions = Column(Text, nullable=False, default="")
    prep_time_minutes = Column(Integer, nullable=True)
    servings = Column(Integer, nullable=False, default=1, server_default=text("1"))

    calories = Column(Numeric(8, 2), nullable=True)
    protein = Column(Numeric(8, 2), nullable=True)
    carbs = Column(Numeric(8, 2), nullable=True)
    fats = Column(Numeric(8, 2), nullable=True)

    # --- columns added by add_recipe_table.py ---
    cook_time_minutes = Column(Integer, nullable=True)
    meal_type = Column(String, nullable=True)
    cuisine = Column(String, nullable=True)
    tags = Column(JSON, nullable=False, default=list, server_default=text("'[]'"))
    source_url = Column(String, nullable=True)
    source_name = Column(String, nullable=True)
    recipe_notes = Column(Text, default="")
    starred = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    rating = Column(Integer, nullable=True)
    last_made_at = Column(DateTime(timezone=True), nullable=True)
    times_made = Column(Integer, nullable=False, default=0, server_default=text("0"))
    embedding = Column(Vector(settings.embedding_dim))

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User")

    def __repr__(self):
        return f"<Recipe(name='{self.name[:30]}')>"
