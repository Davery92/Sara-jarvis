from typing import Dict, Any, List
from app.tools.base import BaseTool, ToolResult
from app.services.memory_service import MemoryService
from app.db.session import get_db
from sqlalchemy.orm import Session


class MemorySearchTool(BaseTool):
    """Tool for searching personal memory across notes, documents, episodes, and summaries"""
    
    @property
    def name(self) -> str:
        return "memory_search"
    
    @property
    def description(self) -> str:
        return "Search personal memory across notes, document chunks, episodes, and semantic summaries. Use this to find relevant information from the user's knowledge base."
    
    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query to find relevant memories"
                },
                "scopes": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["notes", "docs", "episodes", "summaries"]
                    },
                    "description": "Which types of memory to search. Defaults to all types.",
                    "default": ["notes", "docs", "episodes", "summaries"]
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default: 6)",
                    "default": 6
                }
            },
            "required": ["query"]
        }
    
    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Execute memory search"""
        
        query = kwargs.get("query")
        scopes = kwargs.get("scopes", ["notes", "docs", "episodes", "summaries"])
        limit = kwargs.get("limit", 6)
        
        if not query:
            return ToolResult(
                success=False,
                message="Query is required for memory search"
            )
        
        # Get database session
        db_gen = get_db()
        db: Session = next(db_gen)
        
        try:
            memory_service = MemoryService(db)
            results = await memory_service.search_memory(
                user_id=user_id,
                query=query,
                scopes=scopes,
                limit=limit
            )
            
            # Format results for the LLM
            formatted_results = []
            citations = []
            
            for result in results:
                if result["type"] == "episode":
                    formatted_results.append({
                        "type": "episode",
                        "content": result["text"],
                        "source": result["source"],
                        "role": result["role"],
                        "created_at": result["created_at"],
                        "score": round(result["score"], 3)
                    })
                    citations.append(f"mem:{result['episode_id']}")
                    
                elif result["type"] == "summary":
                    formatted_results.append({
                        "type": "summary",
                        "content": result["text"],
                        "scope": result["scope"],
                        "created_at": result["created_at"],
                        "score": round(result["score"], 3)
                    })
                    citations.append(f"sem:{result['summary_id']}")
                    
                elif result["type"] == "note":
                    formatted_results.append({
                        "type": "note",
                        "title": result["title"],
                        "content": result["text"],
                        "created_at": result["created_at"],
                        "score": round(result["score"], 3)
                    })
                    citations.append(f"note:{result['note_id']}")
                    
                elif result["type"] == "document":
                    formatted_results.append({
                        "type": "document",
                        "title": result["doc_title"],
                        "content": result["text"],
                        "breadcrumb": result["breadcrumb"],
                        "created_at": result["created_at"],
                        "score": round(result["score"], 3)
                    })
                    citations.append(f"doc:{result['doc_id']}#{result['chunk_idx']}")
            
            return ToolResult(
                success=True,
                data={
                    "results": formatted_results,
                    "query": query,
                    "scopes": scopes,
                    "total_found": len(formatted_results)
                },
                message=f"Found {len(formatted_results)} relevant memories",
                citations=citations
            )
            
        except Exception as e:
            return ToolResult(
                success=False,
                message=f"Memory search failed: {str(e)}"
            )
        finally:
            db.close()