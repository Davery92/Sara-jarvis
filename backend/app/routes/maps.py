"""
Maps API Routes
CRUD operations for mindmaps/flowcharts on the workspace canvas.
"""
import logging
import uuid
from typing import Optional, List, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.map import Map

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/maps", tags=["maps"])


# Pydantic models for request/response

class Position(BaseModel):
    x: float
    y: float


class Size(BaseModel):
    width: float
    height: float


class NodeContent(BaseModel):
    type: str  # "text" | "image" | "code" | "embed"
    data: dict


class NodeStyle(BaseModel):
    backgroundColor: Optional[str] = None
    borderColor: Optional[str] = None
    borderWidth: Optional[int] = None
    borderRadius: Optional[int] = None


class EdgeStyle(BaseModel):
    strokeColor: Optional[str] = None
    strokeWidth: Optional[int] = None
    curved: Optional[bool] = True


class MapNode(BaseModel):
    id: str
    position: Position
    size: Size
    content: NodeContent
    style: Optional[NodeStyle] = None


class MapEdge(BaseModel):
    id: str
    source: str
    target: str
    sourceHandle: Optional[str] = "right"
    targetHandle: Optional[str] = "left"
    style: Optional[EdgeStyle] = None


class MapData(BaseModel):
    nodes: List[MapNode] = []
    edges: List[MapEdge] = []


class MapCreate(BaseModel):
    name: str
    description: Optional[str] = None
    map_data: Optional[MapData] = None
    is_readonly: bool = False


class MapUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    map_data: Optional[MapData] = None
    is_readonly: Optional[bool] = None


class NodeCreate(BaseModel):
    position: Position
    size: Size
    content: NodeContent
    style: Optional[NodeStyle] = None


class NodeUpdate(BaseModel):
    position: Optional[Position] = None
    size: Optional[Size] = None
    content: Optional[NodeContent] = None
    style: Optional[NodeStyle] = None


class EdgeCreate(BaseModel):
    source: str
    target: str
    sourceHandle: Optional[str] = "right"
    targetHandle: Optional[str] = "left"
    style: Optional[EdgeStyle] = None


class MapImport(BaseModel):
    name: str
    format: str  # "json" | "mermaid"
    content: str  # Raw JSON or Mermaid syntax
    is_readonly: bool = False
    description: Optional[str] = None


# Helper functions

def parse_mermaid_flowchart(mermaid_text: str) -> dict:
    """Parse Mermaid flowchart syntax into map_data structure."""
    lines = mermaid_text.strip().split('\n')
    nodes = []
    edges = []
    node_map = {}  # mermaid_id -> uuid

    # Grid layout settings
    grid_x, grid_y = 100, 100
    col_width, row_height = 250, 150
    current_row, current_col = 0, 0
    max_cols = 4

    for line in lines:
        line = line.strip()
        if not line or line.startswith('flowchart') or line.startswith('graph'):
            continue

        # Node definition patterns: A[Text], A(Text), A{Text}, A((Text))
        import re
        node_patterns = [
            (r'^(\w+)\[(.+?)\]', 'rectangle'),      # A[Text]
            (r'^(\w+)\((.+?)\)', 'rounded'),        # A(Text)
            (r'^(\w+)\{(.+?)\}', 'diamond'),        # A{Text}
            (r'^(\w+)\(\((.+?)\)\)', 'circle'),     # A((Text))
        ]

        node_match = None
        for pattern, shape in node_patterns:
            match = re.match(pattern, line)
            if match:
                node_match = (match.group(1), match.group(2), shape)
                break

        if node_match:
            mermaid_id, text, shape = node_match
            if mermaid_id not in node_map:
                node_id = str(uuid.uuid4())
                node_map[mermaid_id] = node_id

                # Calculate position in grid
                x = grid_x + (current_col * col_width)
                y = grid_y + (current_row * row_height)
                current_col += 1
                if current_col >= max_cols:
                    current_col = 0
                    current_row += 1

                nodes.append({
                    "id": node_id,
                    "position": {"x": x, "y": y},
                    "size": {"width": 180, "height": 80},
                    "content": {"type": "text", "data": {"text": text}},
                    "style": {"borderRadius": 8 if shape == 'rounded' else 0}
                })
            continue

        # Edge definition patterns: A --> B, A -->|label| B, A --- B
        edge_patterns = [
            r'^(\w+)\s*--+>\s*\|(.+?)\|\s*(\w+)',  # A -->|label| B
            r'^(\w+)\s*--+>\s*(\w+)',               # A --> B
            r'^(\w+)\s*---+\s*(\w+)',               # A --- B
        ]

        for pattern in edge_patterns:
            match = re.match(pattern, line)
            if match:
                groups = match.groups()
                source_id = groups[0]
                target_id = groups[-1]

                # Ensure nodes exist
                for mid in [source_id, target_id]:
                    if mid not in node_map:
                        node_id = str(uuid.uuid4())
                        node_map[mid] = node_id
                        x = grid_x + (current_col * col_width)
                        y = grid_y + (current_row * row_height)
                        current_col += 1
                        if current_col >= max_cols:
                            current_col = 0
                            current_row += 1
                        nodes.append({
                            "id": node_id,
                            "position": {"x": x, "y": y},
                            "size": {"width": 180, "height": 80},
                            "content": {"type": "text", "data": {"text": mid}},
                            "style": {}
                        })

                edges.append({
                    "id": str(uuid.uuid4()),
                    "source": node_map[source_id],
                    "target": node_map[target_id],
                    "sourceHandle": "right",
                    "targetHandle": "left",
                    "style": {"curved": True}
                })
                break

    return {"nodes": nodes, "edges": edges}


