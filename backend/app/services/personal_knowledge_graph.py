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
import re
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any

from app.services.silent_failure_tracker import Tracker

logger = logging.getLogger(__name__)

# Trackers surface PKG fire-and-forget failures in /debug/retrieval-funnel.
# Without these, a stuck embedding service or a broken Neo4j write shows up
# only as "why is semantic recall returning nothing?" hours later.
_PKG_EMBEDDING_TRACKER = Tracker("pkg.embedding")
_PKG_UPSERT_TRACKER = Tracker("pkg.upsert_fact")
_PKG_NEO4J_TRACKER = Tracker("pkg.neo4j_sync")

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

# Statuses that mean the fact is "closed" — historical, not currently relevant.
# Context-building queries should exclude these so stale items don't keep
# showing up in chat prompts.
PKG_CLOSED_STATUSES = ["completed", "abandoned", "archived", "stale"]

# Cypher snippet — exclude closed facts and past-target_date goals.
# Use as: ... AND (n.superseded_by IS NULL) AND ({PKG_FRESH_FILTER})
# `target_date` is a stored ISO-8601 string, so a lex comparison against
# today (as ISO) does the right thing for date-like strings.
PKG_FRESH_FILTER = (
    "(n.status IS NULL OR NOT toLower(n.status) IN $closed_statuses) "
    "AND (NOT 'PKG_Goal' IN labels(n) OR n.target_date IS NULL "
    "OR n.target_date >= $today_iso)"
)


def _pkg_fresh_params() -> dict:
    """Params bound by the PKG_FRESH_FILTER snippet."""
    from datetime import datetime, timezone, timedelta
    # Allow goals within the last 24 hours (covers "today's call" being mentioned)
    cutoff = datetime.now(timezone.utc) - timedelta(days=1)
    return {
        "closed_statuses": PKG_CLOSED_STATUSES,
        "today_iso": cutoff.isoformat(),
    }


def _to_psycopg3_url(database_url: str) -> str:
    """Force a ``postgresql+psycopg://`` (psycopg3) URL.

    The async engine factory uses ``+asyncpg`` URLs. Everywhere this file
    opens a sync engine it used to strip the driver suffix and fall back
    to bare ``postgresql://``, which defaults to psycopg2. psycopg2 isn't
    installed in this project, so every on-demand PKG DB call silently
    hit ``ModuleNotFoundError``. One helper, one correct answer.
    """
    if not database_url:
        return database_url
    if "postgresql+asyncpg://" in database_url:
        return database_url.replace("postgresql+asyncpg://", "postgresql+psycopg://")
    if database_url.startswith("postgresql+psycopg://"):
        return database_url
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


