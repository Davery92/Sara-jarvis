from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from pydantic import BaseModel
from typing import List, Optional
import logging

from app.core.deps import get_current_user, get_db
from app.models.user import User
from app.models.folder import Folder
from app.models.note import Note

logger = logging.getLogger(__name__)

router = APIRouter()


class FolderCreate(BaseModel):
    name: str
    parent_id: Optional[str] = None


class FolderUpdate(BaseModel):
    name: Optional[str] = None
    parent_id: Optional[str] = None


class FolderResponse(BaseModel):
    id: str
    name: str
    parent_id: Optional[str]
    full_path: str
    notes_count: int
    subfolders_count: int
    created_at: str
    updated_at: str


class TreeNodeResponse(BaseModel):
    id: str
    name: str
    type: str  # "folder" or "note"
    parent_id: Optional[str]
    children: List["TreeNodeResponse"] = []
    created_at: str
    updated_at: str


# Enable forward references for recursive models
TreeNodeResponse.model_rebuild()


class FolderTreeResponse(BaseModel):
    tree: List[TreeNodeResponse]


@router.post("/", response_model=FolderResponse)
async def create_folder(
    folder_data: FolderCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new folder"""
    try:
        # Validate parent folder exists and belongs to user
        if folder_data.parent_id:
            parent = db.query(Folder).filter(
                and_(
                    Folder.id == folder_data.parent_id,
                    Folder.user_id == current_user.id
                )
            ).first()
            if not parent:
                raise HTTPException(status_code=404, detail="Parent folder not found")
        
        # Create new folder
        folder = Folder(
            name=folder_data.name,
            parent_id=folder_data.parent_id,
            user_id=current_user.id
        )
        
        db.add(folder)
        db.commit()
        db.refresh(folder)
        
        # Count notes and subfolders
        notes_count = db.query(Note).filter(Note.folder_id == folder.id).count()
        subfolders_count = db.query(Folder).filter(Folder.parent_id == folder.id).count()
        
        return FolderResponse(
            id=str(folder.id),
            name=folder.name,
            parent_id=str(folder.parent_id) if folder.parent_id else None,
            full_path=folder.full_path,
            notes_count=notes_count,
            subfolders_count=subfolders_count,
            created_at=folder.created_at.isoformat(),
            updated_at=folder.updated_at.isoformat()
        )
        
    except Exception as e:
        logger.error(f"Failed to create folder: {e}")
        raise HTTPException(status_code=500, detail="Failed to create folder")


@router.get("/tree", response_model=FolderTreeResponse)
async def get_folder_tree(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get the complete folder and note tree structure"""
    try:
        # Get all folders for the user
        folders = db.query(Folder).filter(Folder.user_id == current_user.id).all()
        
        # Get all notes for the user
        notes = db.query(Note).filter(Note.user_id == current_user.id).all()
        
        # Build tree structure
        def build_tree(parent_id=None):
            nodes = []
            
            # Add folders
            for folder in folders:
                if folder.parent_id == parent_id:
                    node = TreeNodeResponse(
                        id=str(folder.id),
                        name=folder.name,
                        type="folder",
                        parent_id=str(folder.parent_id) if folder.parent_id else None,
                        created_at=folder.created_at.isoformat(),
                        updated_at=folder.updated_at.isoformat(),
                        children=build_tree(folder.id)
                    )
                    nodes.append(node)
            
            # Add notes
            for note in notes:
                if note.folder_id == parent_id:
                    node = TreeNodeResponse(
                        id=str(note.id),
                        name=note.title or "Untitled",
                        type="note",
                        parent_id=str(note.folder_id) if note.folder_id else None,
                        created_at=note.created_at.isoformat(),
                        updated_at=note.updated_at.isoformat(),
                        children=[]
                    )
                    nodes.append(node)
            
            return nodes
        
        tree = build_tree()
        
        return FolderTreeResponse(tree=tree)
        
    except Exception as e:
        logger.error(f"Failed to get folder tree: {e}")
        raise HTTPException(status_code=500, detail="Failed to get folder tree")


@router.put("/{folder_id}", response_model=FolderResponse)
async def update_folder(
    folder_id: str,
    folder_data: FolderUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a folder"""
    try:
        folder = db.query(Folder).filter(
            and_(
                Folder.id == folder_id,
                Folder.user_id == current_user.id
            )
        ).first()
        
        if not folder:
            raise HTTPException(status_code=404, detail="Folder not found")
        
        # Update fields
        if folder_data.name is not None:
            folder.name = folder_data.name
        
        if folder_data.parent_id is not None:
            # Validate new parent exists and belongs to user
            if folder_data.parent_id:
                parent = db.query(Folder).filter(
                    and_(
                        Folder.id == folder_data.parent_id,
                        Folder.user_id == current_user.id
                    )
                ).first()
                if not parent:
                    raise HTTPException(status_code=404, detail="Parent folder not found")
            
            folder.parent_id = folder_data.parent_id
        
        db.commit()
        db.refresh(folder)
        
        # Count notes and subfolders
        notes_count = db.query(Note).filter(Note.folder_id == folder.id).count()
        subfolders_count = db.query(Folder).filter(Folder.parent_id == folder.id).count()
        
        return FolderResponse(
            id=str(folder.id),
            name=folder.name,
            parent_id=str(folder.parent_id) if folder.parent_id else None,
            full_path=folder.full_path,
            notes_count=notes_count,
            subfolders_count=subfolders_count,
            created_at=folder.created_at.isoformat(),
            updated_at=folder.updated_at.isoformat()
        )
        
    except Exception as e:
        logger.error(f"Failed to update folder: {e}")
        raise HTTPException(status_code=500, detail="Failed to update folder")


@router.delete("/{folder_id}")
async def delete_folder(
    folder_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a folder and all its contents"""
    try:
        folder = db.query(Folder).filter(
            and_(
                Folder.id == folder_id,
                Folder.user_id == current_user.id
            )
        ).first()
        
        if not folder:
            raise HTTPException(status_code=404, detail="Folder not found")
        
        db.delete(folder)
        db.commit()
        
        return {"message": "Folder deleted successfully"}
        
    except Exception as e:
        logger.error(f"Failed to delete folder: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete folder")