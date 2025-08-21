"""
Knowledge Graph API routes
Provides graph-native endpoints for Sara's knowledge graph operations using Neo4j.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from app.core.deps import get_current_user
from app.models.user import User
from app.services.neo4j_service import neo4j_service
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/knowledge-graph", tags=["knowledge-graph"])

# Pydantic models for request/response
class GraphNode(BaseModel):
    id: str
    labels: List[str]
    properties: Dict[str, Any]

class GraphRelationship(BaseModel):
    source: str
    target: str
    type: str
    properties: Dict[str, Any]

class KnowledgeGraphResponse(BaseModel):
    nodes: List[GraphNode]
    relationships: List[GraphRelationship]
    total_nodes: int
    total_relationships: int

class SearchRequest(BaseModel):
    query: str
    content_types: Optional[List[str]] = None
    limit: int = 20
    # Metadata filters
    entity_types: Optional[List[str]] = None
    topic_types: Optional[List[str]] = None
    tag_categories: Optional[List[str]] = None
    min_importance: Optional[float] = None
    max_importance: Optional[float] = None
    min_urgency: Optional[float] = None
    max_urgency: Optional[float] = None
    min_confidence: Optional[float] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None

class ConnectedContentRequest(BaseModel):
    node_id: str
    depth: int = 2
    relationship_types: Optional[List[str]] = None

class CreateConnectionRequest(BaseModel):
    source_id: str
    target_id: str
    connection_type: str = "SEMANTIC_SIMILAR"
    strength: float = 0.5

@router.get("/", response_model=KnowledgeGraphResponse)
async def get_user_knowledge_graph(
    depth: int = Query(2, description="Graph traversal depth", ge=1, le=5),
    current_user: User = Depends(get_current_user)
):
    """Get the complete knowledge graph for the current user"""
    try:
        graph_data = await neo4j_service.get_user_knowledge_graph(
            user_id=current_user.id,
            depth=depth
        )
        
        nodes = [
            GraphNode(
                id=node["id"],
                labels=node["labels"],
                properties=node["properties"]
            )
            for node in graph_data.get("nodes", [])
        ]
        
        relationships = [
            GraphRelationship(
                source=rel["source"],
                target=rel["target"],
                type=rel["type"],
                properties=rel["properties"]
            )
            for rel in graph_data.get("relationships", [])
        ]
        
        return KnowledgeGraphResponse(
            nodes=nodes,
            relationships=relationships,
            total_nodes=len(nodes),
            total_relationships=len(relationships)
        )
        
    except Exception as e:
        logger.error(f"Failed to get knowledge graph: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve knowledge graph: {str(e)}")

@router.post("/search")
async def search_knowledge_graph(
    request: SearchRequest,
    current_user: User = Depends(get_current_user)
):
    """Search across all content types in the knowledge graph"""
    try:
        search_results = await neo4j_service.search_knowledge_graph(
            user_id=current_user.id,
            query=request.query,
            content_types=request.content_types,
            limit=request.limit,
            # Metadata filters
            entity_types=request.entity_types,
            topic_types=request.topic_types,
            tag_categories=request.tag_categories,
            min_importance=request.min_importance,
            max_importance=request.max_importance,
            min_urgency=request.min_urgency,
            max_urgency=request.max_urgency,
            min_confidence=request.min_confidence,
            date_from=request.date_from,
            date_to=request.date_to
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
            "query": request.query,
            "results": formatted_results,
            "total_found": len(formatted_results)
        }
        
    except Exception as e:
        logger.error(f"Knowledge graph search failed: {e}")
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")

@router.get("/filter-options")
async def get_filter_options(
    current_user: User = Depends(get_current_user)
):
    """Get available filter options for search"""
    try:
        filter_options = await neo4j_service.get_search_filter_options(str(current_user.id))
        return {
            "entity_types": filter_options.get("entity_types", []),
            "topic_types": filter_options.get("topic_types", []),
            "tag_categories": filter_options.get("tag_categories", []),
            "content_types": filter_options.get("content_types", []),
            "date_range": filter_options.get("date_range", {}),
            "importance_range": filter_options.get("importance_range", {}),
            "urgency_range": filter_options.get("urgency_range", {}),
            "confidence_range": filter_options.get("confidence_range", {})
        }
    except Exception as e:
        logger.error(f"Failed to get filter options: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get filter options: {str(e)}")

@router.post("/connected-content")
async def get_connected_content(
    request: ConnectedContentRequest,
    current_user: User = Depends(get_current_user)
):
    """Find all content connected to a specific node"""
    try:
        connected_items = await neo4j_service.find_connected_content(
            node_id=request.node_id,
            user_id=current_user.id,
            depth=request.depth,
            relationship_types=request.relationship_types
        )
        
        # Format for frontend
        formatted_items = []
        for item in connected_items:
            # Determine content type from the item properties
            content_type = "unknown"
            if "title" in item and "content" in item:
                content_type = "note"
            elif "role" in item:
                content_type = "episode"
            elif "mime_type" in item:
                content_type = "document"
            
            formatted_items.append({
                "id": item.get("id"),
                "type": content_type,
                "title": item.get("title") or f"{item.get('role', '')}: {item.get('content', '')[:30]}...",
                "content": item.get("content") or item.get("content_text", ""),
                "distance": item.get("distance", 0),
                "created_at": item.get("created_at"),
                "metadata": {k: v for k, v in item.items() if k not in ["id", "content", "content_text", "title", "distance"]}
            })
        
        return {
            "source_node_id": request.node_id,
            "connected_content": formatted_items,
            "total_connections": len(formatted_items),
            "max_distance": max([item["distance"] for item in formatted_items], default=0)
        }
        
    except Exception as e:
        logger.error(f"Failed to get connected content: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get connected content: {str(e)}")

@router.get("/clusters")
async def get_knowledge_clusters(
    current_user: User = Depends(get_current_user)
):
    """Get knowledge clusters using community detection"""
    try:
        clusters = await neo4j_service.get_knowledge_clusters(current_user.id)
        
        # Format clusters for frontend
        formatted_clusters = []
        for cluster in clusters:
            formatted_clusters.append({
                "cluster_id": cluster["community_id"],
                "size": cluster["size"],
                "members": [
                    {
                        "id": member.get("id"),
                        "title": member.get("title", "Untitled"),
                        "type": member.get("type", "unknown").lower()
                    }
                    for member in cluster["members"]
                ]
            })
        
        return {
            "clusters": formatted_clusters,
            "total_clusters": len(formatted_clusters),
            "largest_cluster_size": max([c["size"] for c in formatted_clusters], default=0)
        }
        
    except Exception as e:
        logger.error(f"Failed to get knowledge clusters: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get knowledge clusters: {str(e)}")

@router.post("/connections")
async def create_connection(
    request: CreateConnectionRequest,
    current_user: User = Depends(get_current_user)
):
    """Create a manual connection between two nodes"""
    try:
        success = False
        
        if request.connection_type == "REFERENCES":
            success = await neo4j_service.create_reference_link(
                source_id=request.source_id,
                target_id=request.target_id,
                link_type="REFERENCES"
            )
        else:
            success = await neo4j_service.create_semantic_connection(
                node1_id=request.source_id,
                node2_id=request.target_id,
                similarity=request.strength,
                connection_type=request.connection_type
            )
        
        if success:
            return {
                "success": True,
                "message": f"Connection created between {request.source_id} and {request.target_id}",
                "connection_type": request.connection_type,
                "strength": request.strength
            }
        else:
            raise HTTPException(status_code=400, detail="Failed to create connection")
            
    except Exception as e:
        logger.error(f"Failed to create connection: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create connection: {str(e)}")

@router.get("/stats")
async def get_graph_statistics(
    current_user: User = Depends(get_current_user)
):
    """Get knowledge graph statistics for the user"""
    try:
        # Get basic graph structure
        graph_data = await neo4j_service.get_user_knowledge_graph(current_user.id, depth=1)
        
        # Count nodes by type
        node_counts = {}
        for node in graph_data.get("nodes", []):
            for label in node.get("labels", []):
                node_counts[label] = node_counts.get(label, 0) + 1
        
        # Count relationships by type
        relationship_counts = {}
        for rel in graph_data.get("relationships", []):
            rel_type = rel.get("type", "UNKNOWN")
            relationship_counts[rel_type] = relationship_counts.get(rel_type, 0) + 1
        
        return {
            "total_nodes": len(graph_data.get("nodes", [])),
            "total_relationships": len(graph_data.get("relationships", [])),
            "node_counts": node_counts,
            "relationship_counts": relationship_counts,
            "graph_density": len(graph_data.get("relationships", [])) / max(len(graph_data.get("nodes", [])), 1)
        }
        
    except Exception as e:
        logger.error(f"Failed to get graph statistics: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get graph statistics: {str(e)}")

@router.get("/path")
async def find_connection_path(
    source_id: str = Query(..., description="Source node ID"),
    target_id: str = Query(..., description="Target node ID"),
    max_depth: int = Query(5, description="Maximum path depth", ge=1, le=10),
    current_user: User = Depends(get_current_user)
):
    """Find the shortest path between two nodes in the knowledge graph"""
    try:
        # This would require a custom Neo4j query for pathfinding
        # For now, return a placeholder implementation
        return {
            "source_id": source_id,
            "target_id": target_id,
            "path": [],
            "path_length": 0,
            "message": "Pathfinding implementation pending - requires custom Cypher query"
        }
        
    except Exception as e:
        logger.error(f"Failed to find connection path: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to find connection path: {str(e)}")

# Health check endpoint
@router.get("/health")
async def knowledge_graph_health():
    """Check Neo4j connection health"""
    try:
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