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
import logging

from app.models.learning import LearningTopic, TopicSource, SourceChunk, TopicScratchpad
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

    async def generate_learning_path(
        self,
        user_id: str,
        db: Session,
        focus_topic_id: Optional[str] = None,
        max_steps: int = 10
    ) -> Dict[str, Any]:
        """
        Generate a personalized learning path for the user.

        Args:
            user_id: User ID
            db: Database session
            focus_topic_id: Optional topic to focus the path on
            max_steps: Maximum number of steps in the path

        Returns:
            Learning path with prioritized steps and recommendations
        """
        try:
            # Get all active topics with their stats
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

            # Score and prioritize topics
            scored_topics = self._score_topics(topics, focus_topic_id)

            # Generate path steps
            path_steps = self._generate_path_steps(scored_topics, max_steps, db)

            # Generate summary and recommendations
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
                "created_at": topic.created_at
            })

        return result

    def _score_topics(
        self,
        topics: List[Dict],
        focus_topic_id: Optional[str] = None
    ) -> List[Dict]:
        """Score and rank topics for learning priority"""
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
                step["actions"].append({
                    "type": "study",
                    "description": f"Start learning the basics of '{topic['title']}'",
                    "focus": "fundamentals"
                })
                if not topic["has_scratchpad"]:
                    step["actions"].append({
                        "type": "take_notes",
                        "description": "Start a scratchpad to capture key concepts"
                    })
                step["reason"] = "Building foundational knowledge"
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
        """Generate strategic recommendations"""
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
