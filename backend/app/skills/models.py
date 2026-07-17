"""
Skills System Models

Pydantic models for the markdown-based skills system. Skills provide
instruction-based capabilities that inject domain expertise, workflows,
and behavioral guidance into the system prompt.
"""

from datetime import datetime
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel, Field


class SkillRequirements(BaseModel):
    """Requirements that must be met for a skill to load"""
    env: List[str] = Field(default_factory=list, description="Required environment variables")
    config: List[str] = Field(default_factory=list, description="Required config settings (future)")


class SkillMetadata(BaseModel):
    """YAML frontmatter metadata for a skill"""
    name: str = Field(..., description="Unique skill identifier")
    description: str = Field(..., description="Human-readable skill description")
    contexts: List[str] = Field(
        default_factory=list,
        description="Context names when skill should load (empty = always load)"
    )
    enabled: bool = Field(default=True, description="Whether skill is currently active")
    priority: int = Field(default=0, description="Higher priority = injected first")
    requires: SkillRequirements = Field(
        default_factory=SkillRequirements,
        description="Requirements that must be met"
    )
    user_invocable: bool = Field(
        default=False,
        description="If true, user can invoke via /skill-name (future)"
    )


class Skill(BaseModel):
    """A loaded skill with its metadata and instructions"""
    metadata: SkillMetadata
    instructions: str = Field(..., description="The markdown instruction content")
    file_path: Path = Field(..., description="Path to the SKILL.md file")
    last_modified: datetime = Field(..., description="Last modification time of the file")

    class Config:
        arbitrary_types_allowed = True  # Allow Path type

    def __repr__(self) -> str:
        return f"Skill(name={self.metadata.name!r}, priority={self.metadata.priority}, contexts={self.metadata.contexts})"
