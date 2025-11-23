"""
Type-Safe Tool Definition Registry V2
JSON schema-driven tool system with TypeScript type generation
"""
from typing import Dict, List, Any, Optional, Callable
from pydantic import BaseModel, Field, validator
from enum import Enum
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class ToolVersion(str, Enum):
    """Tool version enumeration"""
    V1 = "v1"
    V2 = "v2"


class ToolAuthRequirement(str, Enum):
    """Authentication requirement levels"""
    REQUIRED = "required"
    OPTIONAL = "optional"
    NONE = "none"


class ToolCategory(str, Enum):
    """Tool category enumeration"""
    MEMORY = "memory"
    KNOWLEDGE_GRAPH = "knowledge_graph"
    NOTES = "notes"
    TIME = "time"
    WEB = "web"
    FITNESS = "fitness"
    SHADOW = "shadow"
    HEALTH = "health"  # New for Apple Health integration
    GOALS = "goals"  # New for goal system
    INTELLIGENCE = "intelligence"  # New for proactive features


class ToolParameterType(str, Enum):
    """Parameter type enumeration"""
    STRING = "string"
    NUMBER = "number"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    ARRAY = "array"
    OBJECT = "object"


class ToolParameter(BaseModel):
    """Tool parameter definition"""
    name: str
    type: ToolParameterType
    description: str
    required: bool = False
    default: Optional[Any] = None
    enum: Optional[List[Any]] = None
    items: Optional[Dict[str, Any]] = None  # For array types
    properties: Optional[Dict[str, Any]] = None  # For object types
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    min_length: Optional[int] = None
    max_length: Optional[int] = None
    pattern: Optional[str] = None  # Regex pattern for strings

    def to_json_schema(self) -> Dict[str, Any]:
        """Convert to JSON schema format"""
        schema = {
            "type": self.type.value,
            "description": self.description
        }

        if self.enum is not None:
            schema["enum"] = self.enum

        if self.items is not None:
            schema["items"] = self.items

        if self.properties is not None:
            schema["properties"] = self.properties

        if self.min_value is not None:
            schema["minimum"] = self.min_value

        if self.max_value is not None:
            schema["maximum"] = self.max_value

        if self.min_length is not None:
            schema["minLength"] = self.min_length

        if self.max_length is not None:
            schema["maxLength"] = self.max_length

        if self.pattern is not None:
            schema["pattern"] = self.pattern

        if self.default is not None:
            schema["default"] = self.default

        return schema

    def to_typescript_type(self) -> str:
        """Convert to TypeScript type"""
        type_map = {
            ToolParameterType.STRING: "string",
            ToolParameterType.NUMBER: "number",
            ToolParameterType.INTEGER: "number",
            ToolParameterType.BOOLEAN: "boolean",
            ToolParameterType.ARRAY: "Array<any>",
            ToolParameterType.OBJECT: "Record<string, any>"
        }

        ts_type = type_map.get(self.type, "any")

        # Handle enums
        if self.enum:
            if all(isinstance(v, str) for v in self.enum):
                ts_type = " | ".join(f'"{v}"' for v in self.enum)
            else:
                ts_type = " | ".join(str(v) for v in self.enum)

        # Make optional if not required
        if not self.required:
            ts_type = f"{ts_type} | undefined"

        return ts_type


class ToolOutputSchema(BaseModel):
    """Tool output schema definition"""
    description: str
    properties: Dict[str, Dict[str, Any]]
    example: Optional[Dict[str, Any]] = None


