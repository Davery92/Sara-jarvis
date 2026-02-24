"""Document upload, management, search, and 3D model routes."""
import logging
import os
import uuid
import json
from datetime import datetime

import aiofiles
from fastapi import APIRouter, Depends, HTTPException, UploadFile, Response, File
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.user import User
from app.models.doc import Document
from app.models.document_chunk import DocumentChunk
from app.schemas.documents import DocumentResponse, Model3DResponse, DocumentChunkResponse
from app.core.deps import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Documents"])

# --- Constants ---
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./uploads")

ALLOWED_3D_FORMATS = {'stl', 'obj', 'gltf', 'glb'}
MODEL_MIME_TYPES = {
    'stl': 'model/stl',
    'obj': 'model/obj',
    'gltf': 'model/gltf+json',
    'glb': 'model/gltf-binary',
}

# ──────────────────────────────────────────────
# Document API endpoints
# ──────────────────────────────────────────────

@router.post("/documents", response_model=DocumentResponse)
async def upload_document(
    file: UploadFile = File(...),
    chat_context: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Upload a document with Neo4j-first intelligent processing"""
    # Lazy imports to avoid circular dependencies
    from app.main_simple import document_processor, DATABASE_URL, PGVECTOR_AVAILABLE
    from app.services.embedding_service import embedding_service

    doc_id = str(uuid.uuid4())

    try:
        # Create uploads directory if it doesn't exist
        uploads_dir = "uploads"
        os.makedirs(uploads_dir, exist_ok=True)

        # Generate unique filename while preserving extension
        file_extension = os.path.splitext(file.filename)[1] if file.filename else ""
        unique_filename = f"{uuid.uuid4()}{file_extension}"
        file_path = os.path.join(uploads_dir, unique_filename)

        # Save file to disk
        file_content = await file.read()
        async with aiofiles.open(file_path, 'wb') as f:
            await f.write(file_content)

        # Extract text immediately
        from app.main_simple import DocumentProcessor
        processor = DocumentProcessor()
        extracted_text = ""

        if file.content_type == "application/pdf":
            try:
                extracted_text = processor.extract_text(file_path, file.content_type)
                if not extracted_text or len(extracted_text.strip()) < 10:
                    extracted_text = f"PDF document: {file.filename} (text extraction may have limited success)"
            except Exception as e:
                logger.warning(f"PDF extraction failed: {e}")
                extracted_text = f"PDF document: {file.filename} (text extraction failed)"
        elif file.content_type in ["text/plain", "text/markdown"]:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    extracted_text = f.read()
            except Exception as e:
                logger.warning(f"Text file extraction failed: {e}")
                extracted_text = "Could not extract text from file"
        elif "word" in (file.content_type or "") or file.content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            try:
                extracted_text = processor.extract_text(file_path, file.content_type)
                if not extracted_text:
                    extracted_text = f"Word document: {file.filename}"
            except Exception as e:
                logger.warning(f"Word document extraction failed: {e}")
                extracted_text = f"Word document: {file.filename}"
        else:
            extracted_text = f"Document: {file.filename}"

        # Neo4j-first approach: Create document in Neo4j immediately
        try:
            from app.services.neo4j_service import neo4j_service
            from app.services.intelligence_pipeline import intelligence_pipeline, ContentType

            # Ensure Neo4j connection
            if not neo4j_service.driver:
                await neo4j_service.connect()

            # Create document in Neo4j graph with extracted content
            neo4j_result = await neo4j_service.create_document(
                doc_id=doc_id,
                user_id=current_user.id,
                title=file.filename or "Untitled Document",
                content_text=extracted_text,
                mime_type=file.content_type or "application/octet-stream",
                file_path=file_path
            )

            # Start intelligence pipeline workers if not already running
            await intelligence_pipeline.start_workers()

            # Queue for fast processing (embeddings, obvious connections)
            await intelligence_pipeline.queue_fast_processing(
                content_id=doc_id,
                content_type=ContentType.DOCUMENT,
                metadata={
                    "user_id": current_user.id,
                    "title": file.filename,
                    "mime_type": file.content_type,
                    "file_path": file_path,
                    "file_size": len(file_content)
                }
            )

            logger.info(f"Document {doc_id} created in Neo4j and queued for intelligent processing")

        except Exception as neo_error:
            logger.error(f"Neo4j document creation failed: {neo_error}")
            # Continue with PostgreSQL fallback

        # Background sync to PostgreSQL (backup)
        document = Document(
            id=doc_id,
            user_id=current_user.id,
            filename=unique_filename,
            original_filename=file.filename or "unknown",
            title=file.filename or "Untitled Document",
            file_path=file_path,
            file_size=len(file_content),
            mime_type=file.content_type or "application/octet-stream",
            content_text=extracted_text[:50000] if extracted_text else "",
            is_processed="true"
        )

        db.add(document)
        db.commit()
        db.refresh(document)

        # Legacy chunking for PostgreSQL compatibility (reduced priority)
        try:
            chunks = processor.chunk_text(extracted_text) if extracted_text else []
            max_chunks = 100  # Reduced since Neo4j is primary
            processed_chunks = chunks[:max_chunks]

            if processed_chunks:
                # Generate embeddings for chunks
                chunk_embeddings = await embedding_service.generate_embeddings_batch(processed_chunks)

                # Save chunks to PostgreSQL (skip chunks with failed embeddings)
                saved_chunks = 0
                skipped_chunks = 0
                for i, (chunk_text, embedding) in enumerate(zip(processed_chunks, chunk_embeddings)):
                    if embedding is None:
                        skipped_chunks += 1
                        continue

                    if DATABASE_URL.startswith("postgresql") and PGVECTOR_AVAILABLE:
                        embedding_data = embedding
                    else:
                        embedding_data = json.dumps(embedding)

                    chunk = DocumentChunk(
                        document_id=document.id,
                        user_id=current_user.id,
                        chunk_index=i,
                        chunk_text=chunk_text,
                        embedding=embedding_data
                    )
                    db.add(chunk)
                    saved_chunks += 1

                db.commit()
                if skipped_chunks > 0:
                    logger.warning(f"Legacy chunking: {saved_chunks} chunks saved, {skipped_chunks} skipped (embedding failures)")
                else:
                    logger.info(f"Legacy chunking completed: {saved_chunks} chunks")

        except Exception as chunk_error:
            logger.warning(f"Legacy chunking failed (Neo4j processing continues): {chunk_error}")

        return DocumentResponse(
            id=document.id,
            filename=document.filename,
            original_filename=document.original_filename,
            title=document.title or document.original_filename,
            file_size=document.file_size,
            mime_type=document.mime_type,
            content_text=document.content_text,
            is_processed=document.is_processed,
            created_at=document.created_at.isoformat(),
            updated_at=document.updated_at.isoformat()
        )

    except Exception as e:
        logger.error(f"Document upload error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to upload document: {str(e)}")


@router.get("/documents", response_model=list[DocumentResponse])
async def get_documents(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get all documents for the current user"""
    documents = db.query(Document).filter(Document.user_id == current_user.id).order_by(Document.created_at.desc()).all()

    return [
        DocumentResponse(
            id=doc.id,
            filename=doc.filename,
            original_filename=doc.original_filename,
            title=getattr(doc, 'title', '') or doc.original_filename,
            file_size=doc.file_size,
            mime_type=doc.mime_type,
            content_text=doc.content_text,
            is_processed=doc.is_processed,
            created_at=doc.created_at.isoformat(),
            updated_at=doc.updated_at.isoformat()
        )
        for doc in documents
    ]


@router.get("/documents/{document_id}/file")
async def download_document(
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Download the original document file"""
    document = db.query(Document).filter(
        Document.id == document_id,
        Document.user_id == current_user.id
    ).first()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if not os.path.exists(document.file_path):
        raise HTTPException(status_code=404, detail="Document file not found on disk")

    async with aiofiles.open(document.file_path, 'rb') as f:
        file_content = await f.read()

    return Response(
        content=file_content,
        media_type=document.mime_type,
        headers={
            "Content-Disposition": f"inline; filename=\"{document.original_filename}\"",
            "Access-Control-Expose-Headers": "Content-Disposition"
        }
    )


@router.delete("/documents/{document_id}")
async def delete_document(
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a document and its chunks"""
    document = db.query(Document).filter(
        Document.id == document_id,
        Document.user_id == current_user.id
    ).first()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    # Delete chunks first
    db.query(DocumentChunk).filter(DocumentChunk.document_id == document_id).delete()

    # Skip vector deletion for now to avoid crashes
    logger.info(f"Skipped vector deletion for document {document_id} (disabled for stability)")

    # Delete file from disk
    try:
        if os.path.exists(document.file_path):
            os.remove(document.file_path)
    except Exception as e:
        logger.warning(f"Could not delete file {document.file_path}: {e}")

    # Delete from Neo4j first
    try:
        from app.services.neo4j_service import neo4j_service
        await neo4j_service.delete_document(document_id, current_user.id)
        logger.info(f"Document {document_id} deleted from Neo4j")
    except Exception as e:
        logger.warning(f"Failed to delete document from Neo4j: {e}")

    # Delete document record
    db.delete(document)
    db.commit()

    return {"message": "Document deleted successfully"}


@router.put("/documents/{document_id}", response_model=DocumentResponse)
async def update_document(
    document_id: str,
    title: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update document title"""
    document = db.query(Document).filter(
        Document.id == document_id,
        Document.user_id == current_user.id
    ).first()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    # Update document title
    document.title = title
    db.commit()
    db.refresh(document)

    # Update Neo4j if available
    try:
        from app.services.neo4j_service import neo4j_service
        if neo4j_service.driver:
            await neo4j_service.update_document_title(document_id, title)
    except Exception as e:
        logger.warning(f"Failed to update document title in Neo4j: {e}")

    return DocumentResponse(
        id=document.id,
        filename=document.filename,
        original_filename=document.original_filename,
        title=document.title,
        mime_type=document.mime_type,
        file_size=document.file_size,
        is_processed=document.is_processed,
        content_text=document.content_text,
        created_at=document.created_at.isoformat(),
        updated_at=document.updated_at.isoformat()
    )


@router.get("/documents/search")
async def search_documents(
    query: str,
    limit: int = 5,
    current_user: User = Depends(get_current_user)
):
    """Search for relevant document chunks using vector similarity"""
    # Lazy import to avoid circular dependency
    from app.main_simple import document_processor

    if not query.strip():
        return {"results": []}

    try:
        search_results = document_processor.search_documents(query, current_user.id, limit)

        return {
            "query": query,
            "results": search_results
        }

    except Exception as e:
        logger.error(f"Document search error: {e}")
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


# ──────────────────────────────────────────────
# 3D Model API endpoints
# ──────────────────────────────────────────────

@router.post("/models/upload", response_model=Model3DResponse)
async def upload_3d_model(
    file: UploadFile,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Upload a 3D model file (STL, OBJ, GLTF, GLB)"""
    model_id = str(uuid.uuid4())

    try:
        # Validate file extension
        if not file.filename:
            raise HTTPException(status_code=400, detail="Filename is required")

        file_extension = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
        if file_extension not in ALLOWED_3D_FORMATS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file format. Allowed: {', '.join(ALLOWED_3D_FORMATS)}"
            )

        # Create models directory if it doesn't exist
        models_dir = "uploads/models"
        os.makedirs(models_dir, exist_ok=True)

        # Generate unique filename
        unique_filename = f"{model_id}.{file_extension}"
        file_path = os.path.join(models_dir, unique_filename)

        # Save file to disk
        file_content = await file.read()
        async with aiofiles.open(file_path, 'wb') as f:
            await f.write(file_content)

        # Create database record
        now = datetime.utcnow()
        cursor = db.connection().connection.cursor()
        cursor.execute("""
            INSERT INTO models_3d (id, user_id, filename, display_name, file_format, minio_key, file_size, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (model_id, current_user.id, file.filename, file.filename.rsplit('.', 1)[0], file_extension, file_path, len(file_content), now, now))
        db.commit()

        logger.info(f"3D model uploaded: {model_id} ({file.filename})")

        return Model3DResponse(
            id=model_id,
            filename=file.filename,
            display_name=file.filename.rsplit('.', 1)[0],
            file_format=file_extension,
            file_size=len(file_content),
            download_url=f"/models/{model_id}/file",
            created_at=now.isoformat(),
            updated_at=now.isoformat()
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"3D model upload error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to upload 3D model: {str(e)}")


@router.get("/models", response_model=list[Model3DResponse])
async def list_3d_models(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all 3D models for the current user"""
    try:
        cursor = db.connection().connection.cursor()
        cursor.execute("""
            SELECT id, filename, display_name, file_format, file_size, created_at, updated_at
            FROM models_3d WHERE user_id = %s ORDER BY created_at DESC
        """, (current_user.id,))
        rows = cursor.fetchall()

        return [
            Model3DResponse(
                id=row[0],
                filename=row[1],
                display_name=row[2],
                file_format=row[3],
                file_size=row[4],
                download_url=f"/models/{row[0]}/file",
                created_at=row[5].isoformat() if row[5] else "",
                updated_at=row[6].isoformat() if row[6] else ""
            )
            for row in rows
        ]
    except Exception as e:
        logger.error(f"Error listing 3D models: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list models: {str(e)}")


@router.get("/models/{model_id}", response_model=Model3DResponse)
async def get_3d_model(
    model_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get metadata for a specific 3D model"""
    try:
        cursor = db.connection().connection.cursor()
        cursor.execute("""
            SELECT id, filename, display_name, file_format, file_size, created_at, updated_at
            FROM models_3d WHERE id = %s AND user_id = %s
        """, (model_id, current_user.id))
        row = cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Model not found")

        return Model3DResponse(
            id=row[0],
            filename=row[1],
            display_name=row[2],
            file_format=row[3],
            file_size=row[4],
            download_url=f"/models/{row[0]}/file",
            created_at=row[5].isoformat() if row[5] else "",
            updated_at=row[6].isoformat() if row[6] else ""
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting 3D model: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get model: {str(e)}")


@router.get("/models/{model_id}/file")
async def download_3d_model(
    model_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Download a 3D model file"""
    try:
        cursor = db.connection().connection.cursor()
        cursor.execute("""
            SELECT minio_key, filename, file_format FROM models_3d WHERE id = %s AND user_id = %s
        """, (model_id, current_user.id))
        row = cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Model not found")

        file_path, filename, file_format = row

        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail="Model file not found on disk")

        async with aiofiles.open(file_path, 'rb') as f:
            file_content = await f.read()

        mime_type = MODEL_MIME_TYPES.get(file_format, 'application/octet-stream')

        return Response(
            content=file_content,
            media_type=mime_type,
            headers={
                "Content-Disposition": f"inline; filename=\"{filename}\"",
                "Access-Control-Expose-Headers": "Content-Disposition"
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading 3D model: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to download model: {str(e)}")


@router.delete("/models/{model_id}")
async def delete_3d_model(
    model_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a 3D model"""
    try:
        cursor = db.connection().connection.cursor()
        cursor.execute("""
            SELECT minio_key FROM models_3d WHERE id = %s AND user_id = %s
        """, (model_id, current_user.id))
        row = cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Model not found")

        file_path = row[0]

        # Delete file from disk
        if os.path.exists(file_path):
            os.remove(file_path)

        # Delete database record
        cursor.execute("DELETE FROM models_3d WHERE id = %s", (model_id,))
        db.commit()

        logger.info(f"3D model deleted: {model_id}")
        return {"message": "Model deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting 3D model: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete model: {str(e)}")
