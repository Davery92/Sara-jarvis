"""
Helper to migrate existing BaseTool instances to ToolDefinition format
"""
from typing import Dict, Any
from app.tools.base import BaseTool, ToolResult
from app.tools.registry_v2 import (
    ToolDefinition,
    ToolParameter,
    ToolParameterType,
    ToolCategory,
    ToolAuthRequirement,
    ToolVersion,
    registry_v2
)
import logging

logger = logging.getLogger(__name__)


def json_schema_to_parameter(name: str, schema: Dict[str, Any], required: bool = False) -> ToolParameter:
    """Convert JSON schema property to ToolParameter"""

    # Map JSON schema types to ToolParameterType
    type_map = {
        "string": ToolParameterType.STRING,
        "number": ToolParameterType.NUMBER,
        "integer": ToolParameterType.INTEGER,
        "boolean": ToolParameterType.BOOLEAN,
        "array": ToolParameterType.ARRAY,
        "object": ToolParameterType.OBJECT
    }

    param_type = type_map.get(schema.get("type", "string"), ToolParameterType.STRING)

    return ToolParameter(
        name=name,
        type=param_type,
        description=schema.get("description", ""),
        required=required,
        default=schema.get("default"),
        enum=schema.get("enum"),
        items=schema.get("items"),
        properties=schema.get("properties"),
        min_value=schema.get("minimum"),
        max_value=schema.get("maximum"),
        min_length=schema.get("minLength"),
        max_length=schema.get("maxLength"),
        pattern=schema.get("pattern")
    )


def migrate_tool_to_v2(
    tool: BaseTool,
    category: ToolCategory,
    auth_requirement: ToolAuthRequirement = ToolAuthRequirement.REQUIRED,
    backend_route: str = None,
    tags: list = None
) -> ToolDefinition:
    """
    Migrate a BaseTool to ToolDefinition

    Args:
        tool: Existing BaseTool instance
        category: Tool category
        auth_requirement: Auth requirement level
        backend_route: Optional API route
        tags: Optional tags

    Returns:
        ToolDefinition instance
    """
    # Extract parameters from JSON schema
    params_schema = tool.parameters
    properties = params_schema.get("properties", {})
    required_params = params_schema.get("required", [])

    parameters = []
    for param_name, param_schema in properties.items():
        param = json_schema_to_parameter(
            name=param_name,
            schema=param_schema,
            required=param_name in required_params
        )
        parameters.append(param)

    # Create tool definition
    definition = ToolDefinition(
        name=tool.name,
        version=ToolVersion.V2,
        category=category,
        description=tool.description,
        parameters=parameters,
        auth_requirement=auth_requirement,
        backend_route=backend_route or f"/api/tools/{tool.name}",
        tags=tags or []
    )

    return definition


async def wrap_tool_execute(tool: BaseTool, user_id: str, **kwargs) -> Dict[str, Any]:
    """
    Wrapper to convert BaseTool.execute result to dict format
    """
    result: ToolResult = await tool.execute(user_id, **kwargs)
    return {
        "success": result.success,
        "message": result.message,
        "data": result.data,
        "citations": result.citations
    }


def register_existing_tool(
    tool: BaseTool,
    category: ToolCategory,
    auth_requirement: ToolAuthRequirement = ToolAuthRequirement.REQUIRED,
    tags: list = None
):
    """
    Register an existing BaseTool with the new registry

    Args:
        tool: Existing BaseTool instance
        category: Tool category
        auth_requirement: Auth requirement
        tags: Optional tags
    """
    definition = migrate_tool_to_v2(
        tool=tool,
        category=category,
        auth_requirement=auth_requirement,
        tags=tags
    )

    # Create handler wrapper
    async def handler(user_id: str, **kwargs):
        return await wrap_tool_execute(tool, user_id, **kwargs)

    registry_v2.register_tool(definition, handler)
    logger.info(f"Migrated and registered tool: {tool.name}")


# Category mapping for automatic migration
TOOL_CATEGORY_MAP = {
    "memory_search": ToolCategory.MEMORY,

    # Notes
    "notes_create": ToolCategory.NOTES,
    "notes_search": ToolCategory.NOTES,
    "notes_edit": ToolCategory.NOTES,
    "notes_delete": ToolCategory.NOTES,
    "notes_list": ToolCategory.NOTES,

    # Time management
    "reminders_create": ToolCategory.TIME,
    "reminders_list": ToolCategory.TIME,
    "reminders_cancel": ToolCategory.TIME,
    "timers_start": ToolCategory.TIME,
    "timers_status": ToolCategory.TIME,
    "timers_cancel": ToolCategory.TIME,
    "calendar_list": ToolCategory.TIME,
    "calendar_create": ToolCategory.TIME,

    # Knowledge graph
    "knowledge_graph_search": ToolCategory.KNOWLEDGE_GRAPH,
    "find_connections": ToolCategory.KNOWLEDGE_GRAPH,
    "discover_knowledge_clusters": ToolCategory.KNOWLEDGE_GRAPH,
    "analyze_knowledge_gaps": ToolCategory.KNOWLEDGE_GRAPH,

    # Web
    "web_search": ToolCategory.WEB,
    "get_web_search_details": ToolCategory.WEB,
    "open_page": ToolCategory.WEB,
    "get_page_details": ToolCategory.WEB,

    # Fitness
    "fitness_summary": ToolCategory.FITNESS,
    "fitness_note_create": ToolCategory.FITNESS,
    "fitness_note_search": ToolCategory.FITNESS,
    "fitness_note_edit": ToolCategory.FITNESS,
    "food_search_and_log": ToolCategory.FITNESS,
    "food_log_create": ToolCategory.FITNESS,
    "food_log_search": ToolCategory.FITNESS,
    "food_log_summary": ToolCategory.FITNESS,
    "workout_list": ToolCategory.FITNESS,
    "workout_log_create": ToolCategory.FITNESS,
    "workout_details": ToolCategory.FITNESS,
    "workout_stats": ToolCategory.FITNESS,
    "recovery_log_create": ToolCategory.FITNESS,
    "recovery_log_get": ToolCategory.FITNESS,
    "recovery_log_recent": ToolCategory.FITNESS,
    "template_list": ToolCategory.FITNESS,
    "template_get": ToolCategory.FITNESS,

    # Shadow
    "shadow_start": ToolCategory.SHADOW,
}


def auto_migrate_all_tools(tool_list: list[BaseTool]):
    """
    Automatically migrate all tools from existing registry

    Args:
        tool_list: List of BaseTool instances
    """
    for tool in tool_list:
        category = TOOL_CATEGORY_MAP.get(tool.name, ToolCategory.NOTES)

        try:
            register_existing_tool(
                tool=tool,
                category=category,
                tags=[category.value]
            )
        except Exception as e:
            logger.error(f"Failed to migrate tool {tool.name}: {e}")


if __name__ == "__main__":
    # Test migration
    from app.tools.registry import tool_registry

    print("Migrating existing tools to V2 registry...")
    all_tools = tool_registry.get_all_tools()
    auto_migrate_all_tools(all_tools)

    print(f"\nMigrated {len(registry_v2.tools)} tools")
    print("\nGenerating TypeScript types...")

    ts_code = registry_v2.generate_typescript_types(
        output_path="../../../ios-app/src/types/tools.generated.ts"
    )

    print("Done! TypeScript types generated.")
