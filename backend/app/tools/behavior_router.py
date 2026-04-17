"""
Behavior Router Tool

Exposes the route_behavior tool to Sara, allowing her to route
natural language behavior intents to the appropriate system.
"""

from typing import Any, Dict, Optional
from app.tools.base import BaseTool, ToolResult
from app.services.behavior_router import (
    BehaviorDestination,
    get_behavior_router,
)
import logging

logger = logging.getLogger(__name__)


class RouteBehaviorTool(BaseTool):
    """
    Route a natural language behavior intent to the appropriate system.

    Sara can use this when she wants to "learn" or "remember" something
    without needing to know which underlying system implements it.
    """

    @property
    def name(self) -> str:
        return "route_behavior"

    @property
    def description(self) -> str:
        return """Route a natural language behavior intent to the appropriate system.

Use this when you want to internalize a new behavior, preference, or pattern without
knowing exactly which system should handle it. The router will intelligently classify
the intent and route it to:

- **Soul**: Changes to your fundamental identity, principles, or boundaries
  Example: "Be more direct with David", "Never guilt him about missed workouts"

- **Skill**: Changes to how you approach a specific domain (can append to existing skills)
  Example: "When coaching fitness, always ask about sleep first"

- **Automation**: Deterministic, schedulable actions
  Example: "Turn off the lights at 11pm every night"

- **Heartbeat**: Ongoing monitoring that requires your judgment (database or HEARTBEAT.md)
  Example: "Check if David has logged meals today", "Notice if he seems stressed"

Options:
- dry_run=true: Preview where this would be routed without committing. Useful when the
  intent could reasonably go multiple directions.
- force_destination: Override the classification if you know better than the classifier."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "intent": {
                    "type": "string",
                    "description": "Natural language description of the behavior to route. "
                                   "Be specific about what you want to happen."
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "If true, classify but don't execute. "
                                   "Use to preview where an intent would be routed.",
                    "default": False
                },
                "force_destination": {
                    "type": "string",
                    "enum": ["soul", "skill", "automation", "heartbeat"],
                    "description": "Override the classification and route to a specific destination. "
                                   "Use when you know better than the classifier."
                }
            },
            "required": ["intent"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """
        Execute the behavior routing.

        Args:
            user_id: The user making the request
            intent: The behavior to route
            dry_run: Preview without executing
            force_destination: Override classification

        Returns:
            ToolResult with routing outcome
        """
        intent = kwargs.get("intent")
        dry_run = kwargs.get("dry_run", False)
        force_destination_str = kwargs.get("force_destination")

        if not intent:
            return ToolResult(
                success=False,
                message="intent is required"
            )

        # Parse force_destination if provided
        force_destination = None
        if force_destination_str:
            try:
                force_destination = BehaviorDestination(force_destination_str)
            except ValueError:
                return ToolResult(
                    success=False,
                    message=f"Invalid destination: {force_destination_str}. "
                            f"Must be one of: soul, skill, automation, heartbeat"
                )

        try:
            router = get_behavior_router()
            response = await router.route_and_execute(
                user_id=user_id,
                intent=intent,
                dry_run=dry_run,
                force_destination=force_destination,
            )

            return ToolResult(
                success=response.success,
                data={
                    "destination": response.destination.value,
                    "classification": response.classification,
                    "action_taken": response.action_taken,
                    "next_steps": response.next_steps,
                    "destination_result": response.destination_result,
                },
                message=response.message,
            )

        except Exception as e:
            logger.error(f"route_behavior failed: {e}", exc_info=True)
            return ToolResult(
                success=False,
                message=f"Failed to route behavior: {str(e)}"
            )


class ShowBehaviorConfigTool(BaseTool):
    """
    Show Sara's current behavioral configuration across all systems.

    Provides a unified view of how Sara is currently configured,
    spanning Soul, Skills, Heartbeat, and Automations.
    """

    @property
    def name(self) -> str:
        return "show_behavior_config"

    @property
    def description(self) -> str:
        return """Show Sara's current behavioral configuration across all systems.

Use this to see a unified view of:
- Soul: Current identity, principles, boundaries, and growth areas
- Skills: Active domain-specific capabilities
- Heartbeat: What Sara is currently monitoring
- Automations: Active scheduled/triggered actions

Useful for:
- Auditing what behaviors have been added
- Understanding Sara's current configuration
- Preventing drift into incoherence
- Answering "What are you watching for?" or "How are you configured?"

