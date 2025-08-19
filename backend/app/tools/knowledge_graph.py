"""
Knowledge Graph Tools for Sara
Advanced graph intelligence tools that give Sara deep knowledge graph capabilities.
"""
from typing import Dict, Any, List, Optional
from app.tools.base import BaseTool, ToolResult
from app.services.neo4j_service import neo4j_service
import logging

logger = logging.getLogger(__name__)

class KnowledgeGraphSearchTool(BaseTool):
    """Tool for Sara to search across the entire knowledge graph"""
    
    @property
    def name(self) -> str:
        return "knowledge_graph_search"
    
    @property
    def description(self) -> str:
        return """🧠 Search across ALL of your knowledge - notes, conversations, and documents - using advanced graph intelligence. 
        This tool can find content by topic, discover related items, and show connections between different types of content."""
    
    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string", 
                    "description": "Search query to find relevant content across all types"
                },
                "content_types": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["Note", "Episode", "Document"]},
                    "description": "Optional filter for specific content types (default: all types)"
                },
                "include_connections": {
                    "type": "boolean",
                    "description": "Whether to include connected content in results (default: true)",
                    "default": True
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default: 15)",
                    "default": 15
                }
            },
            "required": ["query"]
        }
    
    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Execute knowledge graph search"""
        query = kwargs.get("query")
        content_types = kwargs.get("content_types")
        include_connections = kwargs.get("include_connections", True)
        limit = kwargs.get("limit", 15)
        
        if not query:
            return ToolResult(
                success=False,
                message="Search query is required"
            )
        
        try:
            # Search the knowledge graph
            search_results = await neo4j_service.search_knowledge_graph(
                user_id=user_id,
                query=query,
                content_types=content_types,
                limit=limit
            )
            
            if not search_results:
                return ToolResult(
                    success=True,
                    message=f"🔍 No content found matching '{query}'. Try different keywords or check your knowledge base.",
                    data={"results": [], "query": query}
                )
            
            # Format results with rich context
            formatted_results = []
            connection_info = []
            
            for item in search_results:
                content_type = self._determine_content_type(item)
                
                # Get basic item info
                item_info = {
                    "id": item.get("id"),
                    "type": content_type,
                    "title": self._get_display_title(item),
                    "content_preview": self._get_content_preview(item),
                    "created_at": item.get("created_at"),
                    "relevance": "high" if query.lower() in self._get_display_title(item).lower() else "medium"
                }
                
                # Get connections if requested
                if include_connections:
                    try:
                        connections = await neo4j_service.find_connected_content(
                            node_id=item.get("id"),
                            user_id=user_id,
                            depth=1
                        )
                        
                        if connections:
                            item_info["connected_items"] = len(connections)
                            connection_info.extend([
                                f"📎 {self._get_display_title(conn)} ({self._determine_content_type(conn)})"
                                for conn in connections[:3]  # Show top 3 connections
                            ])
                    except Exception as e:
                        logger.warning(f"Failed to get connections for {item.get('id')}: {e}")
                
                formatted_results.append(item_info)
            
            # Create comprehensive response
            result_summary = self._create_search_summary(formatted_results, query, connection_info)
            
            return ToolResult(
                success=True,
                message=result_summary,
                data={
                    "query": query,
                    "results": formatted_results,
                    "total_found": len(formatted_results),
                    "has_connections": include_connections,
                    "search_scope": content_types or ["all_types"]
                }
            )
            
        except Exception as e:
            logger.error(f"Knowledge graph search failed: {e}")
            return ToolResult(
                success=False,
                message=f"🚨 Knowledge graph search encountered an error: {str(e)}"
            )
    
    def _determine_content_type(self, item: Dict) -> str:
        """Determine the content type from node properties"""
        if "title" in item and "content" in item and "role" not in item:
            return "note"
        elif "role" in item:
            return "episode"
        elif "mime_type" in item:
            return "document"
        return "unknown"
    
    def _get_display_title(self, item: Dict) -> str:
        """Get appropriate display title for any content type"""
        if item.get("title"):
            return item["title"]
        elif item.get("role"):
            content_preview = (item.get("content", "") or "")[:40]
            return f"{item['role']}: {content_preview}..."
        elif item.get("content"):
            return item["content"][:50] + "..."
        return "Untitled"
    
    def _get_content_preview(self, item: Dict) -> str:
        """Get content preview for any content type"""
        content = item.get("content") or item.get("content_text", "")
        return content[:150] + "..." if len(content) > 150 else content
    
    def _create_search_summary(self, results: List[Dict], query: str, connections: List[str]) -> str:
        """Create a comprehensive search summary"""
        if not results:
            return f"🔍 No results found for '{query}'"
        
        # Count by type
        type_counts = {}
        for result in results:
            content_type = result["type"]
            type_counts[content_type] = type_counts.get(content_type, 0) + 1
        
        # Build summary
        summary_parts = [f"🎯 Found {len(results)} items matching '{query}':"]
        
        # Add type breakdown
        type_breakdown = []
        if type_counts.get("note", 0) > 0:
            type_breakdown.append(f"📝 {type_counts['note']} notes")
        if type_counts.get("episode", 0) > 0:
            type_breakdown.append(f"💭 {type_counts['episode']} conversations")
        if type_counts.get("document", 0) > 0:
            type_breakdown.append(f"📄 {type_counts['document']} documents")
        
        if type_breakdown:
            summary_parts.append("Content types: " + ", ".join(type_breakdown))
        
        # Add top results
        top_results = results[:3]
        summary_parts.append("\n🏆 Top results:")
        for i, result in enumerate(top_results, 1):
            icon = {"note": "📝", "episode": "💭", "document": "📄"}.get(result["type"], "📎")
            summary_parts.append(f"{i}. {icon} {result['title']}")
        
        # Add connection info
        if connections:
            summary_parts.append(f"\n🔗 Related connections found: {len(connections)} items")
        
        return "\n".join(summary_parts)


class ConnectionFinderTool(BaseTool):
    """Tool for Sara to find what's connected to specific content"""
    
    @property
    def name(self) -> str:
        return "find_connections"
    
    @property 
    def description(self) -> str:
        return """🔗 Discover what content is connected to a specific note, conversation, or document. 
        Shows direct and indirect relationships, helping understand how ideas are linked in your knowledge."""
    
    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "content_id": {
                    "type": "string",
                    "description": "ID of the content to find connections for"
                },
                "depth": {
                    "type": "integer",
                    "description": "How many degrees of connection to explore (1=direct, 2=friends of friends, etc.)",
                    "default": 2,
                    "minimum": 1,
                    "maximum": 4
                },
                "connection_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional filter for specific relationship types (REFERENCES, SEMANTIC_SIMILAR, etc.)"
                }
            },
            "required": ["content_id"]
        }
    
    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Find connected content"""
        content_id = kwargs.get("content_id")
        depth = kwargs.get("depth", 2)
        connection_types = kwargs.get("connection_types")
        
        if not content_id:
            return ToolResult(
                success=False,
                message="Content ID is required to find connections"
            )
        
        try:
            # Find connected content
            connected_items = await neo4j_service.find_connected_content(
                node_id=content_id,
                user_id=user_id,
                depth=depth,
                relationship_types=connection_types
            )
            
            if not connected_items:
                return ToolResult(
                    success=True,
                    message=f"🔍 No connections found for the specified content within {depth} degrees of separation.",
                    data={"content_id": content_id, "connections": []}
                )
            
            # Organize by distance and type
            connections_by_distance = {}
            type_counts = {}
            
            for item in connected_items:
                distance = item.get("distance", 0)
                content_type = self._determine_content_type(item)
                
                if distance not in connections_by_distance:
                    connections_by_distance[distance] = []
                
                connections_by_distance[distance].append({
                    "id": item.get("id"),
                    "type": content_type,
                    "title": self._get_display_title(item),
                    "content_preview": self._get_content_preview(item),
                    "distance": distance
                })
                
                type_counts[content_type] = type_counts.get(content_type, 0) + 1
            
            # Create summary
            summary = self._create_connection_summary(connections_by_distance, type_counts, content_id)
            
            return ToolResult(
                success=True,
                message=summary,
                data={
                    "source_content_id": content_id,
                    "connections_by_distance": connections_by_distance,
                    "total_connections": len(connected_items),
                    "type_counts": type_counts,
                    "max_distance": max(connections_by_distance.keys()) if connections_by_distance else 0
                }
            )
            
        except Exception as e:
            logger.error(f"Connection finding failed: {e}")
            return ToolResult(
                success=False,
                message=f"🚨 Failed to find connections: {str(e)}"
            )
    
    def _determine_content_type(self, item: Dict) -> str:
        """Determine content type from item properties"""
        if "title" in item and "content" in item and "role" not in item:
            return "note"
        elif "role" in item:
            return "episode"
        elif "mime_type" in item:
            return "document"
        return "unknown"
    
    def _get_display_title(self, item: Dict) -> str:
        """Get display title for any content type"""
        if item.get("title"):
            return item["title"]
        elif item.get("role"):
            content_preview = (item.get("content", "") or "")[:30]
            return f"{item['role']}: {content_preview}..."
        elif item.get("content"):
            return item["content"][:40] + "..."
        return "Untitled"
    
    def _get_content_preview(self, item: Dict) -> str:
        """Get content preview"""
        content = item.get("content") or item.get("content_text", "")
        return content[:100] + "..." if len(content) > 100 else content
    
    def _create_connection_summary(self, connections_by_distance: Dict, type_counts: Dict, content_id: str) -> str:
        """Create connection summary"""
        total_connections = sum(len(items) for items in connections_by_distance.values())
        
        summary_parts = [f"🔗 Found {total_connections} connected items:"]
        
        # Type breakdown
        type_breakdown = []
        for content_type, count in type_counts.items():
            icon = {"note": "📝", "episode": "💭", "document": "📄"}.get(content_type, "📎")
            type_breakdown.append(f"{icon} {count} {content_type}s")
        
        if type_breakdown:
            summary_parts.append("Types: " + ", ".join(type_breakdown))
        
        # Show by distance
        for distance in sorted(connections_by_distance.keys()):
            items = connections_by_distance[distance]
            if distance == 1:
                summary_parts.append(f"\n🔗 Direct connections ({len(items)}):")
            else:
                summary_parts.append(f"\n🔗 {distance} degrees away ({len(items)}):")
            
            # Show top 3 items at this distance
            for item in items[:3]:
                icon = {"note": "📝", "episode": "💭", "document": "📄"}.get(item["type"], "📎")
                summary_parts.append(f"  {icon} {item['title']}")
            
            if len(items) > 3:
                summary_parts.append(f"  ... and {len(items) - 3} more")
        
        return "\n".join(summary_parts)


class KnowledgeClusterTool(BaseTool):
    """Tool for Sara to discover knowledge clusters and communities"""
    
    @property
    def name(self) -> str:
        return "discover_knowledge_clusters"
    
    @property
    def description(self) -> str:
        return """🧩 Discover knowledge clusters and communities in your content using advanced graph algorithms.
        Finds groups of related content and identifies knowledge themes."""
    
    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "min_cluster_size": {
                    "type": "integer",
                    "description": "Minimum size for clusters to report (default: 3)",
                    "default": 3
                }
            }
        }
    
    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Discover knowledge clusters"""
        min_cluster_size = kwargs.get("min_cluster_size", 3)
        
        try:
            clusters = await neo4j_service.get_knowledge_clusters(user_id)
            
            if not clusters:
                return ToolResult(
                    success=True,
                    message="🧩 No distinct knowledge clusters found. Your content may be well-connected as a unified knowledge base.",
                    data={"clusters": []}
                )
            
            # Filter by minimum size
            significant_clusters = [c for c in clusters if c["size"] >= min_cluster_size]
            
            if not significant_clusters:
                return ToolResult(
                    success=True,
                    message=f"🧩 Found {len(clusters)} small clusters, but none meet the minimum size of {min_cluster_size} items.",
                    data={"clusters": clusters}
                )
            
            # Create summary
            summary = self._create_cluster_summary(significant_clusters)
            
            return ToolResult(
                success=True,
                message=summary,
                data={
                    "clusters": significant_clusters,
                    "total_clusters": len(significant_clusters),
                    "largest_cluster_size": max(c["size"] for c in significant_clusters)
                }
            )
            
        except Exception as e:
            logger.error(f"Knowledge cluster discovery failed: {e}")
            return ToolResult(
                success=False,
                message=f"🚨 Failed to discover knowledge clusters: {str(e)}"
            )
    
    def _create_cluster_summary(self, clusters: List[Dict]) -> str:
        """Create cluster summary"""
        summary_parts = [f"🧩 Discovered {len(clusters)} knowledge clusters:"]
        
        # Sort by size (largest first)
        sorted_clusters = sorted(clusters, key=lambda c: c["size"], reverse=True)
        
        for i, cluster in enumerate(sorted_clusters[:5], 1):  # Show top 5 clusters
            cluster_id = cluster.get("cluster_id", f"cluster_{i}")
            size = cluster["size"]
            members = cluster.get("members", [])
            
            summary_parts.append(f"\n🏷️ Cluster {i} ({size} items):")
            
            # Show sample members
            for member in members[:3]:
                content_type = member.get("type", "unknown")
                icon = {"note": "📝", "episode": "💭", "document": "📄"}.get(content_type, "📎")
                title = member.get("title", "Untitled")
                summary_parts.append(f"  {icon} {title}")
            
            if len(members) > 3:
                summary_parts.append(f"  ... and {len(members) - 3} more items")
        
        if len(sorted_clusters) > 5:
            summary_parts.append(f"\n... and {len(sorted_clusters) - 5} more clusters")
        
        return "\n".join(summary_parts)


