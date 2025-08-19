from fastapi import FastAPI, Depends, HTTPException, status, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, String, DateTime, Text, Integer, text
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.sql import func
try:
    from pgvector.sqlalchemy import Vector
    PGVECTOR_AVAILABLE = True
except ImportError:
    PGVECTOR_AVAILABLE = False
    Vector = None
from pydantic import BaseModel, EmailStr
from typing import Optional
from passlib.context import CryptContext
from datetime import datetime, timedelta, timezone
import jwt
import uuid
import httpx
import json
import logging
import os
import aiofiles
from fastapi import UploadFile

# Configure logging first
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Optional imports for vectorization (graceful degradation)
try:
    import chromadb
    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False
    logger.warning("ChromaDB not available - vector search will be disabled")

try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False
    logger.warning("Sentence Transformers not available - embeddings will be disabled")

# Configuration
ASSISTANT_NAME = os.getenv("ASSISTANT_NAME", "Sara")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./sara_hub.db")
JWT_SECRET = os.getenv("JWT_SECRET", "sara-hub-jwt-secret-development")
JWT_ALGORITHM = "HS256"
CORS_ORIGINS = ["https://sara.avery.cloud", "http://localhost:3000", "http://10.185.1.180:3000", "http://sara.avery.cloud"]
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "http://100.104.68.115:11434/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-oss:120b")
EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL", "http://100.104.68.115:11434")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "bge-m3")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1024"))
UPLOAD_DIR = "./uploads"
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
ALLOWED_MIME_TYPES = [
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "text/plain",
    "text/markdown",
    "text/csv"
]

# Database setup
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Models
class User(Base):
    __tablename__ = "app_user"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

class Note(Base):
    __tablename__ = "note"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)
    folder_id = Column(String, nullable=True)  # Foreign key to folder
    title = Column(String, default="")
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now())

class Folder(Base):
    __tablename__ = "folder"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)
    name = Column(String, nullable=False)
    parent_id = Column(String, nullable=True)  # Self-referencing for hierarchy
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now())

class NoteConnection(Base):
    __tablename__ = "note_connection"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)
    source_note_id = Column(String, nullable=False)  # Note that contains the link/reference
    target_note_id = Column(String, nullable=False)  # Note being referenced
    connection_type = Column(String, nullable=False)  # 'reference', 'semantic', 'temporal'
    strength = Column(Integer, default=50)  # 0-100 strength score
    auto_generated = Column(String, default="true")  # true for auto-detected, false for manual
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now())

class Reminder(Base):
    __tablename__ = "reminder"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, default="")
    reminder_time = Column(DateTime, nullable=False)
    is_completed = Column(String, default="false")  # SQLite compatibility
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now())

class Timer(Base):
    __tablename__ = "timer"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)
    title = Column(String, nullable=False)
    duration_minutes = Column(Integer, nullable=False)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    is_active = Column(String, default="true")  # SQLite compatibility
    is_completed = Column(String, default="false")  # SQLite compatibility
    created_at = Column(DateTime, server_default=func.now())

class Document(Base):
    __tablename__ = "document"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)
    filename = Column(String, nullable=False)
    original_filename = Column(String, nullable=False)
    title = Column(String, default="")  # User-editable title
    file_path = Column(String, nullable=False)
    file_size = Column(Integer, nullable=False)
    mime_type = Column(String, nullable=False)
    content_text = Column(Text, default="")  # Extracted text content
    is_processed = Column(String, default="false")  # SQLite compatibility
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now())

class DocumentChunk(Base):
    __tablename__ = "document_chunk"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id = Column(String, nullable=False)
    user_id = Column(String, nullable=False)
    chunk_text = Column(Text, nullable=False)
    chunk_index = Column(Integer, nullable=False)
    # Store embeddings as JSON for SQLite compatibility, Vector for PostgreSQL
    embedding = Column(Vector(EMBEDDING_DIM) if PGVECTOR_AVAILABLE and DATABASE_URL.startswith("postgresql") else Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

class Conversation(Base):
    __tablename__ = "conversation"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)
    title = Column(String, default="")  # Auto-generated conversation title
    summary = Column(Text, default="")  # Auto-generated conversation summary
    total_messages = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now())

