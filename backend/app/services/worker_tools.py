"""
Worker Tools - Real implementations for agent workers

These tools are available to worker agents for research and data gathering.
Workers have READ-ONLY access to Sara's data and can write to the agent workspace.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.services.note_provenance import SARA_GENERATED_TAG

logger = logging.getLogger(__name__)


class WorkerToolExecutor:
    """Executes worker tools with real implementations"""

    def __init__(self, db: Session, user_id: str, workspace_folder_id: Optional[str] = None):
        """
        Initialize tool executor.

        Args:
            db: Database session for data access
            user_id: User ID for scoping data access
            workspace_folder_id: Folder ID for agent workspace notes
        """
        self.db = db
        self.user_id = user_id
        self.workspace_folder_id = workspace_folder_id
        self._notes_cache: Dict[str, Any] = {}

    async def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """
        Execute a worker tool and return the result as a string.

        Args:
            tool_name: Name of the tool to execute
            arguments: Tool arguments

        Returns:
            JSON string with tool result
        """
        try:
            if tool_name == "web_search":
                return await self._web_search(
                    query=arguments.get("query", ""),
                    num_results=arguments.get("num_results", 5)
                )
            elif tool_name == "read_url":
                return await self._read_url(
                    url=arguments.get("url", "")
                )
            elif tool_name == "take_notes":
                return await self._take_notes(
                    title=arguments.get("title", ""),
                    content=arguments.get("content", "")
                )
            elif tool_name == "read_notes":
                return await self._read_notes(
                    query=arguments.get("query", ""),
                    limit=arguments.get("limit", 5)
                )
            elif tool_name == "read_calendar":
                return await self._read_calendar(
                    days_ahead=arguments.get("days_ahead", 7),
                    days_behind=arguments.get("days_behind", 0)
                )
            elif tool_name == "read_memories":
                return await self._read_memories(
                    query=arguments.get("query", ""),
                    limit=arguments.get("limit", 10)
                )
            else:
                return json.dumps({"error": f"Unknown tool: {tool_name}"})

        except Exception as e:
            logger.error(f"Tool {tool_name} failed: {e}")
            return json.dumps({"error": str(e), "tool": tool_name})

    async def _web_search(self, query: str, num_results: int = 5) -> str:
        """
        Search the web using Tavily or SearXNG.

        Returns real search results with titles, URLs, and snippets.
        """
        try:
            from .search_service import search_service

            result = await search_service.web_search(
                query=query,
                max_results=min(num_results, 10)
            )

            # Format results for the worker
            formatted_results = []
            for item in result.get("results", []):
                formatted_results.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "snippet": item.get("snippet", "")[:300],
                    "source": item.get("source", "web")
                })

            return json.dumps({
                "query": query,
                "results": formatted_results,
                "total_results": len(formatted_results)
            }, indent=2)

        except Exception as e:
            logger.error(f"Web search failed: {e}")
            return json.dumps({
                "error": f"Search failed: {str(e)}",
                "query": query,
                "results": []
            })

    async def _read_url(self, url: str) -> str:
        """
        Fetch and extract content from a URL.

        Returns the page title and readable text content.
        """
        try:
            from .search_service import search_service

            result = await search_service.open_page(url)

            # Get plain text, truncate if too long
            plain_text = result.get("plain_text", "")
            if len(plain_text) > 8000:
                plain_text = plain_text[:8000] + "\n\n[Content truncated...]"

            return json.dumps({
                "url": result.get("final_url", url),
                "title": result.get("title", ""),
                "site": result.get("site_name", ""),
                "content": plain_text,
                "content_length": len(plain_text)
            }, indent=2)

        except Exception as e:
            logger.error(f"URL read failed for {url}: {e}")
            return json.dumps({
                "error": f"Failed to read URL: {str(e)}",
                "url": url
            })

    async def _take_notes(self, title: str, content: str) -> str:
        """
        Save findings to the agent workspace.

        Creates a note in the workspace folder for this task.
        """
        try:
            from ..main_simple import Note
            import uuid

            if not self.workspace_folder_id:
                return json.dumps({
                    "error": "No workspace folder configured",
                    "status": "failed"
                })

            # Create note in workspace
            note = Note(
                id=str(uuid.uuid4()),
                user_id=self.user_id,
                folder_id=self.workspace_folder_id,
                title=f"📝 {title}",
                content=f"*Agent note - {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}*\n\n{content}",
                tags=[SARA_GENERATED_TAG],
            )

            self.db.add(note)
            self.db.commit()

            logger.info(f"Worker created note: {title}")

            return json.dumps({
                "status": "saved",
                "title": title,
                "note_id": note.id,
                "content_length": len(content),
                "message": f"Note '{title}' saved successfully"
            })

        except Exception as e:
            logger.error(f"Take notes failed: {e}")
            return json.dumps({
                "error": f"Failed to save note: {str(e)}",
                "status": "failed"
            })

    async def _read_notes(self, query: str, limit: int = 5) -> str:
        """
        Search user's notes (READ-ONLY).

        Returns matching notes without modification capability.
        """
        try:
            from ..main_simple import Note
            from sqlalchemy import or_

            # Simple search - title and content
            notes = self.db.query(Note).filter(
                Note.user_id == self.user_id,
                or_(
                    Note.title.ilike(f"%{query}%"),
                    Note.content.ilike(f"%{query}%")
                )
            ).order_by(Note.updated_at.desc()).limit(limit).all()

            results = []
            for note in notes:
                # Truncate content for preview
                content_preview = note.content[:500] if note.content else ""
                if len(note.content or "") > 500:
                    content_preview += "..."

                results.append({
                    "title": note.title,
                    "content_preview": content_preview,
                    "updated_at": note.updated_at.isoformat() if note.updated_at else None,
                    "created_at": note.created_at.isoformat() if note.created_at else None
                })

            return json.dumps({
                "query": query,
                "results": results,
                "total_found": len(results),
                "note": "Read-only access - notes cannot be modified"
            }, indent=2)

        except Exception as e:
            logger.error(f"Read notes failed: {e}")
            return json.dumps({
                "error": f"Failed to search notes: {str(e)}",
                "query": query,
                "results": []
            })

    async def _read_calendar(self, days_ahead: int = 7, days_behind: int = 0) -> str:
        """
        Read calendar events (READ-ONLY).

        Returns upcoming and recent events within the specified range.
        """
        try:
            from ..main_simple import CalendarEvent
            from ..core.timezone import now as local_now

            now = local_now()
            start_date = now - timedelta(days=days_behind)
            end_date = now + timedelta(days=days_ahead)

            events = self.db.query(CalendarEvent).filter(
                CalendarEvent.user_id == self.user_id,
                CalendarEvent.start_time >= start_date,
                CalendarEvent.start_time <= end_date
            ).order_by(CalendarEvent.start_time).all()

            results = []
            for event in events:
                results.append({
                    "title": event.title,
                    "description": event.description[:200] if event.description else None,
                    "start_time": event.start_time.isoformat() if event.start_time else None,
                    "end_time": event.end_time.isoformat() if event.end_time else None,
                    "location": event.location,
                    "is_all_day": event.is_all_day
                })

            return json.dumps({
                "range": f"{days_behind} days ago to {days_ahead} days ahead",
                "events": results,
                "total_events": len(results),
                "note": "Read-only access - events cannot be modified"
            }, indent=2)

        except Exception as e:
            logger.error(f"Read calendar failed: {e}")
            return json.dumps({
                "error": f"Failed to read calendar: {str(e)}",
                "events": []
            })

    async def _read_memories(self, query: str, limit: int = 10) -> str:
        """
        Search episodic memories (READ-ONLY).

        Returns relevant memories based on semantic search.
        """
        try:
            from ..main_simple import MemoryEmbedding
            from sqlalchemy import desc

            # Simple keyword search for now (could enhance with vector search)
            memories = self.db.query(MemoryEmbedding).filter(
                MemoryEmbedding.user_id == self.user_id,
                MemoryEmbedding.content.ilike(f"%{query}%")
            ).order_by(desc(MemoryEmbedding.importance)).limit(limit).all()

            results = []
            for mem in memories:
                # Truncate content for preview
                content_preview = mem.content[:400] if mem.content else ""
                if len(mem.content or "") > 400:
                    content_preview += "..."

                results.append({
                    "content": content_preview,
                    "importance": mem.importance,
                    "created_at": mem.created_at.isoformat() if mem.created_at else None,
                    "category": mem.category
                })

            return json.dumps({
                "query": query,
                "memories": results,
                "total_found": len(results),
                "note": "Read-only access - memories cannot be modified"
            }, indent=2)

        except Exception as e:
            logger.error(f"Read memories failed: {e}")
            return json.dumps({
                "error": f"Failed to search memories: {str(e)}",
                "query": query,
                "memories": []
            })


# Tool definitions for worker agents
WORKER_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for information on a topic. Returns real search results with titles, snippets, and URLs from major search engines.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query"
                    },
                    "num_results": {
                        "type": "integer",
                        "description": "Number of results to return (default 5, max 10)"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_url",
            "description": "Fetch and read the content of a specific URL. Returns the main text content of the page, useful for getting detailed information from search results.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The URL to fetch and read"
                    }
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "take_notes",
            "description": "Save important findings to the agent workspace. Use this to record key information you've discovered during research.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "A short title for this note"
                    },
                    "content": {
                        "type": "string",
                        "description": "The content/findings to save"
                    }
                },
                "required": ["title", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_notes",
            "description": "Search the user's existing notes for relevant information. READ-ONLY - you cannot modify notes, only read them.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query to find relevant notes"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of notes to return (default 5)"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_calendar",
            "description": "Read the user's calendar events. READ-ONLY - returns upcoming and recent events within a date range.",
            "parameters": {
                "type": "object",
                "properties": {
                    "days_ahead": {
                        "type": "integer",
                        "description": "Number of days ahead to look (default 7)"
                    },
                    "days_behind": {
                        "type": "integer",
                        "description": "Number of days behind to look (default 0)"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_memories",
            "description": "Search the user's episodic memories for relevant past experiences and information. READ-ONLY - returns memories matching your query.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query to find relevant memories"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of memories to return (default 10)"
                    }
                },
                "required": ["query"]
            }
        }
    }
]

# Updated worker system prompt
WORKER_SYSTEM_PROMPT = """You are a research worker agent. Your job is to thoroughly research the given topic using the tools available to you.

Available tools:
- web_search: Search the web for real, up-to-date information
- read_url: Read the full content of a specific webpage
- take_notes: Save important findings to the workspace
- read_notes: Search the user's existing notes (READ-ONLY)
- read_calendar: View the user's calendar events (READ-ONLY)
- read_memories: Search the user's past memories (READ-ONLY)

IMPORTANT PERMISSIONS:
- You have READ-ONLY access to the user's notes, calendar, and memories
- You can ONLY write to the agent workspace via take_notes
- You CANNOT modify any existing user data
- If you find information that should be acted upon, include it in your final report as a RECOMMENDATION

Strategy:
1. Start by searching for relevant information on the topic
2. Read promising URLs to get detailed information
3. Check the user's notes/memories if the topic might relate to their existing data
4. Take notes on key findings as you go
5. Continue searching and reading until you have comprehensive information
6. When done, provide a final summary with clear recommendations

Be thorough but efficient. Use multiple searches if needed to cover different aspects of the topic."""
