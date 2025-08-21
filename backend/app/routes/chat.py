from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from app.core.deps import get_current_user
from app.core.llm import llm_client
from app.core.config import settings
from app.db.session import get_db
from app.models.user import User
from app.services.memory_service import MemoryService
from app.services.contextual_awareness_service import contextual_awareness_service
from app.tools.registry import tool_registry
import logging
import uuid
import json

logger = logging.getLogger(__name__)

router = APIRouter()


class ChatMessage(BaseModel):
    role: str  # user, assistant, system
    content: str


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    message: ChatMessage
    session_id: str
    citations: List[str] = []
    tool_effects: List[Dict[str, Any]] = []


class ChatRouter:
    """Router for deciding retrieval based on user query"""
    
    def __init__(self):
        # Simple keyword-based routing rules
        self.memory_keywords = [
            "remember", "recall", "what did", "when did", "tell me about",
            "find", "search", "look up", "mentioned", "said", "discussed"
        ]
        
        self.notes_keywords = [
            "note", "notes", "wrote", "written", "documented", "saved"
        ]
        
        self.docs_keywords = [
            "document", "file", "pdf", "uploaded", "doc", "paper"
        ]
        
        self.reminders_keywords = [
            "remind", "reminder", "due", "schedule", "appointment", "meeting"
        ]
        
        self.chit_chat_keywords = [
            "hello", "hi", "how are you", "thanks", "thank you", "goodbye", "bye"
        ]
    
    def should_retrieve_memory(self, user_message: str) -> Dict[str, bool]:
        """Determine what types of retrieval are needed"""
        
        message_lower = user_message.lower()
        
        # Check for chit-chat patterns
        is_chit_chat = any(keyword in message_lower for keyword in self.chit_chat_keywords)
        if is_chit_chat and len(user_message.split()) < 10:
            return {
                "needs_memory": False,
                "needs_notes": False,
                "needs_docs": False,
                "needs_context": False
            }
        
        # Check for specific memory needs
        needs_memory = any(keyword in message_lower for keyword in self.memory_keywords)
        needs_notes = any(keyword in message_lower for keyword in self.notes_keywords)
        needs_docs = any(keyword in message_lower for keyword in self.docs_keywords)
        needs_context = any(keyword in message_lower for keyword in self.reminders_keywords)
        
        # If nothing specific, but it's a question, enable memory search
        if not any([needs_memory, needs_notes, needs_docs]) and ("?" in user_message or message_lower.startswith(("what", "when", "where", "how", "why", "who"))):
            needs_memory = True
        
        return {
            "needs_memory": needs_memory,
            "needs_notes": needs_notes, 
            "needs_docs": needs_docs,
            "needs_context": needs_context or needs_memory or needs_notes or needs_docs
        }


chat_router = ChatRouter()