class ConversationTurn(Base):
    __tablename__ = "conversation_turn"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id = Column(String, nullable=False)
    user_id = Column(String, nullable=False)
    role = Column(String, nullable=False)  # "user" or "assistant"
    content = Column(Text, nullable=False)
    message_index = Column(Integer, nullable=False)  # Order in conversation
    # Store embeddings as JSON for SQLite compatibility, Vector for PostgreSQL  
    embedding = Column(Vector(EMBEDDING_DIM) if PGVECTOR_AVAILABLE and DATABASE_URL.startswith("postgresql") else Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

# Create tables
Base.metadata.create_all(bind=engine)

# Pydantic models
class UserCreate(BaseModel):
    email: EmailStr
    password: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    id: str
    email: str
    created_at: str

class NoteCreate(BaseModel):
    title: str = ""
    content: str
    folder_id: Optional[str] = None

class NoteResponse(BaseModel):
    id: str
    title: str
    content: str
    folder_id: Optional[str] = None
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
    parent_id: str = None

class FolderUpdate(BaseModel):
    name: str = None
    parent_id: str = None

class FolderResponse(BaseModel):
    id: str
    name: str
    parent_id: str = None
    notes_count: int = 0
    subfolders_count: int = 0
    created_at: str
    updated_at: str

class TreeNodeResponse(BaseModel):
    id: str
    name: str
    type: str  # "folder" or "note"
    parent_id: str = None
    children: list = []
    created_at: str
    updated_at: str

class ReminderCreate(BaseModel):
    title: str
    description: str = ""
    reminder_time: str  # ISO format datetime string

class ReminderResponse(BaseModel):
    id: str
    title: str
    description: str
    reminder_time: str
    is_completed: bool
    created_at: str
    updated_at: str

class TimerCreate(BaseModel):
    title: str
    duration_minutes: int

class TimerResponse(BaseModel):
    id: str
    title: str
    duration_minutes: int
    start_time: str
    end_time: str
    is_active: bool
    is_completed: bool
    created_at: str

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: list[ChatMessage]

class ChatResponse(BaseModel):
    message: ChatMessage

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

class ConversationResponse(BaseModel):
    id: str
    title: str
    summary: str
    total_messages: int
    created_at: str
    updated_at: str

class ConversationTurnResponse(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    message_index: int
    created_at: str

# Auth utilities
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_cookie_domain(request: Request) -> str:
    """Determine the appropriate cookie domain based on the request host."""
    host = request.headers.get("host", "")
    if "sara.avery.cloud" in host:
        return ".sara.avery.cloud"
    else:
        # For local development, don't set a domain (defaults to current host)
        return None

def create_access_token(data: dict):
    expire = datetime.now(timezone.utc) + timedelta(hours=24*7)
    to_encode = data.copy()
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)

def verify_token(token: str):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.PyJWTError:
        return None

# Dependencies
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_current_user(request: Request, db: Session = Depends(get_db)):
    access_token = request.cookies.get("access_token")
    if not access_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    payload = verify_token(access_token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    user_id = payload.get("sub")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    
    return user

# LLM Client
class SimpleLLMClient:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=60.0)
    
    async def chat(self, messages: list):
        try:
            response = await self.client.post(
                f"{OPENAI_BASE_URL}/chat/completions",
                json={
                    "model": OPENAI_MODEL,
                    "messages": [{"role": m.role, "content": m.content} for m in messages],
                    "temperature": 0.7
                },
                headers={"Authorization": "Bearer dummy"}
            )
            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"LLM error: {e}")
            return f"I'm sorry, I'm having trouble connecting to my AI service. Error: {str(e)}"

    async def chat_with_tools(self, messages, tools, user_id):
        """Enhanced chat with tool calling support"""
        try:
            logger.info(f"LLM chat_with_tools called with {len(messages)} messages, {len(tools)} tools for user {user_id}")
            payload = {
                "model": OPENAI_MODEL,
                "messages": [{"role": msg.role, "content": msg.content} for msg in messages],
                "tools": tools,
                "tool_choice": "auto",
                "temperature": 0.7,
                "max_tokens": 2000
            }
            
            response = await self.client.post(
                f"{OPENAI_BASE_URL}/chat/completions",
                json=payload,
                headers={"Authorization": "Bearer dummy"}
            )
            response.raise_for_status()
            
            result = response.json()
            message = result["choices"][0]["message"]
            
            # Handle tool calls with recursive support (max 10 rounds for complex queries)
            max_tool_rounds = 10
            current_messages = [{"role": msg.role, "content": msg.content} for msg in messages]
            
            for round_num in range(max_tool_rounds):
                if message.get("tool_calls"):
                    logger.info(f"🔧 Tool calling round {round_num + 1}")
                    tool_responses = []
                    
                    for tool_call in message["tool_calls"]:
                        tool_response = await self.execute_tool(tool_call, user_id)
                        tool_responses.append(tool_response)
                    
                    # Add assistant message with tool calls and tool responses
                    current_messages.append(message)
                    current_messages.extend(tool_responses)
                    
                    # Truncate messages if conversation is getting too long to prevent 500 errors
                    max_messages = 20  # Keep only recent context to prevent payload bloat
                    if len(current_messages) > max_messages:
                        # Keep system message (first) and recent messages
                        truncated_messages = [current_messages[0]] + current_messages[-max_messages+1:]
                        logger.info(f"⚠️ Truncated conversation from {len(current_messages)} to {len(truncated_messages)} messages")
                        current_messages = truncated_messages
                    
                    # Make follow-up request
                    follow_up_payload = {
                        "model": OPENAI_MODEL,
                        "messages": current_messages,
                        "temperature": 0.7,
                        "max_tokens": 2000,
                        "tools": tools
                    }
                    
                    follow_up_response = await self.client.post(
                        f"{OPENAI_BASE_URL}/chat/completions",
                        json=follow_up_payload,
                        headers={"Authorization": "Bearer dummy"}
                    )
                    follow_up_response.raise_for_status()
                    
                    final_result = follow_up_response.json()
                    message = final_result["choices"][0]["message"]
                    
                    # Enhanced debugging
                    logger.info(f"🔍 Round {round_num + 1} - Message keys: {list(message.keys())}")
                    logger.info(f"🔍 Round {round_num + 1} - Content length: {len(message.get('content', '')) if message.get('content') else 0}")
                    logger.info(f"🔍 Round {round_num + 1} - Content preview: {repr(message.get('content', ''))[:100]}")
                    logger.info(f"🔍 Round {round_num + 1} - Has tool_calls: {bool(message.get('tool_calls'))}")
                    if message.get('tool_calls'):
                        logger.info(f"🔍 Round {round_num + 1} - Tool calls: {[tc.get('function', {}).get('name') for tc in message.get('tool_calls', [])]}")
                    if hasattr(message, 'reasoning'):
                        logger.info(f"🔍 Round {round_num + 1} - Reasoning: {message.get('reasoning', '')[:100]}")
                    
                    # If no more tool calls, we're done
                    if not message.get("tool_calls"):
                        response_content = message["content"]
                        await self.store_conversation(messages, response_content, user_id)
                        logger.info(f"Final LLM response after {round_num + 1} rounds: {len(response_content) if response_content else 0}")
                        return response_content
                else:
                    # No tool calls, return the content
                    response_content = message["content"]
                    await self.store_conversation(messages, response_content, user_id)
                    logger.info(f"Final LLM response (no tools): {len(response_content) if response_content else 0}")
                    return response_content
            
            # If we hit max rounds, force a proper response
            logger.warning(f"Hit max tool rounds with message: {message}")
            
            # Try to get the reasoning or any available content
            response_content = message.get("content", "")
            if not response_content and message.get("reasoning"):
                response_content = message.get("reasoning", "")
            
            # If still no content, force a reasonable response
            if not response_content:
                response_content = "I've searched through your documents and found some relevant information, but I encountered an issue providing a complete response. Please try asking your question again."
            
            await self.store_conversation(messages, response_content, user_id)
            logger.warning(f"Hit max tool rounds, returning: {len(response_content)} chars")
            return response_content
                
        except Exception as e:
            logger.error(f"LLM error: {e}")
            return f"I'm sorry, I'm having trouble connecting to my AI service. Error: {str(e)}"

    async def execute_tool(self, tool_call, user_id):
        """Execute a tool call and return the response"""
        function_name = tool_call["function"]["name"]
        arguments = json.loads(tool_call["function"]["arguments"])
        
        logger.info(f"Executing tool {function_name} with arguments: {arguments}")
        
        if function_name == "search_notes":
            result = await self.search_notes_tool(arguments["query"], user_id)
        elif function_name == "create_note":
            result = await self.create_note_tool(arguments.get("title", ""), arguments["content"], user_id)
        elif function_name == "list_notes":
            result = await self.list_notes_tool(user_id)
        elif function_name == "delete_note":
            result = await self.delete_note_tool(arguments["note_id"], user_id)
        elif function_name == "create_reminder":
            result = await self.create_reminder_tool(arguments["title"], arguments.get("description", ""), arguments["reminder_time"], user_id)
        elif function_name == "list_reminders":
            result = await self.list_reminders_tool(user_id)
        elif function_name == "complete_reminder":
            result = await self.complete_reminder_tool(arguments["reminder_id"], user_id)
        elif function_name == "start_timer":
            result = await self.start_timer_tool(arguments["title"], arguments["duration_minutes"], user_id)
        elif function_name == "list_timers":
            result = await self.list_timers_tool(user_id)
        elif function_name == "stop_timer":
            result = await self.stop_timer_tool(arguments["timer_id"], user_id)
        elif function_name == "search_documents":
            result = await self.search_documents_tool(arguments["query"], user_id)
        elif function_name == "search_memory":
            result = await self.search_memory_tool(arguments["query"], user_id)
        else:
            result = f"Unknown tool: {function_name}"
        
        logger.info(f"Tool {function_name} result length: {len(str(result))} chars")
        if function_name == "search_documents":
            logger.info(f"Search result preview: {str(result)[:500]}...")
        return {
            "role": "tool",
            "tool_call_id": tool_call["id"],
            "content": str(result)
        }

    async def search_notes_tool(self, query, user_id):
        """Search notes using Neo4j knowledge graph (with PostgreSQL fallback)"""
        try:
            # Try Neo4j search first
            from app.services.neo4j_service import neo4j_service
            if neo4j_service.driver:
                search_results = await neo4j_service.search_knowledge_graph(
                    user_id=user_id,
                    query=query,
                    content_types=["Note"],
                    limit=10
                )
                
                if search_results:
                    results = []
                    for node in search_results:
                        title = node.get('title', 'Untitled')
                        content = node.get('content', '')[:200]
                        results.append(f"Note: {title}\nContent: {content}...")
                    return "\n\n".join(results)
            
            # Fallback to PostgreSQL
            db = SessionLocal()
            try:
                notes = db.query(Note).filter(
                    Note.user_id == user_id,
                    Note.content.ilike(f"%{query}%")
                ).limit(5).all()
                
                if not notes:
                    return "No notes found matching your query."
                
                results = []
                for note in notes:
                    results.append(f"Note: {note.title or 'Untitled'}\nContent: {note.content[:200]}...")
                
                return "\n\n".join(results)
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error searching notes: {e}")
            return f"Error searching notes: {str(e)}"

    async def create_note_tool(self, title, content, user_id):
        """Create a new note using Neo4j-first architecture with intelligent processing"""
        note_id = str(__import__('uuid').uuid4())
        
        try:
            # Neo4j-first approach: Create note in Neo4j immediately
            from app.services.neo4j_service import neo4j_service
            from app.services.intelligence_pipeline import intelligence_pipeline, ContentType
            
            # Ensure Neo4j connection
            if neo4j_service.driver:
                try:
                    # Create note in Neo4j graph
                    await neo4j_service.create_note(
                        note_id=note_id,
                        user_id=user_id,
                        title=title or "Untitled",
                        content=content
                    )
                    
                    # Queue for intelligent processing
                    await intelligence_pipeline.queue_fast_processing(
                        content_id=note_id,
                        content_type=ContentType.NOTE,
                        metadata={
                            "user_id": user_id,
                            "title": title
                        }
                    )
                    
                    logger.info(f"✅ Tool: Note {note_id} created in Neo4j and queued for processing")
                except Exception as neo_error:
                    logger.warning(f"Neo4j note creation failed in tool: {neo_error}")
            
            # Background sync to PostgreSQL (backup)
            db = SessionLocal()
            try:
                note = Note(
                    id=note_id,
                    user_id=user_id,
                    title=title or "",
                    content=content
                )
                db.add(note)
                db.commit()
                db.refresh(note)
                
                return f"Created note: {note.title or 'Untitled'} (with intelligent graph processing)"
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error creating note: {e}")
            return f"Error creating note: {str(e)}"

    async def list_notes_tool(self, user_id):
        """List all notes for the user"""
        try:
            # First try Neo4j
            from app.services.neo4j_service import neo4j_service
            if neo4j_service.driver:
                try:
                    notes = await neo4j_service.get_user_notes(user_id)
                    if notes:
                        formatted_notes = []
                        for note in notes:
                            title = note.get('title', 'Untitled')
                            note_id = note.get('id', '')
                            content_preview = note.get('content', '')[:100] + "..." if len(note.get('content', '')) > 100 else note.get('content', '')
                            formatted_notes.append(f"• {title} (ID: {note_id})\n  {content_preview}")
                        return f"Your notes:\n\n" + "\n\n".join(formatted_notes)
                except Exception as neo_error:
                    logger.warning(f"Neo4j list notes failed: {neo_error}")
            
            # Fallback to PostgreSQL
            db = SessionLocal()
            try:
                notes = db.query(Note).filter(Note.user_id == user_id).order_by(Note.created_at.desc()).all()
                if not notes:
                    return "You don't have any notes yet."
                
                formatted_notes = []
                for note in notes:
                    title = note.title or "Untitled"
                    content_preview = note.content[:100] + "..." if len(note.content) > 100 else note.content
                    formatted_notes.append(f"• {title} (ID: {note.id})\n  {content_preview}")
                
                return f"Your notes:\n\n" + "\n\n".join(formatted_notes)
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error listing notes: {e}")
            return f"Error listing notes: {str(e)}"

    async def delete_note_tool(self, note_id, user_id):
        """Delete a specific note by ID"""
        try:
            # Delete from Neo4j first
            from app.services.neo4j_service import neo4j_service
            if neo4j_service.driver:
                try:
                    await neo4j_service.delete_note(note_id, user_id)
                    logger.info(f"✅ Tool: Note {note_id} deleted from Neo4j")
                except Exception as neo_error:
                    logger.warning(f"Neo4j note deletion failed: {neo_error}")
            
            # Delete from PostgreSQL
            db = SessionLocal()
            try:
                note = db.query(Note).filter(Note.id == note_id, Note.user_id == user_id).first()
                if not note:
                    return f"Note with ID {note_id} not found."
                
                note_title = note.title or "Untitled"
                db.delete(note)
                db.commit()
                
                return f"Deleted note: {note_title}"
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error deleting note: {e}")
            return f"Error deleting note: {str(e)}"

    async def create_reminder_tool(self, title, description, reminder_time, user_id):
        """Create a new reminder for the user"""
        try:
            db = SessionLocal()
            try:
                # Parse reminder time
                reminder_dt = datetime.fromisoformat(reminder_time.replace('Z', '+00:00'))
                
                reminder = Reminder(
                    user_id=user_id,
                    title=title,
                    description=description,
                    reminder_time=reminder_dt
                )
                db.add(reminder)
                db.commit()
                db.refresh(reminder)
                
                return f"Created reminder: {reminder.title} for {reminder_dt.strftime('%Y-%m-%d %H:%M')}"
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error creating reminder: {e}")
            return f"Error creating reminder: {str(e)}"

    async def list_reminders_tool(self, user_id):
        """List active reminders for the user"""
        try:
            db = SessionLocal()
            try:
                reminders = db.query(Reminder).filter(
                    Reminder.user_id == user_id,
                    Reminder.is_completed == "false"
                ).order_by(Reminder.reminder_time).limit(10).all()
                
                if not reminders:
                    return "No active reminders found."
                
                results = []
                for reminder in reminders:
                    time_str = reminder.reminder_time.strftime('%Y-%m-%d %H:%M')
                    results.append(f"• {reminder.title} ({time_str})")
                    if reminder.description:
                        results.append(f"  {reminder.description}")
                
                return "\n".join(results)
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error listing reminders: {e}")
            return f"Error listing reminders: {str(e)}"

    async def complete_reminder_tool(self, reminder_id, user_id):
        """Mark a reminder as completed"""
        try:
            db = SessionLocal()
            try:
                reminder = db.query(Reminder).filter(
                    Reminder.id == reminder_id,
                    Reminder.user_id == user_id
                ).first()
                
                if not reminder:
                    return "Reminder not found."
                
                reminder.is_completed = "true"
                reminder.updated_at = datetime.now()
                db.commit()
                
                return f"Marked reminder '{reminder.title}' as completed"
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error completing reminder: {e}")
            return f"Error completing reminder: {str(e)}"

    async def start_timer_tool(self, title, duration_minutes, user_id):
        """Start a new timer"""
        try:
            # Validate duration
            if not isinstance(duration_minutes, int) or duration_minutes < 1 or duration_minutes > 480:
                return f"Invalid duration: {duration_minutes}. Please specify between 1 and 480 minutes (8 hours max)."
            
            db = SessionLocal()
            try:
                start_time = datetime.now(timezone.utc)
                end_time = start_time + timedelta(minutes=duration_minutes)
                
                logger.info(f"Timer timestamps - Start: {start_time.isoformat()}, End: {end_time.isoformat()}, Duration: {duration_minutes}m")
                
                timer = Timer(
                    user_id=user_id,
                    title=title,
                    duration_minutes=duration_minutes,
                    start_time=start_time,
                    end_time=end_time
                )
                db.add(timer)
                db.commit()
                db.refresh(timer)
                
                logger.info(f"Created timer: {title} for {duration_minutes} minutes for user {user_id}")
                return f"Started timer '{timer.title}' for {duration_minutes} minutes (ends at {end_time.strftime('%H:%M')})"
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error starting timer: {e}")
            return f"Error starting timer: {str(e)}"

    async def list_timers_tool(self, user_id):
        """List active timers for the user"""
        try:
            db = SessionLocal()
            try:
                now = datetime.now(timezone.utc)
                timers = db.query(Timer).filter(
                    Timer.user_id == user_id,
                    Timer.is_active == "true"
                ).order_by(Timer.created_at.desc()).limit(10).all()
                
                if not timers:
                    return "No active timers found."
                
                results = []
                for timer in timers:
                    # Ensure both datetimes are timezone-aware
                    end_time = timer.end_time
                    if end_time.tzinfo is None:
                        end_time = end_time.replace(tzinfo=timezone.utc)
                    
                    time_left = end_time - now
                    if time_left.total_seconds() > 0:
                        minutes_left = int(time_left.total_seconds() / 60)
                        status = f"{minutes_left}m left"
                    else:
                        status = "FINISHED"
                    
                    results.append(f"• {timer.title} ({timer.duration_minutes}m) - {status} (ID: {timer.id})")
                
                return "\n".join(results)
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error listing timers: {e}")
            return f"Error listing timers: {str(e)}"

    async def stop_timer_tool(self, timer_id, user_id):
        """Stop/cancel an active timer"""
        try:
            db = SessionLocal()
            try:
                timer = db.query(Timer).filter(
                    Timer.id == timer_id,
                    Timer.user_id == user_id,
                    Timer.is_active == "true"
                ).first()
                
                if not timer:
                    return "Active timer not found."
                
                timer.is_active = "false"
                timer.is_completed = "true"
                db.commit()
                
                return f"Stopped timer '{timer.title}'"
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error stopping timer: {e}")
            return f"Error stopping timer: {str(e)}"

    async def search_documents_tool(self, query, user_id):
        """🧠 Advanced hybrid search through uploaded documents using Neo4j knowledge graph + PostgreSQL fallback"""
        try:
            # Try Neo4j search first for enhanced document discovery
            from app.services.neo4j_service import neo4j_service
            if neo4j_service.driver:
                try:
                    search_results = await neo4j_service.search_knowledge_graph(
                        user_id=user_id,
                        query=query,
                        content_types=["Document"],
                        limit=5
                    )
                    
                    if search_results:
                        results = []
                        for node in search_results:
                            title = node.get('title', 'Unknown Document')
                            content = node.get('content_text', '')[:300]
                            results.append(f"From {title}: {content}...")
                        
                        # If Neo4j found results, return them
                        if results:
                            return f"Found {len(results)} relevant results about '{query}' in your documents.\n\n" + "\n\n".join(results)
                except Exception as e:
                    logger.warning(f"Neo4j document search failed: {e}")
            
            # Fallback to PostgreSQL vector search
            db = SessionLocal()
            try:
                # Check if user has documents
                documents = db.query(Document).filter(
                    Document.user_id == user_id,
                    Document.is_processed == "true"
                ).all()
                
                if not documents:
                    return "No documents found. Upload some documents first."
                
                # Generate query embedding for semantic search
                logger.info(f"🔍 Generating embedding for query: '{query}'")
                query_embedding = await embedding_service.generate_embedding(query)
                
                semantic_results = []
                text_results = []
                
                # 1. SEMANTIC VECTOR SEARCH (Primary method)
                if query_embedding:
                    logger.info("🧠 Performing semantic vector search...")
                    try:
                        if DATABASE_URL.startswith("postgresql") and PGVECTOR_AVAILABLE:
                            # Use pgvector for similarity search
                            from sqlalchemy import text
                            similarity_query = text("""
                                SELECT dc.chunk_text, d.original_filename,
                                       (dc.embedding <=> :query_embedding) as distance
                                FROM document_chunk dc
                                JOIN document d ON dc.document_id = d.id
                                WHERE dc.user_id = :user_id 
                                  AND dc.embedding IS NOT NULL
                                  AND d.is_processed = 'true'
                                ORDER BY dc.embedding <=> :query_embedding
                                LIMIT 8
                            """)
                            
                            result = db.execute(similarity_query, {
                                'query_embedding': str(query_embedding),
                                'user_id': user_id
                            })
                            
                            for row in result:
                                similarity = 1 - row.distance  # Convert distance to similarity
                                if similarity > 0.3:  # Only include reasonably similar results
                                    semantic_results.append({
                                        'chunk_text': row.chunk_text,
                                        'filename': row.original_filename,
                                        'similarity': similarity,
                                        'type': 'SEMANTIC'
                                    })
                        else:
                            # SQLite: Manual similarity calculation using JSON embeddings
                            import json
                            import numpy as np
                            
                            chunks = db.query(DocumentChunk, Document).join(
                                Document, DocumentChunk.document_id == Document.id
                            ).filter(
                                DocumentChunk.user_id == user_id,
                                DocumentChunk.embedding.isnot(None),
                                Document.is_processed == "true"
                            ).limit(50).all()  # Get more for manual filtering
                            
                            for chunk, doc in chunks:
                                try:
                                    stored_embedding = json.loads(chunk.embedding)
                                    # Calculate cosine similarity
                                    similarity = np.dot(query_embedding, stored_embedding) / (
                                        np.linalg.norm(query_embedding) * np.linalg.norm(stored_embedding)
                                    )
                                    
                                    if similarity > 0.3:  # Only include reasonably similar results
                                        semantic_results.append({
                                            'chunk_text': chunk.chunk_text,
                                            'filename': doc.original_filename,
                                            'similarity': float(similarity),
                                            'type': 'SEMANTIC'
                                        })
                                except Exception as e:
                                    logger.warning(f"Error processing embedding for chunk {chunk.id}: {e}")
                                    continue
                            
                            # Sort by similarity
                            semantic_results.sort(key=lambda x: x['similarity'], reverse=True)
                            semantic_results = semantic_results[:8]  # Top 8 results
                            
                        logger.info(f"🎯 Found {len(semantic_results)} semantic matches")
                            
                    except Exception as e:
                        logger.warning(f"Vector search failed, using text search: {e}")
                
                # 2. ENHANCED TEXT SEARCH (Fallback + Supplementary)
                logger.info("📝 Performing enhanced text search...")
                query_terms = query.lower().split()
                
                for doc in documents:
                    # Search in document content
                    if doc.content_text:
                        content_lower = doc.content_text.lower()
                        
                        # Exact phrase match
                        if query.lower() in content_lower:
                            start_idx = content_lower.find(query.lower())
                            context_start = max(0, start_idx - 150)
                            context_end = min(len(doc.content_text), start_idx + len(query) + 150)
                            excerpt = doc.content_text[context_start:context_end].strip()
                            if context_start > 0:
                                excerpt = "..." + excerpt
                            if context_end < len(doc.content_text):
                                excerpt = excerpt + "..."
                            
                            text_results.append({
                                'chunk_text': excerpt,
                                'filename': doc.original_filename,
                                'similarity': 0.95,  # High score for exact matches
                                'type': 'EXACT'
                            })
                    
                    # Search in chunks
                    chunks = db.query(DocumentChunk).filter(
                        DocumentChunk.document_id == doc.id,
                        DocumentChunk.chunk_text.ilike(f"%{query}%")
                    ).limit(3).all()
                    
                    for chunk in chunks:
                        text_results.append({
                            'chunk_text': chunk.chunk_text,
                            'filename': doc.original_filename,
                            'similarity': 0.8,  # Good score for text matches
                            'type': 'TEXT'
                        })
                
                # 3. COMBINE AND RANK RESULTS
                all_results = semantic_results + text_results
                
                # Remove duplicates and sort by similarity
                seen_content = set()
                unique_results = []
                for result in all_results:
                    content_key = (result['filename'], result['chunk_text'][:100])
                    if content_key not in seen_content:
                        seen_content.add(content_key)
                        unique_results.append(result)
                
                # Sort by similarity score
                unique_results.sort(key=lambda x: x['similarity'], reverse=True)
                
                if not unique_results:
                    return f"❌ No results found for '{query}' in your documents. Try different search terms or upload more documents."
                
                # 4. FORMAT SIMPLE RESPONSE
                total_results = len(unique_results)
                
                response_parts = [f"Found {total_results} relevant results about '{query}' in your documents."]
                response_parts.append("")
                
                # Show top results from different documents
                seen_docs = set()
                for result in unique_results[:3]:  # Top 3 results
                    filename = result['filename']
                    if filename not in seen_docs:
                        seen_docs.add(filename)
                        
                        # Clean and present content
                        content = result['chunk_text'].strip()
                        if len(content) > 200:
                            content = content[:200] + "..."
                        
                        response_parts.append(f"From {filename}: {content}")
                        response_parts.append("")
                
                return "\n".join(response_parts)
                
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error in advanced document search: {e}")
            return f"⚠️ Search temporarily unavailable. Error: {str(e)}"

    async def search_memory_tool(self, query, user_id):
        """🧠 Search through Sara's conversation memory for past interactions and context"""
        try:
            db = SessionLocal()
            try:
                # Check if user has conversation history
                conversations = db.query(Conversation).filter(
                    Conversation.user_id == user_id
                ).count()
                
                if conversations == 0:
                    return "🆕 This is our first conversation! I don't have any memories to search yet, but I'll remember everything we discuss."
                
                # Generate query embedding for semantic search
                logger.info(f"🔍 Searching Sara's memory for: '{query}'")
                query_embedding = await embedding_service.generate_embedding(query)
                
                semantic_results = []
                text_results = []
                
                # 1. SEMANTIC VECTOR SEARCH through conversation turns
                if query_embedding:
                    logger.info("🧠 Performing semantic memory search...")
                    try:
                        if DATABASE_URL.startswith("postgresql") and PGVECTOR_AVAILABLE:
                            from sqlalchemy import text
                            memory_query = text("""
                                SELECT ct.content, ct.role, c.title, ct.created_at,
                                       (ct.embedding <=> :query_embedding) as distance
                                FROM conversation_turn ct
                                JOIN conversation c ON ct.conversation_id = c.id
                                WHERE ct.user_id = :user_id 
                                  AND ct.embedding IS NOT NULL
                                ORDER BY ct.embedding <=> :query_embedding
                                LIMIT 10
                            """)
                            
                            result = db.execute(memory_query, {
                                'query_embedding': str(query_embedding),
                                'user_id': user_id
                            })
                            
                            for row in result:
                                similarity = 1 - row.distance
                                if similarity > 0.3:  # Only include reasonably similar results
                                    semantic_results.append({
                                        'content': row.content,
                                        'role': row.role,
                                        'title': row.title or "Conversation",
                                        'created_at': row.created_at,
                                        'similarity': similarity,
                                        'type': 'SEMANTIC'
                                    })
                        else:
                            # SQLite: Manual similarity calculation using JSON embeddings
                            import json
                            import numpy as np
                            
                            turns = db.query(ConversationTurn, Conversation).join(
                                Conversation, ConversationTurn.conversation_id == Conversation.id
                            ).filter(
                                ConversationTurn.user_id == user_id,
                                ConversationTurn.embedding.isnot(None)
                            ).limit(50).all()  # Get more for manual filtering
                            
                            for turn, conv in turns:
                                try:
                                    stored_embedding = json.loads(turn.embedding)
                                    # Calculate cosine similarity
                                    similarity = np.dot(query_embedding, stored_embedding) / (
                                        np.linalg.norm(query_embedding) * np.linalg.norm(stored_embedding)
                                    )
                                    
                                    if similarity > 0.3:  # Only include reasonably similar results
                                        semantic_results.append({
                                            'content': turn.content,
                                            'role': turn.role,
                                            'title': conv.title or "Conversation",
                                            'created_at': turn.created_at,
                                            'similarity': float(similarity),
                                            'type': 'SEMANTIC'
                                        })
                                except Exception as e:
                                    logger.warning(f"Error processing memory embedding for turn {turn.id}: {e}")
                                    continue
                            
                            # Sort by similarity
                            semantic_results.sort(key=lambda x: x['similarity'], reverse=True)
                            semantic_results = semantic_results[:10]  # Top 10 results
                            
                        logger.info(f"🎯 Found {len(semantic_results)} semantic memory matches")
                            
                    except Exception as e:
                        logger.warning(f"Vector memory search failed, using text search: {e}")
                
                # 2. TEXT SEARCH through conversations (fallback + supplementary)
                logger.info("📝 Performing text-based memory search...")
                
                # Search conversation turns
                turns = db.query(ConversationTurn, Conversation).join(
                    Conversation, ConversationTurn.conversation_id == Conversation.id
                ).filter(
                    ConversationTurn.user_id == user_id,
                    ConversationTurn.content.ilike(f"%{query}%")
                ).order_by(ConversationTurn.created_at.desc()).limit(8).all()
                
                for turn, conversation in turns:
                    text_results.append({
                        'content': turn.content,
                        'role': turn.role,
                        'title': conversation.title or "Conversation",
                        'created_at': turn.created_at,
                        'similarity': 0.8,  # Good score for text matches
                        'type': 'TEXT'
                    })
                
                # 3. COMBINE AND RANK RESULTS
                all_results = semantic_results + text_results
                
                # Remove duplicates and sort by similarity
                seen_content = set()
                unique_results = []
                for result in all_results:
                    content_key = (result['content'][:100], result['role'])
                    if content_key not in seen_content:
                        seen_content.add(content_key)
                        unique_results.append(result)
                
                # Sort by similarity score and recency
                unique_results.sort(key=lambda x: (x['similarity'], x['created_at']), reverse=True)
                
                if not unique_results:
                    return f"🤔 I searched my memory but couldn't find anything specifically about '{query}'. What would you like to know?"
                
                # 4. FORMAT INTELLIGENT MEMORY RESPONSE
                total_results = len(unique_results)
                semantic_count = len([r for r in unique_results if r['type'] == 'SEMANTIC'])
                
                response_parts = [f"🧠 **Sara's Memory Search: {total_results} memories found for '{query}'**"]
                if semantic_count > 0:
                    response_parts.append(f"✨ {semantic_count} semantic memories using AI understanding")
                response_parts.append("")
                
                # Show top results
                for i, result in enumerate(unique_results[:6]):  # Top 6 memory results
                    role_emoji = "👤" if result['role'] == "user" else "🤖"
                    search_type = result['type']
                    similarity = result['similarity']
                    
                    # Format timestamp
                    try:
                        time_str = result['created_at'].strftime('%Y-%m-%d %H:%M')
                    except:
                        time_str = "Recent"
                    
                    # Format based on search type
                    if search_type == 'SEMANTIC':
                        response_parts.append(f"🧠 *AI Memory Match* (Confidence: {similarity:.1%}) - {time_str}")
                    else:
                        response_parts.append(f"📝 *Text Memory Match* (Confidence: {similarity:.1%}) - {time_str}")
                    
                    # Clean and present content
                    content = result['content'].strip()
                    if len(content) > 200:
                        content = content[:200] + "..."
                    
                    response_parts.append(f"{role_emoji} {content}")
                    response_parts.append("")
                
                # Add contextual note
                response_parts.append(f"💭 *I remember {conversations} total conversations we've had together.*")
                
                return "\n".join(response_parts)
                
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error in memory search: {e}")
            return f"🤔 My memory search is temporarily unavailable. Error: {str(e)}"

    async def store_conversation(self, messages, response_content, user_id):
        """Store the conversation in episodic memory"""
        try:
            db = SessionLocal()
            try:
                # Find or create conversation for this session
                # For now, create a new conversation for each chat interaction
                # In a real app, you'd want to group related messages into conversations
                
                conversation = Conversation(
                    user_id=user_id,
                    title="",  # Will be generated later
                    total_messages=len(messages) + 1  # +1 for assistant response
                )
                db.add(conversation)
                db.commit()
                db.refresh(conversation)
                
                # Store all user messages from this chat
                turn_index = 0
                for message in messages:
                    if message.role in ["user", "assistant"]:  # Skip system messages
                        # Generate embedding for the message
                        embedding = await embedding_service.generate_embedding(message.content)
                        
                        # Format embedding based on database type
                        if DATABASE_URL.startswith("postgresql") and PGVECTOR_AVAILABLE:
                            embedding_data = embedding  # pgvector format
                        else:
                            # SQLite: store as JSON string
                            import json
                            embedding_data = json.dumps(embedding) if embedding else None
                        
                        turn = ConversationTurn(
                            conversation_id=conversation.id,
                            user_id=user_id,
                            role=message.role,
                            content=message.content,
                            message_index=turn_index,
                            embedding=embedding_data
                        )
                        db.add(turn)
                        turn_index += 1
                
                # Store assistant response
                if response_content:
                    response_embedding = await embedding_service.generate_embedding(response_content)
                    
                    # Format embedding based on database type
                    if DATABASE_URL.startswith("postgresql") and PGVECTOR_AVAILABLE:
                        embedding_data = response_embedding  # pgvector format
                    else:
                        # SQLite: store as JSON string
                        import json
                        embedding_data = json.dumps(response_embedding) if response_embedding else None
                    
                    turn = ConversationTurn(
                        conversation_id=conversation.id,
                        user_id=user_id,
                        role="assistant",
                        content=response_content,
                        message_index=turn_index,
                        embedding=embedding_data
                    )
                    db.add(turn)
                
                db.commit()
                
                # Generate a title for the conversation (async, don't wait)
                await self.generate_conversation_title(conversation.id, db)
                
                logger.info(f"Stored conversation {conversation.id} with {turn_index + 1} turns in episodic memory")
                
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error storing conversation in memory: {e}")

    async def generate_conversation_title(self, conversation_id, db):
        """Generate a descriptive title for the conversation"""
        try:
            # Get the first few user messages to generate a title
            turns = db.query(ConversationTurn).filter(
                ConversationTurn.conversation_id == conversation_id,
                ConversationTurn.role == "user"
            ).order_by(ConversationTurn.message_index).limit(3).all()
            
            if not turns:
                return
            
            # Create a summary of the user's initial messages
            user_messages = [turn.content for turn in turns]
            combined_content = " | ".join(user_messages)
            
            # Generate a short title (keep it simple for now)
            if len(combined_content) > 100:
                title = combined_content[:97] + "..."
            else:
                title = combined_content
            
            # Update the conversation with the title
            conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
            if conversation:
                conversation.title = title
                conversation.updated_at = datetime.now()
                db.commit()
                
        except Exception as e:
            logger.error(f"Error generating conversation title: {e}")

