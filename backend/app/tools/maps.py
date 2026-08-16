"""
Map Control Tools

Tools for Sara to create and control mindmaps/flowcharts on the workspace canvas.
These tools return workspace_command data that the workbench-canvas frontend
interprets to show, hide, and manipulate maps.
"""

from typing import Dict, Any, Optional, List
from app.tools.base import BaseTool, ToolResult
from app.models.map import Map
from app.db.session import get_db
from sqlalchemy.orm import Session
from sqlalchemy import select
import logging
import uuid
import json
import os

logger = logging.getLogger(__name__)


def _get_redis():
    """Get Redis client for map state tracking."""
    try:
        from app.core.redis import get_redis_sync
        return get_redis_sync()
    except Exception as e:
        logger.warning(f"Redis not available for map tracking: {e}")
        return None


def set_current_map(user_id: str, map_id: str, map_name: str):
    """Track the currently displayed map for this user."""
    try:
        r = _get_redis()
        if r:
            key = f"user:{user_id}:current_map"
            r.setex(key, 3600, json.dumps({  # 1 hour TTL
                "map_id": map_id,
                "map_name": map_name
            }))
            logger.info(f"📍 Set current map for user: {map_name}")
    except Exception as e:
        logger.error(f"Error setting current map: {e}")


def get_current_map(user_id: str) -> Optional[Dict[str, str]]:
    """Get the currently displayed map for this user."""
    try:
        r = _get_redis()
        if r:
            key = f"user:{user_id}:current_map"
            data = r.get(key)
            if data:
                return json.loads(data)
        return None
    except Exception as e:
        logger.error(f"Error getting current map: {e}")
        return None


def clear_current_map(user_id: str):
    """Clear the current map tracking."""
    try:
        r = _get_redis()
        if r:
            key = f"user:{user_id}:current_map"
            r.delete(key)
    except Exception as e:
        logger.error(f"Error clearing current map: {e}")


