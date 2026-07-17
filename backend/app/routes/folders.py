"""Folder management routes."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.db.session import get_db
from app.models.user import User
from app.models.folder import Folder
from app.models.note import Note
from app.schemas.notes import FolderCreate, FolderUpdate, FolderResponse, TreeNodeResponse
from app.core.deps import get_current_user

router = APIRouter(prefix="/folders", tags=["Folders"])


@router.get("", response_model=List[FolderResponse])
async def list_folders(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all folders for the current user."""
    folders = db.query(Folder).filter(
        Folder.user_id == current_user.id
    ).order_by(Folder.name).all()

    return [
        FolderResponse(
            id=folder.id,
            name=folder.name,
            parent_id=folder.parent_id,
            notes_count=db.query(Note).filter(Note.folder_id == folder.id).count(),
            subfolders_count=db.query(Folder).filter(Folder.parent_id == folder.id).count(),
            created_at=folder.created_at.isoformat(),
            updated_at=folder.updated_at.isoformat()
        )
        for folder in folders
    ]


@router.post("", response_model=FolderResponse)
async def create_folder(
    folder_data: FolderCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new folder."""
    # Validate parent folder exists and belongs to user if provided
    if folder_data.parent_id:
        parent = db.query(Folder).filter(
            Folder.id == folder_data.parent_id,
            Folder.user_id == current_user.id
        ).first()
        if not parent:
            raise HTTPException(status_code=404, detail="Parent folder not found")

    # Check if folder with same name already exists in same parent
    existing = db.query(Folder).filter(
        Folder.user_id == current_user.id,
        Folder.name == folder_data.name,
        Folder.parent_id == folder_data.parent_id
    ).first()
    if existing:
        folder = existing
    else:
        folder = Folder(
            name=folder_data.name,
            parent_id=folder_data.parent_id,
            user_id=current_user.id
        )
        db.add(folder)
        db.commit()
        db.refresh(folder)

    return FolderResponse(
        id=str(folder.id),
        name=folder.name,
        parent_id=str(folder.parent_id) if folder.parent_id else None,
        notes_count=0,
        subfolders_count=0,
        created_at=folder.created_at.isoformat(),
        updated_at=folder.updated_at.isoformat()
    )


@router.get("/tree")
async def get_folder_tree(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get the complete folder and note tree structure."""
    folders = db.query(Folder).filter(Folder.user_id == current_user.id).all()
    notes = db.query(Note).filter(Note.user_id == current_user.id).all()

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
                    created_at=folder.created_at.isoformat() if folder.created_at else "",
                    updated_at=folder.updated_at.isoformat() if folder.updated_at else "",
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
                    created_at=note.created_at.isoformat() if note.created_at else "",
                    updated_at=note.updated_at.isoformat() if note.updated_at else "",
                    children=[]
                )
                nodes.append(node)

        return nodes

    tree = build_tree()
    return {"tree": tree}


@router.put("/{folder_id}", response_model=FolderResponse)
async def update_folder(
    folder_id: str,
    folder_data: FolderUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a folder."""
    folder = db.query(Folder).filter(
        Folder.id == folder_id,
        Folder.user_id == current_user.id
    ).first()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    if folder_data.name is not None:
        folder.name = folder_data.name

    if folder_data.parent_id is not None:
        if folder_data.parent_id:
            parent = db.query(Folder).filter(
                Folder.id == folder_data.parent_id,
                Folder.user_id == current_user.id
            ).first()
            if not parent:
                raise HTTPException(status_code=404, detail="Parent folder not found")
        folder.parent_id = folder_data.parent_id

    db.commit()
    db.refresh(folder)

    notes_count = db.query(Note).filter(Note.folder_id == folder.id).count()
    subfolders_count = db.query(Folder).filter(Folder.parent_id == folder.id).count()

    return FolderResponse(
        id=folder.id,
        name=folder.name,
        parent_id=folder.parent_id,
        notes_count=notes_count,
        subfolders_count=subfolders_count,
        created_at=folder.created_at.isoformat(),
        updated_at=folder.updated_at.isoformat()
    )


@router.delete("/{folder_id}")
async def delete_folder(
    folder_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a folder and move its contents to root."""
    folder = db.query(Folder).filter(
        Folder.id == folder_id,
        Folder.user_id == current_user.id
    ).first()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    # Move notes in this folder to root
    db.query(Note).filter(
        Note.folder_id == folder_id,
        Note.user_id == current_user.id
    ).update({"folder_id": None})

    # Move subfolders to parent folder (or root)
    db.query(Folder).filter(
        Folder.parent_id == folder_id,
        Folder.user_id == current_user.id
    ).update({"parent_id": folder.parent_id})

    db.delete(folder)
    db.commit()

    return {"message": "Folder deleted successfully"}
