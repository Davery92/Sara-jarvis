"""Document schemas."""
from pydantic import BaseModel


class DocumentResponse(BaseModel):
    id: str
    filename: str
    original_filename: str
    title: str = ""  # User-editable title
    file_size: int
    mime_type: str
    content_text: str = ""
    is_processed: str  # String to match database storage ("true", "false", "error")
    created_at: str
    updated_at: str


class DocumentChunkResponse(BaseModel):
    id: str
    document_id: str
    chunk_text: str
    chunk_index: int
    created_at: str