class MapCreateTool(BaseTool):
    """Tool for creating a new mindmap/flowchart"""

    @property
    def name(self) -> str:
        return "map_create"

    @property
    def description(self) -> str:
        return """Create a new mindmap or flowchart. You can optionally provide initial nodes and edges.
The map will be saved and can be shown on the workspace canvas."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name for the map"
                },
                "description": {
                    "type": "string",
                    "description": "Optional description of the map's purpose"
                },
                "nodes": {
                    "type": "array",
                    "description": "Optional initial nodes. Each node: {position: {x, y}, size: {width, height}, content: {type: 'text', data: {text: '...'}}}",
                    "items": {"type": "object"}
                },
                "edges": {
                    "type": "array",
                    "description": "Optional initial edges. Each edge: {source: 'node-id', target: 'node-id'}",
                    "items": {"type": "object"}
                },
                "show_on_canvas": {
                    "type": "boolean",
                    "description": "Whether to immediately show the map on the canvas (default: true)"
                }
            },
            "required": ["name"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        name = kwargs.get("name")
        description = kwargs.get("description")
        nodes = kwargs.get("nodes", [])
        edges = kwargs.get("edges", [])
        show_on_canvas = kwargs.get("show_on_canvas", True)

        if not name:
            return ToolResult(success=False, message="name is required")

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            # Process nodes - assign IDs if not provided
            processed_nodes = []
            node_id_map = {}  # Track original ID -> new ID mapping

            for i, node in enumerate(nodes):
                node_id = node.get("id") or str(uuid.uuid4())
                if "id" in node:
                    node_id_map[node["id"]] = node_id

                processed_nodes.append({
                    "id": node_id,
                    "position": node.get("position", {"x": 100 + (i % 4) * 250, "y": 100 + (i // 4) * 150}),
                    "size": node.get("size", {"width": 180, "height": 80}),
                    "content": node.get("content", {"type": "text", "data": {"text": ""}}),
                    "style": node.get("style", {})
                })

            # Process edges - update IDs if nodes were remapped
            processed_edges = []
            for edge in edges:
                source = node_id_map.get(edge.get("source"), edge.get("source"))
                target = node_id_map.get(edge.get("target"), edge.get("target"))
                processed_edges.append({
                    "id": edge.get("id") or str(uuid.uuid4()),
                    "source": source,
                    "target": target,
                    "sourceHandle": edge.get("sourceHandle", "right"),
                    "targetHandle": edge.get("targetHandle", "left"),
                    "style": edge.get("style", {"curved": True})
                })

            map_obj = Map(
                id=str(uuid.uuid4()),
                user_id=user_id,
                name=name,
                description=description,
                map_data={"nodes": processed_nodes, "edges": processed_edges},
                is_readonly=False
            )
            db.add(map_obj)
            db.commit()
            db.refresh(map_obj)

            result_data = {
                "map_id": map_obj.id,
                "name": map_obj.name,
                "node_count": len(processed_nodes),
                "edge_count": len(processed_edges)
            }

            if show_on_canvas:
                result_data["workspace_command"] = "show_map"
                result_data["map"] = map_obj.to_dict()
                # Track this as the current displayed map
                set_current_map(user_id, map_obj.id, map_obj.name)

            return ToolResult(
                success=True,
                data=result_data,
                message=f"Created map '{name}' with {len(processed_nodes)} nodes and {len(processed_edges)} edges"
            )

        except Exception as e:
            db.rollback()
            return ToolResult(success=False, message=f"Failed to create map: {str(e)}")
        finally:
            db.close()


class MapDeleteTool(BaseTool):
    """Tool for deleting a map"""

    @property
    def name(self) -> str:
        return "map_delete"

    @property
    def description(self) -> str:
        return "Delete a mindmap/flowchart by ID or name."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "map_id": {
                    "type": "string",
                    "description": "The ID of the map to delete"
                },
                "map_name": {
                    "type": "string",
                    "description": "The name of the map to delete (used if map_id not provided)"
                }
            }
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        map_id = kwargs.get("map_id")
        map_name = kwargs.get("map_name")

        if not map_id and not map_name:
            return ToolResult(success=False, message="Either map_id or map_name is required")

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            if map_id:
                stmt = select(Map).where(Map.id == map_id, Map.user_id == user_id)
            else:
                stmt = select(Map).where(Map.name.ilike(f"%{map_name}%"), Map.user_id == user_id)

            map_obj = db.execute(stmt).scalar_one_or_none()

            if not map_obj:
                return ToolResult(success=False, message=f"Map not found: {map_id or map_name}")

            name = map_obj.name
            deleted_id = map_obj.id
            db.delete(map_obj)
            db.commit()

            return ToolResult(
                success=True,
                data={
                    "workspace_command": "hide_map",
                    "map_id": deleted_id,
                    "deleted": True
                },
                message=f"Deleted map '{name}'"
            )

        except Exception as e:
            db.rollback()
            return ToolResult(success=False, message=f"Failed to delete map: {str(e)}")
        finally:
            db.close()


class MapGetTool(BaseTool):
    """Tool for getting map details"""

    @property
    def name(self) -> str:
        return "map_get"

    @property
    def description(self) -> str:
        return "Get the current state of a mindmap (nodes, edges, and metadata)."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "map_id": {
                    "type": "string",
                    "description": "The ID of the map"
                },
                "map_name": {
                    "type": "string",
                    "description": "The name of the map (used if map_id not provided)"
                }
            }
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        map_id = kwargs.get("map_id")
        map_name = kwargs.get("map_name")

        if not map_id and not map_name:
            return ToolResult(success=False, message="Either map_id or map_name is required")

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            if map_id:
                stmt = select(Map).where(Map.id == map_id, Map.user_id == user_id)
            else:
                stmt = select(Map).where(Map.name.ilike(f"%{map_name}%"), Map.user_id == user_id)

            map_obj = db.execute(stmt).scalar_one_or_none()

            if not map_obj:
                return ToolResult(success=False, message=f"Map not found: {map_id or map_name}")

            return ToolResult(
                success=True,
                data=map_obj.to_dict(),
                message=f"Map '{map_obj.name}': {len(map_obj.map_data.get('nodes', []))} nodes, {len(map_obj.map_data.get('edges', []))} edges"
            )

        except Exception as e:
            return ToolResult(success=False, message=f"Failed to get map: {str(e)}")
        finally:
            db.close()


class MapListTool(BaseTool):
    """Tool for listing all maps"""

    @property
    def name(self) -> str:
        return "map_list"

    @property
    def description(self) -> str:
        return "List all available mindmaps/flowcharts for the user."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {}
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            stmt = select(Map).where(Map.user_id == user_id).order_by(Map.updated_at.desc())
            maps = db.execute(stmt).scalars().all()

            summaries = [m.to_summary() for m in maps]

            return ToolResult(
                success=True,
                data={"maps": summaries, "count": len(summaries)},
                message=f"Found {len(summaries)} maps"
            )

        except Exception as e:
            return ToolResult(success=False, message=f"Failed to list maps: {str(e)}")
        finally:
            db.close()


class MapAddNodeTool(BaseTool):
    """Tool for adding a node to a map"""

    @property
    def name(self) -> str:
        return "map_add_node"

    @property
    def description(self) -> str:
        return "Add a new node to an existing mindmap/flowchart."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "map_id": {
                    "type": "string",
                    "description": "The ID of the map"
                },
                "content_type": {
                    "type": "string",
                    "enum": ["text", "code", "image"],
                    "description": "Type of content for the node"
                },
                "content_data": {
                    "type": "object",
                    "description": "Content data. For text: {text: '...'}. For code: {code: '...', language: '...'}. For image: {imageUrl: '...'}"
                },
                "position": {
                    "type": "object",
                    "description": "Position {x, y} on the map. If not provided, auto-positions below existing nodes"
                },
                "size": {
                    "type": "object",
                    "description": "Size {width, height}. Default: 180x80"
                }
            },
            "required": ["map_id", "content_type", "content_data"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        map_id = kwargs.get("map_id")
        content_type = kwargs.get("content_type", "text")
        content_data = kwargs.get("content_data", {})
        position = kwargs.get("position")
        size = kwargs.get("size", {"width": 180, "height": 80})

        if not map_id:
            return ToolResult(success=False, message="map_id is required")

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            stmt = select(Map).where(Map.id == map_id, Map.user_id == user_id)
            map_obj = db.execute(stmt).scalar_one_or_none()

            if not map_obj:
                return ToolResult(success=False, message=f"Map not found: {map_id}")

            if map_obj.is_readonly:
                return ToolResult(success=False, message="Map is read-only")

            map_data = map_obj.map_data or {"nodes": [], "edges": []}

            # Auto-calculate position if not provided
            if not position:
                existing_nodes = map_data.get("nodes", [])
                if existing_nodes:
                    max_y = max(n.get("position", {}).get("y", 0) for n in existing_nodes)
                    position = {"x": 100, "y": max_y + 150}
                else:
                    position = {"x": 100, "y": 100}

            node_id = str(uuid.uuid4())
            new_node = {
                "id": node_id,
                "position": position,
                "size": size,
                "content": {"type": content_type, "data": content_data},
                "style": {}
            }

            map_data["nodes"].append(new_node)
            map_obj.map_data = map_data
            db.commit()
            db.refresh(map_obj)

            return ToolResult(
                success=True,
                data={
                    "workspace_command": "update_map",
                    "map_id": map_id,
                    "node_id": node_id,
                    "node": new_node,
                    "map": map_obj.to_dict()
                },
                message=f"Added node to map '{map_obj.name}'"
            )

        except Exception as e:
            db.rollback()
            return ToolResult(success=False, message=f"Failed to add node: {str(e)}")
        finally:
            db.close()


class MapEditNodeTool(BaseTool):
    """Tool for editing a node's content"""

    @property
    def name(self) -> str:
        return "map_edit_node"

    @property
    def description(self) -> str:
        return "Edit the content of a node in a mindmap."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "map_id": {
                    "type": "string",
                    "description": "The ID of the map"
                },
                "node_id": {
                    "type": "string",
                    "description": "The ID of the node to edit"
                },
                "content_type": {
                    "type": "string",
                    "enum": ["text", "code", "image"],
                    "description": "New content type (optional)"
                },
                "content_data": {
                    "type": "object",
                    "description": "New content data"
                }
            },
            "required": ["map_id", "node_id", "content_data"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        map_id = kwargs.get("map_id")
        node_id = kwargs.get("node_id")
        content_type = kwargs.get("content_type")
        content_data = kwargs.get("content_data")

        if not map_id or not node_id:
            return ToolResult(success=False, message="map_id and node_id are required")

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            stmt = select(Map).where(Map.id == map_id, Map.user_id == user_id)
            map_obj = db.execute(stmt).scalar_one_or_none()

            if not map_obj:
                return ToolResult(success=False, message=f"Map not found: {map_id}")

            if map_obj.is_readonly:
                return ToolResult(success=False, message="Map is read-only")

            map_data = map_obj.map_data or {"nodes": [], "edges": []}

            node_found = False
            for node in map_data.get("nodes", []):
                if node["id"] == node_id:
                    if content_type:
                        node["content"]["type"] = content_type
                    if content_data:
                        node["content"]["data"] = content_data
                    node_found = True
                    break

            if not node_found:
                return ToolResult(success=False, message=f"Node not found: {node_id}")

            map_obj.map_data = map_data
            db.commit()
            db.refresh(map_obj)

            return ToolResult(
                success=True,
                data={
                    "workspace_command": "update_map",
                    "map_id": map_id,
                    "map": map_obj.to_dict()
                },
                message=f"Updated node in map '{map_obj.name}'"
            )

        except Exception as e:
            db.rollback()
            return ToolResult(success=False, message=f"Failed to edit node: {str(e)}")
        finally:
            db.close()


class MapDeleteNodeTool(BaseTool):
    """Tool for deleting a node from a map"""

    @property
    def name(self) -> str:
        return "map_delete_node"

    @property
    def description(self) -> str:
        return "Delete a node from a mindmap. This also removes any edges connected to the node."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "map_id": {
                    "type": "string",
                    "description": "The ID of the map"
                },
                "node_id": {
                    "type": "string",
                    "description": "The ID of the node to delete"
                }
            },
            "required": ["map_id", "node_id"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        map_id = kwargs.get("map_id")
        node_id = kwargs.get("node_id")

        if not map_id or not node_id:
            return ToolResult(success=False, message="map_id and node_id are required")

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            stmt = select(Map).where(Map.id == map_id, Map.user_id == user_id)
            map_obj = db.execute(stmt).scalar_one_or_none()

            if not map_obj:
                return ToolResult(success=False, message=f"Map not found: {map_id}")

            if map_obj.is_readonly:
                return ToolResult(success=False, message="Map is read-only")

            map_data = map_obj.map_data or {"nodes": [], "edges": []}

            original_count = len(map_data.get("nodes", []))
            map_data["nodes"] = [n for n in map_data.get("nodes", []) if n["id"] != node_id]

            if len(map_data["nodes"]) == original_count:
                return ToolResult(success=False, message=f"Node not found: {node_id}")

            # Remove connected edges
            map_data["edges"] = [
                e for e in map_data.get("edges", [])
                if e["source"] != node_id and e["target"] != node_id
            ]

            map_obj.map_data = map_data
            db.commit()
            db.refresh(map_obj)

            return ToolResult(
                success=True,
                data={
                    "workspace_command": "update_map",
                    "map_id": map_id,
                    "map": map_obj.to_dict()
                },
                message=f"Deleted node from map '{map_obj.name}'"
            )

        except Exception as e:
            db.rollback()
            return ToolResult(success=False, message=f"Failed to delete node: {str(e)}")
        finally:
            db.close()


class MapConnectTool(BaseTool):
    """Tool for connecting two nodes"""

    @property
    def name(self) -> str:
        return "map_connect"

    @property
    def description(self) -> str:
        return "Create an edge (connection) between two nodes in a mindmap."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "map_id": {
                    "type": "string",
                    "description": "The ID of the map"
                },
                "source_node_id": {
                    "type": "string",
                    "description": "The ID of the source node"
                },
                "target_node_id": {
                    "type": "string",
                    "description": "The ID of the target node"
                },
                "source_handle": {
                    "type": "string",
                    "enum": ["top", "right", "bottom", "left"],
                    "description": "Which side of the source node to connect from (default: right)"
                },
                "target_handle": {
                    "type": "string",
                    "enum": ["top", "right", "bottom", "left"],
                    "description": "Which side of the target node to connect to (default: left)"
                }
            },
            "required": ["map_id", "source_node_id", "target_node_id"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        map_id = kwargs.get("map_id")
        source_node_id = kwargs.get("source_node_id")
        target_node_id = kwargs.get("target_node_id")
        source_handle = kwargs.get("source_handle", "right")
        target_handle = kwargs.get("target_handle", "left")

        if not all([map_id, source_node_id, target_node_id]):
            return ToolResult(success=False, message="map_id, source_node_id, and target_node_id are required")

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            stmt = select(Map).where(Map.id == map_id, Map.user_id == user_id)
            map_obj = db.execute(stmt).scalar_one_or_none()

            if not map_obj:
                return ToolResult(success=False, message=f"Map not found: {map_id}")

            if map_obj.is_readonly:
                return ToolResult(success=False, message="Map is read-only")

            map_data = map_obj.map_data or {"nodes": [], "edges": []}

            # Verify nodes exist
            node_ids = {n["id"] for n in map_data.get("nodes", [])}
            if source_node_id not in node_ids:
                return ToolResult(success=False, message=f"Source node not found: {source_node_id}")
            if target_node_id not in node_ids:
                return ToolResult(success=False, message=f"Target node not found: {target_node_id}")

            # Check for duplicate edge
            for edge in map_data.get("edges", []):
                if edge["source"] == source_node_id and edge["target"] == target_node_id:
                    return ToolResult(success=False, message="Edge already exists")

            edge_id = str(uuid.uuid4())
            new_edge = {
                "id": edge_id,
                "source": source_node_id,
                "target": target_node_id,
                "sourceHandle": source_handle,
                "targetHandle": target_handle,
                "style": {"curved": True}
            }

            map_data["edges"].append(new_edge)
            map_obj.map_data = map_data
            db.commit()
            db.refresh(map_obj)

            return ToolResult(
                success=True,
                data={
                    "workspace_command": "update_map",
                    "map_id": map_id,
                    "edge_id": edge_id,
                    "map": map_obj.to_dict()
                },
                message=f"Connected nodes in map '{map_obj.name}'"
            )

        except Exception as e:
            db.rollback()
            return ToolResult(success=False, message=f"Failed to connect nodes: {str(e)}")
        finally:
            db.close()


class MapDisconnectTool(BaseTool):
    """Tool for removing a connection between nodes"""

    @property
    def name(self) -> str:
        return "map_disconnect"

    @property
    def description(self) -> str:
        return "Remove an edge (connection) between nodes in a mindmap."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "map_id": {
                    "type": "string",
                    "description": "The ID of the map"
                },
                "edge_id": {
                    "type": "string",
                    "description": "The ID of the edge to remove"
                },
                "source_node_id": {
                    "type": "string",
                    "description": "Alternative: source node ID (used with target_node_id if edge_id not provided)"
                },
                "target_node_id": {
                    "type": "string",
                    "description": "Alternative: target node ID (used with source_node_id if edge_id not provided)"
                }
            },
            "required": ["map_id"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        map_id = kwargs.get("map_id")
        edge_id = kwargs.get("edge_id")
        source_node_id = kwargs.get("source_node_id")
        target_node_id = kwargs.get("target_node_id")

        if not map_id:
            return ToolResult(success=False, message="map_id is required")

        if not edge_id and not (source_node_id and target_node_id):
            return ToolResult(success=False, message="Either edge_id or both source_node_id and target_node_id are required")

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            stmt = select(Map).where(Map.id == map_id, Map.user_id == user_id)
            map_obj = db.execute(stmt).scalar_one_or_none()

            if not map_obj:
                return ToolResult(success=False, message=f"Map not found: {map_id}")

            if map_obj.is_readonly:
                return ToolResult(success=False, message="Map is read-only")

            map_data = map_obj.map_data or {"nodes": [], "edges": []}

            original_count = len(map_data.get("edges", []))

            if edge_id:
                map_data["edges"] = [e for e in map_data.get("edges", []) if e["id"] != edge_id]
            else:
                map_data["edges"] = [
                    e for e in map_data.get("edges", [])
                    if not (e["source"] == source_node_id and e["target"] == target_node_id)
                ]

            if len(map_data["edges"]) == original_count:
                return ToolResult(success=False, message="Edge not found")

            map_obj.map_data = map_data
            db.commit()
            db.refresh(map_obj)

            return ToolResult(
                success=True,
                data={
                    "workspace_command": "update_map",
                    "map_id": map_id,
                    "map": map_obj.to_dict()
                },
                message=f"Removed connection in map '{map_obj.name}'"
            )

        except Exception as e:
            db.rollback()
            return ToolResult(success=False, message=f"Failed to disconnect nodes: {str(e)}")
        finally:
            db.close()


class MapShowTool(BaseTool):
    """Tool for showing a map on the canvas"""

    @property
    def name(self) -> str:
        return "map_show"

    @property
    def description(self) -> str:
        return "Show a mindmap on the workspace canvas. If already visible, brings it to focus."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "map_id": {
                    "type": "string",
                    "description": "The ID of the map to show"
                },
                "map_name": {
                    "type": "string",
                    "description": "The name of the map (used if map_id not provided)"
                },
                "position": {
                    "type": "object",
                    "description": "Position {x, y} on the canvas where to show the map"
                }
            }
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        map_id = kwargs.get("map_id")
        map_name = kwargs.get("map_name")
        position = kwargs.get("position", {"x": 200, "y": 200})

        if not map_id and not map_name:
            return ToolResult(success=False, message="Either map_id or map_name is required")

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            if map_id:
                stmt = select(Map).where(Map.id == map_id, Map.user_id == user_id)
            else:
                stmt = select(Map).where(Map.name.ilike(f"%{map_name}%"), Map.user_id == user_id)

            map_obj = db.execute(stmt).scalar_one_or_none()

            if not map_obj:
                return ToolResult(success=False, message=f"Map not found: {map_id or map_name}")

            # Track this as the current displayed map
            set_current_map(user_id, map_obj.id, map_obj.name)

            return ToolResult(
                success=True,
                data={
                    "workspace_command": "show_map",
                    "map_id": map_obj.id,
                    "position": position,
                    "collapsed": False,
                    "map": map_obj.to_dict()
                },
                message=f"Showing map '{map_obj.name}' on canvas"
            )

        except Exception as e:
            return ToolResult(success=False, message=f"Failed to show map: {str(e)}")
        finally:
            db.close()