class PersonalKnowledgeGraph:
    """
    Neo4j-based personal knowledge graph about David.

    All nodes are prefixed PKG_ to separate from the content graph (habits, notes, etc.).
    Every node carries confidence, source provenance, and temporal versioning.
    """

    # On-demand backfill rate limit. Without this, a flurry of zero-result
    # semantic queries would each trigger their own Neo4j-heavy backfill run.
    _last_backfill_attempt: float = 0.0
    _BACKFILL_COOLDOWN_SEC: float = 300.0  # 5 minutes

    def __init__(self):
        self.driver = None
        self._initialized = False

    def _maybe_schedule_backfill(self, reason: str = "") -> None:
        """Fire-and-forget backfill, gated by a class-level cooldown.

        Called when ``query_semantic`` hits a zero-match — common failure
        mode is that pkg_embedding is missing rows for nodes Neo4j has.
        The regular hourly reconcile will eventually catch it, but that
        leaves Sara looking forgetful for up to an hour.
        """
        import time as _time
        import asyncio as _asyncio
        now = _time.monotonic()
        if now - type(self)._last_backfill_attempt < self._BACKFILL_COOLDOWN_SEC:
            return  # still cooling down
        type(self)._last_backfill_attempt = now

        try:
            loop = _asyncio.get_running_loop()
        except RuntimeError:
            # No event loop — not much we can do from sync context.
            _PKG_EMBEDDING_TRACKER.note(f"backfill_skipped_no_loop:{reason}")
            return

        async def _run_backfill():
            try:
                # backfill_embeddings is async; awaiting directly keeps us
                # on the current event loop. to_thread would give us a
                # coroutine object instead of running it.
                count = await self.backfill_embeddings()
                if count:
                    logger.info(
                        f"PKG: on-demand backfill ({reason}) filled {count} nodes"
                    )
                else:
                    logger.debug(f"PKG: on-demand backfill ({reason}) found no gaps")
            except Exception as exc:
                _PKG_EMBEDDING_TRACKER.note(f"backfill_failed:{type(exc).__name__}")

        loop.create_task(_run_backfill())

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
                           n.times_confirmed as times_confirmed,
                           n.status as status
                """, {"dedup_key": dedup_key})

                existing = result.single()

                if existing:
                    # Don't resurrect closed facts. If the existing node was
                    # explicitly marked completed/abandoned/archived/stale, a
                    # later mention shouldn't bump confidence or last_confirmed
                    # — that just keeps stale items at the top of context. We
                    # still allow explicit property updates if the caller
                    # passes new fields, but the timestamp stays frozen.
                    closed_statuses = {"completed", "abandoned", "archived", "stale"}
                    is_closed = (existing.get("status") or "").lower() in closed_statuses

                    if is_closed:
                        logger.debug(
                            f"PKG: skipping confirmation bump for closed {label} "
                            f"(status={existing.get('status')}, dedup={dedup_key[:30]})"
                        )
                        # Still allow explicit non-base property updates if any.
                        if properties:
                            set_clauses = ", ".join(
                                f"n.{k} = ${k}" for k in properties.keys()
                                if k not in BASE_PROPERTIES and k != "dedup_key" and k != "status"
                            )
                            if set_clauses:
                                session.run(f"""
                                    MATCH (n:{label} {{pkg_id: $pkg_id}})
                                    SET {set_clauses}
                                """, {"pkg_id": existing["pkg_id"], **properties})
                        return existing["pkg_id"]

                    # Confirmation: record the repeat observation, but do NOT
                    # bump confidence here (Arc 5.2 minter ruling — any path
                    # may mint at entry tier, but only dreaming promotes;
                    # this was the one structural violation: every minter
                    # that calls upsert_fact, dreaming or not, was silently
                    # promoting confidence on every repeat match).
                    # promote_corroborated_facts() is the dreaming-only
                    # place confidence now moves upward, reading the
                    # times_confirmed count this still increments.
                    new_times = (existing["times_confirmed"] or 0) + 1

                    session.run(f"""
                        MATCH (n:{label} {{pkg_id: $pkg_id}})
                        SET n.last_confirmed = $now,
                            n.times_confirmed = $times_confirmed
                    """, {
                        "pkg_id": existing["pkg_id"],
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
                               f"confidence unchanged at {existing['confidence']:.2f}, "
                               f"times_confirmed -> {new_times})")
                    # Update embedding in background
                    self._schedule_embedding(existing["pkg_id"], fact_type, properties, existing["confidence"])
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
                    # Store embedding in background
                    self._schedule_embedding(pkg_id, fact_type, properties, confidence)
                    return pkg_id

        except Exception as e:
            _PKG_UPSERT_TRACKER.note(f"exception:{type(e).__name__}")
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

                params.update(_pkg_fresh_params())
                result = session.run(f"""
                    MATCH (n)
                    WHERE ({" OR ".join(f"n:{label}" for label in PKG_LABELS)})
                    AND n.superseded_by IS NULL
                    AND n.confidence > 0.3
                    AND ({PKG_FRESH_FILTER})
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

    def promote_corroborated_facts(
        self, min_confirmations_for_inferred: int = 3, min_confirmations_for_confirmed: int = 8
    ) -> int:
        """Arc 5.2 minter ruling: 'any path may mint facts at entry tiers
        (observed/inferred) provided it goes through confidence_ladder with
        provenance — but dreaming is the sole promotion authority: only it
        graduates, decays, consolidates, prunes.' This is that promotion
        authority — the ONLY place PKG confidence increases now.
        upsert_fact() used to bump confidence by +0.1 on every repeat
        confirmation, from ANY caller (dreaming or not) — the one
        structural violation the audit found; fixed by having
        upsert_fact() only record the observation (times_confirmed,
        last_confirmed) and leaving graduation to here.

        Idempotent by construction: promotion sets confidence TO a tier
        floor (INFERRED_AT / CONFIRMED_AT) rather than adding to it, so a
        fact that's already cleared a floor never re-triggers on the same
        threshold being crossed again — only the next, higher one. Call
        this from the dreaming cycle only. Returns the number promoted."""
        from app.services.confidence_ladder import CONFIRMED_AT, INFERRED_AT

        if not self._ensure_driver():
            return 0
        try:
            with self.driver.session() as session:
                promoted = 0
                # observed -> inferred
                rec = session.run(f"""
                    MATCH (n)
                    WHERE ({" OR ".join(f"n:{label}" for label in PKG_LABELS)})
                    AND n.superseded_by IS NULL
                    AND n.confidence < {INFERRED_AT}
                    AND n.times_confirmed >= $min_confirmations
                    SET n.confidence = {INFERRED_AT}
                    RETURN count(n) as promoted
                """, {"min_confirmations": min_confirmations_for_inferred}).single()
                promoted += (rec["promoted"] if rec else 0) or 0

                # inferred -> confirmed
                rec = session.run(f"""
                    MATCH (n)
                    WHERE ({" OR ".join(f"n:{label}" for label in PKG_LABELS)})
                    AND n.superseded_by IS NULL
                    AND n.confidence >= {INFERRED_AT} AND n.confidence < {CONFIRMED_AT}
                    AND n.times_confirmed >= $min_confirmations
                    SET n.confidence = {CONFIRMED_AT}
                    RETURN count(n) as promoted
                """, {"min_confirmations": min_confirmations_for_confirmed}).single()
                promoted += (rec["promoted"] if rec else 0) or 0

                if promoted:
                    logger.info(f"PKG: promoted {promoted} well-corroborated facts (dreaming-only)")
                return promoted
        except Exception as e:
            logger.error(f"PKG: promote_corroborated_facts failed: {e}")
            return 0

    def validate_against_recent(self, db_session=None) -> Dict[str, Any]:
        """
        Validate active PKG facts against recent episode content.

        Queries all active (non-superseded) PKG nodes (up to 200), then checks
        30 days of episodes for confirmations, contradictions, or staleness.

        No LLM calls — uses keyword matching and negation pattern detection.

        Args:
            db_session: Optional SQLAlchemy session. If None, creates one.

        Returns:
            {confirmed: int, contradictions: [...], stale: int, total_checked: int}
        """
        if not self._ensure_driver():
            return {"confirmed": 0, "contradictions": [], "stale": 0, "total_checked": 0}

        # 1. Fetch all active PKG nodes
        try:
            with self.driver.session() as neo_session:
                result = neo_session.run(f"""
                    MATCH (n)
                    WHERE ({" OR ".join(f"n:{label}" for label in PKG_LABELS)})
                    AND n.superseded_by IS NULL
                    RETURN labels(n) as labels, properties(n) as props
                    ORDER BY n.confidence DESC
                    LIMIT 200
                """)
                nodes = []
                for record in result:
                    nodes.append({
                        "type": self._extract_pkg_label(record["labels"]),
                        "props": dict(record["props"]),
                    })
        except Exception as e:
            logger.error(f"PKG: validate_against_recent — Neo4j query failed: {e}")
            return {"confirmed": 0, "contradictions": [], "stale": 0, "total_checked": 0}

        if not nodes:
            return {"confirmed": 0, "contradictions": [], "stale": 0, "total_checked": 0}

        # 2. Fetch recent episode content from PostgreSQL
        episode_texts = self._fetch_recent_episodes(db_session, days=30)

        # 3. For each fact, check against episode content
        now = datetime.now(timezone.utc)
        stale_cutoff = now - timedelta(days=60)
        confirmed = 0
        contradictions = []
        stale = 0

        # Negation patterns that suggest a fact has changed
        NEGATION_PATTERNS = [
            r"(?:don'?t|doesn'?t|do not|does not)\s+(?:like|want|enjoy|prefer|use|do|eat|drink)",
            r"(?:stopped|quit|gave up|no longer|not anymore|switched from|changed to)",
            r"(?:hate|hates|dislike|dislikes|can'?t stand)",
            r"(?:used to|formerly|previously)\s+(?:like|enjoy|prefer|do)",
            r"(?:actually|now)\s+(?:prefer|like|enjoy|want|use)",
        ]
        negation_re = re.compile("|".join(NEGATION_PATTERNS), re.IGNORECASE)

        for node in nodes:
            props = node["props"]
            pkg_id = props.get("pkg_id")
            if not pkg_id:
                continue

            # Extract searchable terms from the fact
            terms = self._extract_search_terms(node["type"], props)
            if not terms:
                continue

            # Search episodes for term mentions
            found_mention = False
            found_contradiction = False
            contradiction_evidence = ""

            for episode_content in episode_texts:
                content_lower = episode_content.lower()

                # Check if any key terms appear in episode content
                matching_terms = [t for t in terms if t.lower() in content_lower]
                if not matching_terms:
                    continue

                found_mention = True

                # Check for negation patterns near the matching terms
                for term in matching_terms:
                    # Find positions of the term in content
                    term_lower = term.lower()
                    idx = content_lower.find(term_lower)
                    while idx != -1:
                        # Check surrounding context (100 chars before and after)
                        start = max(0, idx - 100)
                        end = min(len(episode_content), idx + len(term) + 100)
                        context_window = episode_content[start:end]

                        if negation_re.search(context_window):
                            found_contradiction = True
                            contradiction_evidence = context_window.strip()[:200]
                            break

                        idx = content_lower.find(term_lower, idx + 1)

                    if found_contradiction:
                        break
                if found_contradiction:
                    break

            # Apply results
            if found_contradiction:
                fact_summary = self._format_fact_natural(node["type"], props)
                contradictions.append({
                    "node_id": pkg_id,
                    "fact_type": node["type"],
                    "fact_summary": fact_summary,
                    "contradiction_evidence": contradiction_evidence,
                    "confidence": props.get("confidence", 0),
                })
                # Flag the node in Neo4j
                try:
                    with self.driver.session() as neo_session:
                        neo_session.run("""
                            MATCH (n {pkg_id: $pkg_id})
                            SET n.needs_review = true,
                                n.review_reason = 'contradiction_detected',
                                n.review_evidence = $evidence,
                                n.review_flagged_at = $now
                        """, {
                            "pkg_id": pkg_id,
                            "evidence": contradiction_evidence[:500],
                            "now": now.isoformat(),
                        })
                except Exception as e:
                    logger.debug(f"PKG: Failed to flag node {pkg_id}: {e}")

            elif found_mention:
                # Fact is confirmed — bump confidence slightly
                confirmed += 1
                try:
                    with self.driver.session() as neo_session:
                        neo_session.run("""
                            MATCH (n {pkg_id: $pkg_id})
                            SET n.confidence = CASE
                                WHEN n.confidence + 0.05 > 0.99 THEN 0.99
                                ELSE n.confidence + 0.05
                            END,
                            n.last_confirmed = $now
                        """, {"pkg_id": pkg_id, "now": now.isoformat()})
                except Exception as e:
                    logger.debug(f"PKG: Failed to confirm node {pkg_id}: {e}")

            else:
                # Fact not mentioned at all — check if it's stale
                last_confirmed = props.get("last_confirmed", "")
                if last_confirmed:
                    try:
                        # Handle both datetime and string
                        if isinstance(last_confirmed, str):
                            lc_dt = datetime.fromisoformat(last_confirmed.replace("Z", "+00:00"))
                        else:
                            lc_dt = last_confirmed
                        if lc_dt.tzinfo is None:
                            lc_dt = lc_dt.replace(tzinfo=timezone.utc)
                        if lc_dt < stale_cutoff:
                            stale += 1
                            # Reduce confidence slightly for stale facts
                            try:
                                with self.driver.session() as neo_session:
                                    neo_session.run("""
                                        MATCH (n {pkg_id: $pkg_id})
                                        WHERE n.confidence > 0.2
                                        SET n.confidence = n.confidence - 0.05
                                    """, {"pkg_id": pkg_id})
                            except Exception as e:
                                logger.debug(f"PKG: Failed to decay stale node {pkg_id}: {e}")
                    except (ValueError, TypeError):
                        pass  # Unparseable timestamp, skip

        report = {
            "confirmed": confirmed,
            "contradictions": contradictions,
            "stale": stale,
            "total_checked": len(nodes),
            "validated_at": now.isoformat(),
        }

        logger.info(
            f"PKG: Validation complete — {confirmed} confirmed, "
            f"{len(contradictions)} contradictions, {stale} stale "
            f"(of {len(nodes)} checked)"
        )
        return report

    def get_needs_review(self) -> List[Dict]:
        """
        Return all PKG nodes flagged with needs_review = true.
        Used by the UI to show items needing human verification.
        """
        if not self._ensure_driver():
            return []

        try:
            with self.driver.session() as session:
                result = session.run(f"""
                    MATCH (n)
                    WHERE ({" OR ".join(f"n:{label}" for label in PKG_LABELS)})
                    AND n.superseded_by IS NULL
                    AND n.needs_review = true
                    RETURN labels(n) as labels, properties(n) as props
                    ORDER BY n.review_flagged_at DESC
                """)

                items = []
                for record in result:
                    props = dict(record["props"])
                    items.append({
                        "type": self._extract_pkg_label(record["labels"]),
                        "pkg_id": props.get("pkg_id"),
                        "fact_summary": self._format_fact_natural(
                            self._extract_pkg_label(record["labels"]), props
                        ),
                        "review_reason": props.get("review_reason", "unknown"),
                        "review_evidence": props.get("review_evidence", ""),
                        "review_flagged_at": props.get("review_flagged_at", ""),
                        "confidence": props.get("confidence", 0),
                        **{k: v for k, v in props.items()
                           if k not in ("dedup_key", "needs_review",
                                        "review_reason", "review_evidence",
                                        "review_flagged_at")},
                    })

                return items
        except Exception as e:
            logger.error(f"PKG: get_needs_review failed: {e}")
            return []

    def mark_reviewed(self, pkg_id: str, new_confidence: Optional[float] = None) -> bool:
        """
        Clear the needs_review flag after a user reviews a fact.
        Optionally update confidence if the user adjusts it.

        Args:
            pkg_id: The PKG node ID
            new_confidence: Optional new confidence value (0.0–1.0)

        Returns:
            True on success
        """
        if not self._ensure_driver():
            return False

        try:
            now = datetime.now(timezone.utc).isoformat()
            with self.driver.session() as session:
                if new_confidence is not None:
                    new_confidence = min(max(new_confidence, 0.0), 0.99)
                    session.run("""
                        MATCH (n {pkg_id: $pkg_id})
                        SET n.needs_review = false,
                            n.confidence = $confidence,
                            n.last_confirmed = $now
                        REMOVE n.review_reason, n.review_evidence, n.review_flagged_at
                    """, {
                        "pkg_id": pkg_id,
                        "confidence": new_confidence,
                        "now": now,
                    })
                else:
                    session.run("""
                        MATCH (n {pkg_id: $pkg_id})
                        SET n.needs_review = false,
                            n.last_confirmed = $now
                        REMOVE n.review_reason, n.review_evidence, n.review_flagged_at
                    """, {"pkg_id": pkg_id, "now": now})

                logger.info(f"PKG: Marked {pkg_id} as reviewed"
                           + (f" (confidence={new_confidence})" if new_confidence is not None else ""))
                return True
        except Exception as e:
            logger.error(f"PKG: mark_reviewed failed: {e}")
            return False

    def _extract_search_terms(self, fact_type: str, props: Dict) -> List[str]:
        """
        Extract key terms from a PKG fact for text-matching against episodes.
        Returns a list of terms that are meaningful enough to search for.
        """
        terms = []

        # Type-specific key fields
        if fact_type == "Person":
            name = props.get("name", "")
            if name and len(name) >= 2:
                terms.append(name)

        elif fact_type == "Preference":
            value = props.get("value", "")
            key = props.get("key", "")
            if value and len(value) >= 3:
                terms.append(value)
            if key and len(key) >= 3:
                terms.append(key)

        elif fact_type == "Routine":
            activity = props.get("activity", "")
            if activity and len(activity) >= 3:
                terms.append(activity)

        elif fact_type == "Goal":
            desc = props.get("description", "")
            if desc:
                # Extract significant words from goal description
                words = [w for w in desc.split() if len(w) >= 4]
                terms.extend(words[:3])

        elif fact_type == "Interest":
            topic = props.get("topic", "")
            if topic and len(topic) >= 3:
                terms.append(topic)

        elif fact_type == "Health":
            metric = props.get("metric", "")
            if metric and len(metric) >= 3:
                terms.append(metric)

        elif fact_type == "Place":
            name = props.get("name", "")
            if name and len(name) >= 3:
                terms.append(name)

        elif fact_type == "Fact":
            subject = props.get("subject", "")
            obj = props.get("object", "")
            if subject and len(subject) >= 3:
                terms.append(subject)
            if obj and len(obj) >= 3:
                terms.append(obj)

        # Also check generic value/name fields
        for field in ("name", "value", "topic", "activity", "metric"):
            val = props.get(field, "")
            if val and len(val) >= 3 and val not in terms:
                terms.append(val)

        # Deduplicate
        seen = set()
        unique_terms = []
        for t in terms:
            t_lower = t.lower()
            if t_lower not in seen:
                seen.add(t_lower)
                unique_terms.append(t)

        return unique_terms

    def _fetch_recent_episodes(self, db_session=None, days: int = 30) -> List[str]:
        """
        Fetch recent episode content from PostgreSQL.
        Returns a list of episode content strings.
        """
        from sqlalchemy import text as sa_text

        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        # If a synchronous session is provided, use it
        if db_session is not None:
            try:
                rows = db_session.execute(sa_text("""
                    SELECT content FROM episode
                    WHERE created_at >= :since
                    AND content IS NOT NULL
                    ORDER BY created_at DESC
                    LIMIT 500
                """), {"since": since}).fetchall()
                return [row.content for row in rows if row.content]
            except Exception as e:
                logger.error(f"PKG: _fetch_recent_episodes (sync) failed: {e}")
                return []

        # Otherwise create our own sync session
        try:
            # Keep psycopg3 driver — bare postgresql:// defaults to psycopg2,
            # which isn't installed. Use project-wide psycopg3 suffix.
            database_url = _to_psycopg3_url(os.getenv("DATABASE_URL", ""))

            from sqlalchemy import create_engine
            engine = create_engine(database_url, echo=False)
            from sqlalchemy.orm import sessionmaker as sync_sessionmaker
            Session = sync_sessionmaker(bind=engine)
            session = Session()
            try:
                rows = session.execute(sa_text("""
                    SELECT content FROM episode
                    WHERE created_at >= :since
                    AND content IS NOT NULL
                    ORDER BY created_at DESC
                    LIMIT 500
                """), {"since": since}).fetchall()
                return [row.content for row in rows if row.content]
            finally:
                session.close()
                engine.dispose()
        except Exception as e:
            logger.error(f"PKG: _fetch_recent_episodes (own session) failed: {e}")
            return []

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
                params = {"limit": max_facts, **_pkg_fresh_params()}
                result = session.run(f"""
                    MATCH (n)
                    WHERE ({" OR ".join(f"n:{label}" for label in PKG_LABELS)})
                    AND n.superseded_by IS NULL
                    AND n.confidence > 0.5
                    AND ({PKG_FRESH_FILTER})
                    RETURN labels(n) as labels, properties(n) as props
                    ORDER BY n.confidence DESC, n.last_confirmed DESC
                    LIMIT $limit
                """, params)

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

    def decay_node_confidence(self, pkg_id: str, factor: float = 0.8) -> Optional[float]:
        """Multiply a single node's confidence by `factor` (P4 routine decay).

        Returns the new confidence, or None on failure. Used by the routine
        corroboration sweep to gradually demote a routine whose calendar
        support has dried up before retiring it outright.
        """
        if not self._ensure_driver():
            return None
        try:
            with self.driver.session() as session:
                rec = session.run(f"""
                    MATCH (n) WHERE n.pkg_id = $pkg_id
                    AND ({" OR ".join(f"n:{label}" for label in PKG_LABELS)})
                    SET n.confidence = n.confidence * $factor
                    RETURN n.confidence AS confidence
                """, {"pkg_id": pkg_id, "factor": factor}).single()
                return float(rec["confidence"]) if rec else None
        except Exception as e:
            logger.warning(f"PKG: decay_node_confidence failed for {pkg_id}: {e}")
            return None

    def get_node_status(self, pkg_id: str) -> Optional[Dict[str, Any]]:
        """Confidence + needs_review for one node, by pkg_id. Used by the
        verification loop to decide whether a fact is still unresolved
        regardless of which of the two ways it got flagged (a genuine
        needs_review contradiction, or just low confidence) — mark_reviewed
        and the other single-node helpers here don't need this since they
        only ever write, but resolving "is there still something to
        retire against" needs a read first."""
        if not self._ensure_driver():
            return None
        try:
            with self.driver.session() as session:
                rec = session.run(f"""
                    MATCH (n) WHERE n.pkg_id = $pkg_id
                    AND ({" OR ".join(f"n:{label}" for label in PKG_LABELS)})
                    RETURN n.confidence AS confidence, n.needs_review AS needs_review
                """, {"pkg_id": pkg_id}).single()
                if not rec:
                    return None
                return {
                    "confidence": float(rec["confidence"]) if rec["confidence"] is not None else 0.5,
                    "needs_review": bool(rec["needs_review"]),
                }
        except Exception as e:
            logger.warning(f"PKG: get_node_status failed for {pkg_id}: {e}")
            return None

    def retire_node(self, pkg_id: str) -> bool:
        """Permanently retire a PKG node: DETACH DELETE in Neo4j AND drop its
        pkg_embedding shadow row, together (P4). A node deleted from only one
        store is exactly the immortal-fact bug this fixes.
        """
        ok_graph = False
        if self._ensure_driver():
            try:
                with self.driver.session() as session:
                    session.run(f"""
                        MATCH (n) WHERE n.pkg_id = $pkg_id
                        AND ({" OR ".join(f"n:{label}" for label in PKG_LABELS)})
                        DETACH DELETE n
                    """, {"pkg_id": pkg_id})
                    ok_graph = True
            except Exception as e:
                logger.warning(f"PKG: retire_node Neo4j delete failed for {pkg_id}: {e}")
        try:
            from sqlalchemy import text as sa_text, create_engine
            from sqlalchemy.orm import sessionmaker as sync_sm
            database_url = _to_psycopg3_url(os.getenv("DATABASE_URL", ""))
            engine = create_engine(database_url, echo=False)
            Session = sync_sm(bind=engine)
            session = Session()
            try:
                session.execute(sa_text("DELETE FROM pkg_embedding WHERE pkg_id = :pid"),
                                {"pid": pkg_id})
                session.commit()
            finally:
                session.close()
                engine.dispose()
        except Exception as e:
            logger.warning(f"PKG: retire_node embedding delete failed for {pkg_id}: {e}")
        if ok_graph:
            logger.info(f"PKG: retired node {pkg_id} (Neo4j + pkg_embedding)")
        return ok_graph

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
                params = {"limit": limit, **_pkg_fresh_params()}
                result = session.run(f"""
                    MATCH (n)
                    WHERE ({label_clause})
                    AND n.superseded_by IS NULL
                    AND n.confidence > 0.5
                    AND ({PKG_FRESH_FILTER})
                    RETURN labels(n) as labels, properties(n) as props
                    ORDER BY n.confidence DESC
                    LIMIT $limit
                """, params)

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

    def identify_knowledge_gaps(self, db_session=None) -> List[Dict]:
        """
        Find topics David discusses frequently but that have no PKG representation.

        Queries the last 30 days of episodes for recurring topics/entities,
        then cross-references against existing PKG nodes. If a topic appears
        3+ times in user messages but has no matching PKG node, it's a gap.

        Args:
            db_session: Optional SQLAlchemy sync session. Creates one if None.

        Returns:
            List of gap dicts: [{"topic": ..., "mentions": N, "suggested_type": "Interest/Fact/Person"}]
        """
        # 1. Get episode content (user messages only, last 30 days)
        from sqlalchemy import text as sa_text

        if db_session is not None:
            try:
                rows = db_session.execute(sa_text("""
                    SELECT content FROM episode
                    WHERE role = 'user'
                      AND content IS NOT NULL
                      AND created_at >= NOW() - INTERVAL '30 days'
                    ORDER BY created_at DESC
                    LIMIT 500
                """)).fetchall()
                user_texts = [row.content for row in rows if row.content]
            except Exception as e:
                logger.error(f"PKG: identify_knowledge_gaps — episode query failed: {e}")
                return []
        else:
            try:
                database_url = _to_psycopg3_url(os.getenv("DATABASE_URL", ""))

                from sqlalchemy import create_engine
                from sqlalchemy.orm import sessionmaker as sync_sessionmaker
                engine = create_engine(database_url, echo=False)
                Session = sync_sessionmaker(bind=engine)
                session = Session()
                try:
                    rows = session.execute(sa_text("""
                        SELECT content FROM episode
                        WHERE role = 'user'
                          AND content IS NOT NULL
                          AND created_at >= NOW() - INTERVAL '30 days'
                        ORDER BY created_at DESC
                        LIMIT 500
                    """)).fetchall()
                    user_texts = [row.content for row in rows if row.content]
                finally:
                    session.close()
                    engine.dispose()
            except Exception as e:
                logger.error(f"PKG: identify_knowledge_gaps — own session failed: {e}")
                return []

        if not user_texts:
            return []

        # 2. Extract meaningful multi-word phrases and single significant words
        import re
        from collections import Counter

        stop_words = {
            "that", "this", "with", "from", "have", "been", "will",
            "would", "could", "should", "about", "which", "their",
            "there", "what", "when", "where", "your", "just",
            "like", "know", "make", "also", "well", "some",
            "them", "than", "then", "into", "over", "such",
            "more", "most", "much", "many", "each", "very",
            "they", "here", "were", "being", "does", "doing",
            "done", "going", "want", "need", "sure", "yeah",
            "okay", "really", "think", "good", "thanks", "thank",
            "please", "right", "thing", "things", "look", "help",
            "can't", "don't", "it's", "i'm", "i've", "let's",
            "didn't", "doesn't", "isn't", "aren't", "wasn't",
            "weren't", "hadn't", "hasn't", "haven't", "won't",
            "wouldn't", "couldn't", "shouldn't", "might", "still",
            "sara", "tell", "show", "give", "take", "come",
            "time", "even", "back", "only", "gets", "keep",
        }

        # Count significant words per message (unique per message)
        word_counter = Counter()
        for text_content in user_texts:
            words = re.findall(r'\b[a-z]{4,}\b', text_content.lower())
            significant = set(w for w in words if w not in stop_words)
            word_counter.update(significant)

        # Topics mentioned 3+ times across distinct messages
        frequent = [(word, count) for word, count in word_counter.most_common(50) if count >= 3]

        if not frequent:
            return []

        # 3. Cross-reference against existing PKG nodes
        if not self._ensure_driver():
            return []

        # Get all active PKG node text content for matching
        existing_terms = set()
        try:
            with self.driver.session() as neo_session:
                result = neo_session.run(f"""
                    MATCH (n)
                    WHERE ({" OR ".join(f"n:{label}" for label in PKG_LABELS)})
                    AND n.superseded_by IS NULL
                    RETURN
                        coalesce(toLower(n.topic), '') as topic,
                        coalesce(toLower(n.name), '') as name,
                        coalesce(toLower(n.activity), '') as activity,
                        coalesce(toLower(n.key), '') as key_prop,
                        coalesce(toLower(n.value), '') as value_prop,
                        coalesce(toLower(n.subject), '') as subject,
                        coalesce(toLower(n.metric), '') as metric,
                        coalesce(toLower(n.description), '') as description
                """)
                for record in result:
                    for field_val in [record["topic"], record["name"], record["activity"],
                                     record["key_prop"], record["value_prop"],
                                     record["subject"], record["metric"],
                                     record["description"]]:
                        if field_val and len(field_val) >= 3:
                            existing_terms.add(field_val)
                            # Also add individual words for fuzzy matching
                            for word in re.findall(r'\b[a-z]{4,}\b', field_val):
                                existing_terms.add(word)
        except Exception as e:
            logger.error(f"PKG: identify_knowledge_gaps — Neo4j query failed: {e}")
            return []

        # 4. Find gaps: frequently discussed topics NOT in PKG
        gaps = []
        for topic, mentions in frequent:
            # Check if this word (or a close form) exists in PKG
            if topic in existing_terms:
                continue

            # Guess the likely PKG type
            # Proper nouns (capitalized in original text) are likely Person names
            # Check original text for capitalization
            is_capitalized = False
            for text_content in user_texts[:50]:  # check first 50 messages
                pattern = re.compile(r'\b' + re.escape(topic) + r'\b', re.IGNORECASE)
                match = pattern.search(text_content)
                if match:
                    # Check if it was capitalized in original
                    original_word = match.group()
                    if original_word[0].isupper():
                        is_capitalized = True
                        break

            if is_capitalized and len(topic) <= 15:
                suggested_type = "Person"
            elif topic in ("project", "goal", "plan", "build", "create", "finish", "learn"):
                suggested_type = "Goal"
            else:
                suggested_type = "Interest"

            gaps.append({
                "topic": topic,
                "mentions": mentions,
                "suggested_type": suggested_type,
            })

        # Sort by mention count descending, cap at 10
        gaps.sort(key=lambda g: g["mentions"], reverse=True)
        gaps = gaps[:10]

        logger.info(f"PKG: Identified {len(gaps)} knowledge gaps")
        return gaps

    def promote_high_confidence(self, db_session=None, min_confirmations: int = 3) -> int:
        """
        Promote facts confirmed multiple times in the last 30 days to high confidence (0.9+).

        Checks times_confirmed and recent confirmation evidence to boost
        well-established facts.

        Args:
            db_session: Optional SQLAlchemy sync session (unused, kept for consistency)
            min_confirmations: Minimum times_confirmed to qualify for promotion

        Returns:
            Number of facts promoted
        """
        if not self._ensure_driver():
            return 0

        now = datetime.now(timezone.utc).isoformat()
        thirty_days_ago = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

        try:
            with self.driver.session() as session:
                result = session.run(f"""
                    MATCH (n)
                    WHERE ({" OR ".join(f"n:{label}" for label in PKG_LABELS)})
                    AND n.superseded_by IS NULL
                    AND n.confidence < 0.9
                    AND n.confidence >= 0.5
                    AND n.times_confirmed >= $min_confirmations
                    AND n.last_confirmed >= $since
                    SET n.confidence = CASE
                        WHEN n.confidence + 0.1 > 0.95 THEN 0.95
                        ELSE n.confidence + 0.1
                    END,
                    n.last_confirmed = $now
                    RETURN count(n) as promoted
                """, {
                    "min_confirmations": min_confirmations,
                    "since": thirty_days_ago,
                    "now": now,
                })
                record = result.single()
                promoted = record["promoted"] if record else 0

                if promoted > 0:
                    logger.info(f"PKG: Promoted {promoted} well-confirmed facts to higher confidence")
                return promoted
        except Exception as e:
            logger.error(f"PKG: promote_high_confidence failed: {e}")
            return 0

    def _schedule_embedding(
        self, pkg_id: str, fact_type: str, properties: Dict, confidence: float
    ):
        """Fire-and-forget embedding generation for a PKG node."""
        try:
            import asyncio
            loop = asyncio.get_running_loop()
            loop.create_task(self.store_embedding_async(pkg_id, fact_type, properties, confidence))
        except RuntimeError:
            # No running event loop — skip embedding. pkg_sync reconciliation
            # will backfill it at the top of the next hour.
            _PKG_EMBEDDING_TRACKER.note("no_event_loop")
            logger.debug(f"PKG: No event loop for embedding of {pkg_id}, will backfill later")

    def store_life_fact_embedding(self, pkg_id: str, content_text: str, confidence: float = 0.9) -> None:
        """Fire-and-forget embedding write for a Brain-Alignment life_fact
        (node_type='life_fact'). The life_fact table is authoritative; this
        only makes the fact semantically retrievable alongside other PKG nodes."""
        async def _write():
            try:
                from app.services.embedding_service import EmbeddingService
                svc = EmbeddingService()
                embedding = await svc.generate_embedding(content_text, capability="embedding_cognition")  # fire-and-forget write, never blocks presence
                if not embedding:
                    return
                from sqlalchemy import text as sa_text, create_engine
                from sqlalchemy.orm import sessionmaker as sync_sm
                engine = create_engine(_to_psycopg3_url(os.getenv("DATABASE_URL", "")), echo=False)
                Session = sync_sm(bind=engine)
                session = Session()
                try:
                    session.execute(sa_text("""
                        INSERT INTO pkg_embedding (pkg_id, node_type, content_text, embedding, confidence, updated_at)
                        VALUES (:pkg_id, 'life_fact', :content_text, :embedding, :confidence, NOW())
                        ON CONFLICT (pkg_id) DO UPDATE SET
                            content_text = EXCLUDED.content_text,
                            embedding = EXCLUDED.embedding,
                            confidence = EXCLUDED.confidence,
                            updated_at = NOW()
                    """), {"pkg_id": pkg_id, "content_text": content_text,
                           "embedding": str(embedding), "confidence": confidence})
                    session.commit()
                finally:
                    session.close()
                    engine.dispose()
            except Exception as e:
                _PKG_EMBEDDING_TRACKER.note(f"life_fact:{type(e).__name__}")
                logger.debug(f"PKG: life_fact embedding write failed: {e}")

        try:
            import asyncio
            asyncio.get_running_loop().create_task(_write())
        except RuntimeError:
            _PKG_EMBEDDING_TRACKER.note("life_fact_no_event_loop")

    def get_graduation_candidates(
        self, min_confirmed: int = 5, min_age_days: int = 21, limit: int = 20
    ) -> List[Dict]:
        """H7.2: PKG preferences/routines confirmed enough, over a long enough
        span, not yet internalized or flagged for review — candidates to become
        standing soul directives."""
        if not self._ensure_driver():
            return []
        from datetime import datetime, timezone, timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=min_age_days)).isoformat()
        out: List[Dict] = []
        try:
            with self.driver.session() as session:
                result = session.run(f"""
                    MATCH (n)
                    WHERE (n:PKG_Preference OR n:PKG_Routine)
                      AND n.superseded_by IS NULL
                      AND coalesce(n.times_confirmed, 1) >= $min_confirmed
                      AND n.first_learned <= $cutoff
                      AND coalesce(n.internalized, false) = false
                      AND coalesce(n.needs_review, false) = false
                      AND coalesce(n.confidence, 0) >= 0.7
                    RETURN n.pkg_id AS pkg_id, labels(n) AS labels,
                           properties(n) AS props, coalesce(n.times_confirmed,1) AS ev
                    ORDER BY ev DESC
                    LIMIT $limit
                """, {"min_confirmed": min_confirmed, "cutoff": cutoff, "limit": limit})
                for row in result:
                    label = self._extract_pkg_label(row["labels"])
                    out.append({
                        "pkg_id": row["pkg_id"],
                        "label": label,
                        "natural": self._format_fact_natural(label, row["props"] or {}),
                        "evidence_count": row["ev"],
                    })
        except Exception as e:
            _PKG_NEO4J_TRACKER.note(f"graduation:{type(e).__name__}")
            logger.debug(f"PKG graduation query failed: {e}")
        return out

    def mark_internalized(self, pkg_id: str) -> bool:
        """H7.2: mark a fact as inherent — retrieval stops spending context
        budget re-fetching what is now standing prompt."""
        if not self._ensure_driver() or not pkg_id:
            return False
        try:
            with self.driver.session() as session:
                session.run(
                    "MATCH (n {pkg_id: $pkg_id}) SET n.internalized = true, "
                    "n.internalized_at = $now",
                    {"pkg_id": pkg_id, "now": datetime.now(timezone.utc).isoformat()},
                )
            return True
        except Exception as e:
            logger.debug(f"PKG mark_internalized failed: {e}")
            return False

    # --- Semantic search via pgvector shadow table ---

    def _node_to_text(self, fact_type: str, properties: Dict) -> str:
        """Convert PKG node to a text string for embedding generation."""
        if fact_type == "Person":
            name = properties.get("name", "")
            rel = properties.get("relationship_to_david", "")
            notes = properties.get("notes", "")
            parts = [f"Person: {name}"]
            if rel:
                parts.append(f"relationship: {rel}")
            if notes:
                parts.append(notes)
            return ". ".join(parts)
        elif fact_type == "Preference":
            domain = properties.get("domain", "")
            key = properties.get("key", "")
            value = properties.get("value", "")
            strength = properties.get("strength", "likes")
            return f"David {strength} {value}. Domain: {domain}, key: {key}"
        elif fact_type == "Routine":
            activity = properties.get("activity", "")
            day = properties.get("day_of_week", "")
            time = properties.get("typical_time", "")
            freq = properties.get("frequency", "")
            parts = [f"Routine: David {activity}"]
            if day:
                parts.append(f"on {day}")
            if time:
                parts.append(f"at {time}")
            if freq:
                parts.append(f"({freq})")
            return " ".join(parts)
        elif fact_type == "Goal":
            desc = properties.get("description", "")
            status = properties.get("status", "active")
            return f"Goal: {desc}. Status: {status}"
        elif fact_type == "Interest":
            topic = properties.get("topic", "")
            depth = properties.get("depth", "")
            return f"Interest: {topic}" + (f" (depth: {depth})" if depth else "")
        elif fact_type == "Health":
            metric = properties.get("metric", "")
            value = properties.get("current_value", "")
            trend = properties.get("trend", "")
            return f"Health metric: {metric} = {value}" + (f", trending {trend}" if trend else "")
        elif fact_type == "Place":
            name = properties.get("name", "")
            ptype = properties.get("type", "")
            sig = properties.get("significance", "")
            return f"Place: {name} ({ptype})" + (f". {sig}" if sig else "")
        elif fact_type == "Fact":
            subj = properties.get("subject", "David")
            pred = properties.get("predicate", "")
            obj = properties.get("object", "")
            return f"{subj} {pred} {obj}"
        return str(properties)

    async def store_embedding_async(
        self, pkg_id: str, fact_type: str, properties: Dict, confidence: float = 0.7
    ) -> bool:
        """Generate embedding for a PKG node and store in pgvector shadow table."""
        try:
            content_text = self._node_to_text(fact_type, properties)
            if not content_text or len(content_text) < 5:
                return False

            from app.services.embedding_service import EmbeddingService
            svc = EmbeddingService()
            embedding = await svc.generate_embedding(content_text, capability="embedding_cognition")  # write path, never blocks presence
            if not embedding:
                logger.warning(f"PKG: Failed to generate embedding for {pkg_id}")
                return False

            from sqlalchemy import text as sa_text
            database_url = _to_psycopg3_url(os.getenv("DATABASE_URL", ""))

            from sqlalchemy import create_engine
            from sqlalchemy.orm import sessionmaker as sync_sm
            engine = create_engine(database_url, echo=False)
            Session = sync_sm(bind=engine)
            session = Session()
            try:
                # Upsert: insert or update
                session.execute(sa_text("""
                    INSERT INTO pkg_embedding (pkg_id, node_type, content_text, embedding, confidence, updated_at)
                    VALUES (:pkg_id, :node_type, :content_text, :embedding, :confidence, NOW())
                    ON CONFLICT (pkg_id)
                    DO UPDATE SET
                        content_text = EXCLUDED.content_text,
                        embedding = EXCLUDED.embedding,
                        confidence = EXCLUDED.confidence,
                        updated_at = NOW()
                """), {
                    "pkg_id": pkg_id,
                    "node_type": fact_type,
                    "content_text": content_text,
                    "embedding": str(embedding),
                    "confidence": confidence,
                })
                session.commit()
                logger.debug(f"PKG: Stored embedding for {pkg_id} ({fact_type})")
                return True
            finally:
                session.close()
                engine.dispose()
        except Exception as e:
            _PKG_EMBEDDING_TRACKER.note(f"exception:{type(e).__name__}")
            logger.warning(f"PKG: store_embedding_async failed for {pkg_id}: {e}")
            return False

    async def query_semantic(
        self, query_text: str, limit: int = 10, min_similarity: float = 0.3,
        embedding_capability: str = "embedding",
    ) -> List[Dict]:
        """
        Semantic search over PKG nodes using pgvector cosine similarity.

        `embedding_capability`: "embedding" (default, GPU host) for callers
        inside a real chat turn; "embedding_cognition" (CPU fallback host)
        for background/non-interactive callers (lesson matching,
        consolidation, sweeps) — presence-latency follow-up ruling 1
        (2026-07-31), so background work can never queue behind (or be
        queued behind by) a real chat turn's own PKG lookup.

        Returns list of dicts with pkg_id, node_type, content_text, similarity.
        Then fetches full node data from Neo4j.
        """
        import time as _t
        _t0 = _t.monotonic()
        try:
            from app.services.embedding_service import EmbeddingService
            svc = EmbeddingService()
            query_embedding = await svc.generate_embedding(query_text, capability=embedding_capability)
            _t_embed = _t.monotonic()
            if not query_embedding:
                return []

            from sqlalchemy import text as sa_text
            database_url = os.getenv("DATABASE_URL", "")
            if "asyncpg" in database_url:
                database_url = database_url.replace("postgresql+asyncpg://", "postgresql+psycopg://")
            elif not database_url.startswith("postgresql+psycopg://"):
                # Ensure we use psycopg (v3) driver, not psycopg2
                database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)

            # Presence-latency follow-up (item 1.3 Session 1, 2026-07-31):
            # timed separately below to confirm/refute the suspicion that
            # create_engine() fresh on every single call (no pooling reuse)
            # is the real cost here, before touching it.
            from sqlalchemy import create_engine
            from sqlalchemy.orm import sessionmaker as sync_sm
            _t_pre_engine = _t.monotonic()
            engine = create_engine(database_url, echo=False)
            Session = sync_sm(bind=engine)
            session = Session()
            _t_engine_ready = _t.monotonic()
            try:
                rows = session.execute(sa_text("""
                    SELECT pkg_id, node_type, content_text,
                           1 - (embedding <=> CAST(:query_embedding AS vector)) as similarity
                    FROM pkg_embedding
                    WHERE embedding IS NOT NULL
                    ORDER BY embedding <=> CAST(:query_embedding AS vector)
                    LIMIT :limit
                """), {
                    "query_embedding": str(query_embedding),
                    "limit": limit,
                }).fetchall()

                # Filter by min similarity
                matches = [
                    {"pkg_id": r.pkg_id, "node_type": r.node_type,
                     "content_text": r.content_text, "similarity": r.similarity}
                    for r in rows if r.similarity >= min_similarity
                ]
            finally:
                session.close()
                engine.dispose()
            _t_query_done = _t.monotonic()
            logger.info(
                f"⏱️ [pkg-query-semantic-timing] embedding={_t_embed-_t0:.2f}s "
                f"engine_create={_t_engine_ready-_t_pre_engine:.2f}s "
                f"pgvector_query={_t_query_done-_t_engine_ready:.2f}s"
            )

            if not matches:
                # Zero semantic matches is legitimate when nothing is relevant,
                # but it also hides the case where pkg_embedding is simply
                # missing rows for nodes Neo4j has. Schedule a fire-and-forget
                # backfill (rate-limited) so we self-heal rather than waiting
                # for the hourly reconcile.
                self._maybe_schedule_backfill(reason="zero_semantic_matches")
                return []

            # Fetch full node data from Neo4j
            if not self._ensure_driver():
                return matches  # return partial data without Neo4j props

            _t_neo4j_start = _t.monotonic()
            pkg_ids = [m["pkg_id"] for m in matches]
            try:
                with self.driver.session() as neo_session:
                    params = {"pkg_ids": pkg_ids, **_pkg_fresh_params()}
                    result = neo_session.run(f"""
                        MATCH (n)
                        WHERE ({" OR ".join(f"n:{label}" for label in PKG_LABELS)})
                        AND n.pkg_id IN $pkg_ids
                        AND n.superseded_by IS NULL
                        AND ({PKG_FRESH_FILTER})
                        RETURN n.pkg_id as pkg_id, labels(n) as labels, properties(n) as props
                    """, params)

                    neo4j_data = {}
                    for record in result:
                        neo4j_data[record["pkg_id"]] = {
                            "type": self._extract_pkg_label(record["labels"]),
                            **{k: v for k, v in record["props"].items()
                               if k not in ("dedup_key",)}
                        }
            except Exception as e:
                logger.warning(f"PKG: Neo4j fetch for semantic results failed: {e}")
                neo4j_data = {}
            logger.info(f"⏱️ [pkg-query-semantic-timing] neo4j_fetch={_t.monotonic()-_t_neo4j_start:.2f}s")

            # Merge: prefer Neo4j data, fall back to content_text
            results = []
            for m in matches:
                if m["pkg_id"] in neo4j_data:
                    entry = neo4j_data[m["pkg_id"]]
                    entry["similarity"] = m["similarity"]
                    results.append(entry)
                else:
                    # Node may have been superseded since embedding was stored
                    results.append({
                        "type": m["node_type"],
                        "content_text": m["content_text"],
                        "similarity": m["similarity"],
                    })

            return results
        except Exception as e:
            logger.warning(f"PKG: query_semantic failed: {e}")
            return []

    async def query_top_confidence(self, limit: int = 20) -> List[Dict]:
        """Top-N facts by confidence, no query text — the same Cypher shape
        as get_david_summary() but returning raw rows (type + full node
        props) instead of pre-formatted text, so callers that want "brief
        top facts about David" (not a topic-specific search) can go through
        memory_recall.recall() too: query_semantic() needs a query to
        embed and compare against, which a context-free "give me your top
        facts" request doesn't have — this is that request's actual data
        source. Row shape matches query_semantic()'s Neo4j-fetched rows
        (`similarity` set from confidence as a stand-in score) so
        memory_recall._from_facts can format either the same way."""
        if not self._ensure_driver():
            return []
        try:
            with self.driver.session() as session:
                params = {"limit": limit, **_pkg_fresh_params()}
                result = session.run(f"""
                    MATCH (n)
                    WHERE ({" OR ".join(f"n:{label}" for label in PKG_LABELS)})
                    AND n.superseded_by IS NULL
                    AND n.confidence > 0.5
                    AND ({PKG_FRESH_FILTER})
                    RETURN n.pkg_id as pkg_id, labels(n) as labels, properties(n) as props
                    ORDER BY n.confidence DESC, n.last_confirmed DESC
                    LIMIT $limit
                """, params)
                return [
                    {
                        "type": self._extract_pkg_label(record["labels"]),
                        "pkg_id": record["pkg_id"],
                        "similarity": float((record["props"] or {}).get("confidence", 0.5) or 0.5),
                        **{k: v for k, v in (record["props"] or {}).items() if k not in ("dedup_key",)},
                    }
                    for record in result
                ]
        except Exception as e:
            logger.warning(f"PKG: query_top_confidence failed: {e}")
            return []

    async def backfill_embeddings(self) -> int:
        """Backfill embeddings for all active PKG nodes that don't have one yet."""
        if not self._ensure_driver():
            return 0

        try:
            # Get all active nodes
            with self.driver.session() as session:
                result = session.run(f"""
                    MATCH (n)
                    WHERE ({" OR ".join(f"n:{label}" for label in PKG_LABELS)})
                    AND n.superseded_by IS NULL
                    RETURN labels(n) as labels, properties(n) as props
                """)
                nodes = [
                    {"type": self._extract_pkg_label(r["labels"]), "props": dict(r["props"])}
                    for r in result
                ]
        except Exception as e:
            logger.error(f"PKG: backfill_embeddings — Neo4j query failed: {e}")
            return 0

        # Check which pkg_ids already have embeddings.
        # Keep the psycopg3 driver in the URL — bare ``postgresql://`` defaults
        # to psycopg2, which isn't installed. Previously this silently broke
        # every backfill attempt with ModuleNotFoundError.
        from sqlalchemy import text as sa_text
        database_url = os.getenv("DATABASE_URL", "")
        if "asyncpg" in database_url:
            database_url = database_url.replace("postgresql+asyncpg://", "postgresql+psycopg://")
        elif not database_url.startswith("postgresql+psycopg://"):
            database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)

        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker as sync_sm
        engine = create_engine(database_url, echo=False)
        Session = sync_sm(bind=engine)
        session = Session()
        try:
            existing = set()
            rows = session.execute(sa_text("SELECT pkg_id FROM pkg_embedding")).fetchall()
            existing = {r.pkg_id for r in rows}
        finally:
            session.close()
            engine.dispose()

        count = 0
        for node in nodes:
            pkg_id = node["props"].get("pkg_id")
            if not pkg_id or pkg_id in existing:
                continue
            confidence = node["props"].get("confidence", 0.7)
            ok = await self.store_embedding_async(pkg_id, node["type"], node["props"], confidence)
            if ok:
                count += 1

        logger.info(f"PKG: Backfilled {count} embeddings (of {len(nodes)} total nodes)")
        return count

    def close(self):
        """Close Neo4j driver"""
        if self.driver:
            self.driver.close()
            self.driver = None


