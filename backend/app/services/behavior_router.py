"""
Behavior Router Service

Routes natural language behavior intents to the appropriate system:
- Soul: Identity, personality, fundamental principles
- Skill: Domain-specific methodologies and approaches
- Automation: Deterministic, schedulable actions
- Heartbeat: Ongoing judgment-based monitoring
"""

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from app.tools.base import ToolResult

logger = logging.getLogger(__name__)


class BehaviorDestination(str, Enum):
    """Possible routing destinations for behavior intents"""
    SOUL = "soul"
    SKILL = "skill"
    AUTOMATION = "automation"
    HEARTBEAT = "heartbeat"


# Routing criteria - questions and indicators for each destination
ROUTING_CRITERIA = {
    BehaviorDestination.SOUL: {
        "question": "Does this change who Sara fundamentally is?",
        "indicators": [
            "identity or personality change",
            "core principles or ethics",
            "fundamental boundaries",
            "voice or tone adjustments",
            "values or beliefs",
            "how Sara sees herself",
        ],
        "examples": [
            "Be more direct with me",
            "Never guilt David about missed workouts",
            "Always be honest even if uncomfortable",
            "Be less formal in conversations",
        ],
    },
    BehaviorDestination.SKILL: {
        "question": "Does this change how Sara approaches a specific domain?",
        "indicators": [
            "domain-specific methodology",
            "style preferences within a domain",
            "expertise or approach changes",
            "how to handle specific topics",
            "coaching or teaching style for a topic",
        ],
        "examples": [
            "When coaching fitness, ask about sleep first",
            "For learning topics, use spaced repetition",
            "During code reviews, focus on readability",
            "When discussing finances, be conservative",
        ],
    },
    BehaviorDestination.AUTOMATION: {
        "question": "Can this be fully specified without ongoing judgment?",
        "indicators": [
            "specific time schedule (cron, interval, one-time)",
            "deterministic trigger with deterministic action",
            "state-based trigger with simple action",
            "turn on/off at specific times",
            "alert if specific condition met",
            "recurring schedule",
        ],
        "examples": [
            "Turn off lights at 11pm",
            "Alert if garage door opens after 10pm",
            "Run the dishwasher every night at midnight",
            "Send me a summary email every Monday at 9am",
        ],
    },
    BehaviorDestination.HEARTBEAT: {
        "question": "Does this require ongoing judgment or context-dependent evaluation?",
        "indicators": [
            "periodic checks needing evaluation",
            "context-dependent decisions",
            "notice or keep an eye on something",
            "suggest if appropriate",
            "monitor trends or patterns",
            "check in about something",
            "requires Sara to decide when/how to act",
        ],
        "examples": [
            "Check if I've logged meals today",
            "Notice if I seem stressed",
            "Remind me about open tasks if I'm idle",
            "Keep an eye on my sleep patterns",
        ],
    },
}