# Routes

@router.get("")
async def list_maps(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all maps for the current user."""
    stmt = select(Map).where(Map.user_id == current_user.id).order_by(Map.updated_at.desc())
    maps = db.execute(stmt).scalars().all()
    return [m.to_summary() for m in maps]


@router.post("")
async def create_map(
    data: MapCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new map."""
    map_obj = Map(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        name=data.name,
        description=data.description,
        map_data=data.map_data.model_dump() if data.map_data else {"nodes": [], "edges": []},
        is_readonly=data.is_readonly
    )
    db.add(map_obj)
    db.commit()
    db.refresh(map_obj)

    logger.info(f"Map created: {map_obj.name} (id={map_obj.id}) for user {current_user.id}")
    return map_obj.to_dict()


@router.get("/{map_id}")
async def get_map(
    map_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a specific map by ID."""
    stmt = select(Map).where(Map.id == map_id, Map.user_id == current_user.id)
    map_obj = db.execute(stmt).scalar_one_or_none()

    if not map_obj:
        raise HTTPException(status_code=404, detail="Map not found")

    return map_obj.to_dict()


@router.put("/{map_id}")
async def update_map(
    map_id: str,
    data: MapUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a map."""
    stmt = select(Map).where(Map.id == map_id, Map.user_id == current_user.id)
    map_obj = db.execute(stmt).scalar_one_or_none()

    if not map_obj:
        raise HTTPException(status_code=404, detail="Map not found")

    if data.name is not None:
        map_obj.name = data.name
    if data.description is not None:
        map_obj.description = data.description
    if data.map_data is not None:
        map_obj.map_data = data.map_data.model_dump()
    if data.is_readonly is not None:
        map_obj.is_readonly = data.is_readonly

    db.commit()
    db.refresh(map_obj)

    logger.info(f"Map updated: {map_obj.name} (id={map_obj.id})")
    return map_obj.to_dict()


@router.delete("/{map_id}")
async def delete_map(
    map_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a map."""
    stmt = select(Map).where(Map.id == map_id, Map.user_id == current_user.id)
    map_obj = db.execute(stmt).scalar_one_or_none()

    if not map_obj:
        raise HTTPException(status_code=404, detail="Map not found")

    name = map_obj.name
    db.delete(map_obj)
    db.commit()

    logger.info(f"Map deleted: {name} (id={map_id})")
    return {"message": f"Map '{name}' deleted", "id": map_id}


# Node operations

@router.post("/{map_id}/nodes")
async def add_node(
    map_id: str,
    data: NodeCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Add a node to a map."""
    stmt = select(Map).where(Map.id == map_id, Map.user_id == current_user.id)
    map_obj = db.execute(stmt).scalar_one_or_none()

    if not map_obj:
        raise HTTPException(status_code=404, detail="Map not found")

    if map_obj.is_readonly:
        raise HTTPException(status_code=403, detail="Map is read-only")

    # Get current map data
    map_data = map_obj.map_data or {"nodes": [], "edges": []}

    # Create new node
    node_id = str(uuid.uuid4())
    new_node = {
        "id": node_id,
        "position": data.position.model_dump(),
        "size": data.size.model_dump(),
        "content": data.content.model_dump(),
        "style": data.style.model_dump() if data.style else {}
    }

    map_data["nodes"].append(new_node)
    map_obj.map_data = map_data

    db.commit()
    db.refresh(map_obj)

    logger.info(f"Node added to map {map_id}: {node_id}")
    return {"node": new_node, "map": map_obj.to_dict()}


@router.put("/{map_id}/nodes/{node_id}")
async def update_node(
    map_id: str,
    node_id: str,
    data: NodeUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a node in a map."""
    stmt = select(Map).where(Map.id == map_id, Map.user_id == current_user.id)
    map_obj = db.execute(stmt).scalar_one_or_none()

    if not map_obj:
        raise HTTPException(status_code=404, detail="Map not found")

    if map_obj.is_readonly:
        raise HTTPException(status_code=403, detail="Map is read-only")

    map_data = map_obj.map_data or {"nodes": [], "edges": []}

    # Find and update node
    node_found = False
    for node in map_data.get("nodes", []):
        if node["id"] == node_id:
            if data.position is not None:
                node["position"] = data.position.model_dump()
            if data.size is not None:
                node["size"] = data.size.model_dump()
            if data.content is not None:
                node["content"] = data.content.model_dump()
            if data.style is not None:
                node["style"] = data.style.model_dump()
            node_found = True
            break

    if not node_found:
        raise HTTPException(status_code=404, detail="Node not found")

    map_obj.map_data = map_data
    db.commit()
    db.refresh(map_obj)

    logger.info(f"Node updated in map {map_id}: {node_id}")
    return map_obj.to_dict()


@router.delete("/{map_id}/nodes/{node_id}")
async def delete_node(
    map_id: str,
    node_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a node from a map (also removes connected edges)."""
    stmt = select(Map).where(Map.id == map_id, Map.user_id == current_user.id)
    map_obj = db.execute(stmt).scalar_one_or_none()

    if not map_obj:
        raise HTTPException(status_code=404, detail="Map not found")

    if map_obj.is_readonly:
        raise HTTPException(status_code=403, detail="Map is read-only")

    map_data = map_obj.map_data or {"nodes": [], "edges": []}

    # Remove node
    original_count = len(map_data.get("nodes", []))
    map_data["nodes"] = [n for n in map_data.get("nodes", []) if n["id"] != node_id]

    if len(map_data["nodes"]) == original_count:
        raise HTTPException(status_code=404, detail="Node not found")

    # Remove edges connected to this node
    map_data["edges"] = [
        e for e in map_data.get("edges", [])
        if e["source"] != node_id and e["target"] != node_id
    ]

    map_obj.map_data = map_data
    db.commit()
    db.refresh(map_obj)

    logger.info(f"Node deleted from map {map_id}: {node_id}")
    return map_obj.to_dict()


# Edge operations

@router.post("/{map_id}/edges")
async def add_edge(
    map_id: str,
    data: EdgeCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Add an edge (connection) between nodes."""
    stmt = select(Map).where(Map.id == map_id, Map.user_id == current_user.id)
    map_obj = db.execute(stmt).scalar_one_or_none()

    if not map_obj:
        raise HTTPException(status_code=404, detail="Map not found")

    if map_obj.is_readonly:
        raise HTTPException(status_code=403, detail="Map is read-only")

    map_data = map_obj.map_data or {"nodes": [], "edges": []}

    # Verify both nodes exist
    node_ids = {n["id"] for n in map_data.get("nodes", [])}
    if data.source not in node_ids:
        raise HTTPException(status_code=400, detail=f"Source node '{data.source}' not found")
    if data.target not in node_ids:
        raise HTTPException(status_code=400, detail=f"Target node '{data.target}' not found")

    # Check for duplicate edge
    for edge in map_data.get("edges", []):
        if edge["source"] == data.source and edge["target"] == data.target:
            raise HTTPException(status_code=400, detail="Edge already exists")

    # Create new edge
    edge_id = str(uuid.uuid4())
    new_edge = {
        "id": edge_id,
        "source": data.source,
        "target": data.target,
        "sourceHandle": data.sourceHandle,
        "targetHandle": data.targetHandle,
        "style": data.style.model_dump() if data.style else {"curved": True}
    }

    map_data["edges"].append(new_edge)
    map_obj.map_data = map_data

    db.commit()
    db.refresh(map_obj)

    logger.info(f"Edge added to map {map_id}: {data.source} -> {data.target}")
    return {"edge": new_edge, "map": map_obj.to_dict()}


@router.delete("/{map_id}/edges/{edge_id}")
async def delete_edge(
    map_id: str,
    edge_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete an edge from a map."""
    stmt = select(Map).where(Map.id == map_id, Map.user_id == current_user.id)
    map_obj = db.execute(stmt).scalar_one_or_none()

    if not map_obj:
        raise HTTPException(status_code=404, detail="Map not found")

    if map_obj.is_readonly:
        raise HTTPException(status_code=403, detail="Map is read-only")

    map_data = map_obj.map_data or {"nodes": [], "edges": []}

    # Remove edge
    original_count = len(map_data.get("edges", []))
    map_data["edges"] = [e for e in map_data.get("edges", []) if e["id"] != edge_id]

    if len(map_data["edges"]) == original_count:
        raise HTTPException(status_code=404, detail="Edge not found")

    map_obj.map_data = map_data
    db.commit()
    db.refresh(map_obj)

    logger.info(f"Edge deleted from map {map_id}: {edge_id}")
    return map_obj.to_dict()


# Import

@router.post("/import")
async def import_map(
    data: MapImport,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Import a map from JSON or Mermaid syntax."""

    if data.format == "mermaid":
        map_data = parse_mermaid_flowchart(data.content)
    elif data.format == "json":
        import json
        try:
            parsed = json.loads(data.content)
            # Normalize structure
            nodes = []
            for n in parsed.get("nodes", []):
                node_id = n.get("id", str(uuid.uuid4()))
                nodes.append({
                    "id": node_id,
                    "position": n.get("position", {"x": 0, "y": 0}),
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
            raise HTTPException(status_code=400, detail=f"Invalid JSON: {str(e)}")
    else:
        raise HTTPException(status_code=400, detail=f"Unknown format: {data.format}")

    # Create the map
    map_obj = Map(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        name=data.name,
        description=data.description,
        map_data=map_data,
        is_readonly=data.is_readonly,
        import_source=data.format,
        import_raw=data.content
    )
    db.add(map_obj)
    db.commit()
    db.refresh(map_obj)

    logger.info(f"Map imported ({data.format}): {map_obj.name} (id={map_obj.id}) with {len(map_data['nodes'])} nodes, {len(map_data['edges'])} edges")
    return map_obj.to_dict()


# Current map tracking (for Sara's auto-detect feature)

class SetCurrentMapRequest(BaseModel):
    map_id: str
    map_name: str


@router.post("/current")
async def set_current_map_endpoint(
    data: SetCurrentMapRequest,
    current_user: User = Depends(get_current_user)
):
    """Set the currently displayed map for this user (for Sara's auto-detect)."""
    from app.tools.maps import set_current_map
    set_current_map(current_user.id, data.map_id, data.map_name)
    return {"success": True, "message": f"Current map set to: {data.map_name}"}


@router.delete("/current")
async def clear_current_map_endpoint(
    current_user: User = Depends(get_current_user)
):
    """Clear the currently displayed map for this user."""
    from app.tools.maps import clear_current_map
    clear_current_map(current_user.id)
    return {"success": True, "message": "Current map cleared"}


@router.get("/current")
async def get_current_map_endpoint(
    current_user: User = Depends(get_current_user)
):
    """Get the currently displayed map for this user."""
    from app.tools.maps import get_current_map
    current = get_current_map(current_user.id)
    if current:
        return {"current_map": current}
    return {"current_map": None}


class ExplodeMapRequest(BaseModel):
    map_id: Optional[str] = None
    spacing_factor: float = 1.5
    min_node_width: int = 150
    max_node_width: int = 400


@router.post("/{map_id}/explode")
async def explode_map_endpoint(
    map_id: str,
    request: ExplodeMapRequest = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Explode a map - resize nodes to fit text and spread them apart."""
    import math

    map_obj = db.execute(
        select(Map).where(Map.id == map_id, Map.user_id == current_user.id)
    ).scalar_one_or_none()

    if not map_obj:
        raise HTTPException(status_code=404, detail="Map not found")

    if map_obj.is_readonly:
        raise HTTPException(status_code=400, detail="Map is read-only")

    req = request or ExplodeMapRequest()
    map_data = map_obj.map_data or {"nodes": [], "edges": []}
    nodes = map_data.get("nodes", [])
    edges = map_data.get("edges", [])

    if not nodes:
        raise HTTPException(status_code=400, detail="Map has no nodes")

    # Resize nodes based on text content
    for node in nodes:
        content = node.get("content", {})
        text = ""
        if content.get("type") == "text":
            text = content.get("data", {}).get("text", "")
        elif content.get("type") == "code":
            text = content.get("data", {}).get("code", "")

        if not text:
            node["size"] = {"width": req.min_node_width, "height": 60}
            continue

        # Calculate size based on text
        chars_per_line = req.max_node_width // 10
        lines = text.split("\n")
        total_lines = 0
        max_line_length = 0

        for line in lines:
            if len(line) <= chars_per_line:
                total_lines += 1
                max_line_length = max(max_line_length, len(line))
            else:
                wrapped = (len(line) + chars_per_line - 1) // chars_per_line
                total_lines += wrapped
                max_line_length = chars_per_line

        width = min(max(req.min_node_width, max_line_length * 10 + 40), req.max_node_width)
        height = min(max(60, total_lines * 24 + 40), 500)
        node["size"] = {"width": int(width), "height": int(height)}

    # Apply force-directed layout
    if len(nodes) > 1:
        adjacency = {n["id"]: set() for n in nodes}
        for edge in edges:
            src, dst = edge.get("source"), edge.get("target")
            if src in adjacency and dst in adjacency:
                adjacency[src].add(dst)
                adjacency[dst].add(src)

        repulsion_strength = 50000 * req.spacing_factor
        min_distance = 100 * req.spacing_factor
        velocities = {n["id"]: {"vx": 0, "vy": 0} for n in nodes}

        for _ in range(50):  # iterations
            forces = {n["id"]: {"fx": 0, "fy": 0} for n in nodes}

            for i, n1 in enumerate(nodes):
                for n2 in nodes[i+1:]:
                    dx = n1["position"]["x"] - n2["position"]["x"]
                    dy = n1["position"]["y"] - n2["position"]["y"]
                    w1, h1 = n1["size"]["width"], n1["size"]["height"]
                    w2, h2 = n2["size"]["width"], n2["size"]["height"]
                    size_offset = (w1 + w2) / 2 + (h1 + h2) / 4
                    distance = math.sqrt(dx * dx + dy * dy) or 1

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

            # Update positions
            for node in nodes:
                nid = node["id"]
                velocities[nid]["vx"] = (velocities[nid]["vx"] + forces[nid]["fx"]) * 0.9
                velocities[nid]["vy"] = (velocities[nid]["vy"] + forces[nid]["fy"]) * 0.9
                node["position"]["x"] += velocities[nid]["vx"]
                node["position"]["y"] += velocities[nid]["vy"]

    # For compact mode (spacing_factor < 1), scale positions toward center
    if req.spacing_factor < 1.0:
        # Calculate centroid
        centroid_x = sum(n["position"]["x"] for n in nodes) / len(nodes)
        centroid_y = sum(n["position"]["y"] for n in nodes) / len(nodes)

        # Scale positions toward centroid
        scale = req.spacing_factor  # 0.5 means move halfway to center
        for node in nodes:
            dx = node["position"]["x"] - centroid_x
            dy = node["position"]["y"] - centroid_y
            node["position"]["x"] = centroid_x + dx * scale
            node["position"]["y"] = centroid_y + dy * scale

    # Normalize positions
    min_x = min(n["position"]["x"] for n in nodes)
    min_y = min(n["position"]["y"] for n in nodes)
    for node in nodes:
        node["position"]["x"] = node["position"]["x"] - min_x + 50
        node["position"]["y"] = node["position"]["y"] - min_y + 50

    map_data["nodes"] = nodes
    # SQLAlchemy doesn't detect JSONB mutations - must flag or reassign
    from sqlalchemy.orm.attributes import flag_modified
    map_obj.map_data = dict(map_data)  # Create new dict to ensure change detection
    flag_modified(map_obj, "map_data")
    db.commit()
    db.refresh(map_obj)

    first_node = nodes[0] if nodes else {}
    logger.info(f"Exploded map {map_id}: resized {len(nodes)} nodes. First node now at ({first_node.get('position', {}).get('x', 0):.0f}, {first_node.get('position', {}).get('y', 0):.0f})")
    return map_obj.to_dict()
