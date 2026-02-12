"""
Dream Consolidation Service

This service performs nightly memory consolidation ("dreaming"):
1. Fetch recent memory traces from the day
2. Cluster similar traces by semantic similarity
3. Generate LLM-powered summaries for each cluster
4. Extract temporal and causal edges
5. Generate insights (patterns, forgotten gems, connections)
6. Store as DreamInsight records for user consumption

Runs nightly at 2 AM via cron job.
"""

from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text, desc
import logging
import json
import asyncio
import numpy as np
from collections import defaultdict

logger = logging.getLogger(__name__)


class DreamConsolidationService:
    """
    Nightly memory consolidation service that processes the day's memories
    to generate insights, summaries, and strengthen important connections.
    """

    def __init__(self):
        self.enabled = True
        self.max_traces_per_night = 1000
        self.max_runtime_minutes = 10
        self.min_cluster_size = 3
        self.similarity_threshold = 0.75  # Cosine similarity for clustering
        self._llm_client = None
        self._embedding_service = None

    def _get_llm_client(self):
        """Lazy-load LLM client"""
        if self._llm_client:
            return self._llm_client

        try:
            from app.core.llm import llm_client
            self._llm_client = llm_client
            return self._llm_client
        except Exception as e:
            logger.error(f"Failed to initialize LLM client: {e}")
            return None

    def _get_embedding_service(self):
        """Lazy-load embedding service"""
        if self._embedding_service:
            return self._embedding_service

        try:
            from app.services.embeddings import get_embedding
            self._embedding_service = get_embedding
            return self._embedding_service
        except Exception as e:
            logger.error(f"Failed to initialize embedding service: {e}")
            return None

    async def run_dream_pipeline(
        self,
        db: Session,
        user_id: str,
        day: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Run the complete dream consolidation pipeline for a user.

        Args:
            db: Database session
            user_id: User identifier
            day: Day to consolidate (default: yesterday)

        Returns:
            Pipeline execution summary with metrics
        """
        if not self.enabled:
            logger.info("Dream pipeline disabled")
            return {"status": "disabled"}

        start_time = datetime.now()
        logger.info(f"🌙 Starting dream consolidation for user {user_id}")

        try:
            # Default to yesterday
            if day is None:
                day = datetime.now(timezone.utc) - timedelta(days=1)

            start = day.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=1)

            # Step 1: Fetch day's memory traces
            traces = await self._fetch_traces(db, user_id, start, end)

            if len(traces) < self.min_cluster_size:
                logger.info(f"Not enough traces to consolidate ({len(traces)} < {self.min_cluster_size})")
                return {
                    "status": "skipped",
                    "reason": "insufficient_traces",
                    "traces_found": len(traces)
                }

            logger.info(f"📚 Fetched {len(traces)} traces for consolidation")

            # Step 2: Cluster traces by semantic similarity
            clusters = await self._cluster_traces(traces)
            logger.info(f"🗂️ Created {len(clusters)} semantic clusters")

            # Step 3: Generate LLM summaries for each cluster
            summaries = await self._generate_summaries(clusters)
            logger.info(f"📝 Generated {len(summaries)} cluster summaries")

            # Step 4: Extract temporal and causal edges
            edges_created = await self._extract_edges(db, user_id, traces, clusters)
            logger.info(f"🕸️ Created {edges_created} memory edges")

            # Step 5: Generate insights
            insights = await self._generate_insights(db, user_id, day, traces, clusters, summaries)
            logger.info(f"💡 Generated {len(insights)} dream insights")

            # Step 6: Store summaries as memory traces
            summary_ids = await self._store_summaries(db, user_id, day, summaries)
            logger.info(f"💾 Stored {len(summary_ids)} summary traces")

            # Step 7: Generate policy candidates from insights (Phase 3 — Cortana Evolution)
            policy_candidate_ids = []
            try:
                from app.core.config import settings
                if getattr(settings, 'autonomy_policy_candidates_enabled', False) and insights:
                    from app.services.autonomy.policy_candidate import policy_candidate_service
                    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession as AsyncDB
                    from sqlalchemy.orm import sessionmaker
                    import os

                    database_url = os.getenv("DATABASE_URL", "")
                    async_url = database_url.replace("postgresql://", "postgresql+asyncpg://").replace("postgresql+psycopg://", "postgresql+asyncpg://")
                    engine = create_async_engine(async_url, echo=False)
                    async_session = sessionmaker(engine, class_=AsyncDB, expire_on_commit=False)
                    async with async_session() as async_db:
                        policy_candidate_ids = await policy_candidate_service.generate_from_dream_insights(
                            db=async_db, user_id=user_id, insights=insights,
                        )
                        await async_db.commit()
                    await engine.dispose()
                    if policy_candidate_ids:
                        logger.info(f"Generated {len(policy_candidate_ids)} policy candidates from dream insights")
            except Exception as e:
                logger.debug(f"Policy candidate generation from dreams failed (non-fatal): {e}")

            runtime_seconds = (datetime.now() - start_time).total_seconds()
            logger.info(f"🌙 Dream consolidation complete in {runtime_seconds:.2f}s")

            return {
                "status": "success",
                "day": day.isoformat(),
                "traces_processed": len(traces),
                "clusters_created": len(clusters),
                "summaries_generated": len(summaries),
                "edges_created": edges_created,
                "insights_extracted": len(insights),
                "summary_traces": summary_ids,
                "policy_candidates": len(policy_candidate_ids),
                "runtime_seconds": runtime_seconds
            }

        except Exception as e:
            logger.error(f"❌ Dream consolidation failed: {e}", exc_info=True)
            return {
                "status": "error",
                "error": str(e),
                "runtime_seconds": (datetime.now() - start_time).total_seconds()
            }

    async def _fetch_traces(
        self,
        db: Session,
        user_id: str,
        start: datetime,
        end: datetime
    ) -> List[Dict[str, Any]]:
        """Fetch memory traces for the specified day"""
        from app.main_simple import MemoryTrace

        traces = db.query(MemoryTrace).filter(
            MemoryTrace.user_id == user_id,
            MemoryTrace.created_at >= start,
            MemoryTrace.created_at < end,
            MemoryTrace.role != "summary"  # Exclude existing summaries
        ).order_by(MemoryTrace.created_at.asc()).limit(self.max_traces_per_night).all()

        return [
            {
                "id": t.id,
                "content": t.content,
                "role": t.role,
                "salience": t.salience or 0.5,
                "created_at": t.created_at,
                "source": json.loads(t.source) if t.source else {},
                "meta": json.loads(t.meta) if t.meta else {}
            }
            for t in traces
        ]

    async def _cluster_traces(self, traces: List[Dict]) -> List[List[Dict]]:
        """
        Cluster traces by semantic similarity using embeddings.
        Uses a simple threshold-based approach (can be upgraded to HDBSCAN).
        """
        if len(traces) < self.min_cluster_size:
            return [traces] if traces else []

        # Get embeddings for all traces
        embedding_fn = self._get_embedding_service()
        if not embedding_fn:
            logger.warning("Embedding service unavailable, returning single cluster")
            return [traces]

        try:
            # Generate embeddings
            embeddings = []
            for trace in traces:
                try:
                    emb = await embedding_fn(trace["content"])
                    embeddings.append(emb if emb else [0.0] * 1024)
                except Exception:
                    embeddings.append([0.0] * 1024)  # Fallback zero vector

            embeddings_array = np.array(embeddings, dtype=float)

            # Simple greedy clustering by similarity threshold
            clusters = []
            used = set()

            for i, trace in enumerate(traces):
                if i in used:
                    continue

                # Start new cluster with this trace
                cluster = [trace]
                cluster_embedding = embeddings_array[i]
                used.add(i)

                # Find similar traces
                for j, other_trace in enumerate(traces):
                    if j in used or i == j:
                        continue

                    # Calculate cosine similarity
                    similarity = np.dot(cluster_embedding, embeddings_array[j]) / (
                        np.linalg.norm(cluster_embedding) * np.linalg.norm(embeddings_array[j]) + 1e-8
                    )

                    if similarity >= self.similarity_threshold:
                        cluster.append(other_trace)
                        used.add(j)
                        # Update cluster centroid
                        cluster_embedding = np.mean([embeddings_array[k] for k in used if k <= j], axis=0)

                if len(cluster) >= self.min_cluster_size:
                    clusters.append(cluster)

            # Add remaining traces as singleton clusters if significant
            for i, trace in enumerate(traces):
                if i not in used and trace["salience"] > 0.7:  # High salience traces get their own cluster
                    clusters.append([trace])

            return clusters if clusters else [traces]

        except Exception as e:
            logger.error(f"Clustering failed: {e}")
            return [traces]  # Fallback to single cluster

    async def _generate_summaries(self, clusters: List[List[Dict]]) -> List[Dict[str, Any]]:
        """Generate LLM-powered summaries for each cluster"""
        llm = self._get_llm_client()
        if not llm:
            logger.warning("LLM unavailable, using keyword-based summaries")
            return [self._fallback_summary(cluster) for cluster in clusters]

        summaries = []

        for i, cluster in enumerate(clusters):
            try:
                summary = await self._generate_cluster_summary(llm, cluster)
                summaries.append(summary)
            except Exception as e:
                logger.error(f"Failed to generate summary for cluster {i}: {e}")
                summaries.append(self._fallback_summary(cluster))

        return summaries

    async def _generate_cluster_summary(self, llm, cluster: List[Dict]) -> Dict[str, Any]:
        """Generate an intelligent summary for a cluster using LLM"""
        # Combine cluster traces into context
        combined_content = "\n\n".join([
            f"[{t['role']}] {t['content']}"
            for t in cluster[:10]  # Limit to first 10 traces
        ])

        prompt = f"""Analyze these related memory traces from a user's day and provide a concise summary.

Traces:
{combined_content}

Provide a JSON response with:
1. "summary": A 2-3 sentence summary of the main theme
2. "key_points": List of 3-5 key points or events
3. "emotional_tone": Overall emotional tone (positive, neutral, negative, mixed)
4. "topics": List of main topics/themes (3-5 tags)

Respond with only valid JSON."""

        try:
            response = await llm.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=500
            )

            if isinstance(response, dict):
                content = (
                    response.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                )
            else:
                content = str(response)

            # Some models wrap JSON in markdown fences.
            content = content.strip()
            if "```" in content:
                fenced = content.split("```")
                if len(fenced) >= 2:
                    content = fenced[1]
                    if content.startswith("json"):
                        content = content[4:]
                    content = content.strip()

            result = json.loads(content)

            return {
                "cluster_size": len(cluster),
                "trace_ids": [t["id"] for t in cluster],
                "summary": result.get("summary", ""),
                "key_points": result.get("key_points", []),
                "emotional_tone": result.get("emotional_tone", "neutral"),
                "topics": result.get("topics", []),
                "time_span": {
                    "start": cluster[0]["created_at"].isoformat(),
                    "end": cluster[-1]["created_at"].isoformat()
                }
            }

        except Exception as e:
            logger.error(f"LLM summary generation failed: {e}")
            return self._fallback_summary(cluster)

    def _fallback_summary(self, cluster: List[Dict]) -> Dict[str, Any]:
        """Fallback keyword-based summary when LLM unavailable"""
        # Extract common keywords
        all_words = []
        for trace in cluster:
            words = trace["content"].lower().split()
            all_words.extend([w for w in words if len(w) > 4])

        word_freq = defaultdict(int)
        for word in all_words:
            word_freq[word] += 1

        top_keywords = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)[:5]
        keywords = [kw[0] for kw in top_keywords]

        return {
            "cluster_size": len(cluster),
            "trace_ids": [t["id"] for t in cluster],
            "summary": f"Cluster of {len(cluster)} related memories about: {', '.join(keywords[:3])}",
            "key_points": keywords,
            "emotional_tone": "neutral",
            "topics": keywords,
            "time_span": {
                "start": cluster[0]["created_at"].isoformat(),
                "end": cluster[-1]["created_at"].isoformat()
            }
        }

    async def _extract_edges(
        self,
        db: Session,
        user_id: str,
        traces: List[Dict],
        clusters: List[List[Dict]]
    ) -> int:
        """Extract and store temporal and causal edges between traces"""
        from app.main_simple import MemoryEdge

        edges_created = 0

        try:
            # 1. Temporal edges within clusters
            for cluster in clusters:
                for i in range(len(cluster) - 1):
                    edge = MemoryEdge(
                        src=cluster[i]["id"],
                        dst=cluster[i + 1]["id"],
                        type="temporal",
                        weight=0.2
                    )
                    db.merge(edge)
                    edges_created += 1

            # 2. Semantic edges between cluster centroids
            for i, cluster1 in enumerate(clusters):
                for j, cluster2 in enumerate(clusters):
                    if i >= j:
                        continue

                    # Link first trace of each cluster
                    edge = MemoryEdge(
                        src=cluster1[0]["id"],
                        dst=cluster2[0]["id"],
                        type="semantic",
                        weight=0.1
                    )
                    db.merge(edge)
                    edges_created += 1

            db.commit()
            return edges_created

        except Exception as e:
            logger.error(f"Edge extraction failed: {e}")
            db.rollback()
            return 0

    async def _fetch_fitness_metrics(
        self,
        db: Session,
        user_id: str,
        day: datetime
    ) -> Dict[str, Any]:
        """Fetch fitness metrics for the day"""
        from sqlalchemy import text as sql_text

        start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)

        metrics = {}

        try:
            # Get workout logs for the day
            workout_sql = sql_text("""
                SELECT
                    COUNT(DISTINCT wl.workout_id) as workouts_count,
                    COUNT(wl.id) as total_sets,
                    SUM(wl.weight * wl.reps) as total_volume,
                    AVG(wl.rpe) as avg_rpe
                FROM workout_log wl
                WHERE wl.user_id = :user_id
                AND wl.created_at >= :start
                AND wl.created_at < :end
            """)

            workout_result = db.execute(workout_sql, {
                "user_id": user_id,
                "start": start,
                "end": end
            }).fetchone()

            metrics["workouts"] = {
                "count": workout_result.workouts_count or 0,
                "total_sets": workout_result.total_sets or 0,
                "total_volume": round(workout_result.total_volume or 0, 1),
                "avg_rpe": round(workout_result.avg_rpe or 0, 1)
            }

            # Get nutrition for the day
            nutrition_sql = sql_text("""
                SELECT
                    COUNT(*) as meals_count,
                    SUM(calories) as total_calories,
                    SUM(protein) as total_protein,
                    SUM(carbs) as total_carbs,
                    SUM(fats) as total_fats
                FROM food_log
                WHERE user_id = :user_id
                AND DATE(created_at) = DATE(:day)
            """)

            nutrition_result = db.execute(nutrition_sql, {
                "user_id": user_id,
                "day": day
            }).fetchone()

            metrics["nutrition"] = {
                "meals_count": nutrition_result.meals_count or 0,
                "calories": round(nutrition_result.total_calories or 0, 1),
                "protein": round(nutrition_result.total_protein or 0, 1),
                "carbs": round(nutrition_result.total_carbs or 0, 1),
                "fats": round(nutrition_result.total_fats or 0, 1)
            }

            # Get weekly comparison
            week_start = day - timedelta(days=7)
            weekly_sql = sql_text("""
                SELECT
                    COUNT(DISTINCT wl.workout_id) as workouts_count,
                    SUM(wl.weight * wl.reps) as total_volume
                FROM workout_log wl
                WHERE wl.user_id = :user_id
                AND wl.created_at >= :week_start
                AND wl.created_at < :start
            """)

            weekly_result = db.execute(weekly_sql, {
                "user_id": user_id,
                "week_start": week_start,
                "start": start
            }).fetchone()

            metrics["weekly_avg"] = {
                "workouts": round((weekly_result.workouts_count or 0) / 7, 1),
                "volume": round((weekly_result.total_volume or 0) / 7, 1)
            }

            return metrics

        except Exception as e:
            logger.error(f"Failed to fetch fitness metrics: {e}")
            return {
                "workouts": {"count": 0, "total_sets": 0, "total_volume": 0, "avg_rpe": 0},
                "nutrition": {"meals_count": 0, "calories": 0, "protein": 0, "carbs": 0, "fats": 0},
                "weekly_avg": {"workouts": 0, "volume": 0}
            }

    async def _generate_insights(
        self,
        db: Session,
        user_id: str,
        day: datetime,
        traces: List[Dict],
        clusters: List[List[Dict]],
        summaries: List[Dict]
    ) -> List[str]:
        """Generate LLM-powered DreamInsight records from daily conversations"""
        from app.main_simple import DreamInsight
        import uuid

        insights = []

        try:
            # Gather context for the LLM
            context = await self._gather_insight_context(db, user_id, day, traces, clusters, summaries)

            # Generate LLM-powered insights
            llm_insights = await self._generate_llm_insights(context)

            # Store each insight
            for insight_data in llm_insights:
                try:
                    # Calculate expiry if specified
                    expiry_at = None
                    if insight_data.get("expiry_days"):
                        expiry_at = day + timedelta(days=insight_data["expiry_days"])

                    # Find related trace IDs based on evidence
                    related_ids = self._find_related_traces(traces, insight_data.get("evidence", ""))

                    insight = DreamInsight(
                        id=str(uuid.uuid4()),
                        user_id=user_id,
                        dream_date=day,
                        insight_type=insight_data.get("type", "pattern"),
                        confidence=insight_data.get("confidence", 0.5),
                        title=insight_data.get("title", "Insight"),
                        content=insight_data.get("content", ""),
                        related_episodes=json.dumps(related_ids),
                        surface_strategy=insight_data.get("surface_strategy", "contextual"),
                        evidence=insight_data.get("evidence", ""),
                        expiry_at=expiry_at,
                        surfaced_count=0
                    )
                    db.add(insight)
                    insights.append(insight.id)

                    logger.info(f"💡 Created insight: {insight_data.get('title', 'Unknown')[:50]}...")

                except Exception as e:
                    logger.error(f"Failed to store insight: {e}")
                    continue

            # Also generate fitness insights (these are data-driven, not LLM)
            fitness_insights = await self._generate_fitness_insights(db, user_id, day)
            for fi in fitness_insights:
                db.add(fi)
                insights.append(fi.id)

            db.commit()
            logger.info(f"💡 Generated {len(insights)} total insights ({len(llm_insights)} LLM, {len(fitness_insights)} fitness)")
            return insights

        except Exception as e:
            logger.error(f"Insight generation failed: {e}", exc_info=True)
            db.rollback()
            return []

    async def _gather_insight_context(
        self,
        db: Session,
        user_id: str,
        day: datetime,
        traces: List[Dict],
        clusters: List[List[Dict]],
        summaries: List[Dict]
    ) -> Dict[str, Any]:
        """Gather all context needed for LLM insight generation"""

        # Get recent insights to avoid repetition
        recent_insights = await self._get_recent_insights(db, user_id, days=7)

        # Get active projects
        active_projects = await self._get_active_projects(db, user_id)

        # Extract representative conversation snippets
        conversation_snippets = self._extract_conversation_snippets(traces, clusters)

        return {
            "day": day.strftime("%A, %B %d, %Y"),
            "total_traces": len(traces),
            "cluster_count": len(clusters),
            "summaries": summaries,
            "conversation_snippets": conversation_snippets,
            "recent_insights": recent_insights,
            "active_projects": active_projects
        }

    async def _get_recent_insights(self, db: Session, user_id: str, days: int = 7) -> List[Dict]:
        """Get insights from the last N days to avoid repetition"""
        from app.main_simple import DreamInsight

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        recent = db.query(DreamInsight).filter(
            DreamInsight.user_id == user_id,
            DreamInsight.dream_date >= cutoff
        ).order_by(desc(DreamInsight.dream_date)).limit(20).all()

        return [
            {
                "type": r.insight_type,
                "title": r.title,
                "content": r.content[:200],
                "date": r.dream_date.strftime("%Y-%m-%d")
            }
            for r in recent
        ]

    async def _get_active_projects(self, db: Session, user_id: str) -> List[Dict]:
        """Get active projects for context"""
        try:
            from app.models.project_tracker import DevProject, TaskItem

            projects = db.query(DevProject).filter(
                DevProject.user_id == user_id,
                DevProject.is_active == True
            ).all()

            result = []
            for p in projects:
                # Get recent tasks
                recent_tasks = db.query(TaskItem).filter(
                    TaskItem.project_id == p.id,
                    TaskItem.is_deleted == False,
                    TaskItem.status.in_(["in_progress", "todo"])
                ).limit(5).all()

                result.append({
                    "name": p.name,
                    "prefix": p.prefix,
                    "active_tasks": [t.title for t in recent_tasks]
                })

            return result
        except Exception as e:
            logger.warning(f"Could not fetch projects: {e}")
            return []

    def _extract_conversation_snippets(
        self,
        traces: List[Dict],
        clusters: List[List[Dict]]
    ) -> List[Dict]:
        """Extract representative conversation snippets with raw quotes"""
        snippets = []

        for i, cluster in enumerate(clusters[:5]):  # Limit to 5 clusters
            # Get user messages from this cluster
            user_messages = [t for t in cluster if t.get("role") == "user"]
            sara_messages = [t for t in cluster if t.get("role") != "user"]

            # Pick representative quotes (up to 3 per cluster)
            quotes = []
            for msg in user_messages[:3]:
                content = msg.get("content", "")[:300]
                if content:
                    quotes.append(f"David: \"{content}\"")

            for msg in sara_messages[:2]:
                content = msg.get("content", "")[:200]
                if content:
                    quotes.append(f"Sara: \"{content}\"")

            if quotes:
                snippets.append({
                    "cluster_id": i + 1,
                    "message_count": len(cluster),
                    "quotes": quotes,
                    "time_range": f"{cluster[0]['created_at'].strftime('%H:%M')} - {cluster[-1]['created_at'].strftime('%H:%M')}"
                })

        return snippets

    async def _generate_llm_insights(self, context: Dict[str, Any]) -> List[Dict]:
        """Use LLM to generate meaningful insights from context"""
        llm = self._get_llm_client()
        if not llm:
            logger.warning("LLM unavailable, skipping insight generation")
            return []

        # Build the prompt
        prompt = self._build_insight_prompt(context)

        try:
            result = await llm.chat_completion(
                messages=[
                    {"role": "system", "content": self._get_insight_system_prompt()},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.4,
                max_tokens=2000
            )

            response_text = result["choices"][0]["message"]["content"]

            # Parse JSON response
            insights = self._parse_insight_response(response_text)

            logger.info(f"LLM generated {len(insights)} insights")
            return insights

        except Exception as e:
            logger.error(f"LLM insight generation failed: {e}")
            return []

    def _get_insight_system_prompt(self) -> str:
        """System prompt for insight generation"""
        return """You are Sara's reflective subsystem, processing a day of conversations with David to extract insights worth remembering.

Your task is to generate 3-7 insights that are genuinely valuable - things worth surfacing later either proactively or when contextually relevant.

## Insight Types (use exactly these type values)

1. **behavioral_pattern** - Recurring behaviors, habits, or tendencies
   Example: "Third time this week you've mentioned putting off the QA documentation."

2. **connection** - Links between separate conversations or topics
   Example: "Your frustration with the deployment pipeline echoes what you said about CI/CD two weeks ago."

3. **unresolved_thread** - Questions asked, intentions stated, or tasks mentioned without closure
   Example: "On Monday you said you'd look into the FatSecret API rate limits but haven't mentioned it since."

4. **emerging_pattern** - New interests, concerns, or focus areas
   Example: "You've brought up voice interaction quality three times recently."

5. **contradiction** - Changes in stance, mood, or priorities
   Example: "Last week you were excited about projection mapping, but you seem more focused on core features now."

6. **wellbeing_signal** - Energy levels, stress indicators, sleep/exercise mentions
   Example: "You've mentioned being tired in 4 of the last 5 morning conversations."

## Bad Insights (avoid these)
- Pure summaries: "You discussed fitness today"
- Vague emotional labels: "Emotional pattern: neutral"
- Obvious observations: "You're working on Sara"
- Generic encouragement: "Keep up the good work"

## Output Format
Respond with ONLY a JSON array. Each insight object must have:
- "type": One of the 6 types above (lowercase with underscore)
- "title": Short title (under 60 chars)
- "content": The insight itself, written naturally as Sara would say it
- "confidence": 0.0-1.0 based on evidence strength
- "evidence": Brief note on what conversations/data support this
- "surface_strategy": One of "proactive", "contextual", or "passive"
- "expiry_days": How long this stays relevant (null if indefinite, 14 for unresolved threads)

Example output:
[
  {
    "type": "unresolved_thread",
    "title": "API Rate Limits Investigation",
    "content": "You mentioned wanting to look into the FatSecret API rate limits on Monday but haven't brought it up since. Did that get resolved or deprioritized?",
    "confidence": 0.75,
    "evidence": "Monday conversation about food logging performance",
    "surface_strategy": "proactive",
    "expiry_days": 14
  }
]"""

    def _build_insight_prompt(self, context: Dict[str, Any]) -> str:
        """Build the user prompt with context"""
        parts = [f"## Today's Conversations ({context['day']})"]
        parts.append(f"Total messages: {context['total_traces']} across {context['cluster_count']} conversation sessions\n")

        # Add conversation snippets with actual quotes
        if context.get("conversation_snippets"):
            parts.append("### Conversation Excerpts")
            for snippet in context["conversation_snippets"]:
                parts.append(f"\n**Session {snippet['cluster_id']}** ({snippet['time_range']}, {snippet['message_count']} messages):")
                for quote in snippet["quotes"]:
                    parts.append(f"  {quote}")

        # Add summaries if available
        if context.get("summaries"):
            parts.append("\n### Session Summaries")
            for i, summary in enumerate(context["summaries"][:5]):
                topics = ", ".join(summary.get("topics", [])[:3])
                parts.append(f"- Session {i+1}: {summary.get('summary', 'N/A')[:150]} (Topics: {topics})")

        # Add active projects context
        if context.get("active_projects"):
            parts.append("\n### Active Projects")
            for proj in context["active_projects"]:
                tasks = ", ".join(proj.get("active_tasks", [])[:3]) or "No active tasks"
                parts.append(f"- {proj['name']} ({proj['prefix']}): {tasks}")

        # Add recent insights to avoid repetition
        if context.get("recent_insights"):
            parts.append("\n### Recent Insights (avoid repeating these)")
            for ri in context["recent_insights"][:5]:
                parts.append(f"- [{ri['date']}] {ri['title']}: {ri['content'][:100]}...")

        parts.append("\n---")
        parts.append("Generate 3-7 insights based on today's conversations. Focus on unresolved threads, behavioral patterns, and emerging concerns. Respond with only a JSON array.")

        return "\n".join(parts)

    def _parse_insight_response(self, response_text: str) -> List[Dict]:
        """Parse JSON response from LLM"""
        try:
            # Try to extract JSON from response
            text = response_text.strip()

            # Handle markdown code blocks
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            insights = json.loads(text)

            # Validate and clean each insight
            valid_types = ["behavioral_pattern", "connection", "unresolved_thread",
                         "emerging_pattern", "contradiction", "wellbeing_signal"]
            valid_strategies = ["proactive", "contextual", "passive"]

            validated = []
            for insight in insights:
                if not isinstance(insight, dict):
                    continue

                # Validate required fields
                if not insight.get("content") or not insight.get("type"):
                    continue

                # Normalize type
                insight_type = insight["type"].lower().replace(" ", "_")
                if insight_type not in valid_types:
                    insight_type = "pattern"  # Fallback

                # Normalize strategy
                strategy = insight.get("surface_strategy", "contextual").lower()
                if strategy not in valid_strategies:
                    strategy = "contextual"

                validated.append({
                    "type": insight_type,
                    "title": insight.get("title", insight["content"][:50]),
                    "content": insight["content"],
                    "confidence": max(0.0, min(1.0, float(insight.get("confidence", 0.5)))),
                    "evidence": insight.get("evidence", ""),
                    "surface_strategy": strategy,
                    "expiry_days": insight.get("expiry_days")
                })

            return validated

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse insight JSON: {e}")
            logger.debug(f"Response was: {response_text[:500]}")
            return []
        except Exception as e:
            logger.error(f"Error parsing insights: {e}")
            return []

    def _find_related_traces(self, traces: List[Dict], evidence: str) -> List[str]:
        """Find trace IDs that might be related to the evidence"""
        if not evidence:
            return []

        evidence_lower = evidence.lower()
        related = []

        for trace in traces:
            content = (trace.get("content") or "").lower()
            # Simple keyword matching
            if any(word in content for word in evidence_lower.split()[:5]):
                related.append(trace["id"])
                if len(related) >= 5:
                    break

        return related

    async def _generate_fitness_insights(
        self,
        db: Session,
        user_id: str,
        day: datetime
    ) -> List:
        """Generate data-driven fitness insights (separate from LLM insights)"""
        from app.main_simple import DreamInsight
        import uuid

        insights = []
        fitness_metrics = await self._fetch_fitness_metrics(db, user_id, day)

        # Workout summary
        if fitness_metrics["workouts"]["count"] > 0:
            insights.append(DreamInsight(
                id=str(uuid.uuid4()),
                user_id=user_id,
                dream_date=day,
                insight_type="fitness_workout",
                confidence=0.9,
                title=f"Training Day - {fitness_metrics['workouts']['count']} Workout{'s' if fitness_metrics['workouts']['count'] > 1 else ''}",
                content=f"Completed {fitness_metrics['workouts']['total_sets']} sets with {fitness_metrics['workouts']['total_volume']}lbs total volume (avg RPE: {fitness_metrics['workouts']['avg_rpe']})",
                related_episodes=json.dumps([]),
                surface_strategy="passive",  # Don't proactively surface fitness metrics
                surfaced_count=0
            ))

        # Nutrition summary
        if fitness_metrics["nutrition"]["meals_count"] > 0:
            insights.append(DreamInsight(
                id=str(uuid.uuid4()),
                user_id=user_id,
                dream_date=day,
                insight_type="fitness_nutrition",
                confidence=0.9,
                title=f"Nutrition - {fitness_metrics['nutrition']['meals_count']} Meals Logged",
                content=f"{fitness_metrics['nutrition']['calories']}cal | {fitness_metrics['nutrition']['protein']}g protein, {fitness_metrics['nutrition']['carbs']}g carbs, {fitness_metrics['nutrition']['fats']}g fats",
                related_episodes=json.dumps([]),
                surface_strategy="passive",
                surfaced_count=0
            ))

        # Training volume trend (only if significant change)
        if fitness_metrics["workouts"]["count"] > 0 and fitness_metrics["weekly_avg"]["workouts"] > 0:
            volume_change = fitness_metrics["workouts"]["total_volume"] - fitness_metrics["weekly_avg"]["volume"]
            if abs(volume_change) > fitness_metrics["weekly_avg"]["volume"] * 0.2:
                trend_direction = "increased" if volume_change > 0 else "decreased"
                insights.append(DreamInsight(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    dream_date=day,
                    insight_type="fitness_trend",
                    confidence=0.75,
                    title=f"Training Volume {trend_direction.title()}",
                    content=f"Today's volume ({fitness_metrics['workouts']['total_volume']}lbs) {trend_direction} by {abs(volume_change):.0f}lbs compared to your 7-day average ({fitness_metrics['weekly_avg']['volume']}lbs)",
                    related_episodes=json.dumps([]),
                    surface_strategy="contextual",  # Surface when discussing fitness
                    surfaced_count=0
                ))

        return insights

    async def _store_summaries(
        self,
        db: Session,
        user_id: str,
        day: datetime,
        summaries: List[Dict]
    ) -> List[str]:
        """Store cluster summaries as memory traces"""
        from app.main_simple import MemoryTrace, MemoryEmbedding, MemoryEdge, PGVECTOR_AVAILABLE, DATABASE_URL

        summary_ids = []
        embedding_fn = self._get_embedding_service()

        try:
            for i, summary in enumerate(summaries):
                # Create summary trace
                summary_id = str(__import__('uuid').uuid4())
                trace = MemoryTrace(
                    id=summary_id,
                    user_id=user_id,
                    content=summary["summary"],
                    role="summary",
                    salience=0.7,  # Summaries are important
                    source=json.dumps({
                        "type": "dream_consolidation",
                        "cluster_size": summary["cluster_size"],
                        "day": day.isoformat()
                    }),
                    meta=json.dumps({
                        "topics": summary["topics"],
                        "emotional_tone": summary["emotional_tone"],
                        "key_points": summary["key_points"]
                    })
                )
                db.add(trace)
                summary_ids.append(summary_id)

                # Generate embedding for summary
                if embedding_fn:
                    try:
                        emb = await embedding_fn(summary["summary"])
                        if emb:
                            me = MemoryEmbedding(
                                trace_id=summary_id,
                                head="semantic",
                                embedding=emb if (PGVECTOR_AVAILABLE and DATABASE_URL.startswith("postgresql")) else json.dumps(emb)
                            )
                            db.add(me)
                    except Exception as e:
                        logger.warning(f"Failed to generate summary embedding: {e}")

                # Link summary to its constituent traces
                for trace_id in summary["trace_ids"]:
                    edge = MemoryEdge(
                        src=summary_id,
                        dst=trace_id,
                        type="summary_of",
                        weight=0.8
                    )
                    db.merge(edge)

            db.commit()
            return summary_ids

        except Exception as e:
            logger.error(f"Failed to store summaries: {e}")
            db.rollback()
            return []


# Global instance
dream_consolidation_service = DreamConsolidationService()