CLASSIFICATION_PROMPT = """You are a behavior routing classifier for Sara, a personal AI assistant.

Given a natural language behavior intent, classify which system should handle it.

## Classification Rules

Check these questions in order - the FIRST one that applies is the correct destination:

1. SOUL - Does this change who Sara fundamentally is?
   - Identity, personality, voice changes
   - Core principles or ethics
   - Fundamental boundaries
   - Examples: "Be more direct", "Never guilt me about workouts"

2. SKILL - Does this change how Sara approaches a specific domain?
   - Domain-specific methodology (fitness, learning, work, etc.)
   - Style preferences within a domain
   - NOT triggers/schedules - just HOW to approach topics
   - Examples: "When coaching fitness, ask about sleep first"

3. AUTOMATION - Can this be fully specified without judgment?
   - Deterministic trigger + deterministic action
   - Time schedules (cron, interval, one-time)
   - State-based triggers with simple actions
   - Examples: "Turn off lights at 11pm", "Alert if garage opens after 10pm"

4. HEARTBEAT (DEFAULT) - Requires ongoing judgment
   - Periodic checks needing Sara's evaluation
   - Context-dependent decisions
   - "Notice", "keep an eye on", "suggest if"
   - Examples: "Check if I've logged meals", "Notice if I seem stressed"

## Disambiguation: Soul vs Skill

The key distinction is SCOPE:
- SOUL = WHO Sara is (applies regardless of what we're talking about)
- SKILL = HOW Sara approaches a topic (only matters in a specific domain)

Signals that indicate SKILL (domain-scoped):
- "about [topic]", "when discussing [topic]", "for [domain]"
- "when coaching", "during [activity]", "in [context]"
- References a specific subject area

Signals that indicate SOUL (universal):
- No domain scoping - applies to all interactions
- About personality, tone, or communication style generally
- About values or principles that transcend context

Examples:
- "Be more encouraging" → SOUL (applies everywhere)
- "Be more encouraging about fitness" → SKILL (scoped to fitness)
- "Never be condescending" → SOUL (universal principle)
- "When discussing code, never be condescending" → SKILL (scoped to code)

## Existing Skills Context

These skills already exist:
{existing_skills}

When the intent relates to an existing skill's domain, consider whether to:
- APPEND: Add to existing skill (small refinement, additive instruction)
- CREATE: New skill (different domain or fundamentally different approach)

## Intent to classify

{intent}

## Response Format

Return ONLY valid JSON (no markdown, no explanation):
{{
  "classification": "soul"|"skill"|"automation"|"heartbeat",
  "confidence": 0.0-1.0,
  "reasoning": "Brief explanation of why this classification",
  "alternative": "Second-best classification if confidence < 0.8, else null",
  "alternative_confidence": 0.0-1.0 or null,
  "formatted_for_destination": {{ ... see formats below ... }}
}}

## Destination-specific formats for formatted_for_destination:

For SOUL:
{{"section": "principles"|"boundaries"|"identity"|"growth", "proposed_change": "The specific change text", "rationale": "Why this change based on the intent"}}

For SKILL:
{{
  "operation": "create"|"append",
  "name": "skill-name-kebab-case",
  "existing_skill": "name of existing skill if appending, else null",
  "description": "What this skill does (for create) or what's being added (for append)",
  "contexts": ["relevant", "contexts"],
  "instructions": "The markdown instructions to add"
}}

For AUTOMATION:
{{"intent": "The natural language intent for the automation system", "expires_hours": 24}}

For HEARTBEAT:
{{
  "storage": "database"|"file",
  "item_type": "monitor"|"time_bound"|"conditional",
  "description": "What to check",
  "check_logic": "custom"|"meal_logging"|"home_assistant"|"reminder"|"hrv_threshold"|"conversation_gap"|"email_check",
  "priority": "low"|"normal"|"high"
}}

HEARTBEAT storage guidance:
- "file" (HEARTBEAT.md): Natural language rules Sara reviews and reflects on. Human-readable reminders and checks.
- "database": Structured monitors needing metadata like expiration, trigger counts, specific check_logic types, priority ordering.
"""


@dataclass
class RoutingResult:
    """Result of behavior classification"""
    destination: BehaviorDestination
    confidence: float
    reasoning: str
    formatted_params: Dict[str, Any]
    alternative: Optional[BehaviorDestination] = None
    alternative_confidence: Optional[float] = None
    needs_clarification: bool = False


@dataclass
class RoutingResponse:
    """Response from routing and executing a behavior"""
    success: bool
    destination: BehaviorDestination
    classification: Dict[str, Any]
    action_taken: Optional[str] = None
    next_steps: Optional[str] = None
    destination_result: Optional[Dict[str, Any]] = None
    message: str = ""


