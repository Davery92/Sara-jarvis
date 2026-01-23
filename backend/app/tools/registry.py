from typing import Dict, List, Any
from app.tools.base import BaseTool, ToolResult
from app.tools.memory import MemorySearchTool
from app.tools.notes import NotesCreateTool, NotesSearchTool, NotesEditTool, NotesDeleteTool, NotesListTool
from app.tools.reminders import RemindersCreateTool, RemindersListTool, RemindersCancelTool
from app.tools.timers import TimersStartTool, TimersStatusTool, TimersCancelTool
from app.tools.calendar import CalendarListTool, CalendarCreateTool, CalendarSetRecurringTool
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
    TemplateGetTool,
    TemplateCreateTool,
    TemplateUpdateTool,
    TemplateDeleteTool
)
from app.tools.fitness.program_tools import (
    ProgramListTool,
    ProgramGetTool,
    ProgramCreateTool,
    ProgramUpdateTool,
    ProgramActivateTool,
    ProgramDeleteTool,
    PhaseListTool,
    PhaseGetTool,
    PhaseCreateTool,
    PhaseUpdateTool,
    PhaseActivateTool,
    PhaseDeleteTool
)
from app.tools.fitness.workout_suggest import WorkoutSuggestTool
from app.tools.fitness.summary import FitnessSummaryTool
from app.tools.fitness.workout_mode import (
    WorkoutModeLogTool,
    WorkoutModeStartTool,
    WorkoutModeCompleteTool
)
from app.tools.chess import (
    ChessStartGameTool,
    ChessMoveTool,
    ChessGetBoardTool,
    ChessResignTool,
    ChessDrawTool,
    ChessPauseTool,
    ChessResumeTool,
    ChessStatsTool,
    ChessHistoryTool,
    ChessAnalyzeTool,
    ChessCoachTool,
    ChessReviewGameTool,
    ChessProgressTool
)
from app.tools.learning import (
    LearningTopicCreateTool,
    LearningTopicListTool,
    LearningTopicUpdateTool,
    LearningSourceAddTool,
    LearningSourceListTool,
    LearningScratchpadReadTool,
    LearningScratchpadUpdateTool,
    LearningResearchTool,
    LearningAnalyzeGapsTool,
    LearningFetchSourceTool,
    LearningPathTool,
    LearningNextSessionTool
)
from app.tools.morning_brief import MorningBriefTool, WeatherTool
from app.tools.projects import PROJECT_TOOLS
from app.tools.home import HOME_TOOLS
from app.tools.agents import HandoffToAgentsTool, GetBackgroundTasksTool
from app.tools.health import HEALTH_TOOLS
from app.tools.canvas import (
    CanvasOpenTool,
    CanvasUpdateTool,
    CanvasCloseTool,
    CanvasOpenNoteTool,
    CanvasSaveAsNoteTool
)
from app.tools.patterns import PATTERN_TOOLS
from app.tools.device_commands import DEVICE_TOOLS
from app.tools.workspace import WORKSPACE_TOOLS
from app.tools.maps import MAP_TOOLS
from app.tools.self_knowledge import SELF_KNOWLEDGE_TOOLS
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
            'description': 'Track and manage fitness, nutrition, workouts, recovery, training programs and phases',
            'tools': [
                'fitness_summary',
                'fitness_note_create', 'fitness_note_search', 'fitness_note_edit',
                'food_search_and_log', 'food_log_create', 'food_log_search', 'food_log_summary',
                'workout_list', 'workout_log_create', 'workout_details', 'workout_stats',
                'recovery_log_create', 'recovery_log_get', 'recovery_log_recent',
                'template_list', 'template_get', 'template_create', 'template_update', 'template_delete',
                'program_list', 'program_get', 'program_create', 'program_update', 'program_activate', 'program_delete',
                'phase_list', 'phase_get', 'phase_create', 'phase_update', 'phase_activate', 'phase_delete',
                'workout_suggest'
            ]
        },
        'chess': {
            'description': 'Play chess games, track statistics, get coaching and analysis',
            'tools': [
                'chess_start_game', 'chess_move', 'chess_get_board',
                'chess_resign', 'chess_offer_draw', 'chess_pause',
                'chess_resume', 'chess_stats', 'chess_history',
                'chess_analyze_game', 'chess_coach', 'chess_review_game',
                'chess_learning_progress'
            ]
        },
        'learning': {
            'description': 'Manage learning topics, sources, study notes, autonomous research, and personalized learning paths',
            'tools': [
                'learning_topic_create', 'learning_topic_list', 'learning_topic_update',
                'learning_source_add', 'learning_source_list', 'learning_fetch_source',
                'learning_scratchpad_read', 'learning_scratchpad_update',
                'learning_research', 'learning_analyze_gaps',
                'learning_path', 'learning_next_session'
            ]
        },
        'daily': {
            'description': 'Get daily briefings with news, weather, calendar, and training recommendations',
            'tools': ['morning_brief', 'weather']
        },
        'projects': {
            'description': 'Track software development projects, tasks, commits, and development progress',
            'tools': [
                'get_project_state', 'get_task_detail', 'list_tasks_by_status',
                'get_open_bugs', 'get_shipped_this_week', 'get_recent_commits',
                'suggest_next_task', 'get_weekly_velocity'
            ]
        },
        'home': {
            'description': 'Control smart home devices via Home Assistant - get home status, control lights, switches, thermostats, locks, covers, scenes, media players. Schedule actions for later.',
            'tools': [
                'home_status',  # Quick overview of entire home - use first!
                'home_get_devices', 'home_light_control', 'home_switch_control',
                'home_climate_control', 'home_cover_control', 'home_lock_control',
                'home_scene_activate', 'home_media_control', 'home_all_lights_off',
                'home_schedule_action', 'home_list_scheduled', 'home_cancel_scheduled'
            ]
        },
        'agents': {
            'description': 'Hand off research tasks to background worker agents for autonomous investigation',
            'tools': [
                'handoff_to_agents', 'get_background_tasks'
            ]
        },
        'health': {
            'description': 'Access health metrics, trends, insights, and alerts from HealthKit data',
            'tools': [
                'health_status', 'health_trend'
            ]
        },
        'canvas': {
            'description': 'Control the canvas panel to show code, documents, mindmaps, diagrams, or notes alongside the chat',
            'tools': [
                'canvas_open', 'canvas_update', 'canvas_close',
                'canvas_open_note', 'canvas_save_as_note'
            ]
        },
        'patterns': {
            'description': 'Query discovered cross-domain patterns and correlations (sleep vs productivity, food vs energy, etc.)',
            'tools': [
                'pattern_query', 'pattern_insights',
                'pattern_timeseries', 'pattern_correlation'
            ]
        },
        'devices': {
            'description': 'Control connected desktop agents - send notifications, open URLs, show notes, take screenshots, open workspace on user devices',
            'tools': [
                'device_list', 'device_send_notification', 'device_open_url',
                'device_show_note', 'device_take_screenshot', 'device_open_workspace'
            ]
        },
        'workspace': {
            'description': 'Control the workbench-canvas workspace - open windows, arrange layout, manage notes in the infinite canvas. Use workspace_list_windows to see what windows are open before focusing or closing.',
            'tools': [
                'workspace_list_windows', 'workspace_open_window', 'workspace_open_note',
                'workspace_close_window', 'workspace_save_state', 'workspace_arrange',
                'workspace_focus_window'
            ]
        },
        'maps': {
            'description': 'Create and control mindmaps/flowcharts on the workspace canvas - create maps, add/edit/delete nodes, connect nodes, import from JSON or Mermaid, explode/expand maps',
            'tools': [
                'map_create', 'map_delete', 'map_get', 'map_list',
                'map_add_node', 'map_edit_node', 'map_delete_node',
                'map_connect', 'map_disconnect',
                'map_show', 'map_hide', 'map_import_json', 'map_explode'
            ]
        },
        'self_knowledge': {
            'description': 'Retrieve detailed self-knowledge about Sara\'s architecture, capabilities, autonomous systems, and limitations',
            'tools': ['get_self_knowledge']
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

            # Calendar
            CalendarListTool(),
            CalendarCreateTool(),
            CalendarSetRecurringTool(),

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
            TemplateCreateTool(),
            TemplateUpdateTool(),
            TemplateDeleteTool(),

            # Program Tools
            ProgramListTool(),
            ProgramGetTool(),
            ProgramCreateTool(),
            ProgramUpdateTool(),
            ProgramActivateTool(),
            ProgramDeleteTool(),

            # Phase Tools
            PhaseListTool(),
            PhaseGetTool(),
            PhaseCreateTool(),
            PhaseUpdateTool(),
            PhaseActivateTool(),
            PhaseDeleteTool(),

            # Workout Suggestion (intelligent weight recommendations)
            WorkoutSuggestTool(),

            # Fitness Summary (for regular Sara)
            FitnessSummaryTool(),

            # Workout Mode Tools (real-time coaching during active workout)
            WorkoutModeLogTool(),
            WorkoutModeStartTool(),
            WorkoutModeCompleteTool(),

            # Chess Tools
            ChessStartGameTool(),
            ChessMoveTool(),
            ChessGetBoardTool(),
            ChessResignTool(),
            ChessDrawTool(),
            ChessPauseTool(),
            ChessResumeTool(),
            ChessStatsTool(),
            ChessHistoryTool(),
            ChessAnalyzeTool(),
            ChessCoachTool(),
            ChessReviewGameTool(),
            ChessProgressTool(),

            # Learning Tools
            LearningTopicCreateTool(),
            LearningTopicListTool(),
            LearningTopicUpdateTool(),
            LearningSourceAddTool(),
            LearningSourceListTool(),
            LearningFetchSourceTool(),
            LearningScratchpadReadTool(),
            LearningScratchpadUpdateTool(),
            LearningResearchTool(),
            LearningAnalyzeGapsTool(),
            LearningPathTool(),
            LearningNextSessionTool(),

            # Morning Brief & Weather Tools
            MorningBriefTool(),
            WeatherTool(),

            # Project Tracker Tools
            *PROJECT_TOOLS,

            # Home Control Tools
            *HOME_TOOLS,

            # Agent Handoff Tools
            HandoffToAgentsTool(),
            GetBackgroundTasksTool(),

            # Health Monitoring Tools
            *HEALTH_TOOLS,

            # Canvas Control Tools
            CanvasOpenTool(),
            CanvasUpdateTool(),
            CanvasCloseTool(),
            CanvasOpenNoteTool(),
            CanvasSaveAsNoteTool(),

            # Pattern Correlation Tools
            *PATTERN_TOOLS,

            # Device Command Tools (cross-device actions)
            *DEVICE_TOOLS,

            # Workspace Control Tools (for workbench-canvas)
            *WORKSPACE_TOOLS,

            # Map Control Tools (mindmaps/flowcharts on canvas)
            *MAP_TOOLS,

            # Self-Knowledge Tools (Sara's self-awareness)
            *SELF_KNOWLEDGE_TOOLS,
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
                schema = tool.to_openai_schema()
                # Fix empty required arrays that cause Gemini to fail
                params = schema.get('function', {}).get('parameters', {})
                if 'required' in params and len(params['required']) == 0:
                    del params['required']
                schemas.append(schema)
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
