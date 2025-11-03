from typing import Dict, List, Any
from app.tools.base import BaseTool, ToolResult
from app.tools.memory import MemorySearchTool
from app.tools.notes import NotesCreateTool, NotesSearchTool, NotesEditTool, NotesDeleteTool, NotesListTool
from app.tools.reminders import RemindersCreateTool, RemindersListTool, RemindersCancelTool
from app.tools.timers import TimersStartTool, TimersStatusTool, TimersCancelTool
from app.tools.calendar import CalendarListTool, CalendarCreateTool
from app.tools.shadow import ShadowStartTool
from app.tools.knowledge_graph import (
    KnowledgeGraphSearchTool, 
    ConnectionFinderTool, 
    KnowledgeClusterTool,
    KnowledgeGapAnalysisTool
)
from app.tools.web_search import WebSearchTool
from app.tools.open_page import OpenPageTool
from app.tools.fitness.fitness_notes import (
    FitnessNoteCreateTool,
    FitnessNoteSearchTool,
    FitnessNoteEditTool
)
from app.tools.fitness.food_log import (
    FoodLogCreateTool,
    FoodLogSearchTool,
    FoodLogSummaryTool
)
from app.tools.fitness.food_search_log import FoodSearchAndLogTool
from app.tools.fitness.workout_log import (
    WorkoutListTool,
    WorkoutLogCreateTool,
    WorkoutStatsTool
)
from app.tools.fitness.template_tools import (
    TemplateListTool,
    TemplateGetTool
)
from app.tools.fitness.summary import FitnessSummaryTool
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
            NotesDeleteTool(),
            NotesListTool(),
            
            # Reminders
            RemindersCreateTool(),
            RemindersListTool(),
            RemindersCancelTool(),
            
            # Timers
            TimersStartTool(),
            TimersStatusTool(),
            TimersCancelTool(),

            # Shadow Mode
            ShadowStartTool(),

            # Calendar
            CalendarListTool(),
            CalendarCreateTool(),
            
            # Knowledge Graph
            KnowledgeGraphSearchTool(),
            ConnectionFinderTool(),
            KnowledgeClusterTool(),
            KnowledgeGapAnalysisTool(),

            # Web Search
            WebSearchTool(),
            OpenPageTool(),

            # Fitness Tools
            FitnessNoteCreateTool(),
            FitnessNoteSearchTool(),
            FitnessNoteEditTool(),

            # Food Log Tools
            FoodSearchAndLogTool(),  # Natural language food logging with USDA search
            FoodLogCreateTool(),
            FoodLogSearchTool(),
            FoodLogSummaryTool(),

            # Workout Tools
            WorkoutListTool(),
            WorkoutLogCreateTool(),
            WorkoutStatsTool(),

            # Template Tools
            TemplateListTool(),
            TemplateGetTool(),

            # Fitness Summary (for regular Sara)
            FitnessSummaryTool(),
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

    def get_fitness_tools(self) -> List[BaseTool]:
        """Get fitness-specific tools only"""
        fitness_tool_names = [
            'fitness_note_create', 'fitness_note_search', 'fitness_note_edit',
            'food_log_create', 'food_log_search', 'food_log_summary',
            'workout_list', 'workout_log_create', 'workout_stats',
            'template_list', 'template_get'
        ]
        return [self.tools[name] for name in fitness_tool_names if name in self.tools]

    def get_fitness_tool_schemas(self) -> List[Dict[str, Any]]:
        """Get OpenAI function calling schemas for fitness tools"""
        return [tool.to_openai_schema() for tool in self.get_fitness_tools()]

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
            if result.success:
                logger.info(f"Tool '{name}' executed successfully: {result.message}")
            else:
                logger.warning(f"Tool '{name}' executed but returned failure: {result.message}")
            return result
        except Exception as e:
            logger.error(f"Tool '{name}' execution failed with exception: {e}")
            return ToolResult(
                success=False,
                message=f"Tool execution failed: {str(e)}"
            )


# Global tool registry instance
tool_registry = ToolRegistry()