@router.post("/", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Main chat endpoint with selective RAG"""
    
    if not request.messages:
        raise HTTPException(status_code=400, detail="No messages provided")
    
    # Get or create session ID
    session_id = request.session_id or str(uuid.uuid4())
    
    # Get the latest user message
    user_message = None
    for msg in reversed(request.messages):
        if msg.role == "user":
            user_message = msg.content
            break
    
    if not user_message:
        raise HTTPException(status_code=400, detail="No user message found")
    
    memory_service = MemoryService(db)
    
    try:
        # Store user message as episode
        await memory_service.store_episode(
            user_id=str(current_user.id),
            source="chat",
            role="user",
            content=user_message,
            meta={"session_id": session_id}
        )
        
        # Determine retrieval needs
        retrieval_needs = chat_router.should_retrieve_memory(user_message)
        
        # Get Sara's current contextual awareness (living context)
        living_context = await contextual_awareness_service.get_current_living_context(str(current_user.id))
        
        # Prepare context
        context_parts = []
        citations = []
        
        # Always include living context for Sara's awareness
        if living_context:
            context_parts.append("## Sara's Current Contextual Awareness")
            context_parts.append(living_context)
            context_parts.append("")  # Add spacing
        
        if retrieval_needs["needs_context"]:
            # Determine which scopes to search
            scopes = []
            if retrieval_needs["needs_memory"]:
                scopes.extend(["episodes", "summaries"])
            if retrieval_needs["needs_notes"]:
                scopes.append("notes")
            if retrieval_needs["needs_docs"]:
                scopes.append("docs")
            
            if scopes:
                # Search memory
                memory_results = await memory_service.search_memory(
                    user_id=str(current_user.id),
                    query=user_message,
                    scopes=scopes,
                    limit=8
                )
                
                if memory_results:
                    context_parts.append("## Relevant Context")
                    for result in memory_results:
                        if result["type"] == "episode":
                            context_parts.append(f"- {result['text']} (from {result['source']})")
                            citations.append(f"mem:{result['episode_id']}")
                        elif result["type"] == "summary":
                            context_parts.append(f"- {result['text']} (summary: {result['scope']})")
                            citations.append(f"sem:{result['summary_id']}")
                        elif result["type"] == "note":
                            context_parts.append(f"- Note '{result['title']}': {result['text'][:200]}...")
                            citations.append(f"note:{result['note_id']}")
                        elif result["type"] == "document":
                            context_parts.append(f"- Document '{result['doc_title']}': {result['text'][:200]}...")
                            citations.append(f"doc:{result['doc_id']}#{result['chunk_idx']}")
        
        # Generate proactive suggestions based on context and user message
        proactive_suggestions = await _generate_proactive_suggestions(
            str(current_user.id), user_message, living_context
        )
        
        # Prepare messages for LLM
        base_prompt = f"""You are {settings.assistant_name}, a helpful personal assistant with contextual awareness. You have access to tools to manage notes, reminders, timers, calendar events, and search through personal memory.

You have been provided with your current contextual awareness which includes active timers, upcoming reminders, mood analysis, and priority items. Use this information to provide proactive and contextually appropriate responses.

When you use information from memory or documents, cite them using the format provided in the context. Keep responses conversational and helpful, and consider your current contextual awareness when providing assistance.

Available tools: notes management, reminders, timers, calendar events, and memory search."""
        
        # Add proactive suggestions if any were generated
        if proactive_suggestions:
            suggestions_text = "\n".join([f"- {suggestion}" for suggestion in proactive_suggestions])
            system_prompt = base_prompt + f"""

PROACTIVE SUGGESTIONS: Based on the user's message and current context, consider offering these helpful suggestions naturally in your response:
{suggestions_text}

Only mention suggestions that feel genuinely helpful and relevant to the conversation flow. Don't force all suggestions - use your judgment."""
        else:
            system_prompt = base_prompt
        
        llm_messages = [{"role": "system", "content": system_prompt}]
        
        # Add context if we found any
        if context_parts:
            context_message = "\n".join(context_parts)
            llm_messages.append({"role": "system", "content": context_message})
        
        # Add conversation history (last 6 messages to keep context manageable)
        recent_messages = request.messages[-6:]
        for msg in recent_messages:
            llm_messages.append({"role": msg.role, "content": msg.content})
        
        # Get tool schemas
        tools = tool_registry.get_openai_schemas()
        
        # Call LLM
        response = await llm_client.chat_completion(
            messages=llm_messages,
            tools=tools,
            tool_choice="auto",
            temperature=0.7
        )
        
        assistant_message = response["choices"][0]["message"]
        tool_effects = []
        
        # Handle tool calls
        if assistant_message.get("tool_calls"):
            for tool_call in assistant_message["tool_calls"]:
                tool_name = tool_call["function"]["name"]
                tool_params = json.loads(tool_call["function"]["arguments"])
                
                # Execute tool
                tool_result = await tool_registry.execute_tool(
                    name=tool_name,
                    user_id=str(current_user.id),
                    parameters=tool_params
                )
                
                if tool_result.success:
                    tool_effects.append({
                        "tool": tool_name,
                        "action": tool_result.message,
                        "data": tool_result.data
                    })
                    
                    # Add tool citations
                    if tool_result.citations:
                        citations.extend(tool_result.citations)
                
                # Add tool result to conversation for final response
                llm_messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": json.dumps({
                        "success": tool_result.success,
                        "message": tool_result.message,
                        "data": tool_result.data
                    })
                })
            
            # Get final response after tool execution
            final_response = await llm_client.chat_completion(
                messages=llm_messages,
                temperature=0.7
            )
            final_message = final_response["choices"][0]["message"]["content"]
        else:
            final_message = assistant_message["content"]
        
        # Store assistant response as episode
        await memory_service.store_episode(
            user_id=str(current_user.id),
            source="chat",
            role="assistant",
            content=final_message,
            meta={
                "session_id": session_id,
                "tool_calls": len(assistant_message.get("tool_calls", [])),
                "citations": citations
            }
        )
        
        # Update session summary
        if len(request.messages) >= 4:  # Update summary every few turns
            from app.models.episode import Episode
            recent_episodes = db.query(Episode).filter(
                Episode.user_id == str(current_user.id),
                Episode.meta["session_id"].astext == session_id
            ).order_by(Episode.created_at.desc()).limit(10).all()
            
            if recent_episodes:
                await memory_service.create_session_summary(
                    user_id=str(current_user.id),
                    session_id=session_id,
                    episodes=recent_episodes
                )
        
        return ChatResponse(
            message=ChatMessage(role="assistant", content=final_message),
            session_id=session_id,
            citations=list(set(citations)),  # Remove duplicates
            tool_effects=tool_effects
        )
        
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=f"Chat processing failed: {str(e)}")


