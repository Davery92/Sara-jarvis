"""
Personal Knowledge Graph Tools for Sara's Chat

Allows Sara to query and add facts about David during conversation.
"""

from typing import Dict, Any

from app.tools.base import BaseTool, ToolResult


class QueryDavidKnowledgeTool(BaseTool):
    """Search Sara's knowledge about David by topic/category"""

    @property
    def name(self) -> str:
        return "query_david_knowledge"

    @property
    def description(self) -> str:
        return (
            "Search Sara's personal knowledge graph about David. Query by topic keywords "
            "or browse by category. Returns facts Sara has learned about David's preferences, "
            "routines, goals, interests, health, relationships, and places."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query — topic, keyword, or question about David"
                },
                "category": {
                    "type": "string",
                    "description": "Filter by category",
                    "enum": ["Person", "Preference", "Routine", "Goal", "Interest", "Health", "Place", "Fact"]
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default 10)",
                    "default": 10
                }
            },
            "required": []
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        try:
            from app.services.personal_knowledge_graph import personal_kg

            query = kwargs.get("query", "")
            category = kwargs.get("category")
            limit = kwargs.get("limit", 10)

            if query:
                facts = personal_kg.query_relevant([query], limit=limit)
            elif category:
                facts = personal_kg.browse(category=category, limit=limit)
            else:
                facts = personal_kg.browse(limit=limit)

            if not facts:
                return ToolResult(
                    success=True,
                    message="No matching knowledge found about David.",
                    data={"facts": []}
                )

            # Format for display
            formatted = []
            for f in facts:
                fact_type = f.get("type", "Unknown")
                confidence = f.get("confidence", 0)
                times_confirmed = f.get("times_confirmed", 1)
                formatted.append({
                    "type": fact_type,
                    "details": {k: v for k, v in f.items()
                               if k not in ("type", "pkg_id", "dedup_key", "version",
                                          "superseded_by", "source", "first_learned",
                                          "last_confirmed", "times_confirmed", "confidence")},
                    "confidence": round(confidence, 2),
                    "times_confirmed": times_confirmed,
                })

            return ToolResult(
                success=True,
                message=f"Found {len(formatted)} facts about David.",
                data={"facts": formatted}
            )

        except Exception as e:
            return ToolResult(
                success=False,
                message=f"Failed to query knowledge: {str(e)}"
            )


class RememberAboutDavidTool(BaseTool):
    """Explicitly store a fact about David in the knowledge graph"""

    @property
    def name(self) -> str:
        return "remember_about_david"

    @property
    def description(self) -> str:
        return (
            "Explicitly store a fact about David in Sara's personal knowledge graph. "
            "Use when David says 'remember that I...' or when Sara notices something "
            "important about David that should be remembered. "
            "Do NOT use fact_type='Place' for a physical location Sara should recognize by "
            "GPS or use for location-triggered reminders (e.g. 'remember this place as home', "
            "'when I leave the office...') — that needs actual coordinates, which this tool "
            "does not capture. Use places_save for those instead; reserve this tool's 'Place' "
            "type for places David just mentions in passing without needing geofencing."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "fact_type": {
                    "type": "string",
                    "description": "Type of fact",
                    "enum": ["Person", "Preference", "Routine", "Goal", "Interest", "Health", "Place", "Fact"]
                },
                "properties": {
                    "type": "object",
                    "description": "Fact-specific properties. See type schemas:\n"
                                   "Person: {name, relationship_to_david, notes}\n"
                                   "Preference: {domain, key, value, strength: love/like/dislike/hate}\n"
                                   "Routine: {activity, typical_time, day_of_week, frequency}\n"
                                   "Goal: {description, status: active/completed/abandoned, target_date}\n"
                                   "Interest: {topic, depth: surface/moderate/deep}\n"
                                   "Health: {metric, current_value, trend: improving/stable/declining}\n"
                                   "Place: {name, type, address, significance}\n"
                                   "Fact: {subject, predicate, object, category}"
                },
                "confidence": {
                    "type": "number",
                    "description": "How confident Sara is (0.0-1.0). Capped at entry tier "
                                   "regardless of what's passed here — see execute().",
                    "default": 0.6
                }
            },
            "required": ["fact_type", "properties"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        try:
            from app.services.personal_knowledge_graph import personal_kg
            from app.services.confidence_ladder import CONFIRMED_AT

            fact_type = kwargs.get("fact_type", "Fact")
            properties = kwargs.get("properties", {})
            # Arc 5.2 minter ruling: any path may mint at entry tier; only
            # dreaming promotes. This tool is LLM-self-assessed (Sara
            # decides both whether to call it and what confidence to
            # claim) with no independent check that a "David said X"
            # interpretation was actually explicit rather than Sara's own
            # inference — real David statements get to confirmed tier for
            # real either via the verification loop's retire half
            # (CONFIRMED graduates immediately) or via
            # promote_corroborated_facts() once corroborated, not by
            # trusting the tool call's own confidence claim at write time.
            confidence = min(max(kwargs.get("confidence", 0.6), 0.1), CONFIRMED_AT - 0.01)

            if not properties:
                return ToolResult(
                    success=False,
                    message="No properties provided for the fact."
                )

            pkg_id = personal_kg.upsert_fact(
                fact_type=fact_type,
                properties=properties,
                confidence=confidence,
                source="explicit_statement"
            )

            if pkg_id:
                return ToolResult(
                    success=True,
                    message=f"Remembered! Stored as {fact_type} with {confidence:.0%} confidence.",
                    data={"pkg_id": pkg_id, "type": fact_type}
                )
            else:
                return ToolResult(
                    success=False,
                    message="Failed to store fact — PKG may be unavailable."
                )

        except Exception as e:
            return ToolResult(
                success=False,
                message=f"Failed to store fact: {str(e)}"
            )


# Export for registry
PKG_TOOLS = [
    QueryDavidKnowledgeTool(),
    RememberAboutDavidTool(),
]
