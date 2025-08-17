from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File, Form
from sqlalchemy.orm import Session
from sqlalchemy import desc, or_
from pydantic import BaseModel
from typing import List, Optional
from uuid import UUID
import uuid
import logging
import asyncio
import mimetypes
from pathlib import Path
from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.doc import Document, DocChunk
from app.services.embeddings import get_embedding, chunk_text, get_embeddings_batch
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


class DocumentResponse(BaseModel):
    id: str
    title: str
    storage_key: str
    mime_type: Optional[str]
    meta: dict
    created_at: str
    chunk_count: int


class DocumentsListResponse(BaseModel):
    documents: List[DocumentResponse]
    total: int
    page: int
    per_page: int


class ChunkResponse(BaseModel):
    id: str
    chunk_idx: int
    text: str
    breadcrumb: str


class DocumentWithChunksResponse(BaseModel):
    id: str
    title: str
    storage_key: str
    mime_type: Optional[str]
    meta: dict
    created_at: str
    chunks: List[ChunkResponse]


class DocumentSearchResult(BaseModel):
    document_id: str
    document_title: str
    chunk_id: str
    chunk_idx: int
    text: str
    breadcrumb: str
    similarity_score: float


class DocumentSearchResponse(BaseModel):
    results: List[DocumentSearchResult]
    total: int


# Supported file types
SUPPORTED_MIME_TYPES = {
    "application/pdf": [".pdf"],
    "text/plain": [".txt"],
    "text/markdown": [".md", ".markdown"],
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [".docx"],
    "application/msword": [".doc"],
    "text/html": [".html", ".htm"],
    "application/json": [".json"],
    "text/csv": [".csv"],
    "application/rtf": [".rtf"]
}

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


def extract_text_from_file(file_content: bytes, mime_type: str, filename: str) -> str:
    """Extract text content from uploaded file based on MIME type"""
    
    try:
        if mime_type == "text/plain" or mime_type == "text/markdown":
            return file_content.decode('utf-8')
        
        elif mime_type == "text/html":
            # Basic HTML text extraction (in production, use BeautifulSoup)
            import re
            text = file_content.decode('utf-8')
            text = re.sub(r'<[^>]+>', '', text)  # Remove HTML tags
            return text
        
        elif mime_type == "application/json":
            import json
            data = json.loads(file_content.decode('utf-8'))
            return json.dumps(data, indent=2)
        
        elif mime_type == "text/csv":
            return file_content.decode('utf-8')
        
        elif mime_type == "application/pdf":
            # For PDF extraction, you'd use PyPDF2 or similar
            # For now, return placeholder
            return f"PDF content extraction not implemented for {filename}"
        
        elif mime_type in ["application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/msword"]:
            # For Word docs, you'd use python-docx or similar
            return f"Word document content extraction not implemented for {filename}"
        
        else:
            return f"Text extraction not supported for {mime_type}"
            
    except Exception as e:
        logger.error(f"Failed to extract text from {filename}: {e}")
        return f"Failed to extract text: {str(e)}"


