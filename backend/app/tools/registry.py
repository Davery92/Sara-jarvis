from typing import Dict, List, Any
from app.tools.base import BaseTool, ToolResult
from app.tools.memory import MemorySearchTool
from app.tools.notes import NotesCreateTool, NotesSearchTool, NotesEditTool
from app.tools.reminders import RemindersCreateTool, RemindersListTool, RemindersCancelTool
from app.tools.timers import TimersStartTool, TimersStatusTool, TimersCancelTool
from app.tools.calendar import CalendarListTool, CalendarCreateTool
import logging

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Registry for all available AI tools"""
    
    def __init__(self):
        self.tools: Dict[str, BaseTool] = {}
        self._register_tools()
    
    def _register_tools(self):
        """Register all available tools"""
        tools = [
            # Memory
            MemorySearchTool(),
            
            # Notes
            NotesCreateTool(),
            NotesSearchTool(),
            NotesEditTool(),
            
            # Reminders
            RemindersCreateTool(),
            RemindersListTool(),
            RemindersCancelTool(),
            
            # Timers
            TimersStartTool(),
            TimersStatusTool(),
            TimersCancelTool(),
            
            # Calendar
            CalendarListTool(),
            CalendarCreateTool(),
        ]
        
        for tool in tools:
            self.tools[tool.name] = tool
            logger.info(f"Registered tool: {tool.name}")
    
    def get_tool(self, name: str) -> BaseTool:
        """Get a tool by name"""
        return self.tools.get(name)
    
    def get_all_tools(self) -> List[BaseTool]:
        """Get all registered tools"""
        return list(self.tools.values())
    
    def get_openai_schemas(self) -> List[Dict[str, Any]]:
        """Get OpenAI function calling schemas for all tools"""
        return [tool.to_openai_schema() for tool in self.tools.values()]
    
    async def execute_tool(
        self, name: str, user_id: str, parameters: Dict[str, Any]
    ) -> ToolResult:
        """Execute a tool by name"""
        tool = self.get_tool(name)
        if not tool:
            return ToolResult(
                success=False,
                message=f"Tool '{name}' not found"
            )
        
        try:
            result = await tool.execute(user_id, **parameters)
            logger.info(f"Tool '{name}' executed successfully")
            return result
        except Exception as e:
            logger.error(f"Tool '{name}' execution failed: {e}")
            return ToolResult(
                success=False,
                message=f"Tool execution failed: {str(e)}"
            )


# Global tool registry instance
tool_registry = ToolRegistry()