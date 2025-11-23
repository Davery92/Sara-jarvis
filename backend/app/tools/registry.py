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
from app.tools.get_web_search_details import GetWebSearchDetailsTool
from app.tools.open_page import OpenPageTool
from app.tools.get_page_details import GetPageDetailsTool
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
    WorkoutDetailsTool,
    WorkoutStatsTool
)
from app.tools.fitness.recovery_log import (
    RecoveryLogCreateTool,
    RecoveryLogGetTool,
    RecoveryLogRecentTool
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

    # Tool category definitions
    TOOL_CATEGORIES = {
        'memory': {
            'description': 'Search personal knowledge across notes, documents, episodes, and summaries',
            'tools': ['memory_search']
        },
        'knowledge_graph': {
            'description': 'Explore connections, discover patterns, and analyze knowledge relationships',
            'tools': [
                'knowledge_graph_search',
                'find_connections',
                'discover_knowledge_clusters',
                'analyze_knowledge_gaps'
            ]
        },
        'notes': {
            'description': 'Create, edit, search, list, and delete notes in the knowledge garden',
            'tools': [
                'notes_create',
                'notes_search',
                'notes_edit',
                'notes_delete',
                'notes_list'
            ]
        },
        'time': {
            'description': 'Manage reminders, timers, and calendar events',
            'tools': [
                'reminders_create',
                'reminders_list',
                'reminders_cancel',
                'timers_start',
                'timers_status',
                'timers_cancel',
                'calendar_list',
                'calendar_create'
            ]
        },
        'web': {
            'description': 'Search the web and browse pages for real-time information',
            'tools': [
                'web_search',
                'get_web_search_details',
                'open_page',
                'get_page_details'
            ]
        },
        'fitness': {
            'description': 'Track and manage fitness, nutrition, workouts, and recovery',
            'tools': [
                'fitness_summary',
                'fitness_note_create', 'fitness_note_search', 'fitness_note_edit',
                'food_search_and_log', 'food_log_create', 'food_log_search', 'food_log_summary',
                'workout_list', 'workout_log_create', 'workout_details', 'workout_stats',
                'recovery_log_create', 'recovery_log_get', 'recovery_log_recent',
                'template_list', 'template_get'
            ]
        },
        'shadow': {
            'description': 'Activate silent observation mode to monitor without responding',
            'tools': ['shadow_start']
        }
    }

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
            GetWebSearchDetailsTool(),
            OpenPageTool(),
            GetPageDetailsTool(),

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
            WorkoutDetailsTool(),
            WorkoutStatsTool(),

            # Recovery Tools
            RecoveryLogCreateTool(),
            RecoveryLogGetTool(),
            RecoveryLogRecentTool(),

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

    def get_category_schemas(self) -> List[Dict[str, Any]]:
        """
        Get minimal category descriptions for tier 1 tool selection.
        Returns OpenAI-compatible schema describing available tool categories.
        """
        categories_list = []
        for category, info in self.TOOL_CATEGORIES.items():
            categories_list.append({
                'name': category,
                'description': info['description']
            })

        # Build the description string for available categories
        categories_desc_parts = []
        for c in categories_list:
            categories_desc_parts.append(f"{c['name']} ({c['description']})")
        categories_description = 'Categories to load. Available: ' + ', '.join(categories_desc_parts)

        return [{
            'type': 'function',
            'function': {
                'name': 'load_tool_categories',
                'description': 'Load tools from one or more categories to use them. Call this first to access specific functionality.',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'categories': {
                            'type': 'array',
                            'items': {
                                'type': 'string',
                                'enum': list(self.TOOL_CATEGORIES.keys())
                            },
                            'description': categories_description
                        }
                    },
                    'required': ['categories']
                }
            }
        }]

    def get_tools_by_categories(self, categories: List[str]) -> List[Dict[str, Any]]:
        """
        Get OpenAI function calling schemas for tools in specified categories.

        Args:
            categories: List of category names to load tools from

        Returns:
            List of OpenAI function schemas for tools in those categories
        """
        tool_names = set()
        for category in categories:
            if category in self.TOOL_CATEGORIES:
                tool_names.update(self.TOOL_CATEGORIES[category]['tools'])
            else:
                logger.warning(f"Unknown category requested: {category}")

        schemas = []
        for tool_name in tool_names:
            tool = self.tools.get(tool_name)
            if tool:
                schemas.append(tool.to_openai_schema())
            else:
                logger.warning(f"Tool '{tool_name}' not found in registry")

        logger.info(f"Loaded {len(schemas)} tools from categories: {categories}")
        return schemas

    async def execute_tool(
        self, name: str, user_id: str, parameters: Dict[str, Any]
    ) -> ToolResult:
        """Execute a tool by name"""
        # Handle special meta-tool for loading categories
        if name == "load_tool_categories":
            categories = parameters.get("categories", [])
            logger.info(f"Tool category loader called with categories: {categories}")
            return ToolResult(
                success=True,
                message=f"Tools loaded for categories: {', '.join(categories)}",
                data={"categories": categories}
            )

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
