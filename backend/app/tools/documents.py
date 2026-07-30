from typing import Dict, Any
import logging

from app.tools.base import BaseTool, ToolResult
from app.models.doc import Document
from app.models.document_chunk import DocumentChunk
from app.services.embedding_service import embedding_service
from app.db.session import get_db
from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)


class DocumentsSearchTool(BaseTool):
    """Search through the user's uploaded documents (semantic + text match).

    Ported from main_simple.py's search_documents_tool (work-order item 5,
    2026-07-30) — that method was never reachable from chat: it lived behind
    an `elif function_name == "search_documents"` branch in execute_tool, but
    the tools list handed to the model is built exclusively from
    tool_registry, which never emitted that schema name. Document search was
    a real capability gap, not just a naming mismatch.
    """

    @property
    def name(self) -> str:
        return "documents_search"

    @property
    def description(self) -> str:
        return "Search through the user's uploaded documents using semantic similarity and text matching."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query for finding relevant document content"
                }
            },
            "required": ["query"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        query = kwargs.get("query")
        if not query:
            return ToolResult(success=False, message="Search query is required")

        # Try Neo4j knowledge graph first for enhanced document discovery.
        try:
            from app.services.neo4j_service import neo4j_service
            if neo4j_service.driver:
                graph_results = await neo4j_service.search_knowledge_graph(
                    user_id=user_id, query=query, content_types=["Document"], limit=5
                )
                if graph_results:
                    citations = []
                    lines = []
                    for node in graph_results:
                        title = node.get("title", "Unknown Document")
                        content = (node.get("content_text") or "")[:300]
                        lines.append(f"From {title}: {content}...")
                        citations.append(f"doc:{node.get('id', title)}")
                    return ToolResult(
                        success=True,
                        message=f"Found {len(lines)} relevant results about '{query}' in your documents.\n\n" + "\n\n".join(lines),
                        citations=citations,
                    )
        except Exception as e:
            logger.warning(f"Neo4j document search failed, falling back to pgvector: {e}")

        db_gen = get_db()
        db: Session = next(db_gen)
        try:
            documents = db.query(Document).filter(
                Document.user_id == user_id,
                Document.is_processed == "true"
            ).all()
            if not documents:
                return ToolResult(success=True, message="No documents found. Upload some documents first.")

            semantic_results = []
            query_embedding = await embedding_service.generate_embedding(query)
            if query_embedding:
                try:
                    similarity_query = text("""
                        SELECT dc.chunk_text, d.original_filename,
                               (dc.embedding <=> CAST(:query_embedding AS vector)) as distance
                        FROM document_chunk dc
                        JOIN document d ON dc.document_id = d.id
                        WHERE dc.user_id = :user_id
                          AND dc.embedding IS NOT NULL
                          AND d.is_processed = 'true'
                        ORDER BY dc.embedding <=> CAST(:query_embedding AS vector)
                        LIMIT 8
                    """)
                    rows = db.execute(similarity_query, {
                        "query_embedding": str(query_embedding),
                        "user_id": user_id
                    })
                    for row in rows:
                        similarity = 1 - row.distance
                        if similarity > 0.3:
                            semantic_results.append({
                                "chunk_text": row.chunk_text,
                                "filename": row.original_filename,
                                "similarity": similarity,
                            })
                except Exception as e:
                    logger.warning(f"pgvector document search failed, using text search only: {e}")

            text_results = []
            for doc in documents:
                if doc.content_text and query.lower() in doc.content_text.lower():
                    content_lower = doc.content_text.lower()
                    start_idx = content_lower.find(query.lower())
                    context_start = max(0, start_idx - 150)
                    context_end = min(len(doc.content_text), start_idx + len(query) + 150)
                    excerpt = doc.content_text[context_start:context_end].strip()
                    if context_start > 0:
                        excerpt = "..." + excerpt
                    if context_end < len(doc.content_text):
                        excerpt = excerpt + "..."
                    text_results.append({"chunk_text": excerpt, "filename": doc.original_filename, "similarity": 0.95})

                chunks = db.query(DocumentChunk).filter(
                    DocumentChunk.document_id == doc.id,
                    DocumentChunk.chunk_text.ilike(f"%{query}%")
                ).limit(3).all()
                for chunk in chunks:
                    text_results.append({"chunk_text": chunk.chunk_text, "filename": doc.original_filename, "similarity": 0.8})

            seen_content = set()
            unique_results = []
            for result in semantic_results + text_results:
                key = (result["filename"], result["chunk_text"][:100])
                if key not in seen_content:
                    seen_content.add(key)
                    unique_results.append(result)
            unique_results.sort(key=lambda r: r["similarity"], reverse=True)

            if not unique_results:
                return ToolResult(
                    success=True,
                    message=f"No results found for '{query}' in your documents. Try different search terms or upload more documents."
                )

            response_parts = [f"Found {len(unique_results)} relevant results about '{query}' in your documents.", ""]
            seen_docs = set()
            citations = []
            for result in unique_results[:3]:
                if result["filename"] in seen_docs:
                    continue
                seen_docs.add(result["filename"])
                content = result["chunk_text"].strip()
                if len(content) > 200:
                    content = content[:200] + "..."
                response_parts.append(f"From {result['filename']}: {content}")
                response_parts.append("")
                citations.append(f"doc:{result['filename']}")

            return ToolResult(success=True, message="\n".join(response_parts), citations=citations)
        finally:
            db.close()