# Singleton instance
personal_kg = PersonalKnowledgeGraph()


def get_memory_health() -> Dict[str, Any]:
    """Count embedding gaps — PKG nodes without a pkg_embedding row and
    episodes with NULL embeddings.

    Used by /debug/retrieval-funnel so a stuck embedding pipeline shows up
    at a glance instead of silently eroding retrieval quality.
    """
    from sqlalchemy import create_engine, text as sa_text
    from sqlalchemy.orm import sessionmaker as _sm

    health: Dict[str, Any] = {
        "episode_embedding_gaps": None,
        "episode_total": None,
        "pkg_embedding_gaps": None,
        "pkg_active_total": None,
    }

    database_url = os.getenv("DATABASE_URL", "")
    if "asyncpg" in database_url:
        database_url = database_url.replace("postgresql+asyncpg://", "postgresql+psycopg://")
    elif not database_url.startswith("postgresql+psycopg://"):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)

    try:
        engine = create_engine(database_url, echo=False)
        Session = _sm(bind=engine)
        session = Session()
        try:
            row = session.execute(sa_text(
                "SELECT COUNT(*) AS total, COUNT(*) FILTER (WHERE embedding IS NULL) AS gaps FROM episode"
            )).fetchone()
            if row:
                health["episode_total"] = int(row.total or 0)
                health["episode_embedding_gaps"] = int(row.gaps or 0)

            row = session.execute(sa_text(
                "SELECT COUNT(*) AS total FROM pkg_embedding"
            )).fetchone()
            pkg_embedding_count = int(row.total or 0) if row else 0
        finally:
            session.close()
            engine.dispose()
    except Exception as exc:
        health["error"] = f"pg_query_failed:{type(exc).__name__}"
        return health

    # PKG active count from Neo4j (may fail if Neo4j down — that's fine).
    try:
        if personal_kg._ensure_driver():
            with personal_kg.driver.session() as neo:
                result = neo.run(
                    f"""
                    MATCH (n)
                    WHERE ({" OR ".join(f"n:{label}" for label in PKG_LABELS)})
                      AND n.superseded_by IS NULL
                    RETURN count(n) AS c
                    """
                )
                record = result.single()
                active = int(record["c"]) if record else 0
                health["pkg_active_total"] = active
                health["pkg_embedding_gaps"] = max(0, active - pkg_embedding_count)
    except Exception as exc:
        health["pkg_error"] = f"neo4j_query_failed:{type(exc).__name__}"

    return health