@router.get("/sessions")
async def list_chat_sessions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List recent chat sessions"""
    
    try:
        # Get recent sessions from episode metadata
        from sqlalchemy import text
        
        sql = text("""
            SELECT 
                meta->>'session_id' as session_id,
                MIN(created_at) as started_at,
                MAX(created_at) as last_activity,
                COUNT(*) as message_count
            FROM episode 
            WHERE user_id = :user_id 
                AND source = 'chat'
                AND meta->>'session_id' IS NOT NULL
            GROUP BY meta->>'session_id'
            ORDER BY MAX(created_at) DESC
            LIMIT 20
        """)
        
        result = db.execute(sql, {"user_id": str(current_user.id)})
        
        sessions = []
        for row in result.fetchall():
            sessions.append({
                "session_id": row.session_id,
                "started_at": row.started_at.isoformat(),
                "last_activity": row.last_activity.isoformat(),
                "message_count": row.message_count
            })
        
        return {"sessions": sessions}
        
    except Exception as e:
        logger.error(f"Failed to list sessions: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve sessions")


async def _generate_proactive_suggestions(user_id: str, user_message: str, living_context: str = None) -> List[str]:
    """Generate proactive suggestions based on user message and context"""
    
    suggestions = []
    message_lower = user_message.lower()
    
    try:
        # Time-based suggestions
        time_keywords = ["later", "tomorrow", "next week", "in an hour", "tonight", "this afternoon"]
        if any(keyword in message_lower for keyword in time_keywords):
            if "remind" not in message_lower and "timer" not in message_lower:
                suggestions.append("Would you like me to create a reminder for this?")
        
        # Task/activity suggestions
        task_keywords = ["need to", "have to", "should", "must", "going to", "planning to"]
        if any(keyword in message_lower for keyword in task_keywords):
            if "remind" not in message_lower and "note" not in message_lower:
                suggestions.append("I can help you create a reminder or note to track this task.")
        
        # Meeting/appointment suggestions
        meeting_keywords = ["meeting", "appointment", "call", "zoom", "conference"]
        if any(keyword in message_lower for keyword in meeting_keywords):
            suggestions.append("Would you like me to add this to your calendar or set a reminder?")
        
        # Learning/reference suggestions
        learning_keywords = ["learned", "interesting", "important", "remember this", "good to know"]
        if any(keyword in message_lower for keyword in learning_keywords):
            if "note" not in message_lower:
                suggestions.append("This sounds like something worth saving as a note for future reference.")
        
        # Recipe/cooking suggestions
        cooking_keywords = ["cook", "recipe", "ingredients", "grocery", "shopping"]
        if any(keyword in message_lower for keyword in cooking_keywords):
            suggestions.append("I can help you save this recipe or create a shopping list.")
        
        # Workout/fitness suggestions  
        fitness_keywords = ["workout", "exercise", "gym", "run", "training"]
        if any(keyword in message_lower for keyword in fitness_keywords):
            if "timer" not in message_lower:
                suggestions.append("Would you like me to set a workout timer or log this session?")
        
        # Context-based suggestions from living context
        if living_context:
            # Check for active timers
            if "Active Timers: 0" not in living_context and "timer" in message_lower:
                suggestions.append("I notice you have active timers running. Let me know if you need to check or modify them.")
            
            # Check for upcoming reminders
            if "Upcoming Reminders: 0" not in living_context and any(word in message_lower for word in ["busy", "schedule", "time"]):
                suggestions.append("You have upcoming reminders - would you like me to review what's coming up?")
        
        # Question/uncertainty suggestions
        question_keywords = ["how do i", "what should", "not sure", "confused", "help"]
        if any(keyword in message_lower for keyword in question_keywords):
            suggestions.append("I can search through your notes and memories to see if we've discussed this before.")
        
        # Limit suggestions to avoid overwhelming
        return suggestions[:2]  # Maximum 2 suggestions
        
    except Exception as e:
        logger.error(f"Error generating proactive suggestions: {e}")
        return []