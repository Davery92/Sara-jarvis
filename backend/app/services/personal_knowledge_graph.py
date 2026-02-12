"""
Personal Knowledge Graph (PKG) Service

Neo4j-based knowledge graph about David that Sara populates incrementally
from conversations. Stores preferences, routines, goals, relationships,
health data, places, and freeform facts with confidence tracking and
temporal versioning.
"""

import os
import json
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

# PKG node labels
PKG_LABELS = [
    "PKG_Person", "PKG_Preference", "PKG_Routine", "PKG_Goal",
    "PKG_Interest", "PKG_Health", "PKG_Place", "PKG_Fact"
]

# Base properties every PKG node gets
BASE_PROPERTIES = [
    "confidence", "source", "first_learned", "last_confirmed",
    "times_confirmed", "version", "superseded_by", "pkg_id"
]


class PersonalKnowledgeGraph:
    """
    Neo4j-based personal knowledge graph about David.

    All nodes are prefixed PKG_ to separate from the content graph (habits, notes, etc.).
    Every node carries confidence, source provenance, and temporal versioning.
    """

    def __init__(self):
        self.driver = None
        self._initialized = False

    def _ensure_driver(self):
        """Lazy-initialize Neo4j driver"""
        if self.driver is not None:
            return True
        try:
            from neo4j import GraphDatabase
            uri = os.getenv("NEO4J_URI", "bolt://10.185.1.180:7687")
            user = os.getenv("NEO4J_USER", "neo4j")
            password = os.getenv("NEO4J_PASSWORD", "sara-graph-secret")
            self.driver = GraphDatabase.driver(uri, auth=(user, password))
            logger.info("PKG: Neo4j driver initialized")
            return True
        except Exception as e:
            logger.warning(f"PKG: Neo4j not available: {e}")
            return False

    def initialize_schema(self):
        """Create constraints and indexes for PKG nodes"""
        if not self._ensure_driver():
            return False

        try:
            with self.driver.session() as session:
                # Unique constraint on pkg_id for each label
                for label in PKG_LABELS:
                    try:
                        session.run(f"""
                            CREATE CONSTRAINT {label.lower()}_pkg_id IF NOT EXISTS
                            FOR (n:{label}) REQUIRE n.pkg_id IS UNIQUE
                        """)
                    except Exception as e:
                        logger.debug(f"Constraint may already exist for {label}: {e}")

                # Indexes for common query patterns
                for label in PKG_LABELS:
                    try:
                        session.run(f"""
                            CREATE INDEX {label.lower()}_confidence IF NOT EXISTS
                            FOR (n:{label}) ON (n.confidence)
                        """)
                        session.run(f"""
                            CREATE INDEX {label.lower()}_source IF NOT EXISTS
                            FOR (n:{label}) ON (n.source)
                        """)
                    except Exception as e:
                        logger.debug(f"Index may already exist for {label}: {e}")

                # Specific indexes for common lookups
                index_pairs = [
                    ("PKG_Person", "name"),
                    ("PKG_Preference", "domain"),
                    ("PKG_Routine", "activity"),
                    ("PKG_Goal", "status"),
                    ("PKG_Interest", "topic"),
                    ("PKG_Health", "metric"),
                    ("PKG_Place", "name"),
                    ("PKG_Fact", "category"),
                ]
                for label, prop in index_pairs:
                    try:
                        session.run(f"""
                            CREATE INDEX {label.lower()}_{prop} IF NOT EXISTS
                            FOR (n:{label}) ON (n.{prop})
                        """)
                    except Exception:
                        pass

            self._initialized = True
            logger.info("PKG: Schema initialized successfully")
            return True
        except Exception as e:
            logger.error(f"PKG: Schema initialization failed: {e}")
            return False

    def upsert_fact(
        self,
        fact_type: str,
        properties: Dict[str, Any],
        confidence: float = 0.7,
        source: str = "inferred",
        dedup_key: Optional[str] = None
    ) -> Optional[str]:
        """
        MERGE a fact into the PKG. If a matching node exists, bump confidence.

        Args:
            fact_type: One of Person, Preference, Routine, Goal, Interest, Health, Place, Fact
            properties: Domain-specific properties for the node
            confidence: Initial confidence (0.0-1.0)
            source: One of dream_extraction, subconscious_extraction, explicit_statement, inferred
            dedup_key: Optional key for deduplication. If None, generates from properties.

        Returns:
            pkg_id of the upserted node, or None on failure
        """
        if not self._ensure_driver():
            return None

        label = f"PKG_{fact_type}"
        if label not in PKG_LABELS:
            logger.warning(f"PKG: Unknown fact type '{fact_type}', using PKG_Fact")
            label = "PKG_Fact"

        # Build dedup key from core identifying properties
        if not dedup_key:
            dedup_key = self._build_dedup_key(fact_type, properties)

        now = datetime.now(timezone.utc).isoformat()
        pkg_id = str(uuid.uuid4())

        try:
            with self.driver.session() as session:
                # Try to find existing node with same dedup_key
                result = session.run(f"""
                    MATCH (n:{label} {{dedup_key: $dedup_key}})
                    WHERE n.superseded_by IS NULL
                    RETURN n.pkg_id as pkg_id, n.confidence as confidence,
                           n.times_confirmed as times_confirmed
                """, {"dedup_key": dedup_key})

                existing = result.single()

                if existing:
                    # Confirmation: bump confidence and update
                    new_confidence = min(existing["confidence"] + 0.1, 0.99)
                    new_times = (existing["times_confirmed"] or 0) + 1

                    session.run(f"""
                        MATCH (n:{label} {{pkg_id: $pkg_id}})
                        SET n.confidence = $confidence,
                            n.last_confirmed = $now,
                            n.times_confirmed = $times_confirmed
                    """, {
                        "pkg_id": existing["pkg_id"],
                        "confidence": new_confidence,
                        "now": now,
                        "times_confirmed": new_times
                    })

                    # Also update any changed properties
                    if properties:
                        set_clauses = ", ".join(
                            f"n.{k} = ${k}" for k in properties.keys()
                            if k not in BASE_PROPERTIES and k != "dedup_key"
                        )
                        if set_clauses:
                            session.run(f"""
                                MATCH (n:{label} {{pkg_id: $pkg_id}})
                                SET {set_clauses}
                            """, {"pkg_id": existing["pkg_id"], **properties})

                    logger.debug(f"PKG: Confirmed {label} (dedup={dedup_key[:30]}, "
                               f"confidence {existing['confidence']:.2f} -> {new_confidence:.2f})")
                    return existing["pkg_id"]
                else:
                    # New fact: create node
                    all_props = {
                        **properties,
                        "pkg_id": pkg_id,
                        "dedup_key": dedup_key,
                        "confidence": confidence,
                        "source": source,
                        "first_learned": now,
                        "last_confirmed": now,
                        "times_confirmed": 1,
                        "version": 1,
                        "superseded_by": None
                    }

                    prop_assignments = ", ".join(f"n.{k} = ${k}" for k in all_props.keys())
                    session.run(f"""
                        CREATE (n:{label})
                        SET {prop_assignments}
                    """, all_props)

                    logger.debug(f"PKG: Created {label} (dedup={dedup_key[:30]}, confidence={confidence:.2f})")
                    return pkg_id

        except Exception as e:
            logger.error(f"PKG: upsert_fact failed: {e}")
            return None

    def supersede_fact(self, old_pkg_id: str, new_properties: Dict[str, Any],
                       fact_type: str, confidence: float = 0.8,
                       source: str = "explicit_statement") -> Optional[str]:
        """
        Supersede an existing fact with a new version (temporal versioning).
        Used when David says "I now prefer X" to replace "prefers Y".
        """
        if not self._ensure_driver():
            return None

        new_pkg_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        label = f"PKG_{fact_type}"

        try:
            with self.driver.session() as session:
                # Mark old as superseded
                session.run("""
                    MATCH (n {pkg_id: $old_id})
                    SET n.superseded_by = $new_id
                """, {"old_id": old_pkg_id, "new_id": new_pkg_id})

                # Create new version
                all_props = {
                    **new_properties,
                    "pkg_id": new_pkg_id,
                    "confidence": confidence,
                    "source": source,
                    "first_learned": now,
                    "last_confirmed": now,
                    "times_confirmed": 1,
                    "version": 1,
                    "superseded_by": None,
                    "dedup_key": self._build_dedup_key(fact_type, new_properties)
                }

                prop_assignments = ", ".join(f"n.{k} = ${k}" for k in all_props.keys())
                session.run(f"""
                    CREATE (n:{label})
                    SET {prop_assignments}
                """, all_props)

                logger.info(f"PKG: Superseded {old_pkg_id} with {new_pkg_id}")
                return new_pkg_id
        except Exception as e:
            logger.error(f"PKG: supersede_fact failed: {e}")
            return None

    def create_relationship(self, from_pkg_id: str, to_pkg_id: str,
                           rel_type: str, properties: Optional[Dict] = None) -> bool:
        """Create a relationship between two PKG nodes"""
        if not self._ensure_driver():
            return False

        try:
            with self.driver.session() as session:
                props = properties or {}
                prop_str = ""
                if props:
                    prop_str = " {" + ", ".join(f"{k}: ${k}" for k in props.keys()) + "}"

                session.run(f"""
                    MATCH (a {{pkg_id: $from_id}})
                    MATCH (b {{pkg_id: $to_id}})
                    MERGE (a)-[r:{rel_type}{prop_str}]->(b)
                """, {"from_id": from_pkg_id, "to_id": to_pkg_id, **props})
                return True
        except Exception as e:
            logger.error(f"PKG: create_relationship failed: {e}")
            return False

    def query_relevant(self, topics: List[str], limit: int = 10) -> List[Dict]:
        """
        Query PKG for nodes relevant to given topics.
        Uses text matching across key properties.
        """
        if not self._ensure_driver():
            return []

        try:
            with self.driver.session() as session:
                # Build topic matching with CONTAINS across key fields
                topic_conditions = []
                params = {"limit": limit}
                for i, topic in enumerate(topics):
                    key = f"topic_{i}"
                    params[key] = topic.lower()
                    topic_conditions.append(f"""
                        toLower(coalesce(n.name, '')) CONTAINS ${key} OR
                        toLower(coalesce(n.domain, '')) CONTAINS ${key} OR
                        toLower(coalesce(n.key, '')) CONTAINS ${key} OR
                        toLower(coalesce(n.value, '')) CONTAINS ${key} OR
                        toLower(coalesce(n.activity, '')) CONTAINS ${key} OR
                        toLower(coalesce(n.topic, '')) CONTAINS ${key} OR
                        toLower(coalesce(n.description, '')) CONTAINS ${key} OR
                        toLower(coalesce(n.subject, '')) CONTAINS ${key} OR
                        toLower(coalesce(n.predicate, '')) CONTAINS ${key} OR
                        toLower(coalesce(n.object, '')) CONTAINS ${key} OR
                        toLower(coalesce(n.metric, '')) CONTAINS ${key}
                    """)

                where_clause = " OR ".join(f"({c})" for c in topic_conditions)

                result = session.run(f"""
                    MATCH (n)
                    WHERE ({" OR ".join(f"n:{label}" for label in PKG_LABELS)})
                    AND n.superseded_by IS NULL
                    AND n.confidence > 0.3
                    AND ({where_clause})
                    RETURN labels(n) as labels, properties(n) as props
                    ORDER BY n.confidence DESC
                    LIMIT $limit
                """, params)

                return [
                    {
                        "type": self._extract_pkg_label(record["labels"]),
                        **{k: v for k, v in record["props"].items()
                           if k not in ("dedup_key",)}
                    }
                    for record in result
                ]
        except Exception as e:
            logger.error(f"PKG: query_relevant failed: {e}")
            return []

    def query_for_heartbeat(self, context: Dict) -> List[Dict]:
        """
        Query PKG for facts relevant to heartbeat decision-making.
        Uses context keys like time_of_day, day_of_week, current_activity.
        """
        if not self._ensure_driver():
            return []

        topics = []
        if "day_of_week" in context:
            topics.append(context["day_of_week"])
        if "time_of_day" in context:
            topics.append(context["time_of_day"])
        if "query" in context:
            topics.append(context["query"])

        if not topics:
            # Default: get high-confidence routines and goals
            return self._get_top_facts(["PKG_Routine", "PKG_Goal"], limit=5)

        return self.query_relevant(topics, limit=10)

    def decay_stale_knowledge(self, days_threshold: int = 90):
        """Reduce confidence on facts not confirmed in days_threshold days"""
        if not self._ensure_driver():
            return

        cutoff = (datetime.now(timezone.utc) - timedelta(days=days_threshold)).isoformat()

        try:
            with self.driver.session() as session:
                result = session.run(f"""
                    MATCH (n)
                    WHERE ({" OR ".join(f"n:{label}" for label in PKG_LABELS)})
                    AND n.superseded_by IS NULL
                    AND n.last_confirmed < $cutoff
                    AND n.confidence > 0.2
                    SET n.confidence = n.confidence * 0.9
                    RETURN count(n) as decayed
                """, {"cutoff": cutoff})

                record = result.single()
                if record and record["decayed"] > 0:
                    logger.info(f"PKG: Decayed {record['decayed']} stale facts "
                              f"(not confirmed in {days_threshold} days)")
        except Exception as e:
            logger.error(f"PKG: decay_stale_knowledge failed: {e}")

    def detect_contradictions(self, fact_type: str, properties: Dict) -> List[Dict]:
        """
        Find potentially conflicting existing facts.
        E.g., if new fact says "prefers tea", find existing "prefers coffee" in same domain.
        """
        if not self._ensure_driver():
            return []

        label = f"PKG_{fact_type}"
        dedup_key = self._build_dedup_key(fact_type, properties)

        try:
            with self.driver.session() as session:
                # Look for same-domain facts with different values
                if fact_type == "Preference" and "domain" in properties and "key" in properties:
                    result = session.run(f"""
                        MATCH (n:{label})
                        WHERE n.domain = $domain AND n.key = $key
                        AND n.superseded_by IS NULL
                        AND n.dedup_key <> $dedup_key
                        RETURN properties(n) as props
                    """, {
                        "domain": properties["domain"],
                        "key": properties["key"],
                        "dedup_key": dedup_key
                    })
                elif fact_type == "Routine" and "activity" in properties:
                    result = session.run(f"""
                        MATCH (n:{label})
                        WHERE n.activity = $activity
                        AND n.superseded_by IS NULL
                        AND n.dedup_key <> $dedup_key
                        RETURN properties(n) as props
                    """, {
                        "activity": properties["activity"],
                        "dedup_key": dedup_key
                    })
                elif fact_type == "Health" and "metric" in properties:
                    result = session.run(f"""
                        MATCH (n:{label})
                        WHERE n.metric = $metric
                        AND n.superseded_by IS NULL
                        AND n.dedup_key <> $dedup_key
                        RETURN properties(n) as props
                    """, {
                        "metric": properties["metric"],
                        "dedup_key": dedup_key
                    })
                else:
                    return []

                return [record["props"] for record in result]
        except Exception as e:
            logger.error(f"PKG: detect_contradictions failed: {e}")
            return []

    def get_david_summary(self, max_facts: int = 20) -> str:
        """Get a compressed text summary of what Sara knows about David"""
        if not self._ensure_driver():
            return ""

        try:
            with self.driver.session() as session:
                result = session.run(f"""
                    MATCH (n)
                    WHERE ({" OR ".join(f"n:{label}" for label in PKG_LABELS)})
                    AND n.superseded_by IS NULL
                    AND n.confidence > 0.5
                    RETURN labels(n) as labels, properties(n) as props
                    ORDER BY n.confidence DESC, n.last_confirmed DESC
                    LIMIT $limit
                """, {"limit": max_facts})

                lines = []
                for record in result:
                    label = self._extract_pkg_label(record["labels"])
                    props = record["props"]
                    line = self._format_fact_natural(label, props)
                    if line:
                        conf = props.get("confidence", 0)
                        conf_str = "high" if conf > 0.8 else "moderate" if conf > 0.6 else "low"
                        confirmed = props.get("times_confirmed", 1)
                        lines.append(f"- {line} (confidence: {conf_str}, confirmed {confirmed}x)")

                if not lines:
                    return ""

                return "## What Sara Knows About David\n" + "\n".join(lines)
        except Exception as e:
            logger.error(f"PKG: get_david_summary failed: {e}")
            return ""

    def browse(self, category: Optional[str] = None, limit: int = 50) -> List[Dict]:
        """Browse PKG nodes, optionally filtered by category"""
        if not self._ensure_driver():
            return []

        try:
            with self.driver.session() as session:
                if category:
                    label = f"PKG_{category}"
                    if label not in PKG_LABELS:
                        return []
                    result = session.run(f"""
                        MATCH (n:{label})
                        WHERE n.superseded_by IS NULL
                        RETURN labels(n) as labels, properties(n) as props
                        ORDER BY n.confidence DESC, n.last_confirmed DESC
                        LIMIT $limit
                    """, {"limit": limit})
                else:
                    result = session.run(f"""
                        MATCH (n)
                        WHERE ({" OR ".join(f"n:{label}" for label in PKG_LABELS)})
                        AND n.superseded_by IS NULL
                        RETURN labels(n) as labels, properties(n) as props
                        ORDER BY n.confidence DESC, n.last_confirmed DESC
                        LIMIT $limit
                    """, {"limit": limit})

                return [
                    {
                        "type": self._extract_pkg_label(record["labels"]),
                        **record["props"]
                    }
                    for record in result
                ]
        except Exception as e:
            logger.error(f"PKG: browse failed: {e}")
            return []

    def get_stats(self) -> Dict[str, Any]:
        """Get node counts and confidence distribution"""
        if not self._ensure_driver():
            return {}

        try:
            with self.driver.session() as session:
                stats = {"total": 0, "by_type": {}, "confidence_distribution": {}}

                for label in PKG_LABELS:
                    result = session.run(f"""
                        MATCH (n:{label})
                        WHERE n.superseded_by IS NULL
                        RETURN count(n) as cnt
                    """)
                    count = result.single()["cnt"]
                    short_name = label.replace("PKG_", "")
                    stats["by_type"][short_name] = count
                    stats["total"] += count

                # Confidence distribution
                result = session.run(f"""
                    MATCH (n)
                    WHERE ({" OR ".join(f"n:{label}" for label in PKG_LABELS)})
                    AND n.superseded_by IS NULL
                    RETURN
                        sum(CASE WHEN n.confidence >= 0.8 THEN 1 ELSE 0 END) as high,
                        sum(CASE WHEN n.confidence >= 0.5 AND n.confidence < 0.8 THEN 1 ELSE 0 END) as medium,
                        sum(CASE WHEN n.confidence < 0.5 THEN 1 ELSE 0 END) as low
                """)
                dist = result.single()
                stats["confidence_distribution"] = {
                    "high": dist["high"],
                    "medium": dist["medium"],
                    "low": dist["low"]
                }

                return stats
        except Exception as e:
            logger.error(f"PKG: get_stats failed: {e}")
            return {}

    def get_graph_data(self, limit: int = 100) -> Dict[str, Any]:
        """Get graph data for visualization (nodes + relationships)"""
        if not self._ensure_driver():
            return {"nodes": [], "edges": []}

        try:
            with self.driver.session() as session:
                # Get nodes
                result = session.run(f"""
                    MATCH (n)
                    WHERE ({" OR ".join(f"n:{label}" for label in PKG_LABELS)})
                    AND n.superseded_by IS NULL
                    RETURN labels(n) as labels, properties(n) as props
                    ORDER BY n.confidence DESC
                    LIMIT $limit
                """, {"limit": limit})

                nodes = []
                node_ids = set()
                for record in result:
                    pkg_id = record["props"].get("pkg_id")
                    if pkg_id:
                        node_ids.add(pkg_id)
                        nodes.append({
                            "id": pkg_id,
                            "type": self._extract_pkg_label(record["labels"]),
                            **{k: v for k, v in record["props"].items()
                               if k not in ("dedup_key",)}
                        })

                # Get relationships between these nodes
                edges = []
                if node_ids:
                    result = session.run("""
                        MATCH (a)-[r]->(b)
                        WHERE a.pkg_id IN $ids AND b.pkg_id IN $ids
                        RETURN a.pkg_id as source, b.pkg_id as target,
                               type(r) as rel_type, properties(r) as props
                    """, {"ids": list(node_ids)})

                    for record in result:
                        edges.append({
                            "source": record["source"],
                            "target": record["target"],
                            "type": record["rel_type"],
                            **(record["props"] or {})
                        })

                return {"nodes": nodes, "edges": edges}
        except Exception as e:
            logger.error(f"PKG: get_graph_data failed: {e}")
            return {"nodes": [], "edges": []}

    def delete_node(self, pkg_id: str) -> bool:
        """Delete a PKG node and its relationships"""
        if not self._ensure_driver():
            return False

        try:
            with self.driver.session() as session:
                session.run("""
                    MATCH (n {pkg_id: $pkg_id})
                    DETACH DELETE n
                """, {"pkg_id": pkg_id})
                logger.info(f"PKG: Deleted node {pkg_id}")
                return True
        except Exception as e:
            logger.error(f"PKG: delete_node failed: {e}")
            return False

    def update_node(self, pkg_id: str, updates: Dict[str, Any]) -> bool:
        """Update properties of a PKG node"""
        if not self._ensure_driver():
            return False

        try:
            with self.driver.session() as session:
                # Don't allow updating protected fields
                safe_updates = {k: v for k, v in updates.items()
                               if k not in ("pkg_id", "dedup_key", "first_learned")}
                if not safe_updates:
                    return False

                set_clauses = ", ".join(f"n.{k} = ${k}" for k in safe_updates.keys())
                session.run(f"""
                    MATCH (n {{pkg_id: $pkg_id}})
                    SET {set_clauses}
                """, {"pkg_id": pkg_id, **safe_updates})
                return True
        except Exception as e:
            logger.error(f"PKG: update_node failed: {e}")
            return False

    # --- Private helpers ---

    def _build_dedup_key(self, fact_type: str, properties: Dict) -> str:
        """Build a deduplication key from the identifying properties of a fact"""
        if fact_type == "Person":
            return f"person:{properties.get('name', '').lower()}"
        elif fact_type == "Preference":
            return f"pref:{properties.get('domain', '')}:{properties.get('key', '')}".lower()
        elif fact_type == "Routine":
            return f"routine:{properties.get('activity', '')}:{properties.get('day_of_week', '')}".lower()
        elif fact_type == "Goal":
            return f"goal:{properties.get('description', '')[:50]}".lower()
        elif fact_type == "Interest":
            return f"interest:{properties.get('topic', '')}".lower()
        elif fact_type == "Health":
            return f"health:{properties.get('metric', '')}".lower()
        elif fact_type == "Place":
            return f"place:{properties.get('name', '')}:{properties.get('type', '')}".lower()
        elif fact_type == "Fact":
            return f"fact:{properties.get('subject', '')}:{properties.get('predicate', '')}:{properties.get('object', '')}".lower()
        else:
            return f"unknown:{json.dumps(properties, sort_keys=True)[:80]}".lower()

    def _extract_pkg_label(self, labels: List[str]) -> str:
        """Extract the PKG_ label from a list of node labels"""
        for label in labels:
            if label.startswith("PKG_"):
                return label.replace("PKG_", "")
        return "Unknown"

    def _format_fact_natural(self, label: str, props: Dict) -> str:
        """Format a PKG fact as natural language"""
        if label == "Person":
            name = props.get("name", "unknown")
            rel = props.get("relationship_to_david", "")
            notes = props.get("notes", "")
            parts = [name]
            if rel:
                parts.append(f"— {rel}")
            if notes:
                parts.append(f"({notes})")
            return " ".join(parts)
        elif label == "Preference":
            domain = props.get("domain", "")
            key = props.get("key", "")
            value = props.get("value", "")
            strength = props.get("strength", "")
            return f"David {'loves' if strength == 'love' else 'prefers'} {value} ({domain}/{key})"
        elif label == "Routine":
            activity = props.get("activity", "")
            time = props.get("typical_time", "")
            day = props.get("day_of_week", "")
            freq = props.get("frequency", "")
            parts = [f"David {activity}"]
            if day:
                parts.append(f"on {day}")
            if time:
                parts.append(f"at {time}")
            if freq:
                parts.append(f"({freq})")
            return " ".join(parts)
        elif label == "Goal":
            desc = props.get("description", "")
            status = props.get("status", "active")
            return f"Goal: {desc} (status: {status})"
        elif label == "Interest":
            topic = props.get("topic", "")
            depth = props.get("depth", "")
            return f"Interested in {topic}" + (f" (depth: {depth})" if depth else "")
        elif label == "Health":
            metric = props.get("metric", "")
            value = props.get("current_value", "")
            trend = props.get("trend", "")
            return f"{metric}: {value}" + (f" (trend: {trend})" if trend else "")
        elif label == "Place":
            name = props.get("name", "")
            ptype = props.get("type", "")
            sig = props.get("significance", "")
            return f"{name} ({ptype})" + (f" — {sig}" if sig else "")
        elif label == "Fact":
            return f"{props.get('subject', '')} {props.get('predicate', '')} {props.get('object', '')}"
        return str(props)

    def _get_top_facts(self, labels: List[str], limit: int = 5) -> List[Dict]:
        """Get top-confidence facts from specific labels"""
        if not self._ensure_driver():
            return []

        try:
            with self.driver.session() as session:
                label_clause = " OR ".join(f"n:{l}" for l in labels)
                result = session.run(f"""
                    MATCH (n)
                    WHERE ({label_clause})
                    AND n.superseded_by IS NULL
                    AND n.confidence > 0.5
                    RETURN labels(n) as labels, properties(n) as props
                    ORDER BY n.confidence DESC
                    LIMIT $limit
                """, {"limit": limit})

                return [
                    {
                        "type": self._extract_pkg_label(record["labels"]),
                        **record["props"]
                    }
                    for record in result
                ]
        except Exception as e:
            logger.error(f"PKG: _get_top_facts failed: {e}")
            return []

    def close(self):
        """Close Neo4j driver"""
        if self.driver:
            self.driver.close()
            self.driver = None


# Singleton instance
personal_kg = PersonalKnowledgeGraph()