class ToolDefinition(BaseModel):
    """Complete tool definition with validation"""
    name: str = Field(..., pattern=r"^[a-z_][a-z0-9_]*$")
    version: ToolVersion = ToolVersion.V2
    category: ToolCategory
    description: str = Field(..., min_length=10, max_length=500)
    parameters: List[ToolParameter] = []
    output_schema: Optional[ToolOutputSchema] = None
    auth_requirement: ToolAuthRequirement = ToolAuthRequirement.REQUIRED
    backend_route: Optional[str] = None  # API route for execution
    deprecated: bool = False
    deprecation_message: Optional[str] = None
    rate_limit: Optional[int] = None  # Max calls per minute
    examples: List[Dict[str, Any]] = []
    tags: List[str] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @validator('deprecation_message')
    def check_deprecation_message(cls, v, values):
        if values.get('deprecated') and not v:
            raise ValueError("Deprecated tools must have a deprecation_message")
        return v

    def get_required_parameters(self) -> List[str]:
        """Get list of required parameter names"""
        return [p.name for p in self.parameters if p.required]

    def validate_parameters(self, params: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        Validate provided parameters against schema
        Returns: (is_valid, error_message)
        """
        # Check required parameters
        required = self.get_required_parameters()
        missing = set(required) - set(params.keys())
        if missing:
            return False, f"Missing required parameters: {', '.join(missing)}"

        # Check parameter types and constraints
        for param in self.parameters:
            if param.name not in params:
                continue

            value = params[param.name]

            # Type checking (basic)
            if param.type == ToolParameterType.STRING and not isinstance(value, str):
                return False, f"Parameter '{param.name}' must be a string"
            elif param.type == ToolParameterType.NUMBER and not isinstance(value, (int, float)):
                return False, f"Parameter '{param.name}' must be a number"
            elif param.type == ToolParameterType.INTEGER and not isinstance(value, int):
                return False, f"Parameter '{param.name}' must be an integer"
            elif param.type == ToolParameterType.BOOLEAN and not isinstance(value, bool):
                return False, f"Parameter '{param.name}' must be a boolean"
            elif param.type == ToolParameterType.ARRAY and not isinstance(value, list):
                return False, f"Parameter '{param.name}' must be an array"
            elif param.type == ToolParameterType.OBJECT and not isinstance(value, dict):
                return False, f"Parameter '{param.name}' must be an object"

            # Enum validation
            if param.enum and value not in param.enum:
                return False, f"Parameter '{param.name}' must be one of: {param.enum}"

            # Range validation for numbers
            if param.type in [ToolParameterType.NUMBER, ToolParameterType.INTEGER]:
                if param.min_value is not None and value < param.min_value:
                    return False, f"Parameter '{param.name}' must be >= {param.min_value}"
                if param.max_value is not None and value > param.max_value:
                    return False, f"Parameter '{param.name}' must be <= {param.max_value}"

            # Length validation for strings
            if param.type == ToolParameterType.STRING:
                if param.min_length is not None and len(value) < param.min_length:
                    return False, f"Parameter '{param.name}' must be at least {param.min_length} characters"
                if param.max_length is not None and len(value) > param.max_length:
                    return False, f"Parameter '{param.name}' must be at most {param.max_length} characters"

        return True, None

    def to_openai_schema(self) -> Dict[str, Any]:
        """Convert to OpenAI function calling schema"""
        properties = {}
        for param in self.parameters:
            properties[param.name] = param.to_json_schema()

        schema = {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": self.get_required_parameters()
                }
            }
        }

        return schema

    def to_typescript_interface(self) -> str:
        """Generate TypeScript interface for this tool"""
        lines = [f"// {self.description}"]
        lines.append(f"// Category: {self.category.value}")
        if self.deprecated:
            lines.append(f"// @deprecated {self.deprecation_message}")
        lines.append(f"export interface {self._to_camel_case(self.name)}Params {{")

        for param in self.parameters:
            optional = "?" if not param.required else ""
            ts_type = param.to_typescript_type()
            lines.append(f"  {param.name}{optional}: {ts_type}; // {param.description}")

        lines.append("}")

        # Add result interface if output schema exists
        if self.output_schema:
            lines.append("")
            lines.append(f"export interface {self._to_camel_case(self.name)}Result {{")
            lines.append("  success: boolean;")
            lines.append("  message?: string;")
            lines.append("  data?: {")

            for prop_name, prop_schema in self.output_schema.properties.items():
                prop_type = prop_schema.get("type", "any")
                lines.append(f"    {prop_name}?: {prop_type};")

            lines.append("  };")
            lines.append("}")

        return "\n".join(lines)

    @staticmethod
    def _to_camel_case(snake_str: str) -> str:
        """Convert snake_case to PascalCase"""
        return ''.join(word.capitalize() for word in snake_str.split('_'))


class ToolRegistryV2:
    """Type-safe tool registry with validation and TypeScript generation"""

    def __init__(self):
        self.tools: Dict[str, ToolDefinition] = {}
        self.tool_handlers: Dict[str, Callable] = {}
        self.categories: Dict[ToolCategory, List[str]] = {
            category: [] for category in ToolCategory
        }

    def register_tool(
        self,
        definition: ToolDefinition,
        handler: Optional[Callable] = None
    ) -> None:
        """
        Register a tool with its definition and optional handler

        Args:
            definition: Tool definition with schema
            handler: Async function to execute tool (optional)
        """
        if definition.name in self.tools:
            logger.warning(f"Tool '{definition.name}' already registered, overwriting")

        self.tools[definition.name] = definition

        if handler:
            self.tool_handlers[definition.name] = handler

        # Add to category index
        if definition.name not in self.categories[definition.category]:
            self.categories[definition.category].append(definition.name)

        logger.info(f"Registered tool: {definition.name} (v{definition.version.value}, {definition.category.value})")

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        """Get tool definition by name"""
        return self.tools.get(name)

    def get_tools_by_category(self, category: ToolCategory) -> List[ToolDefinition]:
        """Get all tools in a category"""
        tool_names = self.categories.get(category, [])
        return [self.tools[name] for name in tool_names if name in self.tools]

    def get_all_tools(self) -> List[ToolDefinition]:
        """Get all registered tools"""
        return list(self.tools.values())

    def get_openai_schemas(self, categories: Optional[List[ToolCategory]] = None) -> List[Dict[str, Any]]:
        """
        Get OpenAI function calling schemas

        Args:
            categories: Optional filter by categories

        Returns:
            List of OpenAI function schemas
        """
        if categories:
            tools = []
            for category in categories:
                tools.extend(self.get_tools_by_category(category))
        else:
            tools = self.get_all_tools()

        # Filter out deprecated tools
        tools = [t for t in tools if not t.deprecated]

        return [tool.to_openai_schema() for tool in tools]

    def validate_tool_call(self, name: str, parameters: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        Validate a tool call

        Returns: (is_valid, error_message)
        """
        tool = self.get_tool(name)
        if not tool:
            return False, f"Tool '{name}' not found"

        if tool.deprecated:
            logger.warning(f"Tool '{name}' is deprecated: {tool.deprecation_message}")

        return tool.validate_parameters(parameters)

    async def execute_tool(
        self,
        name: str,
        user_id: str,
        parameters: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute a tool with validation

        Returns:
            Tool result dictionary
        """
        # Validate
        is_valid, error = self.validate_tool_call(name, parameters)
        if not is_valid:
            return {
                "success": False,
                "message": f"Validation error: {error}"
            }

        # Execute if handler exists
        handler = self.tool_handlers.get(name)
        if not handler:
            return {
                "success": False,
                "message": f"No handler registered for tool '{name}'"
            }

        try:
            result = await handler(user_id=user_id, **parameters)
            return result
        except Exception as e:
            logger.error(f"Tool '{name}' execution failed: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"Execution error: {str(e)}"
            }

    def generate_typescript_types(self, output_path: Optional[str] = None) -> str:
        """
        Generate TypeScript type definitions for all tools

        Args:
            output_path: Optional file path to write types to

        Returns:
            Generated TypeScript code
        """
        lines = [
            "// Auto-generated TypeScript types for Sara tools",
            "// Generated at: " + datetime.utcnow().isoformat(),
            "// DO NOT EDIT MANUALLY",
            "",
            "// Tool categories",
            "export enum ToolCategory {",
        ]

        for category in ToolCategory:
            lines.append(f"  {category.name} = '{category.value}',")

        lines.append("}")
        lines.append("")

        # Generate interface for each tool
        for tool in sorted(self.get_all_tools(), key=lambda t: t.name):
            lines.append(tool.to_typescript_interface())
            lines.append("")

        # Generate tool name enum
        lines.append("// Tool names enum")
        lines.append("export enum ToolName {")
        for tool in sorted(self.get_all_tools(), key=lambda t: t.name):
            camel = tool._to_camel_case(tool.name)
            lines.append(f"  {camel} = '{tool.name}',")
        lines.append("}")
        lines.append("")

        # Generate registry type
        lines.append("// Tool registry type")
        lines.append("export interface ToolRegistry {")
        for tool in sorted(self.get_all_tools(), key=lambda t: t.name):
            camel = tool._to_camel_case(tool.name)
            lines.append(f"  {tool.name}: {{")
            lines.append(f"    params: {camel}Params;")
            if tool.output_schema:
                lines.append(f"    result: {camel}Result;")
            else:
                lines.append(f"    result: {{ success: boolean; message?: string; data?: any }};")
            lines.append(f"  }};")
        lines.append("}")

        typescript_code = "\n".join(lines)

        # Write to file if path provided
        if output_path:
            with open(output_path, 'w') as f:
                f.write(typescript_code)
            logger.info(f"Generated TypeScript types at: {output_path}")

        return typescript_code

    def export_schema_json(self, output_path: str) -> None:
        """Export all tool schemas as JSON"""
        schemas = {
            "version": "2.0",
            "generated_at": datetime.utcnow().isoformat(),
            "tools": {
                name: tool.dict()
                for name, tool in self.tools.items()
            }
        }

        with open(output_path, 'w') as f:
            json.dump(schemas, f, indent=2, default=str)

        logger.info(f"Exported tool schemas to: {output_path}")


# Global registry instance
registry_v2 = ToolRegistryV2()
