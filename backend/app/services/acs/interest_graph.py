"""
ACS Interest Graph — weighted topic nodes with relationship edges.

Replaces the flat curiosity queue with a rich graph of interests,
supporting semantic dedup, fascination decay, bridge discovery,
and Neo4j mirroring.
"""

import asyncio
import copy
import logging
import math
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from app.core.config import settings

logger = logging.getLogger(__name__)


class InterestGraph:
    """Manages the ACS interest graph (nodes + edges) in PostgreSQL with Neo4j mirror."""

    # Class-level divergence counters so failures are visible even when
    # individual calls are fire-and-forget. Reset on process restart.
    _neo4j_sync_failures = 0
    _neo4j_last_warn_ts = 0.0
    _NEO4J_WARN_INTERVAL_SEC = 300  # Re-warn at most every 5 min per-class

    def __init__(self):
        self._neo4j_driver = None

    def _get_neo4j_driver(self):
        if self._neo4j_driver is not None:
            return self._neo4j_driver
        try:
            from neo4j import GraphDatabase
            uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
            user = os.getenv("NEO4J_USER", "neo4j")
            password = os.getenv("NEO4J_PASSWORD", "password")
            self._neo4j_driver = GraphDatabase.driver(uri, auth=(user, password))
            return self._neo4j_driver
        except Exception as e:
            logger.debug(f"Neo4j not available: {e}")
            return None

    @classmethod
    def _log_neo4j_failure(cls, kind: str, err: Exception):
        """Rate-limited WARNING log so one-off outages don't flood, but sustained
        divergence between PG and Neo4j is visible in ops dashboards."""
        import time
        cls._neo4j_sync_failures += 1
        now = time.time()
        if now - cls._neo4j_last_warn_ts >= cls._NEO4J_WARN_INTERVAL_SEC:
            logger.warning(
                f"Neo4j {kind} sync failed (total failures since restart: "
                f"{cls._neo4j_sync_failures}): {err}"
            )
            cls._neo4j_last_warn_ts = now
        else:
            logger.debug(f"Neo4j {kind} sync failed: {err}")

    def close(self):
        """Close the Neo4j driver. Safe to call multiple times."""
        if self._neo4j_driver is not None:
            try:
                self._neo4j_driver.close()
            except Exception:
                pass
            self._neo4j_driver = None

    async def _neo4j_sync_node(self, node_data: dict):
        """Fire-and-forget sync of an interest node to Neo4j."""
        try:
            driver = self._get_neo4j_driver()
            if not driver:
                return
            with driver.session() as session:
                session.run(
                    """
                    MERGE (n:InterestNode {id: $id})
                    SET n.label = $label, n.description = $description,
                        n.fascination = $fascination, n.depth = $depth,
                        n.status = $status, n.user_id = $user_id
                    """,
                    **node_data,
                )
        except Exception as e:
            self._log_neo4j_failure("node", e)

    async def _sync_to_pkg_interest(self, label: str, description: str, depth: str):
        """Fire-and-forget sync of an interest node to PKG as a PKG_Interest fact."""
        try:
            from app.services.personal_knowledge_graph import personal_kg
            personal_kg.upsert_fact(
                fact_type="Interest",
                properties={
                    "topic": label,
                    "depth": depth,
                    "description": description[:200] if description else "",
                    "category": "acs_interest_sync",
                },
                confidence=0.7,
                source="acs_interest_sync",
            )
            logger.info(f"Synced interest node to PKG: {label} (depth={depth})")
        except Exception as e:
            logger.debug(f"PKG interest sync failed for {label}: {e}")

    async def _neo4j_sync_edge(self, edge_data: dict):
        """Fire-and-forget sync of an interest edge to Neo4j."""
        try:
            driver = self._get_neo4j_driver()
            if not driver:
                return
            with driver.session() as session:
                session.run(
                    """
                    MATCH (a:InterestNode {id: $source_node_id})
                    MATCH (b:InterestNode {id: $target_node_id})
                    MERGE (a)-[r:INTEREST_RELATES {relationship: $relationship}]->(b)
                    SET r.description = $description, r.strength = $strength
                    """,
                    **edge_data,
                )
        except Exception as e:
            self._log_neo4j_failure("edge", e)

    async def add_node(
        self,
        user_id: str,
        label: str,
        description: str = "",
        source: str = "self_discovery",
        fascination: float = 0.5,
        source_detail: str = "",
    ) -> Optional[Dict[str, Any]]:
        """Add an interest node. Deduplicates by embedding similarity > threshold.

        If a near-duplicate exists, merges: bumps fascination +0.1, updates description
        if the new one is richer. Returns the node dict (new or merged).
        """
        from app.services.embedding_service import EmbeddingService
        from app.db.session import get_async_session_factory

        # Generate embedding for dedup check
        svc = EmbeddingService()
        embedding = await svc.generate_embedding(f"{label}: {description}")
        if not embedding:
            logger.warning(f"Failed to generate embedding for interest node: {label}")
            # Proceed without embedding — skip dedup
            embedding = None

        async_session = get_async_session_factory()
        async with async_session() as db:
            # Check exact label match first
            existing = await db.execute(text("""
                SELECT id, label, description, fascination, depth, confidence,
                       source, status, times_engaged
                FROM acs_interest_node
                WHERE user_id = :uid AND label = :label
            """), {"uid": user_id, "label": label})
            row = existing.fetchone()

            if row:
                # Exact match — merge
                node_id = row[0]
                new_fascination = min(1.0, row[3] + 0.1)
                new_desc = description if len(description) > len(row[2] or "") else row[2]
                await db.execute(text("""
                    UPDATE acs_interest_node
                    SET fascination = :fasc, description = :desc,
                        updated_at = NOW()
                    WHERE id = :id
                """), {"fasc": new_fascination, "desc": new_desc, "id": node_id})
                await db.commit()
                logger.info(f"Merged interest node (exact label match): {label}")
                return {"id": node_id, "label": label, "merged": True, "fascination": new_fascination}

            # Semantic dedup check via cosine similarity
            if embedding:
                threshold = settings.acs_v2_similarity_dedup_threshold
                similar = await db.execute(text("""
                    SELECT id, label, description, fascination,
                           GREATEST(0, 1 - (embedding <=> CAST(:emb AS vector))) AS similarity
                    FROM acs_interest_node
                    WHERE user_id = :uid AND status = 'active' AND embedding IS NOT NULL
                    ORDER BY embedding <=> CAST(:emb AS vector)
                    LIMIT 1
                """), {"uid": user_id, "emb": str(embedding)})
                sim_row = similar.fetchone()

                if sim_row and sim_row[4] >= threshold:
                    # Near-duplicate — merge
                    node_id = sim_row[0]
                    new_fascination = min(1.0, sim_row[3] + 0.1)
                    new_desc = description if len(description) > len(sim_row[2] or "") else sim_row[2]
                    await db.execute(text("""
                        UPDATE acs_interest_node
                        SET fascination = :fasc, description = :desc,
                            updated_at = NOW()
                        WHERE id = :id
                    """), {"fasc": new_fascination, "desc": new_desc, "id": node_id})
                    await db.commit()
                    logger.info(f"Merged interest node (semantic dedup, sim={sim_row[4]:.3f}): {label} → {sim_row[1]}")
                    return {"id": node_id, "label": sim_row[1], "merged": True, "fascination": new_fascination}

            # Diversity check: reject self-discovered nodes too similar to existing cluster
            if source == "self_discovery" and embedding:
                cluster_result = await db.execute(text("""
                    SELECT COUNT(*) FROM acs_interest_node
                    WHERE user_id = :uid AND status = 'active' AND embedding IS NOT NULL
                      AND GREATEST(0, 1 - (embedding <=> CAST(:emb AS vector))) > 0.70
                """), {"uid": user_id, "emb": str(embedding)})
                similar_count = cluster_result.scalar() or 0
                if similar_count >= 5:
                    logger.info(
                        f"Interest node rejected (cluster saturation): {label} "
                        f"— {similar_count} similar nodes already exist"
                    )
                    return None

            # Insert new node
            node_id = str(uuid.uuid4())
            await db.execute(text("""
                INSERT INTO acs_interest_node
                    (id, user_id, label, description, fascination, source, source_detail,
                     embedding, status, times_engaged, created_at, updated_at)
                VALUES (:id, :uid, :label, :desc, :fasc, :src, :src_detail,
                        CAST(:emb AS vector), 'active', 0, NOW(), NOW())
            """), {
                "id": node_id, "uid": user_id, "label": label,
                "desc": description, "fasc": fascination,
                "src": source, "src_detail": source_detail,
                "emb": str(embedding) if embedding else None,
            })
            await db.commit()

            logger.info(f"Created interest node: {label} (id={node_id[:8]})")

            # Fire-and-forget Neo4j sync
            asyncio.create_task(self._neo4j_sync_node({
                "id": node_id, "label": label, "description": description,
                "fascination": fascination, "depth": 0.0, "status": "active",
                "user_id": user_id,
            }))

            # Sync david_request nodes to PKG as Interest facts
            if source == "david_request":
                asyncio.create_task(self._sync_to_pkg_interest(label, description, "surface"))

            return {"id": node_id, "label": label, "merged": False, "fascination": fascination}

    async def update_node(self, node_id: str, **kwargs) -> bool:
        """Update node fields. Clamps scores to [0.0, 1.0]."""
        from app.db.session import get_async_session_factory

        # Clamp score fields
        for field in ("fascination", "depth", "confidence"):
            if field in kwargs:
                kwargs[field] = max(0.0, min(1.0, float(kwargs[field])))

        allowed = {"label", "description", "fascination", "depth", "confidence",
                    "source", "source_detail", "status"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return False

        set_clauses = ", ".join(f"{k} = :{k}" for k in updates)
        updates["id"] = node_id

        async_session = get_async_session_factory()
        async with async_session() as db:
            # Check if depth is crossing the 0.5 threshold (for PKG sync)
            sync_pkg = False
            if "depth" in updates and updates["depth"] >= 0.5:
                old = await db.execute(text(
                    "SELECT label, depth FROM acs_interest_node WHERE id = :id"
                ), {"id": node_id})
                old_row = old.fetchone()
                if old_row and (old_row[1] or 0) < 0.5:
                    sync_pkg = True
                    sync_label = old_row[0]

            result = await db.execute(text(f"""
                UPDATE acs_interest_node SET {set_clauses}, updated_at = NOW()
                WHERE id = :id
            """), updates)
            await db.commit()

            if sync_pkg:
                asyncio.create_task(self._sync_to_pkg_interest(
                    sync_label, updates.get("description", ""), "deep"
                ))

            return result.rowcount > 0

    async def engage_node(self, node_id: str, meaningful: bool = False) -> bool:
        """Record engagement with a node.

        Args:
            node_id: The node to engage.
            meaningful: If True, this is a meaningful engagement (depth increase,
                note written, real research). Updates last_engaged_at and boosts
                fascination. If False, just increments the counter — does NOT
                reset the decay timer.
        """
        from app.db.session import get_async_session_factory

        async_session = get_async_session_factory()
        async with async_session() as db:
            if meaningful:
                result = await db.execute(text("""
                    UPDATE acs_interest_node
                    SET times_engaged = times_engaged + 1,
                        last_engaged_at = NOW(),
                        fascination = LEAST(1.0, fascination + 0.03),
                        updated_at = NOW()
                    WHERE id = :id
                """), {"id": node_id})
            else:
                result = await db.execute(text("""
                    UPDATE acs_interest_node
                    SET times_engaged = times_engaged + 1,
                        updated_at = NOW()
                    WHERE id = :id
                """), {"id": node_id})
            await db.commit()
            return result.rowcount > 0

    async def add_edge(
        self,
        user_id: str,
        source_node_id: str,
        target_node_id: str,
        relationship: str,
        description: str = "",
        strength: float = 0.5,
        discovered_during_mode: str = None,
    ) -> Optional[Dict[str, Any]]:
        """Add or update an edge between two interest nodes."""
        from app.db.session import get_async_session_factory

        strength = max(0.0, min(1.0, strength))
        async_session = get_async_session_factory()

        async with async_session() as db:
            # Upsert: update if same relationship exists
            existing = await db.execute(text("""
                SELECT id FROM acs_interest_edge
                WHERE source_node_id = :src AND target_node_id = :tgt AND relationship = :rel
            """), {"src": source_node_id, "tgt": target_node_id, "rel": relationship})
            row = existing.fetchone()

            if row:
                edge_id = row[0]
                await db.execute(text("""
                    UPDATE acs_interest_edge
                    SET description = :desc, strength = :str, updated_at = NOW()
                    WHERE id = :id
                """), {"desc": description, "str": strength, "id": edge_id})
                await db.commit()
                return {"id": edge_id, "updated": True}

            edge_id = str(uuid.uuid4())
            await db.execute(text("""
                INSERT INTO acs_interest_edge
                    (id, user_id, source_node_id, target_node_id, relationship,
                     description, strength, discovered_during_mode, created_at, updated_at)
                VALUES (:id, :uid, :src, :tgt, :rel, :desc, :str, :mode, NOW(), NOW())
            """), {
                "id": edge_id, "uid": user_id,
                "src": source_node_id, "tgt": target_node_id,
                "rel": relationship, "desc": description, "str": strength,
                "mode": discovered_during_mode,
            })
            await db.commit()

            logger.info(f"Created interest edge: {source_node_id[:8]} --[{relationship}]--> {target_node_id[:8]}")

            # Fire-and-forget Neo4j sync
            asyncio.create_task(self._neo4j_sync_edge({
                "source_node_id": source_node_id,
                "target_node_id": target_node_id,
                "relationship": relationship,
                "description": description,
                "strength": strength,
            }))

            return {"id": edge_id, "updated": False}

    async def find_by_label(self, user_id: str, label: str) -> Optional[Dict[str, Any]]:
        """Exact match lookup by label."""
        from app.db.session import get_async_session_factory

        async_session = get_async_session_factory()
        async with async_session() as db:
            result = await db.execute(text("""
                SELECT id, label, description, fascination, depth, confidence,
                       source, status, times_engaged, last_engaged_at, created_at
                FROM acs_interest_node
                WHERE user_id = :uid AND label = :label
            """), {"uid": user_id, "label": label})
            row = result.fetchone()
            if not row:
                return None
            return {
                "id": row[0], "label": row[1], "description": row[2],
                "fascination": row[3], "depth": row[4], "confidence": row[5],
                "source": row[6], "status": row[7], "times_engaged": row[8],
                "last_engaged_at": row[9].isoformat() if row[9] else None,
                "created_at": row[10].isoformat() if row[10] else None,
            }

    async def get_graph_for_context(
        self, user_id: str, max_nodes: int = None
    ) -> Dict[str, Any]:
        """Build a curated context window of the interest graph.

        Selection strategy:
        - Top 5 by fascination
        - Top 3 stale (high fascination, >7d untouched)
        - Top 3 depth-gap (high fascination, low depth)
        - Up to 4 recent (engaged in last 48h)
        Plus edges between selected nodes.
        """
        from app.db.session import get_async_session_factory

        if max_nodes is None:
            max_nodes = settings.acs_v2_max_context_nodes

        async_session = get_async_session_factory()
        async with async_session() as db:
            # Top by fascination
            top_fasc = await db.execute(text("""
                SELECT id, label, description, fascination, depth, confidence,
                       times_engaged, last_engaged_at, status, source
                FROM acs_interest_node
                WHERE user_id = :uid AND status = 'active'
                ORDER BY fascination DESC
                LIMIT 5
            """), {"uid": user_id})
            top_fasc_rows = top_fasc.fetchall()

            # Stale: high fascination, >7d untouched
            stale = await db.execute(text("""
                SELECT id, label, description, fascination, depth, confidence,
                       times_engaged, last_engaged_at, status, source
                FROM acs_interest_node
                WHERE user_id = :uid AND status = 'active'
                  AND fascination > 0.3
                  AND (last_engaged_at IS NULL OR last_engaged_at < NOW() - INTERVAL '7 days')
                ORDER BY fascination DESC
                LIMIT 3
            """), {"uid": user_id})
            stale_rows = stale.fetchall()

            # Depth gap: high fascination, low depth
            depth_gap = await db.execute(text("""
                SELECT id, label, description, fascination, depth, confidence,
                       times_engaged, last_engaged_at, status, source
                FROM acs_interest_node
                WHERE user_id = :uid AND status = 'active'
                  AND fascination > 0.3 AND depth < 0.3
                ORDER BY fascination DESC
                LIMIT 3
            """), {"uid": user_id})
            depth_gap_rows = depth_gap.fetchall()

            # Recent (last 48h)
            recent = await db.execute(text("""
                SELECT id, label, description, fascination, depth, confidence,
                       times_engaged, last_engaged_at, status, source
                FROM acs_interest_node
                WHERE user_id = :uid AND status = 'active'
                  AND last_engaged_at > NOW() - INTERVAL '48 hours'
                ORDER BY last_engaged_at DESC
                LIMIT 4
            """), {"uid": user_id})
            recent_rows = recent.fetchall()

            # Deduplicate and cap
            seen_ids = set()
            nodes = []
            for rows in [top_fasc_rows, stale_rows, depth_gap_rows, recent_rows]:
                for row in rows:
                    if row[0] not in seen_ids and len(nodes) < max_nodes:
                        seen_ids.add(row[0])
                        nodes.append({
                            "id": row[0], "label": row[1], "description": row[2],
                            "fascination": row[3], "depth": row[4], "confidence": row[5],
                            "times_engaged": row[6],
                            "last_engaged_at": row[7].isoformat() if row[7] else None,
                            "status": row[8],
                            "source": row[9] if len(row) > 9 else None,
                        })

            if not nodes:
                return {"nodes": [], "edges": [], "stats": {"total_active": 0}}

            # Get edges between selected nodes
            node_ids = list(seen_ids)
            edges_result = await db.execute(text("""
                SELECT id, source_node_id, target_node_id, relationship, description, strength
                FROM acs_interest_edge
                WHERE user_id = :uid
                  AND source_node_id = ANY(:ids)
                  AND target_node_id = ANY(:ids)
            """), {"uid": user_id, "ids": node_ids})
            edges = [
                {
                    "id": r[0], "source_node_id": r[1], "target_node_id": r[2],
                    "relationship": r[3], "description": r[4], "strength": r[5],
                }
                for r in edges_result.fetchall()
            ]

            # Stats
            total = await db.execute(text("""
                SELECT COUNT(*) FROM acs_interest_node
                WHERE user_id = :uid AND status = 'active'
            """), {"uid": user_id})
            total_active = total.scalar() or 0

            return {"nodes": nodes, "edges": edges, "stats": {"total_active": total_active}}

    async def apply_decay(self, user_id: str) -> int:
        """Apply fascination decay to all nodes for a user.

        fascination *= 0.5^(days_since_engaged / half_life)
        Nodes engaged in last 48h are skipped.
        Nodes with fascination < 0.1 after decay become 'dormant'.

        Returns count of nodes decayed.
        """
        from app.db.session import get_async_session_factory

        half_life = settings.acs_v2_decay_half_life_days

        async_session = get_async_session_factory()
        async with async_session() as db:
            # Get active nodes not recently engaged
            result = await db.execute(text("""
                SELECT id, fascination, last_engaged_at
                FROM acs_interest_node
                WHERE user_id = :uid AND status = 'active'
                  AND (last_engaged_at IS NULL OR last_engaged_at < NOW() - INTERVAL '24 hours')
            """), {"uid": user_id})
            rows = result.fetchall()

            now = datetime.now(timezone.utc)
            decayed = 0

            for row in rows:
                node_id, fascination, last_engaged = row
                if last_engaged:
                    if last_engaged.tzinfo is None:
                        last_engaged = last_engaged.replace(tzinfo=timezone.utc)
                    days = (now - last_engaged).total_seconds() / 86400
                else:
                    days = 30  # Default for never-engaged nodes

                decay_factor = 0.5 ** (days / half_life)
                new_fascination = fascination * decay_factor
                new_status = "dormant" if new_fascination < 0.1 else "active"

                await db.execute(text("""
                    UPDATE acs_interest_node
                    SET fascination = :fasc, status = :status, updated_at = NOW()
                    WHERE id = :id
                """), {"fasc": new_fascination, "status": new_status, "id": node_id})
                decayed += 1

            await db.commit()
            logger.info(f"Interest graph decay: {decayed} nodes updated for user {user_id}")
            return decayed

    async def find_bridge_opportunities(
        self, user_id: str, limit: int = 5
    ) -> List[Dict[str, Any]]:
        """Find pairs of nodes with high embedding similarity but no edge between them."""
        from app.db.session import get_async_session_factory

        threshold = settings.acs_v2_bridge_threshold

        async_session = get_async_session_factory()
        async with async_session() as db:
            # Cross-join nodes and compute cosine similarity, excluding pairs with existing edges
            result = await db.execute(text("""
                SELECT a.id AS a_id, a.label AS a_label,
                       b.id AS b_id, b.label AS b_label,
                       GREATEST(0, 1 - (a.embedding <=> b.embedding)) AS similarity
                FROM acs_interest_node a
                JOIN acs_interest_node b ON a.user_id = b.user_id AND a.id < b.id
                WHERE a.user_id = :uid
                  AND a.status = 'active' AND b.status = 'active'
                  AND a.embedding IS NOT NULL AND b.embedding IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM acs_interest_edge e
                      WHERE (e.source_node_id = a.id AND e.target_node_id = b.id)
                         OR (e.source_node_id = b.id AND e.target_node_id = a.id)
                  )
                  AND GREATEST(0, 1 - (a.embedding <=> b.embedding)) > :threshold
                ORDER BY (a.embedding <=> b.embedding) ASC
                LIMIT :lim
            """), {"uid": user_id, "threshold": threshold, "lim": limit})

            return [
                {
                    "node_a": {"id": r[0], "label": r[1]},
                    "node_b": {"id": r[2], "label": r[3]},
                    "similarity": r[4],
                }
                for r in result.fetchall()
            ]

    async def get_disconnected_clusters(self, user_id: str) -> List[List[str]]:
        """Find connected components by adjacency. Returns list of node ID lists."""
        from app.db.session import get_async_session_factory

        async_session = get_async_session_factory()
        async with async_session() as db:
            nodes_result = await db.execute(text("""
                SELECT id FROM acs_interest_node
                WHERE user_id = :uid AND status = 'active'
            """), {"uid": user_id})
            node_ids = [r[0] for r in nodes_result.fetchall()]

            edges_result = await db.execute(text("""
                SELECT source_node_id, target_node_id FROM acs_interest_edge
                WHERE user_id = :uid
            """), {"uid": user_id})
            edges = [(r[0], r[1]) for r in edges_result.fetchall()]

        # Build adjacency list and find connected components via BFS
        adj: Dict[str, set] = {nid: set() for nid in node_ids}
        for src, tgt in edges:
            if src in adj and tgt in adj:
                adj[src].add(tgt)
                adj[tgt].add(src)

        visited = set()
        clusters = []
        for nid in node_ids:
            if nid in visited:
                continue
            cluster = []
            queue = [nid]
            while queue:
                current = queue.pop(0)
                if current in visited:
                    continue
                visited.add(current)
                cluster.append(current)
                queue.extend(adj[current] - visited)
            clusters.append(cluster)

        return clusters

    async def semantic_search(
        self, user_id: str, query: str, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Semantic search over interest nodes by embedding similarity."""
        from app.services.embedding_service import EmbeddingService
        from app.db.session import get_async_session_factory

        svc = EmbeddingService()
        embedding = await svc.generate_embedding(query)
        if not embedding:
            return []

        async_session = get_async_session_factory()
        async with async_session() as db:
            result = await db.execute(text("""
                SELECT id, label, description, fascination, depth, status,
                       GREATEST(0, 1 - (embedding <=> CAST(:emb AS vector))) AS similarity
                FROM acs_interest_node
                WHERE user_id = :uid AND embedding IS NOT NULL
                ORDER BY embedding <=> CAST(:emb AS vector)
                LIMIT :lim
            """), {"uid": user_id, "emb": str(embedding), "lim": limit})

            return [
                {
                    "id": r[0], "label": r[1], "description": r[2],
                    "fascination": r[3], "depth": r[4], "status": r[5],
                    "similarity": r[6],
                }
                for r in result.fetchall()
            ]

    async def get_all_nodes(
        self, user_id: str, status: str = None, limit: int = 100, offset: int = 0
    ) -> Dict[str, Any]:
        """Get all nodes with optional status filter, paginated."""
        from app.db.session import get_async_session_factory

        async_session = get_async_session_factory()
        async with async_session() as db:
            where = "WHERE user_id = :uid"
            params: dict = {"uid": user_id, "lim": limit, "off": offset}
            if status:
                where += " AND status = :status"
                params["status"] = status

            result = await db.execute(text(f"""
                SELECT id, label, description, fascination, depth, confidence,
                       source, status, times_engaged, last_engaged_at, created_at
                FROM acs_interest_node
                {where}
                ORDER BY fascination DESC
                LIMIT :lim OFFSET :off
            """), params)
            rows = result.fetchall()

            count_result = await db.execute(text(f"""
                SELECT COUNT(*) FROM acs_interest_node {where}
            """), {k: v for k, v in params.items() if k not in ("lim", "off")})
            total = count_result.scalar() or 0

            nodes = [
                {
                    "id": r[0], "label": r[1], "description": r[2],
                    "fascination": r[3], "depth": r[4], "confidence": r[5],
                    "source": r[6], "status": r[7], "times_engaged": r[8],
                    "last_engaged_at": r[9].isoformat() if r[9] else None,
                    "created_at": r[10].isoformat() if r[10] else None,
                }
                for r in rows
            ]

            # Get all edges for these nodes
            node_ids = [n["id"] for n in nodes]
            if node_ids:
                edges_result = await db.execute(text("""
                    SELECT id, source_node_id, target_node_id, relationship,
                           description, strength
                    FROM acs_interest_edge
                    WHERE user_id = :uid
                      AND (source_node_id = ANY(:ids) OR target_node_id = ANY(:ids))
                """), {"uid": user_id, "ids": node_ids})
                edges = [
                    {
                        "id": r[0], "source_node_id": r[1], "target_node_id": r[2],
                        "relationship": r[3], "description": r[4], "strength": r[5],
                    }
                    for r in edges_result.fetchall()
                ]
            else:
                edges = []

            return {"nodes": nodes, "edges": edges, "total": total}

    async def get_node_with_neighborhood(self, node_id: str) -> Optional[Dict[str, Any]]:
        """Get a node and its immediate neighbors."""
        from app.db.session import get_async_session_factory

        async_session = get_async_session_factory()
        async with async_session() as db:
            result = await db.execute(text("""
                SELECT id, user_id, label, description, fascination, depth, confidence,
                       source, status, times_engaged, last_engaged_at, created_at
                FROM acs_interest_node WHERE id = :id
            """), {"id": node_id})
            row = result.fetchone()
            if not row:
                return None

            node = {
                "id": row[0], "user_id": row[1], "label": row[2], "description": row[3],
                "fascination": row[4], "depth": row[5], "confidence": row[6],
                "source": row[7], "status": row[8], "times_engaged": row[9],
                "last_engaged_at": row[10].isoformat() if row[10] else None,
                "created_at": row[11].isoformat() if row[11] else None,
            }

            # Get edges
            edges_result = await db.execute(text("""
                SELECT id, source_node_id, target_node_id, relationship, description, strength
                FROM acs_interest_edge
                WHERE source_node_id = :id OR target_node_id = :id
            """), {"id": node_id})
            edges = [
                {
                    "id": r[0], "source_node_id": r[1], "target_node_id": r[2],
                    "relationship": r[3], "description": r[4], "strength": r[5],
                }
                for r in edges_result.fetchall()
            ]

            # Get neighbor nodes
            neighbor_ids = set()
            for e in edges:
                neighbor_ids.add(e["source_node_id"])
                neighbor_ids.add(e["target_node_id"])
            neighbor_ids.discard(node_id)

            neighbors = []
            if neighbor_ids:
                nb_result = await db.execute(text("""
                    SELECT id, label, fascination, depth, status
                    FROM acs_interest_node WHERE id = ANY(:ids)
                """), {"ids": list(neighbor_ids)})
                neighbors = [
                    {"id": r[0], "label": r[1], "fascination": r[2], "depth": r[3], "status": r[4]}
                    for r in nb_result.fetchall()
                ]

            return {"node": node, "edges": edges, "neighbors": neighbors}

    async def archive_node(self, node_id: str) -> bool:
        """Archive a node (soft delete)."""
        from app.db.session import get_async_session_factory

        async_session = get_async_session_factory()
        async with async_session() as db:
            result = await db.execute(text("""
                UPDATE acs_interest_node SET status = 'archived', updated_at = NOW()
                WHERE id = :id
            """), {"id": node_id})
            await db.commit()
            return result.rowcount > 0

    async def sync_from_pkg(self, user_id: str) -> int:
        """Sync high-confidence PKG_Interest nodes into the interest graph.

        Creates interest nodes for PKG interests that Sara hasn't explored yet.
        Rate-limited to once per 24h via Redis cooldown.
        """
        import redis as sync_redis

        # Check 24h cooldown
        try:
            r = sync_redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)
            cooldown_key = f"sara:acs:pkg_sync_cooldown:{user_id}"
            if r.exists(cooldown_key):
                r.close()
                return 0
            r.set(cooldown_key, "1", ex=86400)
            r.close()
        except Exception:
            pass

        created = 0
        try:
            from app.services.personal_knowledge_graph import personal_kg
            interests = personal_kg.browse(category="Interest", limit=20)

            for interest in interests:
                topic = interest.get("topic", "")
                if not topic or len(topic) < 3:
                    continue

                confidence = interest.get("confidence", 0)
                if confidence < 0.7:
                    continue

                # Check if we already have this as an interest node
                existing = await self.find_by_label(user_id, topic)
                if existing:
                    continue

                # Create with moderate fascination — David cares, Sara hasn't explored
                result = await self.add_node(
                    user_id=user_id,
                    label=topic,
                    description=interest.get("description", f"David is interested in {topic}"),
                    source="pkg_sync",
                    fascination=0.4,
                )
                if result and not result.get("merged"):
                    created += 1

            if created:
                logger.info(f"PKG→interest graph sync: created {created} new nodes from PKG interests")

        except Exception as e:
            logger.debug(f"PKG→interest graph sync failed: {e}")

        return created

    async def get_frontier_nodes(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get top exploration candidates: high fascination, low depth."""
        from app.db.session import get_async_session_factory

        async_session = get_async_session_factory()
        async with async_session() as db:
            result = await db.execute(text("""
                SELECT id, label, description, fascination, depth, confidence,
                       times_engaged, last_engaged_at
                FROM acs_interest_node
                WHERE user_id = :uid AND status = 'active'
                ORDER BY (fascination - depth) DESC, fascination DESC
                LIMIT :lim
            """), {"uid": user_id, "lim": limit})
            return [
                {
                    "id": r[0], "label": r[1], "description": r[2],
                    "fascination": r[3], "depth": r[4], "confidence": r[5],
                    "times_engaged": r[6],
                    "last_engaged_at": r[7].isoformat() if r[7] else None,
                }
                for r in result.fetchall()
            ]
