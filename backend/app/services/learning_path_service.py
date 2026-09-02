"""
Learning Path Service
Generates personalized learning paths and study recommendations based on:
- Knowledge gaps
- Topic relationships
- Mastery levels
- Spaced repetition principles
"""
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from datetime import datetime, timedelta, timezone
import asyncio
import logging

from app.models.learning import (
    LearningTopic, TopicSource, SourceChunk, TopicScratchpad,
    TopicConnection, LearningProgress, LearningArtifact,
)
from app.services.embedding_service import embedding_service

logger = logging.getLogger(__name__)


class LearningPathService:
    """Service for generating learning paths and study recommendations"""

    # Mastery thresholds
    MASTERY_BEGINNER = 0.3
    MASTERY_INTERMEDIATE = 0.6
    MASTERY_ADVANCED = 0.85

    # Time thresholds for spaced repetition
    REVIEW_INTERVALS = {
        "new": timedelta(days=1),
        "learning": timedelta(days=3),
        "reviewing": timedelta(days=7),
        "mastered": timedelta(days=30)
    }

    async def get_persisted_curriculum(
        self,
        topic_id: str,
        user_id: str,
        db: Session
    ) -> Optional[Dict[str, Any]]:
        """Return the persisted curriculum JSONB from topic_scratchpad, or None."""
        scratchpad = db.query(TopicScratchpad).filter(
            TopicScratchpad.topic_id == topic_id,
            TopicScratchpad.user_id == user_id
        ).first()
        if scratchpad and scratchpad.curriculum:
            return scratchpad.curriculum
        return None

    def persist_curriculum(
        self,
        topic_id: str,
        user_id: str,
        db: Session,
        path_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Save a curriculum to topic_scratchpad.curriculum JSONB.
        Adds status fields to each step: first = 'active', rest = 'pending'.
        Returns the persisted curriculum dict.
        """
        from sqlalchemy.orm.attributes import flag_modified

        scratchpad = db.query(TopicScratchpad).filter(
            TopicScratchpad.topic_id == topic_id,
            TopicScratchpad.user_id == user_id
        ).first()

        if not scratchpad:
            import uuid as _uuid
            scratchpad = TopicScratchpad(
                id=str(_uuid.uuid4()),
                topic_id=topic_id,
                user_id=user_id,
                content=""
            )
            db.add(scratchpad)

        steps = path_data.get("path", [])
        curriculum = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary": path_data.get("summary", ""),
            "steps": []
        }
        for i, step in enumerate(steps):
            curriculum["steps"].append({
                "index": i,
                "concept": step.get("topic_title", f"Step {i+1}"),
                "description": step["actions"][0]["description"] if step.get("actions") else "",
                "action_type": step["actions"][0].get("type", "study") if step.get("actions") else "study",
                "estimated_time": step.get("estimated_time", "15 min"),
                "reason": step.get("reason", ""),
                "status": "active" if i == 0 else "pending",
                "completed_at": None
            })

        scratchpad.curriculum = curriculum
        flag_modified(scratchpad, "curriculum")
        db.commit()
        return curriculum

    async def generate_learning_path(
        self,
        user_id: str,
        db: Session,
        focus_topic_id: Optional[str] = None,
        max_steps: int = 10,
        force_regenerate: bool = False
    ) -> Dict[str, Any]:
        """
        Generate a learning path. If focus_topic_id is provided, generates
        a deep study plan for that single topic. Otherwise generates a
        cross-topic prioritization path.
        """
        try:
            # If a specific topic is focused, generate a topic-specific path
            if focus_topic_id:
                # Check for persisted curriculum first (unless force regenerate)
                if not force_regenerate:
                    persisted = await self.get_persisted_curriculum(focus_topic_id, user_id, db)
                    if persisted:
                        # Convert persisted curriculum back to path format
                        return self._curriculum_to_path_format(persisted, focus_topic_id)

                result = await self._generate_topic_path(user_id, focus_topic_id, max_steps, db)

                # Auto-persist after LLM generation
                if result.get("path"):
                    curriculum = self.persist_curriculum(focus_topic_id, user_id, db, result)
                    # Return with persisted status info
                    return self._curriculum_to_path_format(curriculum, focus_topic_id)

                return result

            # Otherwise, generate the cross-topic priority path
            topics = self._get_topics_with_stats(user_id, db)

            if not topics:
                return {
                    "path": [],
                    "summary": "No active learning topics found. Create a topic to get started!",
                    "recommendations": [
                        {
                            "type": "action",
                            "message": "Create your first learning topic to begin your journey",
                            "priority": "high"
                        }
                    ]
                }

            scored_topics = self._score_topics(topics)
            path_steps = self._generate_path_steps(scored_topics, max_steps, db)
            summary = self._generate_summary(topics, path_steps)
            recommendations = self._generate_recommendations(topics, scored_topics)

            return {
                "path": path_steps,
                "summary": summary,
                "recommendations": recommendations,
                "stats": {
                    "total_topics": len(topics),
                    "avg_mastery": sum(t["mastery"] for t in topics) / len(topics) if topics else 0,
                    "topics_needing_review": len([t for t in topics if t["needs_review"]]),
                    "topics_with_gaps": len([t for t in topics if t["has_gaps"]])
                }
            }

        except Exception as e:
            logger.error(f"Failed to generate learning path: {e}")
            return {
                "path": [],
                "summary": f"Error generating learning path: {str(e)}",
                "recommendations": []
            }

    async def _generate_topic_path(
        self,
        user_id: str,
        topic_id: str,
        max_steps: int,
        db: Session
    ) -> Dict[str, Any]:
        """Generate a study plan for a single topic using LLM analysis of its sources."""
        import json as _json
        import re as _re

        topic = db.query(LearningTopic).filter(
            LearningTopic.id == topic_id,
            LearningTopic.user_id == user_id
        ).first()
        if not topic:
            return {"path": [], "summary": "Topic not found.", "recommendations": []}

        mastery = topic.mastery_level or 0.0

        # Gather source chunks for context
        chunks = db.query(SourceChunk).join(TopicSource).filter(
            TopicSource.topic_id == topic_id,
            TopicSource.fetch_status == "fetched"
        ).limit(20).all()

        # Gather anchors
        anchors_text = ""
        try:
            from app.models.anchor_point import AnchorPoint
            anchors = db.query(AnchorPoint).filter(
                AnchorPoint.topic_id == topic_id,
                AnchorPoint.rejected == False
            ).all()
            if anchors:
                anchors_text = "\n".join([
                    f"- {a.anchor_concept} (from {a.anchor_domain}): {a.bridge_description}"
                    for a in anchors
                ])
        except Exception:
            pass

        # Gather existing progress
        progress_items = db.query(LearningProgress).filter(
            LearningProgress.topic_id == topic_id,
            LearningProgress.user_id == user_id
        ).all()
        reviewed_concepts = [p.concept for p in progress_items if p.concept]

        # Gather connected topics
        connections = db.query(TopicConnection).filter(
            (TopicConnection.source_topic_id == topic_id) |
            (TopicConnection.target_topic_id == topic_id)
        ).all()
        prereqs = []
        related = []
        for conn in connections:
            other_id = conn.target_topic_id if conn.source_topic_id == topic_id else conn.source_topic_id
            other = db.query(LearningTopic).filter(LearningTopic.id == other_id).first()
            if other:
                if conn.connection_type == "prerequisite":
                    prereqs.append(other.title)
                else:
                    related.append(other.title)

        # Use LLM to generate a comprehensive study plan based on the topic itself
        try:
            from app.core.llm import llm_client

            # Build context sections outside f-string to avoid backslash issues
            desc_line = f"Description: {topic.description}" if topic.description else ""
            prereqs_line = f"Prerequisites: {', '.join(prereqs)}" if prereqs else ""
            related_line = f"Related topics: {', '.join(related)}" if related else ""
            reviewed_line = f"Concepts already reviewed: {', '.join(reviewed_concepts[:10])}" if reviewed_concepts else "No concepts reviewed yet."
            anchors_line = f"Analogies available:\n{anchors_text}" if anchors_text else ""
            mastery_pct = int(mastery * 100)
            step_count = min(max_steps, 8)
            has_sources = len(chunks) > 0

            prompt = f"""You are a learning coach creating a comprehensive study plan for David on the topic "{topic.title}".
{desc_line}

Current mastery: {mastery_pct}%
{prereqs_line}
{related_line}
{reviewed_line}
{anchors_line}
Has source materials: {"yes" if has_sources else "no"}

David is a software engineer who learns best through analogies. He knows: server architecture, networking, containerization, databases, home automation, fitness, software patterns, AI/LLM systems.

Using YOUR knowledge of this topic, create a complete {step_count}-step learning path from beginner to proficient. Cover ALL the key concepts someone needs to master this topic, ordered from foundational to advanced. Do NOT limit yourself to any provided sources — devise the ideal curriculum.

For each step, include:
- A clear concept/skill name
- What to learn, why it matters, and how it connects to previous steps
- Estimated time
- The right learning activity: study (learn the concept), practice (build something), review (test understanding), or connect (relate to other knowledge)

Output ONLY valid JSON:
{{
  "steps": [
    {{
      "concept": "concept name",
      "description": "what to learn and why — be specific and practical",
      "action_type": "study|practice|review|connect",
      "estimated_time": "10-15 min",
      "reason": "why this step comes here in the sequence"
    }}
  ],
  "summary": "1-2 sentence overview of the full learning journey"
}}"""

            messages = [{"role": "user", "content": prompt}]

            # enable_thinking=False — without it qwen burns the whole token/time
            # budget "thinking" and the request ReadTimeouts before emitting JSON.
            # Retry once to absorb the occasional transient drop from the .115 server.
            result = None
            last_err = None
            for attempt in range(2):
                try:
                    result = await llm_client.chat_completion(
                        messages=messages,
                        max_tokens=2000,
                        temperature=0.5,
                        timeout=60.0,
                        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
                    )
                    break
                except Exception as e:
                    last_err = e
                    logger.warning(f"LLM topic path attempt {attempt + 1}/2 failed: {e!r}")
                    if attempt < 1:
                        await asyncio.sleep(1.5)
            if result is None:
                raise last_err or RuntimeError("LLM call returned no result")

            response = result.get("choices", [{}])[0].get("message", {}).get("content", "")

            json_match = _re.search(r'\{[\s\S]*\}', response)
            if json_match:
                data = _json.loads(json_match.group())
                llm_steps = data.get("steps", [])
                summary = data.get("summary", f"Study plan for {topic.title}")

                path_steps = []
                for i, step in enumerate(llm_steps[:max_steps]):
                    action_type = step.get("action_type", "study")
                    path_steps.append({
                        "topic_id": topic_id,
                        "topic_title": step.get("concept", f"Step {i+1}"),
                        "priority_score": 100 - i * 5,
                        "current_mastery": mastery,
                        "actions": [{
                            "type": action_type,
                            "description": step.get("description", ""),
                        }],
                        "estimated_time": step.get("estimated_time", "15 min"),
                        "reason": step.get("reason", "")
                    })

                recommendations = []
                if not anchors_text:
                    recommendations.append({
                        "type": "anchor_needed",
                        "message": "No analogies mapped yet — generate anchors to make concepts stick faster.",
                        "priority": "medium"
                    })
                if mastery < 0.3 and len(chunks) < 5:
                    recommendations.append({
                        "type": "content_gap",
                        "message": "Limited source material. Consider adding more sources for deeper coverage.",
                        "priority": "medium"
                    })

                return {
                    "path": path_steps,
                    "summary": summary,
                    "recommendations": recommendations,
                    "stats": {
                        "total_topics": 1,
                        "avg_mastery": mastery,
                        "topics_needing_review": 1 if reviewed_concepts else 0,
                        "topics_with_gaps": 1 if len(chunks) < 5 else 0
                    }
                }

        except Exception as e:
            logger.warning(f"LLM topic path generation failed after retries, falling back: {e!r}")

        # Fallback if LLM fails
        return {
            "path": [{
                "topic_id": topic_id,
                "topic_title": topic.title,
                "priority_score": 100,
                "current_mastery": mastery,
                "actions": [{"type": "study", "description": "Start a learning chat to explore this topic with Sara"}],
                "estimated_time": "20-30 min",
                "reason": "Begin exploring the topic"
            }],
            "summary": f"Could not generate a detailed path for '{topic.title}'. Start a learning chat to get going.",
            "recommendations": [],
            "stats": {
                "total_topics": 1,
                "avg_mastery": mastery,
                "topics_needing_review": 0,
                "topics_with_gaps": 0
            }
        }

    def _curriculum_to_path_format(
        self,
        curriculum: Dict[str, Any],
        topic_id: str
    ) -> Dict[str, Any]:
        """Convert persisted curriculum JSONB back to the path response format."""
        steps = curriculum.get("steps", [])
        path_steps = []
        for step in steps:
            path_steps.append({
                "topic_id": topic_id,
                "topic_title": step.get("concept", ""),
                "priority_score": 100 - step.get("index", 0) * 5,
                "current_mastery": 0.0,
                "actions": [{
                    "type": step.get("action_type", "study"),
                    "description": step.get("description", ""),
                }],
                "estimated_time": step.get("estimated_time", "15 min"),
                "reason": step.get("reason", ""),
                "status": step.get("status", "pending"),
                "completed_at": step.get("completed_at"),
            })

        completed = sum(1 for s in steps if s.get("status") == "completed")
        total = len(steps)

        return {
            "path": path_steps,
            "summary": curriculum.get("summary", ""),
            "recommendations": [],
            "stats": {
                "total_topics": 1,
                "avg_mastery": completed / total if total else 0,
                "topics_needing_review": 0,
                "topics_with_gaps": 0
            },
            "persisted": True,
            "generated_at": curriculum.get("generated_at"),
            "progress": {"completed": completed, "total": total}
        }

    def _get_topics_with_stats(self, user_id: str, db: Session) -> List[Dict]:
        """Get all active topics with their statistics"""
        topics = db.query(LearningTopic).filter(
            LearningTopic.user_id == user_id,
            LearningTopic.status == "active"
        ).all()

        result = []
        for topic in topics:
            # Get source stats
            source_count = db.query(TopicSource).filter(
                TopicSource.topic_id == topic.id
            ).count()

            fetched_sources = db.query(TopicSource).filter(
                TopicSource.topic_id == topic.id,
                TopicSource.fetch_status == "fetched"
            ).count()

            chunk_count = db.query(SourceChunk).join(TopicSource).filter(
                TopicSource.topic_id == topic.id
            ).count()

            # Check scratchpad activity
            scratchpad = db.query(TopicScratchpad).filter(
                TopicScratchpad.topic_id == topic.id
            ).first()

            last_activity = topic.updated_at or topic.created_at
            if scratchpad and scratchpad.updated_at:
                if scratchpad.updated_at > last_activity:
                    last_activity = scratchpad.updated_at

            # Determine if needs review based on mastery and time
            mastery = topic.mastery_level or 0.0

            # Handle timezone-aware vs naive datetime comparison
            if last_activity:
                now = datetime.now(timezone.utc)
                # Make last_activity timezone-aware if it isn't
                if last_activity.tzinfo is None:
                    last_activity = last_activity.replace(tzinfo=timezone.utc)
                days_since_activity = (now - last_activity).days
            else:
                days_since_activity = 999

            needs_review = False
            if mastery < self.MASTERY_BEGINNER:
                needs_review = days_since_activity >= 1
            elif mastery < self.MASTERY_INTERMEDIATE:
                needs_review = days_since_activity >= 3
            elif mastery < self.MASTERY_ADVANCED:
                needs_review = days_since_activity >= 7
            else:
                needs_review = days_since_activity >= 30

            # Determine if has gaps
            has_gaps = (
                source_count == 0 or
                fetched_sources == 0 or
                chunk_count < 5
            )

            # Anchor availability (for cognitive scoring)
            has_validated_anchors = False
            has_any_anchors = False
            try:
                from app.models.anchor_point import AnchorPoint
                anchor_count = db.query(AnchorPoint).filter(
                    AnchorPoint.topic_id == topic.id,
                    AnchorPoint.rejected == False
                ).count()
                has_any_anchors = anchor_count > 0
                validated_count = db.query(AnchorPoint).filter(
                    AnchorPoint.topic_id == topic.id,
                    AnchorPoint.validated == True
                ).count()
                has_validated_anchors = validated_count > 0
            except Exception:
                pass

            # Connection density
            connection_count = db.query(TopicConnection).filter(
                (TopicConnection.source_topic_id == topic.id) |
                (TopicConnection.target_topic_id == topic.id)
            ).count()

            # Build artifact exists
            has_artifact = db.query(LearningArtifact).filter(
                LearningArtifact.topic_id == topic.id
            ).count() > 0

            # Click moments from session state (in progress items)
            has_click_moments = False
            try:
                progress_items = db.query(LearningProgress).filter(
                    LearningProgress.topic_id == topic.id,
                    LearningProgress.user_id == user_id
                ).all()
                for p in progress_items:
                    for h in (p.quality_history or []):
                        if h.get("quality", 0) >= 4:
                            has_click_moments = True
                            break
                    if has_click_moments:
                        break
            except Exception:
                pass

            result.append({
                "topic_id": topic.id,
                "title": topic.title,
                "description": topic.description,
                "mastery": mastery,
                "priority": topic.priority or 5,
                "source_count": source_count,
                "fetched_sources": fetched_sources,
                "chunk_count": chunk_count,
                "has_scratchpad": scratchpad is not None and bool(scratchpad.content),
                "last_activity": last_activity,
                "days_since_activity": days_since_activity,
                "needs_review": needs_review,
                "has_gaps": has_gaps,
                "created_at": topic.created_at,
                "has_validated_anchors": has_validated_anchors,
                "has_any_anchors": has_any_anchors,
                "connection_count": connection_count,
                "has_artifact": has_artifact,
                "has_click_moments": has_click_moments,
            })

        return result

    def _score_topics(
        self,
        topics: List[Dict],
        focus_topic_id: Optional[str] = None
    ) -> List[Dict]:
        """Score and rank topics for learning priority.

        Scoring is anchor-aware: topics with validated anchors are easier
        to engage with and get a boost, while topics with no anchors at all
        get a slight penalty (higher friction to start).
        """
        for topic in topics:
            score = 0.0

            # Base priority from user setting (1-10 -> 0-30)
            score += (topic["priority"] / 10) * 30

            # Mastery gap bonus (lower mastery = higher score)
            mastery_gap = 1.0 - topic["mastery"]
            score += mastery_gap * 25

            # Review urgency
            if topic["needs_review"]:
                score += 20

            # Knowledge gap penalty/bonus
            if topic["has_gaps"]:
                if topic["source_count"] == 0:
                    score += 15  # High priority - needs sources
                elif topic["fetched_sources"] == 0:
                    score += 10  # Medium - needs processing

            # Recency factor (recent topics get slight boost)
            if topic["days_since_activity"] < 7:
                score += 5

            # Focus topic bonus
            if focus_topic_id and topic["topic_id"] == focus_topic_id:
                score += 50

            # ── Cognitive profile scoring ──────────────────────

            # Anchor availability: validated anchors = easy to engage
            if topic.get("has_validated_anchors"):
                score += 15
            elif not topic.get("has_any_anchors"):
                score -= 10  # Higher friction — needs anchors first

            # Click moments = momentum, connected to recent breakthroughs
            if topic.get("has_click_moments"):
                score += 10

            # Connection density: well-connected topics are easier to study
            conn_count = min(topic.get("connection_count", 0), 3)
            score += conn_count * 5  # max +15

            # Build artifact exists: proof of encoding
            if topic.get("has_artifact"):
                score += 5

            topic["learning_score"] = round(score, 2)

        # Sort by score (highest first)
        return sorted(topics, key=lambda x: -x["learning_score"])

    def _generate_path_steps(
        self,
        scored_topics: List[Dict],
        max_steps: int,
        db: Session
    ) -> List[Dict]:
        """Generate specific learning path steps"""
        steps = []

        for topic in scored_topics[:max_steps]:
            step = {
                "topic_id": topic["topic_id"],
                "topic_title": topic["title"],
                "priority_score": topic["learning_score"],
                "current_mastery": topic["mastery"],
                "actions": [],
                "estimated_time": "15-30 min",
                "reason": ""
            }

            # Determine what actions to take
            if topic["source_count"] == 0:
                step["actions"].append({
                    "type": "add_sources",
                    "description": f"Find learning resources for '{topic['title']}'",
                    "suggestion": f"Search for '{topic['title']} tutorial' or '{topic['title']} guide'"
                })
                step["reason"] = "No learning sources yet"
                step["estimated_time"] = "5-10 min"

            elif topic["fetched_sources"] == 0:
                step["actions"].append({
                    "type": "fetch_sources",
                    "description": "Process your sources to enable AI-assisted learning"
                })
                step["reason"] = "Sources need to be processed"
                step["estimated_time"] = "2-5 min"

            elif topic["mastery"] < self.MASTERY_BEGINNER:
                if topic.get("has_validated_anchors"):
                    step["actions"].append({
                        "type": "study",
                        "description": f"Start learning '{topic['title']}' — you have strong analogies mapped to build on",
                        "focus": "anchor-guided fundamentals"
                    })
                    step["reason"] = "Anchored topic — easy to engage"
                elif not topic.get("has_any_anchors"):
                    step["actions"].append({
                        "type": "generate_anchors",
                        "description": f"Generate analogy anchors for '{topic['title']}' before diving in"
                    })
                    step["actions"].append({
                        "type": "study",
                        "description": f"Start learning the basics of '{topic['title']}'",
                        "focus": "fundamentals"
                    })
                    step["reason"] = "Needs anchors first — generate analogies to make it stick"
                else:
                    step["actions"].append({
                        "type": "study",
                        "description": f"Start learning the basics of '{topic['title']}'",
                        "focus": "fundamentals"
                    })
                    step["reason"] = "Building foundational knowledge"
                if not topic["has_scratchpad"]:
                    step["actions"].append({
                        "type": "take_notes",
                        "description": "Start a scratchpad to capture key concepts"
                    })
                step["estimated_time"] = "20-30 min"

            elif topic["mastery"] < self.MASTERY_INTERMEDIATE:
                step["actions"].append({
                    "type": "study",
                    "description": f"Deepen understanding of '{topic['title']}'",
                    "focus": "connections and applications"
                })
                step["actions"].append({
                    "type": "practice",
                    "description": "Try explaining concepts in your own words"
                })
                step["reason"] = "Moving from basics to deeper understanding"
                step["estimated_time"] = "25-35 min"

            elif topic["mastery"] < self.MASTERY_ADVANCED:
                step["actions"].append({
                    "type": "review",
                    "description": f"Review and reinforce '{topic['title']}'",
                    "focus": "edge cases and nuances"
                })
                step["actions"].append({
                    "type": "connect",
                    "description": "Explore connections to other topics you know"
                })
                step["reason"] = "Consolidating knowledge"
                step["estimated_time"] = "15-25 min"

            else:
                if topic["needs_review"]:
                    step["actions"].append({
                        "type": "quick_review",
                        "description": f"Quick refresher on '{topic['title']}'"
                    })
                    step["reason"] = "Spaced repetition review"
                    step["estimated_time"] = "5-10 min"
                else:
                    step["actions"].append({
                        "type": "teach",
                        "description": "Try teaching this topic to solidify mastery"
                    })
                    step["reason"] = "Maintaining mastery through teaching"
                    step["estimated_time"] = "10-15 min"

            steps.append(step)

        return steps

    def _generate_summary(self, topics: List[Dict], path_steps: List[Dict]) -> str:
        """Generate a human-readable summary of the learning path"""
        total = len(topics)
        with_gaps = len([t for t in topics if t["has_gaps"]])
        needing_review = len([t for t in topics if t["needs_review"]])
        avg_mastery = sum(t["mastery"] for t in topics) / total if total else 0

        parts = []

        # Overall status
        if avg_mastery < 0.3:
            parts.append(f"You're just getting started with {total} topic(s).")
        elif avg_mastery < 0.6:
            parts.append(f"Good progress on {total} topic(s) - building solid foundations.")
        elif avg_mastery < 0.85:
            parts.append(f"Strong knowledge across {total} topic(s) - keep pushing!")
        else:
            parts.append(f"Excellent mastery of {total} topic(s)!")

        # Specific recommendations
        if with_gaps > 0:
            parts.append(f"{with_gaps} topic(s) need more learning resources.")

        if needing_review > 0:
            parts.append(f"{needing_review} topic(s) are due for review.")

        # Next step
        if path_steps:
            top_step = path_steps[0]
            parts.append(f"Recommended focus: {top_step['topic_title']}")

        return " ".join(parts)

    def _generate_recommendations(
        self,
        topics: List[Dict],
        scored_topics: List[Dict]
    ) -> List[Dict]:
        """Generate strategic recommendations (anchor/tangent-aware)."""
        recommendations = []

        # Check for topics without sources
        no_sources = [t for t in topics if t["source_count"] == 0]
        if no_sources:
            recommendations.append({
                "type": "content_gap",
                "message": f"{len(no_sources)} topic(s) have no learning sources. Add some resources to enable effective studying.",
                "priority": "high",
                "affected_topics": [t["title"] for t in no_sources[:3]]
            })

        # Check for unprocessed sources
        unprocessed = [t for t in topics if t["source_count"] > 0 and t["fetched_sources"] == 0]
        if unprocessed:
            recommendations.append({
                "type": "processing_needed",
                "message": f"{len(unprocessed)} topic(s) have sources that need processing.",
                "priority": "medium",
                "affected_topics": [t["title"] for t in unprocessed[:3]]
            })

        # Topics needing anchors — high friction to start without them
        no_anchors = [t for t in topics if not t.get("has_any_anchors") and t["mastery"] < self.MASTERY_INTERMEDIATE]
        if no_anchors:
            recommendations.append({
                "type": "anchor_needed",
                "message": f"{len(no_anchors)} topic(s) need anchor points — generate analogies from your known domains to make them easier to engage with.",
                "priority": "medium",
                "affected_topics": [t["title"] for t in no_anchors[:3]]
            })

        # Topics with validated anchors ready for deeper study
        anchored_ready = [t for t in scored_topics if t.get("has_validated_anchors") and t["mastery"] < self.MASTERY_INTERMEDIATE]
        if anchored_ready:
            top = anchored_ready[0]
            recommendations.append({
                "type": "anchored_momentum",
                "message": f"'{top['title']}' has strong analogies mapped — great time to dive deeper while the connections are fresh.",
                "priority": "high"
            })

        # Suggest related topics to explore
        if scored_topics and len(scored_topics) >= 2:
            top_topic = scored_topics[0]
            if top_topic["mastery"] >= self.MASTERY_INTERMEDIATE:
                recommendations.append({
                    "type": "exploration",
                    "message": f"You're doing well with '{top_topic['title']}'. Consider exploring related advanced topics.",
                    "priority": "low"
                })

        # Spaced repetition reminder
        overdue_review = [t for t in topics if t["needs_review"] and t["mastery"] >= self.MASTERY_BEGINNER]
        if overdue_review:
            recommendations.append({
                "type": "review_reminder",
                "message": f"{len(overdue_review)} topic(s) are due for spaced repetition review to maintain knowledge.",
                "priority": "medium",
                "affected_topics": [t["title"] for t in overdue_review[:3]]
            })

        # Consistency reminder
        inactive = [t for t in topics if t["days_since_activity"] > 14]
        if inactive:
            recommendations.append({
                "type": "consistency",
                "message": f"{len(inactive)} topic(s) haven't been studied in over 2 weeks. Regular practice helps retention.",
                "priority": "medium"
            })

        return recommendations

    async def get_next_study_session(
        self,
        user_id: str,
        db: Session,
        duration_minutes: int = 30
    ) -> Dict[str, Any]:
        """
        Get a recommended study session based on available time.

        Args:
            user_id: User ID
            db: Database session
            duration_minutes: Available study time in minutes

        Returns:
            Study session plan
        """
        path = await self.generate_learning_path(user_id, db, max_steps=5)

        if not path["path"]:
            return {
                "topic": None,
                "actions": [],
                "message": "Create some learning topics to get started!",
                "duration": 0
            }

        # Find the best fit for the available time
        for step in path["path"]:
            # Parse estimated time
            time_str = step.get("estimated_time", "15-30 min")
            min_time = int(time_str.split("-")[0].replace(" min", ""))

            if min_time <= duration_minutes:
                return {
                    "topic_id": step["topic_id"],
                    "topic_title": step["topic_title"],
                    "actions": step["actions"],
                    "reason": step["reason"],
                    "estimated_time": step["estimated_time"],
                    "message": f"Focus on '{step['topic_title']}': {step['reason']}"
                }

        # If no perfect fit, return the first one
        first_step = path["path"][0]
        return {
            "topic_id": first_step["topic_id"],
            "topic_title": first_step["topic_title"],
            "actions": first_step["actions"],
            "reason": first_step["reason"],
            "estimated_time": first_step["estimated_time"],
            "message": f"Quick session on '{first_step['topic_title']}'"
        }


# Singleton instance
learning_path_service = LearningPathService()