class KnowledgeGapAnalysisTool(BaseTool):
    """Tool for Sara to identify knowledge gaps and isolated content"""
    
    @property
    def name(self) -> str:
        return "analyze_knowledge_gaps"
    
    @property
    def description(self) -> str:
        return """🔍 Analyze your knowledge graph to identify gaps, isolated content, and potential connections.
        Helps discover orphaned content and suggests areas for knowledge expansion."""
    
    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "isolation_threshold": {
                    "type": "integer", 
                    "description": "Consider items with fewer than this many connections as isolated (default: 2)",
                    "default": 2
                }
            }
        }
    
    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Analyze knowledge gaps"""
        isolation_threshold = kwargs.get("isolation_threshold", 2)
        
        try:
            # Get full graph to analyze
            graph_data = await neo4j_service.get_user_knowledge_graph(user_id, depth=3)
            
            nodes = graph_data.get("nodes", [])
            relationships = graph_data.get("relationships", [])
            
            if not nodes:
                return ToolResult(
                    success=True,
                    message="📊 No content found to analyze. Start creating notes, having conversations, or uploading documents.",
                    data={"analysis": "no_content"}
                )
            
            # Analyze connectivity
            connection_counts = {}
            for node in nodes:
                node_id = node["properties"]["id"]
                connection_counts[node_id] = 0
            
            for rel in relationships:
                source = rel.get("source")
                target = rel.get("target")
                if source in connection_counts:
                    connection_counts[source] += 1
                if target in connection_counts:
                    connection_counts[target] += 1
            
            # Find isolated content
            isolated_items = []
            well_connected_items = []
            
            for node in nodes:
                node_id = node["properties"]["id"]
                connections = connection_counts.get(node_id, 0)
                
                item_info = {
                    "id": node_id,
                    "type": self._determine_node_type(node),
                    "title": self._get_node_title(node),
                    "connections": connections
                }
                
                if connections < isolation_threshold:
                    isolated_items.append(item_info)
                elif connections >= 5:
                    well_connected_items.append(item_info)
            
            # Create analysis summary
            summary = self._create_gap_analysis_summary(
                isolated_items, well_connected_items, len(nodes), len(relationships)
            )
            
            return ToolResult(
                success=True,
                message=summary,
                data={
                    "total_items": len(nodes),
                    "total_connections": len(relationships),
                    "isolated_items": isolated_items,
                    "well_connected_items": well_connected_items,
                    "isolation_threshold": isolation_threshold,
                    "connectivity_ratio": len(relationships) / len(nodes) if nodes else 0
                }
            )
            
        except Exception as e:
            logger.error(f"Knowledge gap analysis failed: {e}")
            return ToolResult(
                success=False,
                message=f"🚨 Knowledge gap analysis failed: {str(e)}"
            )
    
    def _determine_node_type(self, node: Dict) -> str:
        """Determine node type from labels"""
        labels = node.get("labels", [])
        if "Note" in labels:
            return "note"
        elif "Episode" in labels:
            return "episode"  
        elif "Document" in labels:
            return "document"
        return "unknown"
    
    def _get_node_title(self, node: Dict) -> str:
        """Get node title from properties"""
        props = node.get("properties", {})
        if props.get("title"):
            return props["title"]
        elif props.get("content"):
            return props["content"][:40] + "..."
        return "Untitled"
    
    def _create_gap_analysis_summary(self, isolated: List, well_connected: List, total_nodes: int, total_relationships: int) -> str:
        """Create gap analysis summary"""
        summary_parts = [f"📊 Knowledge Graph Analysis ({total_nodes} items, {total_relationships} connections):"]
        
        # Connectivity overview
        if total_nodes > 0:
            avg_connections = (total_relationships * 2) / total_nodes  # Each relationship connects 2 nodes
            summary_parts.append(f"📈 Average connections per item: {avg_connections:.1f}")
        
        # Isolated content
        if isolated:
            summary_parts.append(f"\n🏝️ Isolated content ({len(isolated)} items):")
            for item in isolated[:5]:
                icon = {"note": "📝", "episode": "💭", "document": "📄"}.get(item["type"], "📎")
                summary_parts.append(f"  {icon} {item['title']} ({item['connections']} connections)")
            
            if len(isolated) > 5:
                summary_parts.append(f"  ... and {len(isolated) - 5} more isolated items")
        else:
            summary_parts.append("\n✅ No isolated content found - everything is well connected!")
        
        # Well-connected hubs
        if well_connected:
            summary_parts.append(f"\n🌟 Knowledge hubs ({len(well_connected)} items):")
            sorted_hubs = sorted(well_connected, key=lambda x: x["connections"], reverse=True)
            for item in sorted_hubs[:3]:
                icon = {"note": "📝", "episode": "💭", "document": "📄"}.get(item["type"], "📎")
                summary_parts.append(f"  {icon} {item['title']} ({item['connections']} connections)")
        
        # Recommendations
        summary_parts.append("\n💡 Recommendations:")
        if isolated:
            summary_parts.append("• Consider linking isolated content to related topics")
        if len(well_connected) < 3:
            summary_parts.append("• Create more connections between your content")
        if total_relationships < total_nodes:
            summary_parts.append("• Your knowledge graph could benefit from more cross-references")
        
        return "\n".join(summary_parts)