@router.get("/", response_model=DocumentsListResponse)
async def list_documents(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List user's documents with pagination and search"""
    
    try:
        query = db.query(Document).filter(Document.user_id == current_user.id)
        
        # Apply search filter
        if search:
            search_term = f"%{search}%"
            query = query.filter(Document.title.ilike(search_term))
        
        # Get total count
        total = query.count()
        
        # Apply pagination and ordering
        offset = (page - 1) * per_page
        documents = query.order_by(desc(Document.created_at)).offset(offset).limit(per_page).all()
        
        document_responses = []
        for doc in documents:
            chunk_count = db.query(DocChunk).filter(DocChunk.file_id == doc.id).count()
            document_responses.append(
                DocumentResponse(
                    id=str(doc.id),
                    title=doc.title,
                    storage_key=doc.storage_key,
                    mime_type=doc.mime_type,
                    meta=doc.meta,
                    created_at=doc.created_at.isoformat(),
                    chunk_count=chunk_count
                )
            )
        
        return DocumentsListResponse(
            documents=document_responses,
            total=total,
            page=page,
            per_page=per_page
        )
        
    except Exception as e:
        logger.error(f"Failed to list documents: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve documents")


@router.post("/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Upload and process a document"""
    
    try:
        # Validate file size
        if file.size and file.size > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File too large. Maximum size is {MAX_FILE_SIZE // (1024*1024)}MB"
            )
        
        # Determine MIME type
        mime_type = file.content_type
        if not mime_type:
            mime_type, _ = mimetypes.guess_type(file.filename)
        
        # Validate file type
        if mime_type not in SUPPORTED_MIME_TYPES:
            supported_extensions = []
            for exts in SUPPORTED_MIME_TYPES.values():
                supported_extensions.extend(exts)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported file type. Supported extensions: {', '.join(supported_extensions)}"
            )
        
        # Read file content
        file_content = await file.read()
        
        # Use provided title or filename
        doc_title = title or Path(file.filename).stem
        
        # Generate storage key (in production, this would be an S3/MinIO key)
        storage_key = f"documents/{current_user.id}/{uuid.uuid4()}/{file.filename}"
        
        # Extract text content
        text_content = extract_text_from_file(file_content, mime_type, file.filename)
        
        # Create document record
        document = Document(
            user_id=current_user.id,
            title=doc_title,
            storage_key=storage_key,
            mime_type=mime_type,
            meta={
                "filename": file.filename,
                "file_size": len(file_content),
                "extraction_method": "basic"
            }
        )
        
        db.add(document)
        db.flush()  # Get document ID
        
        # Chunk the text content
        chunks = chunk_text(text_content)
        
        if chunks:
            # Generate embeddings for all chunks
            embeddings = await get_embeddings_batch(chunks)
            
            # Create chunk records
            chunk_objects = []
            for idx, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                chunk_obj = DocChunk(
                    file_id=document.id,
                    chunk_idx=idx,
                    text=chunk,
                    breadcrumb=doc_title,  # Basic breadcrumb
                    embedding=embedding
                )
                chunk_objects.append(chunk_obj)
            
            db.add_all(chunk_objects)
        
        db.commit()
        db.refresh(document)
        
        return DocumentResponse(
            id=str(document.id),
            title=document.title,
            storage_key=document.storage_key,
            mime_type=document.mime_type,
            meta=document.meta,
            created_at=document.created_at.isoformat(),
            chunk_count=len(chunks)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to upload document: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to upload document")


@router.get("/{document_id}", response_model=DocumentWithChunksResponse)
async def get_document(
    document_id: UUID,
    include_chunks: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific document, optionally with chunks"""
    
    document = db.query(Document).filter(
        Document.id == document_id,
        Document.user_id == current_user.id
    ).first()
    
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )
    
    chunks = []
    if include_chunks:
        chunk_records = db.query(DocChunk).filter(
            DocChunk.file_id == document_id
        ).order_by(DocChunk.chunk_idx).all()
        
        chunks = [
            ChunkResponse(
                id=str(chunk.id),
                chunk_idx=chunk.chunk_idx,
                text=chunk.text,
                breadcrumb=chunk.breadcrumb
            )
            for chunk in chunk_records
        ]
    
    return DocumentWithChunksResponse(
        id=str(document.id),
        title=document.title,
        storage_key=document.storage_key,
        mime_type=document.mime_type,
        meta=document.meta,
        created_at=document.created_at.isoformat(),
        chunks=chunks
    )


@router.delete("/{document_id}")
async def delete_document(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a document and all its chunks"""
    
    try:
        document = db.query(Document).filter(
            Document.id == document_id,
            Document.user_id == current_user.id
        ).first()
        
        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found"
            )
        
        # Delete document (chunks will be deleted via cascade)
        db.delete(document)
        db.commit()
        
        return {"message": "Document deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete document: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to delete document")


@router.post("/search", response_model=DocumentSearchResponse)
async def search_documents(
    query: str = Form(...),
    limit: int = Form(10, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Search documents using semantic similarity"""
    
    try:
        # Generate query embedding
        query_embedding = await get_embedding(query)
        
        # Search for similar chunks
        sql = """
        SELECT 
            dc.id as chunk_id,
            dc.file_id as document_id,
            dc.chunk_idx,
            dc.text,
            dc.breadcrumb,
            d.title as document_title,
            1 - (dc.embedding <=> :query_embedding) as similarity
        FROM doc_chunk dc
        JOIN document d ON dc.file_id = d.id
        WHERE d.user_id = :user_id
            AND dc.embedding IS NOT NULL
        ORDER BY similarity DESC
        LIMIT :limit
        """
        
        result = db.execute(sql, {
            "query_embedding": query_embedding,
            "user_id": str(current_user.id),
            "limit": limit
        })
        
        search_results = []
        for row in result.fetchall():
            search_results.append(DocumentSearchResult(
                document_id=str(row.document_id),
                document_title=row.document_title,
                chunk_id=str(row.chunk_id),
                chunk_idx=row.chunk_idx,
                text=row.text,
                breadcrumb=row.breadcrumb,
                similarity_score=float(row.similarity)
            ))
        
        return DocumentSearchResponse(
            results=search_results,
            total=len(search_results)
        )
        
    except Exception as e:
        logger.error(f"Failed to search documents: {e}")
        raise HTTPException(status_code=500, detail="Failed to search documents")


@router.get("/{document_id}/chunks", response_model=List[ChunkResponse])
async def get_document_chunks(
    document_id: UUID,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get chunks for a specific document"""
    
    try:
        # Verify document ownership
        document = db.query(Document).filter(
            Document.id == document_id,
            Document.user_id == current_user.id
        ).first()
        
        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found"
            )
        
        # Get chunks with pagination
        offset = (page - 1) * per_page
        chunks = db.query(DocChunk).filter(
            DocChunk.file_id == document_id
        ).order_by(DocChunk.chunk_idx).offset(offset).limit(per_page).all()
        
        return [
            ChunkResponse(
                id=str(chunk.id),
                chunk_idx=chunk.chunk_idx,
                text=chunk.text,
                breadcrumb=chunk.breadcrumb
            )
            for chunk in chunks
        ]
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get document chunks: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve document chunks")


@router.post("/{document_id}/reprocess")
async def reprocess_document(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Reprocess a document (regenerate chunks and embeddings)"""
    
    try:
        document = db.query(Document).filter(
            Document.id == document_id,
            Document.user_id == current_user.id
        ).first()
        
        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found"
            )
        
        # Delete existing chunks
        db.query(DocChunk).filter(DocChunk.file_id == document_id).delete()
        
        # In a real implementation, you'd retrieve the file from storage
        # and re-extract the text. For now, we'll return an error.
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Document reprocessing requires file storage integration"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to reprocess document: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to reprocess document")