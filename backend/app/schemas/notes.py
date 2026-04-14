"""Notes and folders schemas."""
from typing import Optional, List
from pydantic import BaseModel


class NoteCreate(BaseModel):
    title: str = ""
    content: str
    folder_id: Optional[str] = None
    tags: Optional[List[str]] = None
    starred: Optional[bool] = None


class NoteResponse(BaseModel):
    id: str
    title: str
    content: str
    folder_id: Optional[str] = None
    tags: List[str] = []
    starred: bool = False
    user_id: Optional[str] = None
    created_at: str
    updated_at: str


class NoteConnectionCreate(BaseModel):
    target_note_id: str
    connection_type: str  # 'reference', 'semantic', 'temporal'
    strength: int = 50  # 0-100
    auto_generated: bool = True


class NoteConnectionResponse(BaseModel):
    id: str
    source_note_id: str
    target_note_id: str
    connection_type: str
    strength: int
    auto_generated: bool
    created_at: str
    updated_at: str


class FolderCreate(BaseModel):
    name: str
    parent_id: Optional[str] = None


class FolderUpdate(BaseModel):
    name: Optional[str] = None
    parent_id: Optional[str] = None


class FolderResponse(BaseModel):
    id: str
    name: str
    parent_id: Optional[str] = None
    notes_count: int = 0
    subfolders_count: int = 0
    created_at: str
    updated_at: str


class TreeNodeResponse(BaseModel):
    id: str
    name: str
    type: str  # "folder" or "note"
    parent_id: Optional[str] = None
    children: list = []
    created_at: str
    updated_at: str
