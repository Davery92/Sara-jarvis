"""
Learning Tools
AI tools for the Sara Learning System: topic management, sources, scratchpad,
and autonomous research capabilities.
"""
from typing import Dict, Any, List
from app.tools.base import BaseTool, ToolResult
from app.models.learning import LearningTopic, TopicSource, TopicScratchpad, SourceChunk
from app.models.tangent_queue import TangentQueue
from app.models.known_domain import KnownDomain
from app.db.session import get_db
from sqlalchemy.orm import Session
from sqlalchemy import text
import uuid
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class LearningTopicCreateTool(BaseTool):
    """Tool for creating new learning topics"""

    @property
    def name(self) -> str:
        return "learning_topic_create"

    @property
    def description(self) -> str:
        return "Create a new learning topic to organize study material. Topics can be hierarchical (with parent topics)."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Title of the learning topic (e.g., 'Machine Learning', 'Python Basics')"
                },
                "description": {
                    "type": "string",
                    "description": "Optional description of what this topic covers"
                },
                "parent_id": {
                    "type": "string",
                    "description": "Optional ID of a parent topic for hierarchical organization"
                },
                "priority": {
                    "type": "integer",
                    "description": "Priority level 1-10, higher = more important (default: 5)"
                }
            },
            "required": ["title"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Create a new learning topic"""

        title = kwargs.get("title")
        description = kwargs.get("description")
        parent_id = kwargs.get("parent_id")
        priority = kwargs.get("priority", 5)

        if not title:
            return ToolResult(
                success=False,
                message="Topic title is required"
            )

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            topic = LearningTopic(
                id=str(uuid.uuid4()),
                user_id=user_id,
                title=title,
                description=description,
                parent_id=parent_id,
                priority=min(max(priority, 1), 10),
                status="active"
            )

            db.add(topic)
            db.commit()
            db.refresh(topic)

            return ToolResult(
                success=True,
                data={
                    "topic_id": topic.id,
                    "title": topic.title,
                    "description": topic.description,
                    "priority": topic.priority,
                    "status": topic.status,
                    "created_at": topic.created_at.isoformat() if topic.created_at else None
                },
                message=f"Created learning topic: {title}"
            )

        except Exception as e:
            db.rollback()
            return ToolResult(
                success=False,
                message=f"Failed to create topic: {str(e)}"
            )
        finally:
            db.close()


class LearningTopicListTool(BaseTool):
    """Tool for listing learning topics"""

    @property
    def name(self) -> str:
        return "learning_topic_list"

    @property
    def description(self) -> str:
        return "List all learning topics, optionally filtered by status or parent topic."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by status: 'active', 'paused', 'completed', 'archived'",
                    "enum": ["active", "paused", "completed", "archived"]
                },
                "parent_id": {
                    "type": "string",
                    "description": "Get child topics of a specific parent. Use 'root' for top-level topics."
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of topics to return (default: 20)",
                    "default": 20
                }
            }
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """List learning topics"""

        status = kwargs.get("status")
        parent_id = kwargs.get("parent_id")
        limit = kwargs.get("limit", 20)

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            query = db.query(LearningTopic).filter(LearningTopic.user_id == user_id)

            if status:
                query = query.filter(LearningTopic.status == status)

            if parent_id:
                if parent_id == "root":
                    query = query.filter(LearningTopic.parent_id.is_(None))
                else:
                    query = query.filter(LearningTopic.parent_id == parent_id)

            topics = query.order_by(
                LearningTopic.priority.desc(),
                LearningTopic.created_at.desc()
            ).limit(limit).all()

            topics_list = []
            for topic in topics:
                topics_list.append({
                    "topic_id": topic.id,
                    "title": topic.title,
                    "description": topic.description,
                    "status": topic.status,
                    "mastery_level": topic.mastery_level or 0.0,
                    "priority": topic.priority or 5,
                    "parent_id": topic.parent_id,
                    "created_at": topic.created_at.isoformat() if topic.created_at else None
                })

            return ToolResult(
                success=True,
                data={
                    "topics": topics_list,
                    "total": len(topics_list),
                    "filter_status": status,
                    "filter_parent": parent_id
                },
                message=f"Found {len(topics_list)} learning topic(s)"
            )

        except Exception as e:
            return ToolResult(
                success=False,
                message=f"Failed to list topics: {str(e)}"
            )
        finally:
            db.close()


class LearningTopicUpdateTool(BaseTool):
    """Tool for updating learning topics"""

    @property
    def name(self) -> str:
        return "learning_topic_update"

    @property
    def description(self) -> str:
        return "Update a learning topic's title, description, status, or mastery level."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "topic_id": {
                    "type": "string",
                    "description": "ID of the topic to update"
                },
                "title": {
                    "type": "string",
                    "description": "New title for the topic"
                },
                "description": {
                    "type": "string",
                    "description": "New description for the topic"
                },
                "status": {
                    "type": "string",
                    "description": "New status: 'active', 'paused', 'completed', 'archived'",
                    "enum": ["active", "paused", "completed", "archived"]
                },
                "mastery_level": {
                    "type": "number",
                    "description": "Mastery level 0.0-1.0 (0% to 100% mastery)"
                },
                "priority": {
                    "type": "integer",
                    "description": "Priority level 1-10"
                }
            },
            "required": ["topic_id"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Update a learning topic"""

        topic_id = kwargs.get("topic_id")

        if not topic_id:
            return ToolResult(
                success=False,
                message="Topic ID is required"
            )

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            topic = db.query(LearningTopic).filter(
                LearningTopic.id == topic_id,
                LearningTopic.user_id == user_id
            ).first()

            if not topic:
                return ToolResult(
                    success=False,
                    message="Topic not found"
                )

            updated = False
            if kwargs.get("title") is not None:
                topic.title = kwargs["title"]
                updated = True
            if kwargs.get("description") is not None:
                topic.description = kwargs["description"]
                updated = True
            if kwargs.get("status") is not None:
                topic.status = kwargs["status"]
                updated = True
            if kwargs.get("mastery_level") is not None:
                topic.mastery_level = min(max(kwargs["mastery_level"], 0.0), 1.0)
                updated = True
            if kwargs.get("priority") is not None:
                topic.priority = min(max(kwargs["priority"], 1), 10)
                updated = True

            if not updated:
                return ToolResult(
                    success=False,
                    message="No changes provided"
                )

            db.commit()
            db.refresh(topic)

            return ToolResult(
                success=True,
                data={
                    "topic_id": topic.id,
                    "title": topic.title,
                    "description": topic.description,
                    "status": topic.status,
                    "mastery_level": topic.mastery_level,
                    "priority": topic.priority,
                    "updated_at": topic.updated_at.isoformat() if topic.updated_at else None
                },
                message=f"Updated topic: {topic.title}"
            )

        except Exception as e:
            db.rollback()
            return ToolResult(
                success=False,
                message=f"Failed to update topic: {str(e)}"
            )
        finally:
            db.close()


class LearningSourceAddTool(BaseTool):
    """Tool for adding learning sources to topics"""

    @property
    def name(self) -> str:
        return "learning_source_add"

    @property
    def description(self) -> str:
        return "Add a learning source (URL, document, or note) to a topic for reference material."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "topic_id": {
                    "type": "string",
                    "description": "ID of the topic to add the source to"
                },
                "source_type": {
                    "type": "string",
                    "description": "Type of source: 'web' (URL), 'pdf', 'document', 'note', 'video'",
                    "enum": ["web", "pdf", "document", "note", "video"]
                },
                "url": {
                    "type": "string",
                    "description": "URL of the source (for web, pdf, or video sources)"
                },
                "title": {
                    "type": "string",
                    "description": "Title/name of the source"
                }
            },
            "required": ["topic_id", "source_type"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Add a source to a learning topic"""

        topic_id = kwargs.get("topic_id")
        source_type = kwargs.get("source_type")
        url = kwargs.get("url")
        title = kwargs.get("title")

        if not topic_id:
            return ToolResult(
                success=False,
                message="Topic ID is required"
            )

        if not source_type:
            return ToolResult(
                success=False,
                message="Source type is required"
            )

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            # Verify topic exists
            topic = db.query(LearningTopic).filter(
                LearningTopic.id == topic_id,
                LearningTopic.user_id == user_id
            ).first()

            if not topic:
                return ToolResult(
                    success=False,
                    message="Topic not found"
                )

            source = TopicSource(
                id=str(uuid.uuid4()),
                topic_id=topic_id,
                user_id=user_id,
                source_type=source_type,
                url=url,
                title=title or url or f"New {source_type} source",
                fetch_status="pending"
            )

            db.add(source)
            db.commit()
            db.refresh(source)

            return ToolResult(
                success=True,
                data={
                    "source_id": source.id,
                    "topic_id": source.topic_id,
                    "topic_title": topic.title,
                    "source_type": source.source_type,
                    "url": source.url,
                    "title": source.title,
                    "fetch_status": source.fetch_status,
                    "created_at": source.created_at.isoformat() if source.created_at else None
                },
                message=f"Added source '{source.title}' to topic '{topic.title}'"
            )

        except Exception as e:
            db.rollback()
            return ToolResult(
                success=False,
                message=f"Failed to add source: {str(e)}"
            )
        finally:
            db.close()


class LearningSourceListTool(BaseTool):
    """Tool for listing sources of a learning topic"""

    @property
    def name(self) -> str:
        return "learning_source_list"

    @property
    def description(self) -> str:
        return "List all learning sources for a specific topic."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "topic_id": {
                    "type": "string",
                    "description": "ID of the topic to list sources for"
                }
            },
            "required": ["topic_id"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """List sources for a topic"""

        topic_id = kwargs.get("topic_id")

        if not topic_id:
            return ToolResult(
                success=False,
                message="Topic ID is required"
            )

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            # Verify topic exists
            topic = db.query(LearningTopic).filter(
                LearningTopic.id == topic_id,
                LearningTopic.user_id == user_id
            ).first()

            if not topic:
                return ToolResult(
                    success=False,
                    message="Topic not found"
                )

            sources = db.query(TopicSource).filter(
                TopicSource.topic_id == topic_id,
                TopicSource.user_id == user_id
            ).order_by(TopicSource.quality_score.desc()).all()

            sources_list = []
            for source in sources:
                sources_list.append({
                    "source_id": source.id,
                    "source_type": source.source_type,
                    "url": source.url,
                    "title": source.title,
                    "quality_score": source.quality_score or 0.5,
                    "fetch_status": source.fetch_status,
                    "created_at": source.created_at.isoformat() if source.created_at else None
                })

            return ToolResult(
                success=True,
                data={
                    "topic_id": topic_id,
                    "topic_title": topic.title,
                    "sources": sources_list,
                    "total": len(sources_list)
                },
                message=f"Found {len(sources_list)} source(s) for topic '{topic.title}'"
            )

        except Exception as e:
            return ToolResult(
                success=False,
                message=f"Failed to list sources: {str(e)}"
            )
        finally:
            db.close()


class LearningScratchpadReadTool(BaseTool):
    """Tool for reading a topic's scratchpad notes"""

    @property
    def name(self) -> str:
        return "learning_scratchpad_read"

    @property
    def description(self) -> str:
        return "Read the scratchpad notes for a learning topic. The scratchpad contains working notes, summaries, and insights."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "topic_id": {
                    "type": "string",
                    "description": "ID of the topic to read scratchpad for"
                }
            },
            "required": ["topic_id"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Read topic scratchpad"""

        topic_id = kwargs.get("topic_id")

        if not topic_id:
            return ToolResult(
                success=False,
                message="Topic ID is required"
            )

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            # Verify topic exists
            topic = db.query(LearningTopic).filter(
                LearningTopic.id == topic_id,
                LearningTopic.user_id == user_id
            ).first()

            if not topic:
                return ToolResult(
                    success=False,
                    message="Topic not found"
                )

            scratchpad = db.query(TopicScratchpad).filter(
                TopicScratchpad.topic_id == topic_id,
                TopicScratchpad.user_id == user_id
            ).first()

            if scratchpad:
                return ToolResult(
                    success=True,
                    data={
                        "topic_id": topic_id,
                        "topic_title": topic.title,
                        "content": scratchpad.content or "",
                        "version": scratchpad.version or 1,
                        "updated_at": scratchpad.updated_at.isoformat() if scratchpad.updated_at else None
                    },
                    message=f"Retrieved scratchpad for topic '{topic.title}'"
                )
            else:
                return ToolResult(
                    success=True,
                    data={
                        "topic_id": topic_id,
                        "topic_title": topic.title,
                        "content": "",
                        "version": 0,
                        "updated_at": None
                    },
                    message=f"No scratchpad content yet for topic '{topic.title}'"
                )

        except Exception as e:
            return ToolResult(
                success=False,
                message=f"Failed to read scratchpad: {str(e)}"
            )
        finally:
            db.close()


class LearningScratchpadUpdateTool(BaseTool):
    """Tool for updating a topic's scratchpad notes"""

    @property
    def name(self) -> str:
        return "learning_scratchpad_update"

    @property
    def description(self) -> str:
        return "Update the scratchpad notes for a learning topic. Use this to add summaries, key insights, questions, and working notes."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "topic_id": {
                    "type": "string",
                    "description": "ID of the topic to update scratchpad for"
                },
                "content": {
                    "type": "string",
                    "description": "New scratchpad content (replaces existing content)"
                },
                "append": {
                    "type": "boolean",
                    "description": "If true, append to existing content instead of replacing (default: false)"
                }
            },
            "required": ["topic_id", "content"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Update topic scratchpad"""

        topic_id = kwargs.get("topic_id")
        content = kwargs.get("content")
        append = kwargs.get("append", False)

        if not topic_id:
            return ToolResult(
                success=False,
                message="Topic ID is required"
            )

        if content is None:
            return ToolResult(
                success=False,
                message="Content is required"
            )

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            # Verify topic exists
            topic = db.query(LearningTopic).filter(
                LearningTopic.id == topic_id,
                LearningTopic.user_id == user_id
            ).first()

            if not topic:
                return ToolResult(
                    success=False,
                    message="Topic not found"
                )

            scratchpad = db.query(TopicScratchpad).filter(
                TopicScratchpad.topic_id == topic_id,
                TopicScratchpad.user_id == user_id
            ).first()

            if scratchpad:
                if append and scratchpad.content:
                    scratchpad.content = scratchpad.content + "\n\n" + content
                else:
                    scratchpad.content = content
                scratchpad.version = (scratchpad.version or 1) + 1
            else:
                scratchpad = TopicScratchpad(
                    id=str(uuid.uuid4()),
                    topic_id=topic_id,
                    user_id=user_id,
                    content=content,
                    version=1
                )
                db.add(scratchpad)

            db.commit()
            db.refresh(scratchpad)

            return ToolResult(
                success=True,
                data={
                    "topic_id": topic_id,
                    "topic_title": topic.title,
                    "content_length": len(scratchpad.content) if scratchpad.content else 0,
                    "version": scratchpad.version,
                    "updated_at": scratchpad.updated_at.isoformat() if scratchpad.updated_at else None
                },
                message=f"Updated scratchpad for topic '{topic.title}' (version {scratchpad.version})"
            )

        except Exception as e:
            db.rollback()
            return ToolResult(
                success=False,
                message=f"Failed to update scratchpad: {str(e)}"
            )
        finally:
            db.close()


class LearningResearchTool(BaseTool):
    """Tool for autonomous research - searches web and auto-adds sources to a topic"""

    @property
    def name(self) -> str:
        return "learning_research"

    @property
    def description(self) -> str:
        return """Search the web for information about a topic and automatically add relevant sources.
        Use this when you need to find more information to answer the user's question or deepen understanding.
        This will search the web, evaluate results, and add the best sources to the current learning topic."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "topic_id": {
                    "type": "string",
                    "description": "ID of the learning topic to add sources to"
                },
                "query": {
                    "type": "string",
                    "description": "Search query to find relevant information"
                },
                "max_sources": {
                    "type": "integer",
                    "description": "Maximum number of sources to add (default: 3, max: 5)",
                    "default": 3
                },
                "auto_fetch": {
                    "type": "boolean",
                    "description": "Automatically fetch and process added sources (default: true)",
                    "default": True
                }
            },
            "required": ["topic_id", "query"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Search and add sources to a learning topic"""
        from app.services.search_service import search_service
        from app.services.learning_source_service import learning_source_service

        topic_id = kwargs.get("topic_id")
        query = kwargs.get("query")
        max_sources = min(kwargs.get("max_sources", 3), 5)
        auto_fetch = kwargs.get("auto_fetch", True)

        if not topic_id:
            return ToolResult(success=False, message="Topic ID is required")
        if not query:
            return ToolResult(success=False, message="Search query is required")

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            # Verify topic exists
            topic = db.query(LearningTopic).filter(
                LearningTopic.id == topic_id,
                LearningTopic.user_id == user_id
            ).first()

            if not topic:
                return ToolResult(success=False, message="Topic not found")

            # Perform web search
            logger.info(f"🔍 Learning research: searching for '{query}'")
            search_result = await search_service.web_search(
                query=query,
                max_results=max_sources * 2  # Get extra results for filtering
            )

            web_results = search_result.get("results", [])
            if not web_results:
                return ToolResult(
                    success=True,
                    data={"sources_added": 0, "query": query},
                    message=f"No results found for '{query}'"
                )

            # Get existing source URLs to avoid duplicates
            existing_sources = db.query(TopicSource.url).filter(
                TopicSource.topic_id == topic_id
            ).all()
            existing_urls = {s.url for s in existing_sources if s.url}

            # Add top sources
            added_sources = []
            for result in web_results[:max_sources * 2]:
                if len(added_sources) >= max_sources:
                    break

                url = result.get("url")
                if not url or url in existing_urls:
                    continue

                title = result.get("title", url)

                # Create source
                source = TopicSource(
                    id=str(uuid.uuid4()),
                    topic_id=topic_id,
                    user_id=user_id,
                    source_type="web",
                    url=url,
                    title=title,
                    fetch_status="pending"
                )
                db.add(source)
                existing_urls.add(url)
                added_sources.append({
                    "source_id": source.id,
                    "url": url,
                    "title": title
                })

            db.commit()

            # Auto-fetch sources if requested
            fetched_count = 0
            if auto_fetch and added_sources:
                for source_info in added_sources:
                    source = db.query(TopicSource).filter(
                        TopicSource.id == source_info["source_id"]
                    ).first()
                    if source:
                        try:
                            result = await learning_source_service.fetch_and_process_source(source, db)
                            if result.get("status") == "success":
                                fetched_count += 1
                                source_info["fetched"] = True
                                source_info["chunk_count"] = result.get("chunk_count", 0)
                        except Exception as e:
                            logger.warning(f"Failed to fetch source {source.url}: {e}")
                            source_info["fetched"] = False

            return ToolResult(
                success=True,
                data={
                    "topic_id": topic_id,
                    "topic_title": topic.title,
                    "query": query,
                    "sources_added": len(added_sources),
                    "sources_fetched": fetched_count,
                    "sources": added_sources
                },
                message=f"Added {len(added_sources)} source(s) to '{topic.title}' from search '{query}'. {fetched_count} source(s) processed and ready for RAG."
            )

        except Exception as e:
            db.rollback()
            logger.error(f"Learning research failed: {e}")
            return ToolResult(success=False, message=f"Research failed: {str(e)}")
        finally:
            db.close()


class LearningAnalyzeGapsTool(BaseTool):
    """Tool for analyzing knowledge gaps across topics"""

    @property
    def name(self) -> str:
        return "learning_analyze_gaps"

    @property
    def description(self) -> str:
        return """Analyze knowledge gaps across learning topics. This examines:
        - Topics with no sources or few sources
        - Topics with low mastery levels
        - Topics that haven't been studied recently
        - Potential connections between topics
        Use this to help the user identify what to study next."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "include_suggestions": {
                    "type": "boolean",
                    "description": "Include study suggestions for gaps (default: true)",
                    "default": True
                }
            }
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Analyze knowledge gaps"""
        include_suggestions = kwargs.get("include_suggestions", True)

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            # Get all active topics
            topics = db.query(LearningTopic).filter(
                LearningTopic.user_id == user_id,
                LearningTopic.status == "active"
            ).all()

            if not topics:
                return ToolResult(
                    success=True,
                    data={"gaps": [], "suggestions": []},
                    message="No active learning topics found. Create some topics to start learning!"
                )

            gaps = []
            suggestions = []

            for topic in topics:
                # Count sources
                source_count = db.query(TopicSource).filter(
                    TopicSource.topic_id == topic.id
                ).count()

                # Count fetched sources (with chunks)
                fetched_count = db.query(TopicSource).filter(
                    TopicSource.topic_id == topic.id,
                    TopicSource.fetch_status == "fetched"
                ).count()

                # Check chunk count
                chunk_count = db.query(SourceChunk).join(TopicSource).filter(
                    TopicSource.topic_id == topic.id
                ).count()

                gap_info = {
                    "topic_id": topic.id,
                    "title": topic.title,
                    "mastery_level": topic.mastery_level or 0.0,
                    "source_count": source_count,
                    "fetched_source_count": fetched_count,
                    "chunk_count": chunk_count,
                    "priority": topic.priority or 5,
                    "gap_reasons": []
                }

                # Identify gaps
                if source_count == 0:
                    gap_info["gap_reasons"].append("no_sources")
                    if include_suggestions:
                        suggestions.append({
                            "topic_id": topic.id,
                            "topic_title": topic.title,
                            "suggestion": f"Add sources to '{topic.title}' - try searching for '{topic.title} tutorial' or '{topic.title} guide'",
                            "priority": "high"
                        })
                elif fetched_count == 0:
                    gap_info["gap_reasons"].append("sources_not_processed")
                    if include_suggestions:
                        suggestions.append({
                            "topic_id": topic.id,
                            "topic_title": topic.title,
                            "suggestion": f"Fetch and process the sources for '{topic.title}' to enable AI-assisted learning",
                            "priority": "medium"
                        })

                if (topic.mastery_level or 0) < 0.3:
                    gap_info["gap_reasons"].append("low_mastery")
                    if include_suggestions and source_count > 0:
                        suggestions.append({
                            "topic_id": topic.id,
                            "topic_title": topic.title,
                            "suggestion": f"Continue studying '{topic.title}' - current mastery is {int((topic.mastery_level or 0) * 100)}%",
                            "priority": "medium"
                        })

                if gap_info["gap_reasons"]:
                    gaps.append(gap_info)

            # Sort gaps by priority (high priority topics first)
            gaps.sort(key=lambda x: (-x["priority"], x["mastery_level"]))
            suggestions.sort(key=lambda x: {"high": 0, "medium": 1, "low": 2}.get(x["priority"], 3))

            return ToolResult(
                success=True,
                data={
                    "total_topics": len(topics),
                    "topics_with_gaps": len(gaps),
                    "gaps": gaps[:10],  # Limit to top 10
                    "suggestions": suggestions[:5] if include_suggestions else []
                },
                message=f"Analyzed {len(topics)} topics. Found {len(gaps)} topic(s) with knowledge gaps."
            )

        except Exception as e:
            logger.error(f"Gap analysis failed: {e}")
            return ToolResult(success=False, message=f"Analysis failed: {str(e)}")
        finally:
            db.close()


class LearningPathTool(BaseTool):
    """Tool for generating personalized learning paths"""

    @property
    def name(self) -> str:
        return "learning_path"

    @property
    def description(self) -> str:
        return """Generate a personalized learning path based on the user's topics, mastery levels,
        and knowledge gaps. This provides prioritized study recommendations using spaced repetition
        principles. Use this when the user asks 'what should I study?', 'what's next?', or needs guidance."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "focus_topic_id": {
                    "type": "string",
                    "description": "Optional: Focus the path on a specific topic"
                },
                "max_steps": {
                    "type": "integer",
                    "description": "Maximum number of steps in the path (default: 5)",
                    "default": 5
                }
            }
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Generate a learning path"""
        from app.services.learning_path_service import learning_path_service

        focus_topic_id = kwargs.get("focus_topic_id")
        max_steps = kwargs.get("max_steps", 5)

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            result = await learning_path_service.generate_learning_path(
                user_id=user_id,
                db=db,
                focus_topic_id=focus_topic_id,
                max_steps=max_steps
            )

            return ToolResult(
                success=True,
                data=result,
                message=result.get("summary", "Learning path generated")
            )

        except Exception as e:
            logger.error(f"Learning path generation failed: {e}")
            return ToolResult(success=False, message=f"Failed to generate learning path: {str(e)}")
        finally:
            db.close()


class LearningNextSessionTool(BaseTool):
    """Tool for getting the next recommended study session"""

    @property
    def name(self) -> str:
        return "learning_next_session"

    @property
    def description(self) -> str:
        return """Get a recommended study session based on available time. Returns the highest
        priority topic and specific actions to take. Use when the user says 'I have X minutes'
        or 'what should I work on now?'"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "duration_minutes": {
                    "type": "integer",
                    "description": "Available study time in minutes (default: 30)",
                    "default": 30
                }
            }
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Get next study session recommendation"""
        from app.services.learning_path_service import learning_path_service

        duration = kwargs.get("duration_minutes", 30)

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            result = await learning_path_service.get_next_study_session(
                user_id=user_id,
                db=db,
                duration_minutes=duration
            )

            return ToolResult(
                success=True,
                data=result,
                message=result.get("message", "Here's your recommended study session")
            )

        except Exception as e:
            logger.error(f"Next session recommendation failed: {e}")
            return ToolResult(success=False, message=f"Failed to get recommendation: {str(e)}")
        finally:
            db.close()


class LearningFetchSourceTool(BaseTool):
    """Tool for fetching and processing a source"""

    @property
    def name(self) -> str:
        return "learning_fetch_source"

    @property
    def description(self) -> str:
        return """Fetch and process a learning source. This extracts content from the URL,
        chunks it, and creates embeddings for RAG retrieval. Use this after adding a source
        to make its content available for learning conversations."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "source_id": {
                    "type": "string",
                    "description": "ID of the source to fetch and process"
                }
            },
            "required": ["source_id"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Fetch and process a source"""
        from app.services.learning_source_service import learning_source_service

        source_id = kwargs.get("source_id")
        if not source_id:
            return ToolResult(success=False, message="Source ID is required")

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            source = db.query(TopicSource).filter(
                TopicSource.id == source_id,
                TopicSource.user_id == user_id
            ).first()

            if not source:
                return ToolResult(success=False, message="Source not found")

            # Get topic for context
            topic = db.query(LearningTopic).filter(
                LearningTopic.id == source.topic_id
            ).first()

            result = await learning_source_service.fetch_and_process_source(source, db)

            if result.get("status") == "success":
                return ToolResult(
                    success=True,
                    data={
                        "source_id": source.id,
                        "topic_id": source.topic_id,
                        "topic_title": topic.title if topic else None,
                        "title": result.get("title"),
                        "chunk_count": result.get("chunk_count", 0),
                        "content_length": result.get("content_length", 0)
                    },
                    message=f"Processed source '{source.title}' - created {result.get('chunk_count', 0)} chunks for learning"
                )
            else:
                return ToolResult(
                    success=False,
                    message=f"Failed to process source: {result.get('error', 'Unknown error')}"
                )

        except Exception as e:
            logger.error(f"Source fetch failed: {e}")
            return ToolResult(success=False, message=f"Fetch failed: {str(e)}")
        finally:
            db.close()


class LearningTangentCaptureTool(BaseTool):
    """Tool for capturing tangents during learning sessions"""

    @property
    def name(self) -> str:
        return "learning_tangent_capture"

    @property
    def description(self) -> str:
        return "Capture a tangent or side question that came up during learning. Saves it for later exploration without losing focus on the current topic."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "parent_topic_id": {
                    "type": "string",
                    "description": "ID of the current learning topic"
                },
                "tangent_description": {
                    "type": "string",
                    "description": "What the tangent/side question is about"
                },
                "source_context": {
                    "type": "string",
                    "description": "What was being discussed when the tangent arose"
                },
                "priority": {
                    "type": "integer",
                    "description": "Priority 1-5 (5=most interesting, default: 3)"
                }
            },
            "required": ["parent_topic_id", "tangent_description"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        parent_topic_id = kwargs.get("parent_topic_id")
        tangent_description = kwargs.get("tangent_description")
        source_context = kwargs.get("source_context")
        priority = min(max(kwargs.get("priority", 3), 1), 5)

        if not parent_topic_id or not tangent_description:
            return ToolResult(success=False, message="parent_topic_id and tangent_description are required")

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            tangent = TangentQueue(
                id=str(uuid.uuid4()),
                user_id=user_id,
                parent_topic_id=parent_topic_id,
                tangent_description=tangent_description,
                source_context=source_context,
                priority=priority,
                status="queued"
            )
            db.add(tangent)
            db.commit()

            return ToolResult(
                success=True,
                data=tangent.to_dict(),
                message=f"Tangent captured: '{tangent_description[:60]}...' (priority {priority}/5)"
            )
        except Exception as e:
            db.rollback()
            return ToolResult(success=False, message=f"Failed to capture tangent: {str(e)}")
        finally:
            db.close()


class LearningTangentListTool(BaseTool):
    """Tool for listing queued tangents"""

    @property
    def name(self) -> str:
        return "learning_tangent_list"

    @property
    def description(self) -> str:
        return "List queued tangents for a topic. Shows interesting side questions captured during learning that can be explored later or promoted to full topics."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "parent_topic_id": {
                    "type": "string",
                    "description": "Filter by parent topic ID (optional)"
                },
                "status": {
                    "type": "string",
                    "description": "Filter by status: queued, promoted_to_topic, dismissed (default: queued)",
                    "enum": ["queued", "promoted_to_topic", "dismissed"]
                }
            }
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        parent_topic_id = kwargs.get("parent_topic_id")
        status = kwargs.get("status", "queued")

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            query = db.query(TangentQueue).filter(
                TangentQueue.user_id == user_id,
                TangentQueue.status == status
            )
            if parent_topic_id:
                query = query.filter(TangentQueue.parent_topic_id == parent_topic_id)

            tangents = query.order_by(TangentQueue.priority.desc(), TangentQueue.created_at.desc()).all()

            return ToolResult(
                success=True,
                data={
                    "tangents": [t.to_dict() for t in tangents],
                    "total": len(tangents)
                },
                message=f"Found {len(tangents)} queued tangent(s)"
            )
        except Exception as e:
            return ToolResult(success=False, message=f"Failed to list tangents: {str(e)}")
        finally:
            db.close()


class LearningKnownDomainsTool(BaseTool):
    """Tool for querying and managing known domains"""

    @property
    def name(self) -> str:
        return "learning_known_domains"

    @property
    def description(self) -> str:
        return "Query, update, or add to David's known domains — the areas he's already proficient in, used for generating analogies during learning."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Action to perform: query (list all), update (modify existing), add (create new)",
                    "enum": ["query", "update", "add"]
                },
                "domain_name": {
                    "type": "string",
                    "description": "Domain name (required for update/add)"
                },
                "description": {
                    "type": "string",
                    "description": "Domain description (for add)"
                },
                "proficiency": {
                    "type": "string",
                    "description": "Proficiency level (for update/add)",
                    "enum": ["beginner", "intermediate", "expert"]
                },
                "key_concepts": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Key concepts to set or add (for update/add)"
                }
            },
            "required": ["action"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        action = kwargs.get("action", "query")
        domain_name = kwargs.get("domain_name")

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            if action == "query":
                domains = db.query(KnownDomain).filter(
                    KnownDomain.user_id == user_id
                ).order_by(KnownDomain.domain_name).all()
                return ToolResult(
                    success=True,
                    data={"domains": [d.to_dict() for d in domains], "total": len(domains)},
                    message=f"Found {len(domains)} known domain(s)"
                )

            if not domain_name:
                return ToolResult(success=False, message="domain_name is required for update/add")

            if action == "add":
                existing = db.query(KnownDomain).filter(
                    KnownDomain.user_id == user_id,
                    KnownDomain.domain_name == domain_name
                ).first()
                if existing:
                    return ToolResult(success=False, message=f"Domain '{domain_name}' already exists. Use 'update' action.")

                domain = KnownDomain(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    domain_name=domain_name,
                    description=kwargs.get("description"),
                    proficiency=kwargs.get("proficiency", "intermediate"),
                    key_concepts=kwargs.get("key_concepts", [])
                )
                db.add(domain)
                db.commit()
                return ToolResult(success=True, data=domain.to_dict(), message=f"Added known domain: {domain_name}")

            if action == "update":
                domain = db.query(KnownDomain).filter(
                    KnownDomain.user_id == user_id,
                    KnownDomain.domain_name == domain_name
                ).first()
                if not domain:
                    return ToolResult(success=False, message=f"Domain '{domain_name}' not found")

                if kwargs.get("proficiency"):
                    domain.proficiency = kwargs["proficiency"]
                if kwargs.get("key_concepts"):
                    # Merge new concepts with existing
                    existing_concepts = set(domain.key_concepts or [])
                    existing_concepts.update(kwargs["key_concepts"])
                    domain.key_concepts = list(existing_concepts)
                if kwargs.get("description"):
                    domain.description = kwargs["description"]

                db.commit()
                return ToolResult(success=True, data=domain.to_dict(), message=f"Updated domain: {domain_name}")

            return ToolResult(success=False, message=f"Unknown action: {action}")

        except Exception as e:
            db.rollback()
            return ToolResult(success=False, message=f"Known domains operation failed: {str(e)}")
        finally:
            db.close()


class LearningFindAnchorsTool(BaseTool):
    """Tool for finding/generating analogy anchors for a topic"""

    @property
    def name(self) -> str:
        return "learning_find_anchors"

    @property
    def description(self) -> str:
        return "Find or generate analogy anchor points for a learning topic. Anchors connect new concepts to David's existing knowledge domains."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "topic_id": {
                    "type": "string",
                    "description": "ID of the learning topic to find anchors for"
                },
                "regenerate": {
                    "type": "boolean",
                    "description": "If true, generate new anchors even if some exist (default: false)"
                }
            },
            "required": ["topic_id"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        from app.services.anchor_service import anchor_service

        topic_id = kwargs.get("topic_id")
        regenerate = kwargs.get("regenerate", False)

        if not topic_id:
            return ToolResult(success=False, message="topic_id is required")

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            anchors = await anchor_service.generate_anchors(
                topic_id=topic_id,
                user_id=user_id,
                db=db,
                regenerate=regenerate
            )

            if anchors:
                return ToolResult(
                    success=True,
                    data={"anchors": anchors, "count": len(anchors)},
                    message=f"Generated {len(anchors)} analogy anchor(s) for this topic"
                )
            else:
                return ToolResult(
                    success=True,
                    data={"anchors": [], "count": 0},
                    message="No anchors generated — make sure known domains are set up"
                )

        except Exception as e:
            return ToolResult(success=False, message=f"Anchor generation failed: {str(e)}")
        finally:
            db.close()
