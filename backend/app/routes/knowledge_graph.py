"""Knowledge graph routes for Neo4j-backed knowledge graph with PostgreSQL fallback."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text, and_, func

from app.db.session import get_db, SessionLocal
from app.core.deps import get_current_user
from app.core.timezone import format_iso_utc
from app.models.user import User
from app.models.episode import Episode

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/knowledge-graph/health")
async def knowledge_graph_health():
    """Check Neo4j connection health"""
    try:
        from app.services.neo4j_service import neo4j_service
        logger.info(f"Neo4j driver status: {neo4j_service.driver}")
        if not neo4j_service.driver:
            logger.info("Attempting to connect to Neo4j...")
            await neo4j_service.connect()
            logger.info(f"After connect, driver status: {neo4j_service.driver}")
        await neo4j_service.verify_connection()
        return {
            "status": "healthy",
            "neo4j_connected": True,
            "message": "Knowledge graph is operational"
        }
    except Exception as e:
        logger.error(f"Neo4j health check failed: {e}")
        return {
            "status": "unhealthy",
            "neo4j_connected": False,
            "error": str(e),
            "message": "Knowledge graph connection failed"
        }


@router.get("/knowledge-graph/")
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

        nodes = graph_data.get("nodes", [])
        relationships = graph_data.get("relationships", [])

        if not nodes:
            logger.info("Neo4j graph is empty, falling back to PostgreSQL episode data")
            from sqlalchemy import select, and_, func

            db = SessionLocal()
            try:
                episodes = db.query(Episode).filter(
                    and_(
                        Episode.user_id == current_user.id,
                        func.length(Episode.content) > 50
                    )
                ).order_by(Episode.created_at.desc()).limit(20).all()

                fallback_nodes = []
                for episode in episodes:
                    fallback_nodes.append({
                        "id": f"episode_{episode.id}",
                        "labels": ["Episode"],
                        "properties": {
                            "id": episode.id,
                            "title": f"{episode.role}: {episode.content[:50]}..." if len(episode.content) > 50 else episode.content,
                            "content": episode.content,
                            "type": "episode",
                            "role": episode.role,
                            "source": episode.source,
                            "importance": episode.importance or 0.5,
                            "created_at": format_iso_utc(episode.created_at),
                            "group": 1 if episode.role == "user" else 2
                        }
                    })

                nodes = fallback_nodes
                logger.info(f"Generated {len(nodes)} fallback nodes from episodes")
            finally:
                db.close()

        return {
            "nodes": nodes,
            "relationships": relationships,
            "total_nodes": len(nodes),
            "total_relationships": len(relationships)
        }

    except Exception as e:
        logger.error(f"Failed to get knowledge graph: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve knowledge graph: {str(e)}")


@router.post("/knowledge-graph/search")
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

        formatted_results = []
        for item in search_results:
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


@router.post("/knowledge-graph/connection-details")
async def get_connection_details(
    request: dict,
    current_user: User = Depends(get_current_user)
):
    """Get detailed information about a specific connection"""
    try:
        from app.services.neo4j_service import neo4j_service
        source_id = request.get("source_id")
        target_id = request.get("target_id")

        if not source_id or not target_id:
            raise HTTPException(status_code=400, detail="Both source_id and target_id are required")

        connection_details = await neo4j_service.get_connection_details(
            source_id=source_id,
            target_id=target_id,
            user_id=current_user.id
        )

        return connection_details

    except Exception as e:
        logger.error(f"Failed to get connection details: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get connection details: {str(e)}")


@router.post("/knowledge-graph/connected-content")
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