class EmbeddingService:
    def __init__(self):
        self.client = httpx.AsyncClient()
        self.base_url = EMBEDDING_BASE_URL
        self.model = EMBEDDING_MODEL
        self.dimension = EMBEDDING_DIM
    
    async def generate_embedding(self, text: str) -> list[float]:
        """Generate embedding for text using BGE-M3 model"""
        try:
            # Use the embeddings endpoint
            response = await self.client.post(
                f"{self.base_url}/v1/embeddings",
                json={
                    "model": self.model,
                    "input": text,
                    "encoding_format": "float"
                },
                headers={"Authorization": "Bearer dummy"},
                timeout=30.0
            )
            response.raise_for_status()
            
            result = response.json()
            embedding = result["data"][0]["embedding"]
            
            # Ensure the embedding has the correct dimension
            if len(embedding) != self.dimension:
                logger.warning(f"Expected embedding dimension {self.dimension}, got {len(embedding)}")
                # Pad or truncate to match expected dimension
                if len(embedding) < self.dimension:
                    embedding.extend([0.0] * (self.dimension - len(embedding)))
                else:
                    embedding = embedding[:self.dimension]
            
            return embedding
            
        except Exception as e:
            logger.error(f"Error generating embedding: {e}")
            return None
    
    async def generate_embeddings_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts"""
        try:
            # For now, process individually to avoid API limits
            embeddings = []
            for text in texts:
                embedding = await self.generate_embedding(text)
                if embedding:
                    embeddings.append(embedding)
                else:
                    # Return zero vector for failed embeddings
                    embeddings.append([0.0] * self.dimension)
            return embeddings
            
        except Exception as e:
            logger.error(f"Error generating batch embeddings: {e}")
            return [[0.0] * self.dimension] * len(texts)

llm_client = SimpleLLMClient()
embedding_service = EmbeddingService()

# Document Processing Service
class DocumentProcessor:
    def __init__(self):
        self.supported_types = {
            "application/pdf": self._extract_pdf_text,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": self._extract_docx_text,
            "application/msword": self._extract_doc_text,
            "text/plain": self._extract_text_file,
            "text/markdown": self._extract_text_file,
            "text/csv": self._extract_text_file,
        }
        
        # Initialize embedding model
        if SENTENCE_TRANSFORMERS_AVAILABLE:
            try:
                self.embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
                logger.info("Initialized embedding model: all-MiniLM-L6-v2")
            except Exception as e:
                logger.error(f"Failed to initialize embedding model: {e}")
                self.embedding_model = None
        else:
            self.embedding_model = None
        
        # Initialize ChromaDB
        if CHROMADB_AVAILABLE:
            try:
                # Create chroma_data directory if it doesn't exist
                os.makedirs("chroma_data", exist_ok=True)
                self.chroma_client = chromadb.PersistentClient(path="chroma_data")
                logger.info("Initialized ChromaDB client")
            except Exception as e:
                logger.error(f"Failed to initialize ChromaDB: {e}")
                self.chroma_client = None
        else:
            self.chroma_client = None
    
    def _extract_pdf_text(self, file_path: str) -> str:
        """Extract text from PDF file with robust error handling"""
        try:
            import PyPDF2
            text = ""
            
            with open(file_path, 'rb') as file:
                reader = PyPDF2.PdfReader(file)
                
                # Process all pages (or reasonable limit for very large documents)
                max_pages = min(len(reader.pages), 500)  # Up to 500 pages
                
                for i in range(max_pages):
                    try:
                        page = reader.pages[i]
                        page_text = page.extract_text()
                        if page_text:
                            text += page_text + "\n"
                        
                        # Break if we have extremely large text to prevent memory issues
                        if len(text) > 5000000:  # Limit to ~5MB of text
                            logger.info(f"PDF text extraction stopped at {len(text)} characters (5MB limit reached)")
                            break
                            
                    except Exception as page_error:
                        logger.warning(f"Error extracting page {i}: {page_error}")
                        continue
                
                if text.strip():
                    logger.info(f"Successfully extracted {len(text)} characters from PDF")
                    return text.strip()
                else:
                    logger.warning("No text extracted from PDF - might be image-based or encrypted")
                    return ""
                    
        except ImportError:
            logger.error("PyPDF2 not available for PDF text extraction")
            return ""
        except Exception as e:
            logger.error(f"Error extracting PDF text: {e}")
            return ""
    
    def _extract_docx_text(self, file_path: str) -> str:
        """Extract text from DOCX file"""
        try:
            from docx import Document
            doc = Document(file_path)
            text = ""
            for paragraph in doc.paragraphs:
                text += paragraph.text + "\n"
            return text.strip()
        except Exception as e:
            logger.error(f"Error extracting DOCX text: {e}")
            return ""
    
    def _extract_doc_text(self, file_path: str) -> str:
        """Extract text from DOC file (legacy Word format)"""
        # For now, return empty - would need additional libraries like python-docx2txt
        logger.warning("DOC file format not fully supported yet")
        return ""
    
    def _extract_text_file(self, file_path: str) -> str:
        """Extract text from plain text files"""
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                return file.read()
        except UnicodeDecodeError:
            try:
                with open(file_path, 'r', encoding='latin-1') as file:
                    return file.read()
            except Exception as e:
                logger.error(f"Error reading text file: {e}")
                return ""
        except Exception as e:
            logger.error(f"Error reading text file: {e}")
            return ""
    
    def extract_text(self, file_path: str, mime_type: str) -> str:
        """Extract text from a file based on its MIME type"""
        if mime_type not in self.supported_types:
            logger.warning(f"Unsupported MIME type: {mime_type}")
            return ""
        
        try:
            return self.supported_types[mime_type](file_path)
        except Exception as e:
            logger.error(f"Error extracting text from {file_path}: {e}")
            return ""
    
    def chunk_text(self, text: str, chunk_size: int = 1500, overlap: int = 300) -> list[str]:
        """Split text into overlapping chunks for better context preservation"""
        if len(text) <= chunk_size:
            return [text]
        
        chunks = []
        start = 0
        
        while start < len(text):
            end = start + chunk_size
            
            # Try to break at sentence boundary
            if end < len(text):
                # Look for sentence endings
                sentence_end = max(
                    text.rfind('.', start, end),
                    text.rfind('!', start, end),
                    text.rfind('?', start, end)
                )
                if sentence_end > start:
                    end = sentence_end + 1
                else:
                    # Fallback to word boundary
                    word_end = text.rfind(' ', start, end)
                    if word_end > start:
                        end = word_end
            
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            
            start = end - overlap if end < len(text) else end
        
        return chunks
    
    def get_or_create_collection(self, user_id: str):
        """Get or create a ChromaDB collection for a user"""
        if not self.chroma_client:
            return None
        
        collection_name = f"user_{user_id}_documents"
        try:
            return self.chroma_client.get_or_create_collection(name=collection_name)
        except Exception as e:
            logger.error(f"Failed to get/create collection for user {user_id}: {e}")
            return None
    
    def vectorize_chunks(self, chunks: list[str], document_id: str, user_id: str) -> bool:
        """Vectorize document chunks and store in ChromaDB"""
        if not self.embedding_model or not self.chroma_client:
            logger.warning("Embedding model or ChromaDB not available for vectorization")
            return False
        
        collection = self.get_or_create_collection(user_id)
        if not collection:
            return False
        
        try:
            # Generate embeddings for all chunks
            embeddings = self.embedding_model.encode(chunks)
            
            # Prepare metadata and IDs
            ids = [f"{document_id}_chunk_{i}" for i in range(len(chunks))]
            metadatas = [
                {
                    "document_id": document_id,
                    "chunk_index": i,
                    "user_id": user_id
                }
                for i in range(len(chunks))
            ]
            
            # Add to ChromaDB
            collection.add(
                embeddings=embeddings.tolist(),
                documents=chunks,
                metadatas=metadatas,
                ids=ids
            )
            
            logger.info(f"Successfully vectorized {len(chunks)} chunks for document {document_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error vectorizing chunks: {e}")
            return False
    
    def search_documents(self, query: str, user_id: str, n_results: int = 5) -> list[dict]:
        """Search for relevant document chunks using vector similarity"""
        if not self.embedding_model or not self.chroma_client:
            logger.warning("Embedding model or ChromaDB not available for search")
            return []
        
        collection = self.get_or_create_collection(user_id)
        if not collection:
            return []
        
        try:
            # Generate embedding for query
            query_embedding = self.embedding_model.encode([query])
            
            # Search in ChromaDB
            results = collection.query(
                query_embeddings=query_embedding.tolist(),
                n_results=n_results,
                include=['documents', 'metadatas', 'distances']
            )
            
            # Format results
            search_results = []
            if results['documents'] and results['documents'][0]:
                for i, doc in enumerate(results['documents'][0]):
                    search_results.append({
                        'content': doc,
                        'metadata': results['metadatas'][0][i],
                        'similarity': 1 - results['distances'][0][i]  # Convert distance to similarity
                    })
            
            return search_results
            
        except Exception as e:
            logger.error(f"Error searching documents: {e}")
            return []
    
    def delete_document_vectors(self, document_id: str, user_id: str) -> bool:
        """Delete all vectors for a specific document"""
        if not self.chroma_client:
            return False
        
        collection = self.get_or_create_collection(user_id)
        if not collection:
            return False
        
        try:
            # Find all chunk IDs for this document
            results = collection.get(where={"document_id": document_id})
            if results['ids']:
                collection.delete(ids=results['ids'])
                logger.info(f"Deleted {len(results['ids'])} vectors for document {document_id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting document vectors: {e}")
            return False

document_processor = DocumentProcessor()

# FastAPI app
app = FastAPI(
    title=f"{ASSISTANT_NAME} Personal Hub API",
    description=f"Personal AI assistant for sara.avery.cloud",
    version="1.0.0-simple"
)

# Initialize Neo4j on startup
@app.on_event("startup")
async def startup_event():
    """Initialize services on application startup"""
    try:
        # Initialize Neo4j service
        from app.services.neo4j_service import neo4j_service
        await neo4j_service.connect()
        logger.info("✅ Neo4j knowledge graph service initialized")
        
        # Initialize intelligence pipeline
        from app.services.intelligence_pipeline import intelligence_pipeline
        await intelligence_pipeline.start_workers()
        logger.info("🧠 Intelligence pipeline workers started")
        
    except Exception as e:
        logger.warning(f"⚠️ Services initialization failed (will use fallback): {e}")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on application shutdown"""
    try:
        from app.services.neo4j_service import neo4j_service
        neo4j_service.close()
        logger.info("🔌 Neo4j connection closed")
    except Exception as e:
        logger.warning(f"Neo4j shutdown warning: {e}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,  # Use specific origins for credentials
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
@app.get("/")
async def root():
    return {"message": f"Welcome to {ASSISTANT_NAME} Personal Hub API", "version": "1.0.0-simple"}

@app.get("/health")
async def health():
    return {"status": "healthy", "assistant": ASSISTANT_NAME}

@app.post("/auth/signup", response_model=UserResponse)
async def signup(user_data: UserCreate, request: Request, response: Response, db: Session = Depends(get_db)):
    existing_user = db.query(User).filter(User.email == user_data.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    hashed_password = pwd_context.hash(user_data.password)
    user = User(email=user_data.email, password_hash=hashed_password)
    db.add(user)
    db.commit()
    db.refresh(user)
    
    # Auto-login after signup
    access_token = create_access_token(data={"sub": user.id})
    cookie_domain = get_cookie_domain(request)
    cookie_kwargs = {
        "key": "access_token",
        "value": access_token,
        "secure": False,  # Development
        "httponly": True,
        "samesite": "lax",
        "max_age": 24*7*3600
    }
    if cookie_domain:
        cookie_kwargs["domain"] = cookie_domain
    response.set_cookie(**cookie_kwargs)
    
    return UserResponse(
        id=user.id,
        email=user.email,
        created_at=user.created_at.isoformat()
    )

@app.post("/auth/login", response_model=UserResponse)
async def login(user_data: UserLogin, request: Request, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == user_data.email).first()
    if not user or not pwd_context.verify(user_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    
    access_token = create_access_token(data={"sub": user.id})
    cookie_domain = get_cookie_domain(request)
    cookie_kwargs = {
        "key": "access_token",
        "value": access_token,
        "secure": False,  # Development
        "httponly": True,
        "samesite": "lax",
        "max_age": 24*7*3600
    }
    if cookie_domain:
        cookie_kwargs["domain"] = cookie_domain
    response.set_cookie(**cookie_kwargs)
    
    return UserResponse(
        id=user.id,
        email=user.email,
        created_at=user.created_at.isoformat()
    )

@app.post("/auth/logout")
async def logout(request: Request, response: Response):
    cookie_domain = get_cookie_domain(request)
    if cookie_domain:
        response.delete_cookie(key="access_token", domain=cookie_domain)
    else:
        response.delete_cookie(key="access_token")
    return {"message": "Successfully logged out"}

@app.get("/auth/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        created_at=current_user.created_at.isoformat()
    )

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, current_user: User = Depends(get_current_user)):
    logger.info(f"Chat request from user {current_user.email} with {len(request.messages)} messages")
    if not request.messages:
        raise HTTPException(status_code=400, detail="No messages provided")
    
    # Tool definitions
    tools = [
        {
            "type": "function",
            "function": {
                "name": "search_notes",
                "description": "Search through the user's notes for relevant information",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query to find relevant notes"
                        }
                    },
                    "required": ["query"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "create_note",
                "description": "Create a new note with the given content",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Title for the note (optional)"
                        },
                        "content": {
                            "type": "string", 
                            "description": "Content of the note"
                        }
                    },
                    "required": ["content"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "list_notes",
                "description": "List all user's notes with their titles and IDs",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "delete_note",
                "description": "Delete a specific note by its ID",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "note_id": {
                            "type": "string",
                            "description": "The ID of the note to delete"
                        }
                    },
                    "required": ["note_id"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "create_reminder",
                "description": "Create a reminder for the user at a specific time",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Title/summary of the reminder"
                        },
                        "description": {
                            "type": "string",
                            "description": "Optional detailed description of the reminder"
                        },
                        "reminder_time": {
                            "type": "string",
                            "description": "ISO format datetime when to remind (e.g., '2024-08-16T15:30:00Z')"
                        }
                    },
                    "required": ["title", "reminder_time"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "list_reminders",
                "description": "List all active (non-completed) reminders for the user",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "complete_reminder",
                "description": "Mark a reminder as completed using its ID",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "reminder_id": {
                            "type": "string",
                            "description": "The ID of the reminder to mark as completed"
                        }
                    },
                    "required": ["reminder_id"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "start_timer",
                "description": "Start a timer for a specific duration. Always convert time to minutes: 2 minutes = 2, 1 hour = 60, 30 seconds = 1 (round up)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Title/description of what the timer is for"
                        },
                        "duration_minutes": {
                            "type": "integer",
                            "description": "Duration of the timer in minutes only. Examples: 2 minutes = 2, 1 hour = 60, 30 seconds = 1. Always use positive integers between 1 and 480 (8 hours max)."
                        }
                    },
                    "required": ["title", "duration_minutes"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "list_timers",
                "description": "List all active timers and their remaining time",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "stop_timer",
                "description": "Stop/cancel an active timer using its ID",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "timer_id": {
                            "type": "string",
                            "description": "The ID of the timer to stop"
                        }
                    },
                    "required": ["timer_id"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "search_documents",
                "description": "Search through uploaded documents for relevant information",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query to find relevant content in documents"
                        }
                    },
                    "required": ["query"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "search_memory",
                "description": "Search through Sara's conversation memory for past interactions, preferences, and context",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query to find relevant memories from past conversations"
                        }
                    },
                    "required": ["query"]
                }
            }
        }
    ]
    
    # Add enhanced system message
    system_message = ChatMessage(
        role="system",
        content=f"You are {ASSISTANT_NAME}, a helpful personal assistant for {current_user.email}. "
                f"You have access to tools to search and create notes, manage reminders, run timers, search documents, and access your memory. "
                f"Use search_notes when the user asks about saved information, create_note to save information, "
                f"create_reminder to set time-based reminders, list_reminders to show active reminders, "
                f"complete_reminder to mark reminders as done, start_timer to start productivity timers, "
                f"list_timers to check timer status, stop_timer to cancel timers, "
                f"search_documents to find information in uploaded files, and search_memory to recall past conversations. "
                f"IMPORTANT: Use search_memory when the user asks about previous conversations, mentions something you should remember, "
                f"or when context from past interactions would be helpful. You remember everything we discuss! "
                f"When referencing information from documents, use search_documents and include citations when available. "
                f"You can create beautiful Mermaid diagrams using ```mermaid code blocks for flowcharts, mind maps, timelines, tables, and data visualization. "
                f"Use Mermaid diagrams when presenting complex data, relationships, or processes to make them more visually appealing. "
                f"CRITICAL: After using tools, ALWAYS provide a helpful, conversational response based on the results. "
                f"Never end with just tool calls - always follow up with a natural response that addresses the user's question. "
                f"If tools return information, summarize it helpfully. If no relevant information is found, say so politely. "
                f"For timers, always convert durations to minutes correctly: "
                f"2 minutes = 2, 1 hour = 60, 30 seconds = 1 (round up). Always be helpful and concise."
    )
    
    all_messages = [system_message] + request.messages
    logger.info(f"Calling LLM with {len(all_messages)} messages and {len(tools)} tools")
    response_content = await llm_client.chat_with_tools(all_messages, tools, current_user.id)
    
    # Enhanced debugging for empty response issue
    if response_content:
        logger.info(f"✅ LLM response received: length={len(response_content)}, preview='{response_content[:100]}...'")
    else:
        logger.error(f"❌ LLM response is empty or None: {response_content}")
    
    # Additional debugging
    logger.info(f"🔍 Response type: {type(response_content)}")
    logger.info(f"🔍 Response repr: {repr(response_content)[:200]}")
    
    chat_response = ChatResponse(
        message=ChatMessage(role="assistant", content=response_content)
    )
    
    logger.info(f"🔍 ChatResponse created: message.content length={len(chat_response.message.content) if chat_response.message.content else 0}")
    
    # Store conversation in episodic memory
    try:
        logger.info(f"🧠 Storing conversation in Sara's memory...")
        await llm_client.store_conversation(request.messages, response_content, current_user.id)
        logger.info(f"✅ Conversation stored in memory successfully")
    except Exception as e:
        logger.error(f"❌ Failed to store conversation in memory: {e}")
        # Don't fail the request if memory storage fails
    
    return chat_response