class MapHideTool(BaseTool):
    """Tool for hiding a map from the canvas"""

    @property
    def name(self) -> str:
        return "map_hide"

    @property
    def description(self) -> str:
        return "Hide a mindmap from the workspace canvas. Can collapse to icon or fully hide."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "map_id": {
                    "type": "string",
                    "description": "The ID of the map to hide"
                },
                "mode": {
                    "type": "string",
                    "enum": ["collapse", "hide"],
                    "description": "How to hide: 'collapse' shows as icon, 'hide' removes from view entirely"
                }
            },
            "required": ["map_id"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        map_id = kwargs.get("map_id")
        mode = kwargs.get("mode", "collapse")

        if not map_id:
            return ToolResult(success=False, message="map_id is required")

        # Clear current map tracking if fully hiding
        if mode == "hide":
            current = get_current_map(user_id)
            if current and current.get("map_id") == map_id:
                clear_current_map(user_id)

        return ToolResult(
            success=True,
            data={
                "workspace_command": "hide_map" if mode == "hide" else "collapse_map",
                "map_id": map_id,
                "collapsed": mode == "collapse"
            },
            message=f"{'Collapsed' if mode == 'collapse' else 'Hidden'} map"
        )


class MapImportJsonTool(BaseTool):
    """Tool for importing a map from JSON or Mermaid"""

    @property
    def name(self) -> str:
        return "map_import_json"

    @property
    def description(self) -> str:
        return """Import a mindmap from JSON or Mermaid flowchart syntax.

JSON format: {"nodes": [{"id": "a", "label": "Node A"}, ...], "edges": [{"source": "a", "target": "b"}, ...]}

Mermaid format:
flowchart TD
    A[Start] --> B[Process]
    B --> C[End]"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name for the imported map"
                },
                "format": {
                    "type": "string",
                    "enum": ["json", "mermaid"],
                    "description": "Format of the content to import"
                },
                "content": {
                    "type": "string",
                    "description": "The JSON or Mermaid content to import"
                },
                "is_readonly": {
                    "type": "boolean",
                    "description": "Whether the imported map should be read-only (default: false)"
                },
                "show_on_canvas": {
                    "type": "boolean",
                    "description": "Whether to immediately show the map on the canvas (default: true)"
                }
            },
            "required": ["name", "format", "content"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        name = kwargs.get("name")
        format_type = kwargs.get("format")
        content = kwargs.get("content")
        is_readonly = kwargs.get("is_readonly", False)
        show_on_canvas = kwargs.get("show_on_canvas", True)

        if not all([name, format_type, content]):
            return ToolResult(success=False, message="name, format, and content are required")

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            # Import the parse function from routes
            from app.routes.maps import parse_mermaid_flowchart

            if format_type == "mermaid":
                map_data = parse_mermaid_flowchart(content)
            elif format_type == "json":
                try:
                    parsed = json.loads(content)
                    nodes = []
                    for i, n in enumerate(parsed.get("nodes", [])):
                        node_id = n.get("id", str(uuid.uuid4()))
                        nodes.append({
                            "id": node_id,
                            "position": n.get("position", {"x": 100 + (i % 4) * 250, "y": 100 + (i // 4) * 150}),
                            "size": n.get("size", {"width": 180, "height": 80}),
                            "content": n.get("content", {"type": "text", "data": {"text": n.get("label", "")}}),
                            "style": n.get("style", {})
                        })

                    edges = []
                    for e in parsed.get("edges", []):
                        edges.append({
                            "id": e.get("id", str(uuid.uuid4())),
                            "source": e.get("source"),
                            "target": e.get("target"),
                            "sourceHandle": e.get("sourceHandle", "right"),
                            "targetHandle": e.get("targetHandle", "left"),
                            "style": e.get("style", {"curved": True})
                        })

                    map_data = {"nodes": nodes, "edges": edges}
                except json.JSONDecodeError as e:
                    return ToolResult(success=False, message=f"Invalid JSON: {str(e)}")
            else:
                return ToolResult(success=False, message=f"Unknown format: {format_type}")

            map_obj = Map(
                id=str(uuid.uuid4()),
                user_id=user_id,
                name=name,
                map_data=map_data,
                is_readonly=is_readonly,
                import_source=format_type,
                import_raw=content
            )
            db.add(map_obj)
            db.commit()
            db.refresh(map_obj)

            result_data = {
                "map_id": map_obj.id,
                "name": map_obj.name,
                "node_count": len(map_data["nodes"]),
                "edge_count": len(map_data["edges"]),
                "is_readonly": is_readonly
            }

            if show_on_canvas:
                result_data["workspace_command"] = "show_map"
                result_data["map"] = map_obj.to_dict()
                # Track this as the current displayed map
                set_current_map(user_id, map_obj.id, map_obj.name)

            return ToolResult(
                success=True,
                data=result_data,
                message=f"Imported map '{name}' from {format_type} with {len(map_data['nodes'])} nodes and {len(map_data['edges'])} edges"
            )

        except Exception as e:
            db.rollback()
            return ToolResult(success=False, message=f"Failed to import map: {str(e)}")
        finally:
            db.close()


class MapExplodeTool(BaseTool):
    """Tool for exploding/expanding a map to show all content clearly"""

    @property
    def name(self) -> str:
        return "map_explode"

    @property
    def description(self) -> str:
        return """USE THIS TOOL when user says: "explode the map", "explode the graph", "expand the map", "spread out the nodes", "make the map readable", "resize the nodes", or similar requests.

This tool:
- Resizes all nodes to fit their text content (no more cut-off text)
- Spreads nodes apart so connections are clearly visible
- Applies force-directed layout to minimize edge crossings

If no map_id or map_name is provided, automatically uses the currently displayed map - just call the tool with no parameters."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "map_id": {
                    "type": "string",
                    "description": "The ID of the map to explode"
                },
                "map_name": {
                    "type": "string",
                    "description": "The name of the map (used if map_id not provided)"
                },
                "spacing_factor": {
                    "type": "number",
                    "description": "How much to spread nodes apart (1.0 = normal, 2.0 = double spacing). Default: 1.5"
                },
                "min_node_width": {
                    "type": "number",
                    "description": "Minimum node width in pixels. Default: 150"
                },
                "max_node_width": {
                    "type": "number",
                    "description": "Maximum node width in pixels. Default: 400"
                }
            }
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        map_id = kwargs.get("map_id")
        map_name = kwargs.get("map_name")
        spacing_factor = kwargs.get("spacing_factor", 1.5)
        min_node_width = kwargs.get("min_node_width", 150)
        max_node_width = kwargs.get("max_node_width", 400)

        # Auto-detect current map if none specified
        if not map_id and not map_name:
            current = get_current_map(user_id)
            if current:
                map_id = current.get("map_id")
                logger.info(f"📍 Auto-detected current map: {current.get('map_name')}")
            else:
                return ToolResult(success=False, message="No map specified and no map currently displayed. Please show a map first or specify map_id/map_name.")

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            if map_id:
                stmt = select(Map).where(Map.id == map_id, Map.user_id == user_id)
            else:
                stmt = select(Map).where(Map.name.ilike(f"%{map_name}%"), Map.user_id == user_id)

            map_obj = db.execute(stmt).scalar_one_or_none()

            if not map_obj:
                return ToolResult(success=False, message=f"Map not found: {map_id or map_name}")

            if map_obj.is_readonly:
                return ToolResult(success=False, message="Map is read-only")

            map_data = map_obj.map_data or {"nodes": [], "edges": []}
            nodes = map_data.get("nodes", [])
            edges = map_data.get("edges", [])

            if not nodes:
                return ToolResult(success=False, message="Map has no nodes to explode")

            # Step 1: Resize nodes based on text content
            for node in nodes:
                content = node.get("content", {})
                text = ""
                if content.get("type") == "text":
                    text = content.get("data", {}).get("text", "")
                elif content.get("type") == "code":
                    text = content.get("data", {}).get("code", "")

                # Calculate size based on text
                new_size = self._calculate_node_size(text, min_node_width, max_node_width)
                node["size"] = new_size

            # Step 2: Apply force-directed layout to spread nodes
            nodes = self._apply_force_layout(nodes, edges, spacing_factor)

            # Step 3: Normalize positions (ensure no negative coordinates)
            min_x = min(n["position"]["x"] for n in nodes)
            min_y = min(n["position"]["y"] for n in nodes)

            padding = 50
            for node in nodes:
                node["position"]["x"] = node["position"]["x"] - min_x + padding
                node["position"]["y"] = node["position"]["y"] - min_y + padding

            # Update map data
            map_data["nodes"] = nodes
            map_obj.map_data = map_data
            db.commit()
            db.refresh(map_obj)

            return ToolResult(
                success=True,
                data={
                    "workspace_command": "update_map",
                    "map_id": map_obj.id,
                    "map": map_obj.to_dict()
                },
                message=f"Exploded map '{map_obj.name}': resized {len(nodes)} nodes and spread them apart"
            )

        except Exception as e:
            db.rollback()
            logger.error(f"Failed to explode map: {e}")
            return ToolResult(success=False, message=f"Failed to explode map: {str(e)}")
        finally:
            db.close()

    def _calculate_node_size(self, text: str, min_width: int, max_width: int) -> Dict[str, int]:
        """Calculate appropriate node size based on text content"""
        if not text:
            return {"width": min_width, "height": 60}

        # Estimate characters per line (assuming ~8px per char, with padding)
        chars_per_line = max_width // 10
        lines = text.split("\n")

        # Calculate wrapped lines
        total_lines = 0
        max_line_length = 0
        for line in lines:
            if len(line) <= chars_per_line:
                total_lines += 1
                max_line_length = max(max_line_length, len(line))
            else:
                # Line needs wrapping
                wrapped = (len(line) + chars_per_line - 1) // chars_per_line
                total_lines += wrapped
                max_line_length = chars_per_line

        # Calculate dimensions
        # Width: based on longest line, with padding
        width = min(max(min_width, max_line_length * 10 + 40), max_width)

        # Height: based on number of lines (assuming ~24px per line + padding)
        height = max(60, total_lines * 24 + 40)

        # Cap height at reasonable maximum
        height = min(height, 500)

        return {"width": int(width), "height": int(height)}

    def _apply_force_layout(
        self,
        nodes: List[Dict],
        edges: List[Dict],
        spacing_factor: float,
        iterations: int = 50
    ) -> List[Dict]:
        """Apply force-directed layout to spread nodes apart"""
        import math

        if len(nodes) <= 1:
            return nodes

        # Build adjacency for attraction forces
        adjacency = {n["id"]: set() for n in nodes}
        for edge in edges:
            src, dst = edge.get("source"), edge.get("target")
            if src in adjacency and dst in adjacency:
                adjacency[src].add(dst)
                adjacency[dst].add(src)

        # Parameters
        repulsion_strength = 50000 * spacing_factor
        attraction_strength = 0.01
        damping = 0.9
        min_distance = 100 * spacing_factor

        # Initialize velocities
        velocities = {n["id"]: {"vx": 0, "vy": 0} for n in nodes}
        node_map = {n["id"]: n for n in nodes}

        for _ in range(iterations):
            forces = {n["id"]: {"fx": 0, "fy": 0} for n in nodes}

            # Repulsion between all nodes (Coulomb's law)
            for i, n1 in enumerate(nodes):
                for n2 in nodes[i+1:]:
                    dx = n1["position"]["x"] - n2["position"]["x"]
                    dy = n1["position"]["y"] - n2["position"]["y"]

                    # Account for node sizes
                    w1, h1 = n1["size"]["width"], n1["size"]["height"]
                    w2, h2 = n2["size"]["width"], n2["size"]["height"]
                    size_offset = (w1 + w2) / 2 + (h1 + h2) / 4

                    distance = math.sqrt(dx * dx + dy * dy) or 1

                    # Stronger repulsion when nodes overlap
                    if distance < size_offset + min_distance:
                        force = repulsion_strength / (distance * distance) * 2
                    else:
                        force = repulsion_strength / (distance * distance)

                    fx = (dx / distance) * force
                    fy = (dy / distance) * force

                    forces[n1["id"]]["fx"] += fx
                    forces[n1["id"]]["fy"] += fy
                    forces[n2["id"]]["fx"] -= fx
                    forces[n2["id"]]["fy"] -= fy

            # Attraction along edges (Hooke's law)
            for edge in edges:
                src_id, dst_id = edge.get("source"), edge.get("target")
                if src_id not in node_map or dst_id not in node_map:
                    continue

                n1, n2 = node_map[src_id], node_map[dst_id]
                dx = n2["position"]["x"] - n1["position"]["x"]
                dy = n2["position"]["y"] - n1["position"]["y"]
                distance = math.sqrt(dx * dx + dy * dy) or 1

                # Ideal edge length based on node sizes
                ideal_length = (n1["size"]["width"] + n2["size"]["width"]) / 2 + 150 * spacing_factor

                force = attraction_strength * (distance - ideal_length)
                fx = (dx / distance) * force
                fy = (dy / distance) * force

                forces[src_id]["fx"] += fx
                forces[src_id]["fy"] += fy
                forces[dst_id]["fx"] -= fx
                forces[dst_id]["fy"] -= fy

            # Apply forces with damping
            for node in nodes:
                nid = node["id"]
                velocities[nid]["vx"] = (velocities[nid]["vx"] + forces[nid]["fx"]) * damping
                velocities[nid]["vy"] = (velocities[nid]["vy"] + forces[nid]["fy"]) * damping

                # Limit velocity
                max_velocity = 50
                speed = math.sqrt(velocities[nid]["vx"]**2 + velocities[nid]["vy"]**2)
                if speed > max_velocity:
                    velocities[nid]["vx"] = (velocities[nid]["vx"] / speed) * max_velocity
                    velocities[nid]["vy"] = (velocities[nid]["vy"] / speed) * max_velocity

                node["position"]["x"] += velocities[nid]["vx"]
                node["position"]["y"] += velocities[nid]["vy"]

        return nodes


# List of all map tools for easy import
MAP_TOOLS = [
    MapCreateTool(),
    MapDeleteTool(),
    MapGetTool(),
    MapListTool(),
    MapAddNodeTool(),
    MapEditNodeTool(),
    MapDeleteNodeTool(),
    MapConnectTool(),
    MapDisconnectTool(),
    MapShowTool(),
    MapHideTool(),
    MapImportJsonTool(),
    MapExplodeTool(),
]