class BehaviorRouter:
    """
    Routes behavior intents to the appropriate system.

    Uses LLM classification to determine the best destination,
    then executes the intent against that system.
    """

    def __init__(self):
        self._client = None

    async def _get_llm_client(self):
        """Get or create the OpenAI client"""
        if self._client is None:
            from openai import AsyncOpenAI
            from app.core.config import settings
            self._client = AsyncOpenAI(
                base_url=settings.OPENAI_BASE_URL,
                api_key=settings.OPENAI_API_KEY or "not-needed",
            )
        return self._client

    def _get_model(self) -> str:
        """Get the model name from settings"""
        from app.core.config import settings
        return settings.OPENAI_MODEL

    def _get_existing_skills_summary(self) -> str:
        """Get a summary of existing skills for the classification prompt"""
        try:
            from app.skills import get_skill_loader
            loader = get_skill_loader()
            skills = loader.get_all_enabled_skills()

            if not skills:
                return "No skills currently loaded."

            lines = []
            for skill in skills:
                contexts = ", ".join(skill.metadata.contexts) if skill.metadata.contexts else "all"
                lines.append(f"- {skill.metadata.name}: {skill.metadata.description} (contexts: {contexts})")

            return "\n".join(lines)
        except Exception as e:
            logger.warning(f"Could not get existing skills: {e}")
            return "Could not retrieve existing skills."

    async def classify(self, intent: str) -> RoutingResult:
        """
        Classify a behavior intent to determine its destination.

        Args:
            intent: Natural language description of the behavior

        Returns:
            RoutingResult with destination and parameters
        """
        client = await self._get_llm_client()

        # Get existing skills for context
        existing_skills = self._get_existing_skills_summary()

        prompt = CLASSIFICATION_PROMPT.format(
            intent=intent,
            existing_skills=existing_skills
        )

        try:
            response = await client.chat.completions.create(
                model=self._get_model(),
                messages=[
                    {"role": "system", "content": "You are a classification system. Return only valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,  # Low temperature for consistent classification
                max_tokens=1000,
            )

            content = response.choices[0].message.content.strip()

            # Parse the JSON response - handle markdown code blocks
            if content.startswith("```"):
                # Remove markdown code blocks
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()

            result = json.loads(content)

            destination = BehaviorDestination(result["classification"])
            confidence = float(result.get("confidence", 0.5))
            reasoning = result.get("reasoning", "No reasoning provided")
            formatted_params = result.get("formatted_for_destination", {})

            alternative = None
            alternative_confidence = None
            if result.get("alternative"):
                alternative = BehaviorDestination(result["alternative"])
                alternative_confidence = result.get("alternative_confidence")

            return RoutingResult(
                destination=destination,
                confidence=confidence,
                reasoning=reasoning,
                formatted_params=formatted_params,
                alternative=alternative,
                alternative_confidence=alternative_confidence,
                needs_clarification=confidence < 0.5,
            )

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM classification response: {e}")
            # Default to heartbeat with low confidence
            return RoutingResult(
                destination=BehaviorDestination.HEARTBEAT,
                confidence=0.3,
                reasoning="Failed to parse classification, defaulting to heartbeat",
                formatted_params={
                    "item_type": "monitor",
                    "description": intent,
                    "check_logic": "custom",
                    "priority": "normal",
                },
                needs_clarification=True,
            )
        except Exception as e:
            logger.error(f"Classification failed: {e}")
            raise

    async def route_and_execute(
        self,
        user_id: str,
        intent: str,
        dry_run: bool = False,
        force_destination: Optional[BehaviorDestination] = None,
    ) -> RoutingResponse:
        """
        Classify and route a behavior intent to the appropriate system.

        Args:
            user_id: The user making the request
            intent: Natural language description of the behavior
            dry_run: If True, classify but don't execute
            force_destination: Override classification with specific destination

        Returns:
            RoutingResponse with results
        """
        # Classify the intent
        classification = await self.classify(intent)

        # Allow forcing a destination
        if force_destination:
            classification.destination = force_destination
            classification.reasoning = f"Forced to {force_destination.value} (original: {classification.reasoning})"

        destination = classification.destination

        # Build classification data for response
        classification_data = {
            "confidence": classification.confidence,
            "reasoning": classification.reasoning,
            "alternative": classification.alternative.value if classification.alternative else None,
            "alternative_confidence": classification.alternative_confidence,
        }

        # Handle low confidence
        if classification.needs_clarification:
            return RoutingResponse(
                success=True,
                destination=destination,
                classification=classification_data,
                action_taken=None,
                next_steps="Needs clarification - confidence too low",
                message=f"I'm not sure how to handle this (confidence: {classification.confidence:.0%}). "
                        f"Did you mean: {destination.value}? Alternative: {classification.alternative.value if classification.alternative else 'none'}",
            )

        # Dry run - just return classification
        if dry_run:
            return RoutingResponse(
                success=True,
                destination=destination,
                classification=classification_data,
                action_taken=None,
                next_steps=f"Would route to {destination.value}",
                destination_result={"params": classification.formatted_params},
                message=f"Would route to {destination.value}: {classification.reasoning}",
            )

        # Execute based on destination
        try:
            if destination == BehaviorDestination.SOUL:
                result = await self._execute_soul(user_id, classification.formatted_params)
            elif destination == BehaviorDestination.SKILL:
                result = await self._execute_skill(user_id, classification.formatted_params)
            elif destination == BehaviorDestination.AUTOMATION:
                result = await self._execute_automation(user_id, classification.formatted_params)
            else:  # HEARTBEAT
                result = await self._execute_heartbeat(user_id, classification.formatted_params)

            # Add confidence note if not highly confident
            confidence_note = ""
            if classification.confidence < 0.7:
                confidence_note = f" (Note: {classification.confidence:.0%} confident this was the right destination)"

            return RoutingResponse(
                success=result.success,
                destination=destination,
                classification=classification_data,
                action_taken=result.message,
                next_steps=result.data.get("next_steps") if result.data else None,
                destination_result=result.data,
                message=f"Routed to {destination.value}: {result.message}{confidence_note}",
            )

        except Exception as e:
            logger.error(f"Failed to execute {destination.value}: {e}")
            return RoutingResponse(
                success=False,
                destination=destination,
                classification=classification_data,
                action_taken=None,
                message=f"Failed to execute {destination.value}: {str(e)}",
            )

    async def _execute_soul(self, user_id: str, params: Dict[str, Any]) -> ToolResult:
        """Execute a Soul change proposal"""
        from app.tools.soul import ProposeSoulChangeTool

        tool = ProposeSoulChangeTool()

        section = params.get("section", "principles")
        proposed_change = params.get("proposed_change", "")
        rationale = params.get("rationale", "Routed from behavior intent")

        result = await tool.execute(
            user_id,
            section=section,
            proposed_change=proposed_change,
            rationale=rationale,
        )

        if result.success and result.data:
            result.data["next_steps"] = "Soul change proposal created - needs David's approval"

        return result

    async def _execute_skill(self, user_id: str, params: Dict[str, Any]) -> ToolResult:
        """Execute skill creation or append"""
        from app.skills import get_skill_loader

        operation = params.get("operation", "create")
        name = params.get("name", "custom-skill")
        existing_skill = params.get("existing_skill")
        description = params.get("description", "Custom skill from behavior routing")
        contexts = params.get("contexts", [])
        instructions = params.get("instructions", "")
        priority = params.get("priority", 5)

        try:
            # Get the singleton skill loader (already has directories configured)
            loader = get_skill_loader()

            if operation == "append" and existing_skill:
                # Append to existing skill
                skill_file = loader.append_to_skill_file(
                    name=existing_skill,
                    additional_instructions=instructions,
                    section_header=f"## {description}" if description else None,
                )

                if skill_file:
                    return ToolResult(
                        success=True,
                        data={
                            "operation": "append",
                            "name": existing_skill,
                            "file_path": str(skill_file),
                            "next_steps": None,
                        },
                        message=f"Appended to skill '{existing_skill}' at {skill_file}",
                    )
                else:
                    return ToolResult(
                        success=False,
                        message=f"Failed to append to skill '{existing_skill}' - skill not found",
                    )
            else:
                # Create new skill
                skill_file = loader.create_skill_file(
                    name=name,
                    description=description,
                    contexts=contexts,
                    instructions=instructions,
                    priority=priority,
                )

                if skill_file:
                    return ToolResult(
                        success=True,
                        data={
                            "operation": "create",
                            "name": name,
                            "file_path": str(skill_file),
                            "contexts": contexts,
                            "next_steps": None,
                        },
                        message=f"Created skill '{name}' at {skill_file}",
                    )
                else:
                    return ToolResult(
                        success=False,
                        message="Failed to create skill file - check skill directories are configured",
                    )

        except Exception as e:
            logger.error(f"Failed to execute skill operation: {e}")
            return ToolResult(
                success=False,
                message=f"Failed to execute skill operation: {str(e)}",
            )

    async def _execute_automation(self, user_id: str, params: Dict[str, Any]) -> ToolResult:
        """Execute automation creation"""
        from app.tools.automation import AutomationCreateTool

        tool = AutomationCreateTool()

        intent = params.get("intent", "")
        expires_hours = params.get("expires_hours", 24)

        result = await tool.execute(
            user_id,
            intent=intent,
            expires_hours=expires_hours,
        )

        if result.success and result.data:
            result.data["next_steps"] = "Automation created - needs confirmation to activate"

        return result

    async def _execute_heartbeat(self, user_id: str, params: Dict[str, Any]) -> ToolResult:
        """Execute heartbeat item creation (database or file)"""
        storage = params.get("storage", "database")
        description = params.get("description", "")

        if storage == "file":
            # Append to HEARTBEAT.md file
            return await self._execute_heartbeat_file(description, params)
        else:
            # Use structured database
            return await self._execute_heartbeat_database(user_id, params)

    async def _execute_heartbeat_database(self, user_id: str, params: Dict[str, Any]) -> ToolResult:
        """Add heartbeat item to database"""
        from app.tools.heartbeat import AddHeartbeatItemTool

        tool = AddHeartbeatItemTool()

        item_type = params.get("item_type", "monitor")
        description = params.get("description", "")
        check_logic = params.get("check_logic", "custom")
        priority = params.get("priority", "normal")
        condition = params.get("condition")
        expires_at = params.get("expires_at")
        config = params.get("config", {})

        result = await tool.execute(
            user_id,
            item_type=item_type,
            description=description,
            check_logic=check_logic,
            priority=priority,
            condition=condition,
            expires_at=expires_at,
            config=config,
            source_context="Routed from behavior intent",
        )

        if result.success and result.data:
            result.data["storage"] = "database"
            result.data["next_steps"] = None  # Heartbeat items are immediately active

        return result

    async def _execute_heartbeat_file(self, description: str, params: Dict[str, Any]) -> ToolResult:
        """Add rule to HEARTBEAT.md file"""
        from app.tools.heartbeat import UpdateHeartbeatFileTool

        tool = UpdateHeartbeatFileTool()

        # Format as a markdown rule
        priority = params.get("priority", "normal")
        item_type = params.get("item_type", "monitor")

        # Determine which section this belongs in based on item_type and priority
        if item_type == "time_bound":
            section = "## Time-Sensitive"
        elif priority == "high":
            section = "## High Priority"
        else:
            section = "## Always (Every Heartbeat)"

        # Format the rule
        rule_text = f"{section}\n- {description}"

        result = await tool.execute(
            user_id="system",  # File edits don't need user context
            append_section=rule_text,
        )

        if result.success:
            return ToolResult(
                success=True,
                data={
                    "storage": "file",
                    "rule": description,
                    "section": section,
                    "next_steps": None,
                },
                message=f"Added rule to HEARTBEAT.md: {description[:50]}...",
            )
        else:
            return result


# Singleton instance
_router: Optional[BehaviorRouter] = None


def get_behavior_router() -> BehaviorRouter:
    """Get the singleton BehaviorRouter instance"""
    global _router
    if _router is None:
        _router = BehaviorRouter()
    return _router
