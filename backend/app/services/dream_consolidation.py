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

            result = json.loads(response)

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
        """Generate DreamInsight records for interesting patterns"""
        from app.main_simple import DreamInsight

        insights = []

        try:
            # Fetch fitness metrics for the day
            fitness_metrics = await self._fetch_fitness_metrics(db, user_id, day)
            # Insight 1: Daily summary
            if summaries:
                daily_summary = DreamInsight(
                    user_id=user_id,
                    dream_date=day,
                    insight_type="summary",
                    confidence=0.9,
                    title=f"Daily Summary - {day.strftime('%B %d, %Y')}",
                    content=f"Processed {len(traces)} memories across {len(clusters)} themes: " +
                            ", ".join([s.get("topics", ["unknown"])[0] for s in summaries[:3]]),
                    related_episodes=json.dumps([t["id"] for t in traces[:20]])
                )
                db.add(daily_summary)
                insights.append(daily_summary.id)

            # Insight 2: Pattern detection (high-salience clusters)
            for summary in summaries:
                if summary["cluster_size"] >= 5:  # Significant cluster
                    pattern_insight = DreamInsight(
                        user_id=user_id,
                        dream_date=day,
                        insight_type="pattern",
                        confidence=0.75,
                        title=f"Recurring Theme: {summary.get('topics', ['Unknown'])[0].title()}",
                        content=summary.get("summary", "Multiple related memories detected"),
                        related_episodes=json.dumps(summary["trace_ids"][:10])
                    )
                    db.add(pattern_insight)
                    insights.append(pattern_insight.id)

            # Insight 3: Forgotten gems (old but relevant traces)
            high_salience_traces = [t for t in traces if t["salience"] > 0.8]
            if high_salience_traces:
                gem = high_salience_traces[0]  # Most salient
                forgotten_gem = DreamInsight(
                    user_id=user_id,
                    dream_date=day,
                    insight_type="forgotten_gem",
                    confidence=0.6,
                    title="Important Memory Resurfaced",
                    content=gem["content"][:200] + "...",
                    related_episodes=json.dumps([gem["id"]])
                )
                db.add(forgotten_gem)
                insights.append(forgotten_gem.id)

            # Insight 4: Fitness - Workout Summary
            if fitness_metrics["workouts"]["count"] > 0:
                workout_summary = DreamInsight(
                    user_id=user_id,
                    dream_date=day,
                    insight_type="fitness_workout",
                    confidence=0.9,
                    title=f"Training Day - {fitness_metrics['workouts']['count']} Workout{'s' if fitness_metrics['workouts']['count'] > 1 else ''}",
                    content=f"Completed {fitness_metrics['workouts']['total_sets']} sets with {fitness_metrics['workouts']['total_volume']}lbs total volume (avg RPE: {fitness_metrics['workouts']['avg_rpe']})",
                    related_episodes=json.dumps([])
                )
                db.add(workout_summary)
                insights.append(workout_summary.id)

            # Insight 5: Fitness - Nutrition Summary
            if fitness_metrics["nutrition"]["meals_count"] > 0:
                nutrition_summary = DreamInsight(
                    user_id=user_id,
                    dream_date=day,
                    insight_type="fitness_nutrition",
                    confidence=0.9,
                    title=f"Nutrition - {fitness_metrics['nutrition']['meals_count']} Meals Logged",
                    content=f"{fitness_metrics['nutrition']['calories']}cal | {fitness_metrics['nutrition']['protein']}g protein, {fitness_metrics['nutrition']['carbs']}g carbs, {fitness_metrics['nutrition']['fats']}g fats",
                    related_episodes=json.dumps([])
                )
                db.add(nutrition_summary)
                insights.append(nutrition_summary.id)

            # Insight 6: Fitness - Training Trend
            if fitness_metrics["workouts"]["count"] > 0 and fitness_metrics["weekly_avg"]["workouts"] > 0:
                volume_change = fitness_metrics["workouts"]["total_volume"] - fitness_metrics["weekly_avg"]["volume"]
                if abs(volume_change) > fitness_metrics["weekly_avg"]["volume"] * 0.2:  # 20% change
                    trend_direction = "increased" if volume_change > 0 else "decreased"
                    trend_insight = DreamInsight(
                        user_id=user_id,
                        dream_date=day,
                        insight_type="fitness_trend",
                        confidence=0.75,
                        title=f"Training Volume {trend_direction.title()}",
                        content=f"Today's volume ({fitness_metrics['workouts']['total_volume']}lbs) {trend_direction} by {abs(volume_change):.0f}lbs compared to your 7-day average ({fitness_metrics['weekly_avg']['volume']}lbs)",
                        related_episodes=json.dumps([])
                    )
                    db.add(trend_insight)
                    insights.append(trend_insight.id)

            # Insight 7: Fitness - Protein Target
            if fitness_metrics["nutrition"]["protein"] > 0:
                # Assume target of 0.8g per lb bodyweight (adjust as needed)
                # For now, check if they hit >100g as a simple threshold
                if fitness_metrics["nutrition"]["protein"] >= 100:
                    protein_insight = DreamInsight(
                        user_id=user_id,
                        dream_date=day,
                        insight_type="fitness_nutrition",
                        confidence=0.8,
                        title="Protein Goal Achieved",
                        content=f"Hit {fitness_metrics['nutrition']['protein']}g protein today - great for recovery and muscle growth",
                        related_episodes=json.dumps([])
                    )
                    db.add(protein_insight)
                    insights.append(protein_insight.id)

            db.commit()
            return insights

        except Exception as e:
            logger.error(f"Insight generation failed: {e}")
            db.rollback()
            return []

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
