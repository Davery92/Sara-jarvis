"""
Research Routes
API endpoints for web research: simple search with AI summary, deep research via orchestrator
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import json
import logging
import uuid
import httpx

from app.services.search_service import search_service
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/research")


class ResearchRequest(BaseModel):
    query: str
    model: Optional[str] = None
    mode: str = "simple"  # "simple" or "deep"


class SaveResearchRequest(BaseModel):
    query: str
    content: str
    sources: Optional[List[Dict[str, Any]]] = None


class SaveResearchResponse(BaseModel):
    note_id: str
    folder_id: str


def format_sse(data: dict) -> str:
    """Format data as Server-Sent Event"""
    return f"data: {json.dumps(data)}\n\n"


async def stream_llm_completion(messages: List[Dict], model: str):
    """Stream LLM completion using httpx"""
    base_url = settings.llm_primary_url
    api_key = settings.openai_api_key

    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "temperature": 0.7,
        # Local qwen: disable thinking or `content` comes back empty.
        "chat_template_kwargs": {"enable_thinking": False},
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream(
            "POST",
            f"{base_url}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {}
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                if line.startswith("data: "):
                    line = line[6:]
                if line == "[DONE]":
                    break
                try:
                    chunk = json.loads(line)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        yield content
                except json.JSONDecodeError:
                    continue


@router.post("/search")
async def search(
    request: ResearchRequest,
    # Note: Auth handled at app level via middleware
):
    """
    Simple search: Tavily -> AI summary, streamed via SSE

    Event types:
    - sources: List of search result sources
    - content: Streaming AI summary chunks
    - done: Stream complete
    - error: Error occurred
    """
    async def generate_events():
        try:
            logger.info(f"Research search: query='{request.query}', mode={request.mode}, model={request.model}")

            # 1. Search via Tavily/SearchService
            search_results = await search_service.web_search(
                query=request.query,
                max_results=8,
                extract_top_n=6
            )

            results = search_results.get("results", [])

            # 2. Send sources first
            sources = [
                {
                    "url": r.get("url", ""),
                    "title": r.get("title", ""),
                    "snippet": r.get("snippet", "")[:200] if r.get("snippet") else ""
                }
                for r in results
            ]
            yield format_sse({"type": "sources", "data": sources})
            logger.info(f"Sent {len(sources)} sources")

            # 3. Build context for AI summary
            context_parts = []
            for i, r in enumerate(results, 1):
                title = r.get("title", "Untitled")
                snippet = r.get("snippet", "")
                url = r.get("url", "")
                context_parts.append(f"[{i}] {title}\nURL: {url}\n{snippet}\n")

            context = "\n".join(context_parts)

            # 4. Create summary prompt
            system_prompt = """You are a research assistant. Summarize the search results to answer the user's query.
Be comprehensive but concise. Use markdown formatting.
Cite sources using [1], [2], etc. notation when referencing specific information.
Focus on the most relevant and reliable information."""

            user_prompt = f"""Query: {request.query}

Search Results:
{context}

Please provide a comprehensive summary answering the query based on these search results."""

            # 5. Stream AI summary
            model = request.model or settings.openai_model
            logger.info(f"Generating summary with model: {model}")

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]

            try:
                # Use streaming completion via httpx
                async for chunk in stream_llm_completion(messages, model):
                    if chunk:
                        yield format_sse({"type": "content", "data": chunk})
            except Exception as e:
                logger.error(f"Error streaming summary: {e}")
                yield format_sse({"type": "error", "data": {"message": f"Summary generation failed: {str(e)}"}})

            yield format_sse({"type": "done"})
            logger.info("Research search complete")

        except Exception as e:
            logger.error(f"Error in research search: {e}")
            yield format_sse({"type": "error", "data": {"message": str(e)}})
            yield format_sse({"type": "done"})

    return StreamingResponse(
        generate_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Disable nginx buffering
        }
    )


@router.post("/save", response_model=SaveResearchResponse)
async def save_research(
    request: SaveResearchRequest,
    current_user = Depends(lambda: None),  # Placeholder - will be injected by app
    db: "Session" = Depends(lambda: None),  # Placeholder - will be injected by app
):
    """
    Save research result to Research folder in notes.
    Creates the folder if it doesn't exist.
    """
    # Import here to avoid circular imports
    from app.main_simple import SessionLocal, Folder, Note

    # Use injected db or create our own session
    own_db = False
    if db is None:
        db = SessionLocal()
        own_db = True

    try:
        # Get user_id from current_user or use default
        user_id = getattr(current_user, 'id', None) or "default"

        # 1. Find or create "📊 Research" folder
        research_folder_name = "📊 Research"
        folder = db.query(Folder).filter(
            Folder.user_id == user_id,
            Folder.name == research_folder_name
        ).first()

        if not folder:
            folder = Folder(
                id=str(uuid.uuid4()),
                user_id=user_id,
                name=research_folder_name,
                parent_id=None
            )
            db.add(folder)
            db.commit()
            db.refresh(folder)
            logger.info(f"Created research folder: {folder.id}")

        # 2. Create note with research content
        # Build content with sources
        content = request.content
        if request.sources:
            content += "\n\n---\n\n## Sources\n\n"
            for i, source in enumerate(request.sources, 1):
                title = source.get("title", "Untitled")
                url = source.get("url", "")
                content += f"{i}. [{title}]({url})\n"

        # Truncate query for title
        query_short = request.query[:50] + "..." if len(request.query) > 50 else request.query

        note = Note(
            id=str(uuid.uuid4()),
            user_id=user_id,
            folder_id=folder.id,
            title=f"Research: {query_short}",
            content=content
        )
        db.add(note)
        db.commit()
        db.refresh(note)

        logger.info(f"Saved research note: {note.id} in folder {folder.id}")

        return SaveResearchResponse(
            note_id=note.id,
            folder_id=folder.id
        )

    except Exception as e:
        logger.error(f"Error saving research: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if own_db:
            db.close()
