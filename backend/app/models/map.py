"""
Map Model
Stores mindmaps/flowcharts with nodes and edges for the workspace canvas.
"""
from sqlalchemy import Column, String, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base import Base
import uuid


class Map(Base):
    """Mindmap/Flowchart stored as a first-class entity"""
    __tablename__ = "maps"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)

    # Full map data as JSON
    # Structure:
    # {
    #     "nodes": [
    #         {
    #             "id": "node-uuid",
    #             "position": {"x": 100, "y": 200},
    #             "size": {"width": 200, "height": 100},
    #             "content": {
    #                 "type": "text" | "image" | "code" | "embed",
    #                 "data": {...}  # varies by type
    #             },
    #             "style": {"backgroundColor": "#...", "borderColor": "#..."}
    #         }
    #     ],
    #     "edges": [
    #         {
    #             "id": "edge-uuid",
    #             "source": "node-id",
    #             "target": "node-id",
    #             "sourceHandle": "right" | "bottom" | "left" | "top",
    #             "targetHandle": "left" | "top" | "right" | "bottom",
    #             "style": {"strokeColor": "#...", "strokeWidth": 2, "curved": true}
    #         }
    #     ]
    # }
    map_data = Column(JSONB, default=dict)

    # Read-only flag (imported maps can be locked)
    is_readonly = Column(Boolean, default=False)

    # Source tracking for imports
    import_source = Column(String, nullable=True)  # "json" | "mermaid" | null
    import_raw = Column(Text, nullable=True)  # Original import content

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User")

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "name": self.name,
            "description": self.description,
            "map_data": self.map_data or {"nodes": [], "edges": []},
            "is_readonly": self.is_readonly,
            "import_source": self.import_source,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def to_summary(self):
        """Return a lightweight summary without full map_data"""
        map_data = self.map_data or {"nodes": [], "edges": []}
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "is_readonly": self.is_readonly,
            "node_count": len(map_data.get("nodes", [])),
            "edge_count": len(map_data.get("edges", [])),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