Set include_details=true for full content, or false for just summaries."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "include_details": {
                    "type": "boolean",
                    "description": "Include full content of each item (true) or just summaries (false)",
                    "default": False
                },
                "sections": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["soul", "skills", "heartbeat", "automations"]
                    },
                    "description": "Which sections to include. Defaults to all."
                }
            }
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Get unified behavioral configuration"""
        include_details = kwargs.get("include_details", False)
        sections = kwargs.get("sections", ["soul", "skills", "heartbeat", "automations"])

        config = {}
        errors = []

        # Get Soul configuration
        if "soul" in sections:
            try:
                soul_data = await self._get_soul_config(include_details)
                config["soul"] = soul_data
            except Exception as e:
                errors.append(f"Soul: {str(e)}")

        # Get Skills configuration
        if "skills" in sections:
            try:
                skills_data = self._get_skills_config(include_details)
                config["skills"] = skills_data
            except Exception as e:
                errors.append(f"Skills: {str(e)}")

        # Get Heartbeat configuration
        if "heartbeat" in sections:
            try:
                heartbeat_data = await self._get_heartbeat_config(user_id, include_details)
                config["heartbeat"] = heartbeat_data
            except Exception as e:
                errors.append(f"Heartbeat: {str(e)}")

        # Get Automations configuration
        if "automations" in sections:
            try:
                automations_data = await self._get_automations_config(user_id, include_details)
                config["automations"] = automations_data
            except Exception as e:
                errors.append(f"Automations: {str(e)}")

        # Build summary message
        summary_parts = []
        if "soul" in config:
            summary_parts.append(f"Soul: {len(config['soul'].get('sections', []))} sections")
        if "skills" in config:
            summary_parts.append(f"Skills: {config['skills'].get('count', 0)} active")
        if "heartbeat" in config:
            hb = config["heartbeat"]
            summary_parts.append(f"Heartbeat: {hb.get('database_count', 0)} items + {hb.get('file_rules', 0)} rules")
        if "automations" in config:
            summary_parts.append(f"Automations: {config['automations'].get('active_count', 0)} active")

        summary = ", ".join(summary_parts)
        if errors:
            summary += f" (errors: {', '.join(errors)})"

        return ToolResult(
            success=True,
            data=config,
            message=f"Behavioral configuration: {summary}",
        )

    async def _get_soul_config(self, include_details: bool) -> Dict[str, Any]:
        """Get Soul configuration"""
        from app.db.session import get_db
        from sqlalchemy import text

        db_gen = get_db()
        db = next(db_gen)

        try:
            result = db.execute(text("""
                SELECT section, content, version, updated_at
                FROM sara_soul
                ORDER BY CASE section
                    WHEN 'identity' THEN 1
                    WHEN 'principles' THEN 2
                    WHEN 'boundaries' THEN 3
                    WHEN 'growth' THEN 4
                    WHEN 'evolution_log' THEN 5
                END
            """)).fetchall()

            sections = []
            for row in result:
                section_data = {
                    "section": row.section,
                    "version": row.version,
                    "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                }
                if include_details:
                    section_data["content"] = row.content
                else:
                    # Just show first 100 chars
                    section_data["preview"] = row.content[:100] + "..." if row.content and len(row.content) > 100 else row.content
                sections.append(section_data)

            return {"sections": sections}
        finally:
            db.close()

    def _get_skills_config(self, include_details: bool) -> Dict[str, Any]:
        """Get Skills configuration"""
        from app.skills import get_skill_loader

        loader = get_skill_loader()
        skills = loader.get_all_enabled_skills()

        skill_list = []
        for skill in skills:
            skill_data = {
                "name": skill.metadata.name,
                "description": skill.metadata.description,
                "contexts": skill.metadata.contexts,
                "priority": skill.metadata.priority,
            }
            if include_details:
                skill_data["instructions"] = skill.instructions
            skill_list.append(skill_data)

        return {
            "count": len(skill_list),
            "skills": skill_list,
        }

    async def _get_heartbeat_config(self, user_id: str, include_details: bool) -> Dict[str, Any]:
        """Get Heartbeat configuration (database items + file rules)"""
        from app.db.session import get_db
        from sqlalchemy import text
        from pathlib import Path

        # Get database items
        db_gen = get_db()
        db = next(db_gen)

        try:
            result = db.execute(text("""
                SELECT id, item_type, description, check_logic, priority, is_active,
                       times_checked, times_triggered, created_at
                FROM heartbeat_items
                WHERE user_id = :user_id AND is_active = true
                ORDER BY priority DESC, created_at DESC
            """), {"user_id": user_id}).fetchall()

            items = []
            for row in result:
                item_data = {
                    "id": row.id,
                    "type": row.item_type,
                    "description": row.description,
                    "check_logic": row.check_logic,
                    "priority": row.priority,
                    "times_triggered": row.times_triggered,
                }
                items.append(item_data)

            # Get file rules
            heartbeat_path = Path(__file__).parent.parent / "data" / "HEARTBEAT.md"
            file_content = None
            file_rules = 0
            if heartbeat_path.exists():
                file_content = heartbeat_path.read_text()
                # Count rules (lines starting with -)
                file_rules = len([l for l in file_content.split("\n") if l.strip().startswith("-")])

            result_data = {
                "database_count": len(items),
                "database_items": items,
                "file_rules": file_rules,
            }

            if include_details and file_content:
                result_data["file_content"] = file_content

            return result_data
        finally:
            db.close()

    async def _get_automations_config(self, user_id: str, include_details: bool) -> Dict[str, Any]:
        """Get Automations configuration"""
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy import text
        import os

        database_url = os.getenv("DATABASE_URL")
        from app.db.session import get_async_session_factory
        async_session = get_async_session_factory()
        async with async_session() as db:
            result = await db.execute(text("""
                SELECT id, name, status, original_intent, schedule_definition,
                       execution_count, next_wake_at, created_at
                FROM automation_task
                WHERE user_id = :user_id AND status IN ('active', 'paused', 'pending_confirmation')
                ORDER BY created_at DESC
            """), {"user_id": user_id})

            rows = result.fetchall()

        await engine.dispose()

        automations = []
        active_count = 0
        for row in rows:
            auto_data = {
                "id": row.id,
                "name": row.name,
                "status": row.status,
                "execution_count": row.execution_count,
                "next_wake_at": row.next_wake_at.isoformat() if row.next_wake_at else None,
            }
            if include_details:
                auto_data["original_intent"] = row.original_intent
            if row.status == "active":
                active_count += 1
            automations.append(auto_data)

        return {
            "active_count": active_count,
            "total_count": len(automations),
            "automations": automations,
        }


# Export for registration
BEHAVIOR_ROUTER_TOOLS = [
    RouteBehaviorTool(),
    ShowBehaviorConfigTool(),
]