@app.get("/notes", response_model=list[NoteResponse])
async def list_notes(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    notes = db.query(Note).filter(Note.user_id == current_user.id).order_by(Note.updated_at.desc()).limit(20).all()
    return [
        NoteResponse(
            id=note.id,
            title=note.title,
            content=note.content,
            folder_id=note.folder_id,
            created_at=note.created_at.isoformat(),
            updated_at=note.updated_at.isoformat()
        )
        for note in notes
    ]

@app.post("/notes", response_model=NoteResponse)
async def create_note(note_data: NoteCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Neo4j-first approach: Create note in Neo4j immediately
    note_id = str(uuid.uuid4())
    
    try:
        # 1. Create note in Neo4j first with basic properties
        from app.services.neo4j_service import neo4j_service
        from app.services.intelligence_pipeline import intelligence_pipeline, ContentType
        
        # Ensure Neo4j connection
        if not neo4j_service.driver:
            await neo4j_service.connect()
        
        # Create note in Neo4j graph
        neo4j_result = await neo4j_service.create_note(
            note_id=note_id,
            user_id=current_user.id,
            title=note_data.title or "Untitled",
            content=note_data.content,
            folder_id=note_data.folder_id
        )
        
        # 2. Start intelligence pipeline workers if not already running
        await intelligence_pipeline.start_workers()
        
        # 3. Queue for fast processing (embeddings, obvious connections)
        await intelligence_pipeline.queue_fast_processing(
            content_id=note_id,
            content_type=ContentType.NOTE,
            metadata={
                "user_id": current_user.id,
                "title": note_data.title,
                "folder_id": note_data.folder_id
            }
        )
        
        logger.info(f"✅ Note {note_id} created in Neo4j and queued for intelligent processing")
        
    except Exception as neo_error:
        logger.error(f"❌ Neo4j note creation failed: {neo_error}")
        # Continue with PostgreSQL fallback
    
    # 4. Background sync to PostgreSQL (backup)
    note = Note(
        id=note_id,
        user_id=current_user.id,
        title=note_data.title,
        content=note_data.content,
        folder_id=note_data.folder_id
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    
    return NoteResponse(
        id=note.id,
        title=note.title,
        content=note.content,
        folder_id=note.folder_id,
        created_at=note.created_at.isoformat(),
        updated_at=note.updated_at.isoformat()
    )

@app.put("/notes/{note_id}", response_model=NoteResponse)
async def update_note(note_id: str, note_data: NoteCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    note = db.query(Note).filter(Note.id == note_id, Note.user_id == current_user.id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    
    # Neo4j-first approach: Update note in Neo4j and re-process
    try:
        from app.services.neo4j_service import neo4j_service
        from app.services.intelligence_pipeline import intelligence_pipeline, ContentType
        
        # Ensure Neo4j connection
        if not neo4j_service.driver:
            await neo4j_service.connect()
        
        # Update note in Neo4j graph
        await neo4j_service.create_note(
            note_id=note_id,
            user_id=current_user.id,
            title=note_data.title or "Untitled",
            content=note_data.content,
            folder_id=note_data.folder_id
        )
        
        # Re-process with intelligence pipeline for updated content
        await intelligence_pipeline.queue_fast_processing(
            content_id=note_id,
            content_type=ContentType.NOTE,
            metadata={
                "user_id": current_user.id,
                "title": note_data.title,
                "folder_id": note_data.folder_id,
                "is_update": True
            }
        )
        
        logger.info(f"✅ Note {note_id} updated in Neo4j and re-queued for processing")
        
    except Exception as neo_error:
        logger.error(f"❌ Neo4j note update failed: {neo_error}")
    
    # Update PostgreSQL (backup)
    note.title = note_data.title
    note.content = note_data.content
    if note_data.folder_id is not None:
        note.folder_id = note_data.folder_id
    note.updated_at = datetime.now()
    db.commit()
    db.refresh(note)
    
    return NoteResponse(
        id=note.id,
        title=note.title,
        content=note.content,
        folder_id=note.folder_id,
        created_at=note.created_at.isoformat(),
        updated_at=note.updated_at.isoformat()
    )

@app.delete("/notes/{note_id}")
async def delete_note(note_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    note = db.query(Note).filter(Note.id == note_id, Note.user_id == current_user.id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    
    # Also delete associated connections
    db.query(NoteConnection).filter(
        (NoteConnection.source_note_id == note_id) | (NoteConnection.target_note_id == note_id),
        NoteConnection.user_id == current_user.id
    ).delete()
    
    db.delete(note)
    db.commit()
    
    return {"message": "Note deleted successfully"}

# Note Connection endpoints
@app.get("/notes/{note_id}/connections", response_model=list[NoteConnectionResponse])
async def get_note_connections(note_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get all connections for a specific note (both outgoing and incoming)"""
    # Verify note exists and belongs to user
    note = db.query(Note).filter(Note.id == note_id, Note.user_id == current_user.id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    
    connections = db.query(NoteConnection).filter(
        (NoteConnection.source_note_id == note_id) | (NoteConnection.target_note_id == note_id),
        NoteConnection.user_id == current_user.id
    ).all()
    
    return [
        NoteConnectionResponse(
            id=conn.id,
            source_note_id=conn.source_note_id,
            target_note_id=conn.target_note_id,
            connection_type=conn.connection_type,
            strength=conn.strength,
            auto_generated=conn.auto_generated == "true",
            created_at=conn.created_at.isoformat(),
            updated_at=conn.updated_at.isoformat()
        )
        for conn in connections
    ]

@app.post("/notes/{note_id}/connections", response_model=NoteConnectionResponse)
async def create_note_connection(
    note_id: str, 
    connection_data: NoteConnectionCreate, 
    current_user: User = Depends(get_current_user), 
    db: Session = Depends(get_db)
):
    """Create a connection from one note to another"""
    # Verify both notes exist and belong to user
    source_note = db.query(Note).filter(Note.id == note_id, Note.user_id == current_user.id).first()
    if not source_note:
        raise HTTPException(status_code=404, detail="Source note not found")
    
    target_note = db.query(Note).filter(Note.id == connection_data.target_note_id, Note.user_id == current_user.id).first()
    if not target_note:
        raise HTTPException(status_code=404, detail="Target note not found")
    
    # Check if connection already exists
    existing = db.query(NoteConnection).filter(
        NoteConnection.source_note_id == note_id,
        NoteConnection.target_note_id == connection_data.target_note_id,
        NoteConnection.user_id == current_user.id
    ).first()
    
    if existing:
        raise HTTPException(status_code=409, detail="Connection already exists")
    
    connection = NoteConnection(
        user_id=current_user.id,
        source_note_id=note_id,
        target_note_id=connection_data.target_note_id,
        connection_type=connection_data.connection_type,
        strength=connection_data.strength,
        auto_generated="true" if connection_data.auto_generated else "false"
    )
    
    db.add(connection)
    db.commit()
    db.refresh(connection)
    
    return NoteConnectionResponse(
        id=connection.id,
        source_note_id=connection.source_note_id,
        target_note_id=connection.target_note_id,
        connection_type=connection.connection_type,
        strength=connection.strength,
        auto_generated=connection.auto_generated == "true",
        created_at=connection.created_at.isoformat(),
        updated_at=connection.updated_at.isoformat()
    )

@app.delete("/notes/{note_id}/connections/{connection_id}")
async def delete_note_connection(
    note_id: str, 
    connection_id: str, 
    current_user: User = Depends(get_current_user), 
    db: Session = Depends(get_db)
):
    """Delete a specific note connection"""
    connection = db.query(NoteConnection).filter(
        NoteConnection.id == connection_id,
        (NoteConnection.source_note_id == note_id) | (NoteConnection.target_note_id == note_id),
        NoteConnection.user_id == current_user.id
    ).first()
    
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    
    db.delete(connection)
    db.commit()
    
    return {"message": "Connection deleted successfully"}

@app.get("/notes/graph-data")
async def get_notes_graph_data(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get all notes and connections for graph visualization"""
    notes = db.query(Note).filter(Note.user_id == current_user.id).all()
    connections = db.query(NoteConnection).filter(NoteConnection.user_id == current_user.id).all()
    
    return {
        "nodes": [
            {
                "id": note.id,
                "title": note.title,
                "content": note.content[:200] + "..." if len(note.content) > 200 else note.content,
                "type": "note",
                "created_at": note.created_at.isoformat(),
                "updated_at": note.updated_at.isoformat()
            }
            for note in notes
        ],
        "links": [
            {
                "id": conn.id,
                "source": conn.source_note_id,
                "target": conn.target_note_id,
                "type": conn.connection_type,
                "strength": conn.strength / 100.0,  # Normalize to 0-1
                "auto_generated": conn.auto_generated == "true"
            }
            for conn in connections
        ]
    }

# Memory Management endpoints
@app.get("/memory/episodes")
async def get_episodes(
    page: int = 1,
    per_page: int = 20,
    min_importance: float = None,
    max_importance: float = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get episodes with pagination and filtering"""
    # Note: This requires memory service integration
    # For now, return empty response
    return {
        "episodes": [],
        "total": 0,
        "page": page,
        "per_page": per_page
    }

@app.delete("/memory/episodes/{episode_id}")
async def delete_episode(
    episode_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a specific episode"""
    # Note: This requires memory service integration
    # For now, return success
    return {"message": "Episode deletion not yet implemented"}

@app.patch("/memory/episodes/{episode_id}")
async def update_episode(
    episode_id: str,
    importance: float,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update episode importance"""
    # Note: This requires memory service integration
    # For now, return success
    return {"message": "Episode update not yet implemented"}

# Folder endpoints
@app.post("/folders", response_model=FolderResponse)
async def create_folder(folder_data: FolderCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Create a new folder"""
    # Validate parent folder exists and belongs to user if provided
    if folder_data.parent_id:
        parent = db.query(Folder).filter(Folder.id == folder_data.parent_id, Folder.user_id == current_user.id).first()
        if not parent:
            raise HTTPException(status_code=404, detail="Parent folder not found")
    
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
        id=folder.id,
        name=folder.name,
        parent_id=folder.parent_id,
        notes_count=notes_count,
        subfolders_count=subfolders_count,
        created_at=folder.created_at.isoformat(),
        updated_at=folder.updated_at.isoformat()
    )

@app.get("/folders/tree")
async def get_folder_tree(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get the complete folder and note tree structure"""
    # Get all folders for the user
    folders = db.query(Folder).filter(Folder.user_id == current_user.id).all()
    
    # Get all notes for the user
    notes = db.query(Note).filter(Note.user_id == current_user.id).all()
    
    # Build tree structure recursively
    def build_tree(parent_id=None):
        nodes = []
        
        # Add folders
        for folder in folders:
            if folder.parent_id == parent_id:
                node = TreeNodeResponse(
                    id=folder.id,
                    name=folder.name,
                    type="folder",
                    parent_id=folder.parent_id,
                    created_at=folder.created_at.isoformat(),
                    updated_at=folder.updated_at.isoformat(),
                    children=build_tree(folder.id)
                )
                nodes.append(node)
        
        # Add notes
        for note in notes:
            if note.folder_id == parent_id:
                node = TreeNodeResponse(
                    id=note.id,
                    name=note.title or "Untitled",
                    type="note",
                    parent_id=note.folder_id,
                    created_at=note.created_at.isoformat(),
                    updated_at=note.updated_at.isoformat(),
                    children=[]
                )
                nodes.append(node)
        
        return nodes
    
    tree = build_tree()
    return {"tree": tree}

@app.put("/folders/{folder_id}", response_model=FolderResponse)
async def update_folder(folder_id: str, folder_data: FolderUpdate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Update a folder"""
    folder = db.query(Folder).filter(Folder.id == folder_id, Folder.user_id == current_user.id).first()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    
    # Update fields
    if folder_data.name is not None:
        folder.name = folder_data.name
    
    if folder_data.parent_id is not None:
        # Validate new parent exists and belongs to user if provided
        if folder_data.parent_id:
            parent = db.query(Folder).filter(Folder.id == folder_data.parent_id, Folder.user_id == current_user.id).first()
            if not parent:
                raise HTTPException(status_code=404, detail="Parent folder not found")
        
        folder.parent_id = folder_data.parent_id
    
    db.commit()
    db.refresh(folder)
    
    # Count notes and subfolders
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

@app.delete("/folders/{folder_id}")
async def delete_folder(folder_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Delete a folder and all its contents"""
    folder = db.query(Folder).filter(Folder.id == folder_id, Folder.user_id == current_user.id).first()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    
    db.delete(folder)
    db.commit()
    
    return {"message": "Folder deleted successfully"}

@app.get("/reminders", response_model=list[ReminderResponse])
async def list_reminders(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    reminders = db.query(Reminder).filter(
        Reminder.user_id == current_user.id,
        Reminder.is_completed == "false"
    ).order_by(Reminder.reminder_time).limit(20).all()
    
    return [
        ReminderResponse(
            id=reminder.id,
            title=reminder.title,
            description=reminder.description,
            reminder_time=reminder.reminder_time.isoformat(),
            is_completed=reminder.is_completed == "true",
            created_at=reminder.created_at.isoformat(),
            updated_at=reminder.updated_at.isoformat()
        )
        for reminder in reminders
    ]

@app.post("/reminders", response_model=ReminderResponse)
async def create_reminder(reminder_data: ReminderCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    reminder_dt = datetime.fromisoformat(reminder_data.reminder_time.replace('Z', '+00:00'))
    
    reminder = Reminder(
        user_id=current_user.id,
        title=reminder_data.title,
        description=reminder_data.description,
        reminder_time=reminder_dt
    )
    db.add(reminder)
    db.commit()
    db.refresh(reminder)
    
    return ReminderResponse(
        id=reminder.id,
        title=reminder.title,
        description=reminder.description,
        reminder_time=reminder.reminder_time.isoformat(),
        is_completed=reminder.is_completed == "true",
        created_at=reminder.created_at.isoformat(),
        updated_at=reminder.updated_at.isoformat()
    )

@app.patch("/reminders/{reminder_id}/complete")
async def complete_reminder(reminder_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    reminder = db.query(Reminder).filter(
        Reminder.id == reminder_id,
        Reminder.user_id == current_user.id
    ).first()
    
    if not reminder:
        raise HTTPException(status_code=404, detail="Reminder not found")
    
    reminder.is_completed = "true"
    reminder.updated_at = datetime.now()
    db.commit()
    
    return {"message": f"Marked reminder '{reminder.title}' as completed"}

@app.get("/timers", response_model=list[TimerResponse])
async def list_timers(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    timers = db.query(Timer).filter(
        Timer.user_id == current_user.id,
        Timer.is_active == "true"
    ).order_by(Timer.created_at.desc()).limit(20).all()
    
    results = [
        TimerResponse(
            id=timer.id,
            title=timer.title,
            duration_minutes=timer.duration_minutes,
            start_time=timer.start_time.replace(tzinfo=timezone.utc).isoformat(),
            end_time=timer.end_time.replace(tzinfo=timezone.utc).isoformat(),
            is_active=timer.is_active == "true",
            is_completed=timer.is_completed == "true",
            created_at=timer.created_at.replace(tzinfo=timezone.utc).isoformat()
        )
        for timer in timers
    ]
    
    # Debug logging
    for timer_response in results:
        logger.info(f"API returning timer: {timer_response.title} - Start: {timer_response.start_time}, End: {timer_response.end_time}, Duration: {timer_response.duration_minutes}m")
    
    return results

@app.post("/timers", response_model=TimerResponse)
async def start_timer(timer_data: TimerCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    start_time = datetime.now(timezone.utc)
    end_time = start_time + timedelta(minutes=timer_data.duration_minutes)
    
    timer = Timer(
        user_id=current_user.id,
        title=timer_data.title,
        duration_minutes=timer_data.duration_minutes,
        start_time=start_time,
        end_time=end_time
    )
    db.add(timer)
    db.commit()
    db.refresh(timer)
    
    return TimerResponse(
        id=timer.id,
        title=timer.title,
        duration_minutes=timer.duration_minutes,
        start_time=timer.start_time.replace(tzinfo=timezone.utc).isoformat(),
        end_time=timer.end_time.replace(tzinfo=timezone.utc).isoformat(),
        is_active=timer.is_active == "true",
        is_completed=timer.is_completed == "true",
        created_at=timer.created_at.replace(tzinfo=timezone.utc).isoformat()
    )

@app.patch("/timers/{timer_id}/stop")
async def stop_timer(timer_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    timer = db.query(Timer).filter(
        Timer.id == timer_id,
        Timer.user_id == current_user.id,
        Timer.is_active == "true"
    ).first()
    
    if not timer:
        raise HTTPException(status_code=404, detail="Active timer not found")
    
    timer.is_active = "false"
    timer.is_completed = "true"
    db.commit()
    
    return {"message": f"Stopped timer '{timer.title}'"}

# Document API endpoints
@app.post("/documents", response_model=DocumentResponse)
async def upload_document(
    file: UploadFile,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Upload a document with Neo4j-first intelligent processing"""
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
            
            logger.info(f"✅ Document {doc_id} created in Neo4j and queued for intelligent processing")
            
        except Exception as neo_error:
            logger.error(f"❌ Neo4j document creation failed: {neo_error}")
            # Continue with PostgreSQL fallback
        
        # Background sync to PostgreSQL (backup)
        document = Document(
            id=doc_id,
            user_id=current_user.id,
            filename=unique_filename,
            original_filename=file.filename or "unknown",
            title=file.filename or "Untitled Document",  # Add title for backward compatibility
            file_path=file_path,
            file_size=len(file_content),
            mime_type=file.content_type or "application/octet-stream",
            content_text=extracted_text[:50000] if extracted_text else "",  # Store 50KB preview
            is_processed="true"  # Mark as processed since we extracted text
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
                
                # Save chunks to PostgreSQL
                for i, (chunk_text, embedding) in enumerate(zip(processed_chunks, chunk_embeddings)):
                    if DATABASE_URL.startswith("postgresql") and PGVECTOR_AVAILABLE:
                        embedding_data = embedding
                    else:
                        embedding_data = json.dumps(embedding) if embedding else None
                    
                    chunk = DocumentChunk(
                        document_id=document.id,
                        user_id=current_user.id,
                        chunk_index=i,
                        chunk_text=chunk_text,
                        embedding=embedding_data
                    )
                    db.add(chunk)
                
                db.commit()
                logger.info(f"📄 Legacy chunking completed: {len(processed_chunks)} chunks")
        
        except Exception as chunk_error:
            logger.warning(f"⚠️ Legacy chunking failed (Neo4j processing continues): {chunk_error}")
        
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


@app.get("/documents", response_model=list[DocumentResponse])
async def get_documents(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get all documents for the current user"""
    documents = db.query(Document).filter(Document.user_id == current_user.id).order_by(Document.created_at.desc()).all()
    
    return [
        DocumentResponse(
            id=doc.id,
            filename=doc.filename,
            original_filename=doc.original_filename,
            title=getattr(doc, 'title', '') or doc.original_filename,  # Fallback for existing docs
            file_size=doc.file_size,
            mime_type=doc.mime_type,
            content_text=doc.content_text,
            is_processed=doc.is_processed,
            created_at=doc.created_at.isoformat(),
            updated_at=doc.updated_at.isoformat()
        )
        for doc in documents
    ]

@app.get("/documents/{document_id}/file")
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
            "Content-Disposition": f"attachment; filename=\"{document.original_filename}\""
        }
    )

@app.delete("/documents/{document_id}")
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
        logger.info(f"✅ Document {document_id} deleted from Neo4j")
    except Exception as e:
        logger.warning(f"Failed to delete document from Neo4j: {e}")
    
    # Delete document record
    db.delete(document)
    db.commit()
    
    return {"message": "Document deleted successfully"}

@app.put("/documents/{document_id}", response_model=DocumentResponse)
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

@app.get("/documents/search")
async def search_documents(
    query: str,
    limit: int = 5,
    current_user: User = Depends(get_current_user)
):
    """Search for relevant document chunks using vector similarity"""
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

# Conversation memory API endpoints
@app.get("/conversations", response_model=list[ConversationResponse])
async def get_conversations(
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get recent conversations for the current user"""
    conversations = db.query(Conversation).filter(
        Conversation.user_id == current_user.id
    ).order_by(Conversation.updated_at.desc()).limit(limit).all()
    
    return [
        ConversationResponse(
            id=conv.id,
            title=conv.title or "Conversation",
            summary=conv.summary or "",
            total_messages=conv.total_messages,
            created_at=conv.created_at.isoformat(),
            updated_at=conv.updated_at.isoformat()
        )
        for conv in conversations
    ]

@app.get("/conversations/{conversation_id}/turns", response_model=list[ConversationTurnResponse])
async def get_conversation_turns(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all turns/messages for a specific conversation"""
    # Verify the conversation belongs to the user
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.user_id == current_user.id
    ).first()
    
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    turns = db.query(ConversationTurn).filter(
        ConversationTurn.conversation_id == conversation_id
    ).order_by(ConversationTurn.message_index).all()
    
    return [
        ConversationTurnResponse(
            id=turn.id,
            conversation_id=turn.conversation_id,
            role=turn.role,
            content=turn.content,
            message_index=turn.message_index,
            created_at=turn.created_at.isoformat()
        )
        for turn in turns
    ]

@app.get("/memory/search")
async def search_memory(
    query: str,
    limit: int = 10,
    current_user: User = Depends(get_current_user)
):
    """Search through conversation memory"""
    if not query.strip():
        return {"results": []}
    
    try:
        # Use the existing search_memory_tool method
        search_results = await llm_client.search_memory_tool(query, current_user.id)
        
        return {
            "query": query,
            "results": search_results
        }
        
    except Exception as e:
        logger.error(f"Memory search error: {e}")
        raise HTTPException(status_code=500, detail=f"Memory search failed: {str(e)}")

# Knowledge Graph Endpoints
@app.get("/knowledge-graph/health")
async def knowledge_graph_health():
    """Check Neo4j connection health"""
    try:
        from app.services.neo4j_service import neo4j_service
        await neo4j_service.verify_connection()
        return {
            "status": "healthy",
            "neo4j_connected": True,
            "message": "Knowledge graph is operational"
        }
    except Exception as e:
        return {
            "status": "unhealthy", 
            "neo4j_connected": False,
            "error": str(e),
            "message": "Knowledge graph connection failed"
        }

@app.get("/knowledge-graph/")
async def get_user_knowledge_graph(
    depth: int = 2,
    current_user: User = Depends(get_current_user)
):
    """Get the complete knowledge graph for the current user"""
    try:
        from app.services.neo4j_service import neo4j_service
        graph_data = await neo4j_service.get_user_knowledge_graph(
            user_id=current_user.id,
            depth=depth
        )
        
        return {
            "nodes": graph_data.get("nodes", []),
            "relationships": graph_data.get("relationships", []),
            "total_nodes": len(graph_data.get("nodes", [])),
            "total_relationships": len(graph_data.get("relationships", []))
        }
        
    except Exception as e:
        logger.error(f"Failed to get knowledge graph: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve knowledge graph: {str(e)}")

@app.post("/knowledge-graph/search")
async def search_knowledge_graph(
    request: dict,
    current_user: User = Depends(get_current_user)
):
    """Search across all content types in the knowledge graph"""
    try:
        from app.services.neo4j_service import neo4j_service
        query = request.get("query")
        content_types = request.get("content_types")
        limit = request.get("limit", 20)
        
        if not query:
            raise HTTPException(status_code=400, detail="Search query is required")
        
        search_results = await neo4j_service.search_knowledge_graph(
            user_id=current_user.id,
            query=query,
            content_types=content_types,
            limit=limit
        )
        
        # Format results for frontend consumption
        formatted_results = []
        for item in search_results:
            # Determine primary content type
            primary_type = item.get("node_types", ["Unknown"])[0].lower()
            
            formatted_results.append({
                "id": item.get("id"),
                "type": primary_type,
                "title": item.get("title") or item.get("content", "")[:50] + "...",
                "content": item.get("content") or item.get("content_text", ""),
                "created_at": item.get("created_at"),
                "metadata": {
                    "node_types": item.get("node_types", []),
                    "properties": {k: v for k, v in item.items() if k not in ["id", "content", "content_text", "title", "created_at"]}
                }
            })
        
        return {
            "query": query,
            "results": formatted_results,
            "total_found": len(formatted_results)
        }
        
    except Exception as e:
        logger.error(f"Knowledge graph search failed: {e}")
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")

@app.post("/knowledge-graph/connected-content")
async def get_connected_content(
    request: dict,
    current_user: User = Depends(get_current_user)
):
    """Find all content connected to a specific node"""
    try:
        from app.services.neo4j_service import neo4j_service
        node_id = request.get("node_id")
        depth = request.get("depth", 2)
        relationship_types = request.get("relationship_types")
        
        if not node_id:
            raise HTTPException(status_code=400, detail="Node ID is required")
        
        connected_items = await neo4j_service.find_connected_content(
            node_id=node_id,
            user_id=current_user.id,
            depth=depth,
            relationship_types=relationship_types
        )
        
        return {
            "source_node_id": node_id,
            "connected_content": connected_items,
            "total_connections": len(connected_items)
        }
        
    except Exception as e:
        logger.error(f"Failed to get connected content: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get connected content: {str(e)}")

@app.get("/analytics/dashboard")
async def get_analytics_dashboard(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get comprehensive analytics dashboard data"""
    try:
        # Database size and health
        try:
            # Simplified database size query
            db_size_query = text("SELECT pg_size_pretty(pg_database_size(current_database())) as size")
            db_size_result = db.execute(db_size_query).fetchone()
            db_size = db_size_result.size if db_size_result else "Unknown"
            
            # Get connection count
            conn_query = text("SELECT count(*) as connections FROM pg_stat_activity WHERE datname = current_database()")
            conn_result = db.execute(conn_query).fetchone()
            db_connections = conn_result.connections if conn_result else 0
        except Exception as e:
            logger.error(f"Database query error: {e}")
            db_size = "Unknown"
            db_connections = 0
        
        # Total messages and conversations
        total_conversations = db.query(Conversation).filter(Conversation.user_id == current_user.id).count()
        total_messages = db.query(ConversationTurn).filter(ConversationTurn.user_id == current_user.id).count()
        
        # Memory/archival counts
        messages_with_embeddings = db.query(ConversationTurn).filter(
            ConversationTurn.user_id == current_user.id,
            ConversationTurn.embedding.isnot(None)
        ).count()
        
        # System health checks
        try:
            # Test embedding service
            embedding_test = await embedding_service.generate_embedding("test")
            embedding_health = len(embedding_test) == EMBEDDING_DIM
        except:
            embedding_health = False
            
        # Database health
        try:
            db.execute(text("SELECT 1"))
            db_health = True
            logger.info("Database health check: PASS")
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            db_health = False
            
        # AI system metrics (get from recent logs)
        recent_chats = db.query(ConversationTurn).filter(
            ConversationTurn.user_id == current_user.id,
            ConversationTurn.role == "assistant",
            ConversationTurn.created_at >= datetime.now() - timedelta(days=7)
        ).count()
        
        # Tool usage stats (simplified)
        tool_calls_successful = recent_chats  # Approximation
        
        # User activity stats
        notes_count = db.query(Note).filter(Note.user_id == current_user.id).count()
        reminders_count = db.query(Reminder).filter(
            Reminder.user_id == current_user.id,
            Reminder.is_completed == "false"
        ).count()
        documents_count = db.query(Document).filter(Document.user_id == current_user.id).count()
        active_timers = db.query(Timer).filter(
            Timer.user_id == current_user.id,
            Timer.is_active == "true"
        ).count()
        
        # Recent activity
        last_conversation = db.query(Conversation).filter(
            Conversation.user_id == current_user.id
        ).order_by(Conversation.updated_at.desc()).first()
        
        last_activity = last_conversation.updated_at if last_conversation else None
        
        return {
            "database": {
                "size": db_size,
                "connections": db_connections,
                "health": db_health
            },
            "memory": {
                "total_conversations": total_conversations,
                "total_messages": total_messages,
                "archived_count": messages_with_embeddings,
                "archival_percentage": round((messages_with_embeddings / max(total_messages, 1)) * 100, 1)
            },
            "ai_system": {
                "embedding_service_health": embedding_health,
                "successful_responses_7d": recent_chats,
                "tool_calls_successful_7d": tool_calls_successful,
                "last_activity": last_activity.isoformat() if last_activity else None
            },
            "user_data": {
                "notes": notes_count,
                "active_reminders": reminders_count,
                "documents": documents_count,
                "active_timers": active_timers
            },
            "system_health": {
                "overall": db_health and embedding_health,
                "database": db_health,
                "ai_services": embedding_health,
                "status": "healthy" if (db_health and embedding_health) else "degraded"
            }
        }
        
    except Exception as e:
        logger.error(f"Analytics dashboard error: {e}")
        raise HTTPException(status_code=500, detail=f"Analytics failed: {str(e)}")

# Settings endpoints
@app.get("/settings/ai")
async def get_ai_settings(current_user: User = Depends(get_current_user)):
    """Get current AI configuration settings"""
    return {
        "openai_base_url": OPENAI_BASE_URL,
        "openai_model": OPENAI_MODEL,
        "embedding_base_url": EMBEDDING_BASE_URL,
        "embedding_model": EMBEDDING_MODEL,
        "embedding_dimension": EMBEDDING_DIM
    }

class AISettingsUpdate(BaseModel):
    openai_base_url: Optional[str] = None
    openai_model: Optional[str] = None
    embedding_base_url: Optional[str] = None
    embedding_model: Optional[str] = None
    embedding_dimension: Optional[int] = None

@app.put("/settings/ai")
async def update_ai_settings(
    settings: AISettingsUpdate,
    current_user: User = Depends(get_current_user)
):
    """Update AI configuration settings (requires restart to take effect)"""
    global OPENAI_BASE_URL, OPENAI_MODEL, EMBEDDING_BASE_URL, EMBEDDING_MODEL, EMBEDDING_DIM
    
    updated_settings = {}
    
    if settings.openai_base_url is not None:
        OPENAI_BASE_URL = settings.openai_base_url
        updated_settings["openai_base_url"] = settings.openai_base_url
        
    if settings.openai_model is not None:
        OPENAI_MODEL = settings.openai_model
        updated_settings["openai_model"] = settings.openai_model
        
    if settings.embedding_base_url is not None:
        EMBEDDING_BASE_URL = settings.embedding_base_url
        updated_settings["embedding_base_url"] = settings.embedding_base_url
        
    if settings.embedding_model is not None:
        EMBEDDING_MODEL = settings.embedding_model
        updated_settings["embedding_model"] = settings.embedding_model
        
    if settings.embedding_dimension is not None:
        EMBEDDING_DIM = settings.embedding_dimension
        updated_settings["embedding_dimension"] = settings.embedding_dimension
    
    # Reinitialize services with new settings
    global llm_client, embedding_service
    llm_client = SimpleLLMClient()
    embedding_service = EmbeddingService()
    
    logger.info(f"AI settings updated by user {current_user.email}: {updated_settings}")
    
    return {
        "message": "AI settings updated successfully",
        "updated_settings": updated_settings,
        "note": "Some changes may require application restart to take full effect"
    }

@app.post("/settings/ai/test")
async def test_ai_settings(current_user: User = Depends(get_current_user)):
    """Test current AI configuration"""
    test_results = {}
    
    try:
        # Test LLM connection
        test_messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello, just testing the connection. Please respond with 'Connection successful'."}
        ]
        
        response = await httpx.AsyncClient().post(
            f"{OPENAI_BASE_URL}/chat/completions",
            json={
                "model": OPENAI_MODEL,
                "messages": test_messages,
                "max_tokens": 50
            },
            headers={"Authorization": "Bearer dummy"},
            timeout=10.0
        )
        
        if response.status_code == 200:
            test_results["llm"] = {"status": "success", "message": "LLM connection successful"}
        else:
            test_results["llm"] = {"status": "error", "message": f"LLM connection failed: {response.status_code}"}
            
    except Exception as e:
        test_results["llm"] = {"status": "error", "message": f"LLM connection failed: {str(e)}"}
    
    try:
        # Test embedding service
        embedding = await embedding_service.generate_embedding("test")
        if embedding and len(embedding) == EMBEDDING_DIM:
            test_results["embedding"] = {"status": "success", "message": f"Embedding service working (dimension: {len(embedding)})"}
        else:
            test_results["embedding"] = {"status": "error", "message": "Embedding service returned invalid response"}
            
    except Exception as e:
        test_results["embedding"] = {"status": "error", "message": f"Embedding service failed: {str(e)}"}
    
    return test_results

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="10.185.1.180", port=8000)