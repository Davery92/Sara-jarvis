from typing import Dict, List, Any
from app.tools.base import BaseTool, ToolResult
from app.tools.memory import MemorySearchTool
from app.tools.notes import (
    NotesCreateTool, NotesSearchTool, NotesEditTool, NotesDeleteTool, NotesListTool,
    NotesFindSimilarTool, NotesMergeTool, NotesListFoldersTool, NotesCreateFolderTool,
)
from app.tools.reminders import RemindersCreateTool, RemindersListTool, RemindersCancelTool
from app.tools.location import (
    LocationReminderCreateTool, LocationReminderListTool, LocationReminderCancelTool,
    PlacesSaveTool, PlacesListTool, PlacesDeleteTool,
)
from app.tools.daily_tasks import DailyTaskCreateTool, DailyTaskListTool, DailyTaskCompleteTool
from app.tools.timers import TimersStartTool, TimersStatusTool, TimersCancelTool
from app.tools.calendar import CalendarListTool, CalendarCreateTool, CalendarSetRecurringTool
from app.tools.knowledge_graph import (
    KnowledgeGraphSearchTool, 
    ConnectionFinderTool, 
    KnowledgeClusterTool,
    KnowledgeGapAnalysisTool
)
from app.tools.web_search import WebSearchTool
from app.tools.fleet import FleetStatusTool, FleetDiagTool
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
from app.tools.fitness.training_schedule import TrainingScheduleTool
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
    LearningNextSessionTool,
    LearningTangentCaptureTool,
    LearningTangentListTool,
    LearningKnownDomainsTool,
    LearningFindAnchorsTool
)
from app.tools.morning_brief import MorningBriefTool, WeatherTool
from app.tools.projects import PROJECT_TOOLS
from app.tools.home import HOME_TOOLS
from app.tools.agents import GetBackgroundTasksTool
from app.tools.research_plan import CreateResearchPlanTool, ResearchPlanStatusTool
from app.tools.meeting import MeetingPrepTool
from app.tools.lists import LIST_TOOLS
from app.tools.health import HEALTH_TOOLS
from app.tools.canvas import (
    CanvasOpenTool,
    CanvasUpdateTool,
    CanvasCloseTool,
    CanvasOpenNoteTool,
    CanvasSaveAsNoteTool
)
from app.tools.authoring import AUTHORING_TOOLS
from app.tools.surfaces import SURFACE_TOOLS
from app.tools.workspace_jobs import WORKSPACE_JOB_TOOLS
from app.tools.patterns import PATTERN_TOOLS
from app.tools.device_commands import DEVICE_TOOLS
from app.tools.workspace import WORKSPACE_TOOLS
from app.tools.maps import MAP_TOOLS
from app.tools.self_knowledge import SELF_KNOWLEDGE_TOOLS
from app.tools.email import EMAIL_TOOLS
from app.tools.soul import SOUL_TOOLS
from app.tools.heartbeat import HEARTBEAT_TOOLS
from app.tools.behavior_router import BEHAVIOR_ROUTER_TOOLS
from app.tools.personal_knowledge import PKG_TOOLS
from app.tools.standing_orders import STANDING_ORDER_TOOLS
from app.tools.content_inbox import CONTENT_INBOX_TOOLS
from app.tools.agent_dispatch import AGENT_DISPATCH_TOOLS
from app.tools.sara_queue import QueueForSaraTool
from app.tools.notifications import NOTIFICATION_TOOLS
from app.tools.diagnostics import DIAGNOSTICS_TOOLS
from app.tools.interests import INTEREST_TOOLS
from app.tools.scratchpad import SCRATCHPAD_TOOLS
from app.tools.day_type import DAY_TYPE_TOOLS
from app.tools.quiet import QUIET_TOOLS
from app.tools.directives import DIRECTIVE_TOOLS
from app.tools.notification_ack import NOTIFICATION_ACK_TOOLS
from app.tools.shell import SHELL_TOOLS
from app.tools.recipes import RECIPE_TOOLS
from app.tools.people import ListPeopleTool
from app.tools.goals import ManageGoalTool
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
            'description': 'Create, edit, search, list, and delete notes and folders in the knowledge garden',
            'tools': [
                'notes_create',
                'notes_search',
                'notes_edit',
                'notes_delete',
                'notes_list',
                'notes_list_folders',
                'notes_create_folder',
                'find_similar_notes',
                'merge_notes',
            ]
        },
        'time': {
            'description': 'Manage reminders, timers, calendar events, and daily tasks',
            'tools': [
                'reminders_create',
                'reminders_list',
                'reminders_cancel',
                'daily_task_create',
                'daily_task_list',
                'daily_task_complete',
                'timers_start',
                'timers_status',
                'timers_cancel',
                'calendar_list',
                'calendar_create',
                'calendar_set_recurring',
                'meeting_prep'
            ]
        },
        'lists': {
            'description': 'Personal lists — grocery, packing, gift ideas, etc.',
            'tools': [
                'list_add',
                'list_view',
                'list_check',
                'list_remove'
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
                'training_schedule',
                'workout_suggest',
                'start_workout', 'end_workout', 'workout_mode_log', 'workout_history',
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
            'description': 'Manage learning topics, sources, study notes, autonomous research, personalized learning paths, tangent capture, known domains, and analogy anchors',
            'tools': [
                'learning_topic_create', 'learning_topic_list', 'learning_topic_update',
                'learning_source_add', 'learning_source_list', 'learning_fetch_source',
                'learning_scratchpad_read', 'learning_scratchpad_update',
                'learning_research', 'learning_analyze_gaps',
                'learning_path', 'learning_next_session',
                'learning_tangent_capture', 'learning_tangent_list',
                'learning_known_domains', 'learning_find_anchors'
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
            'description': 'Inspect background worker agents and tasks, hand off multi-day work to the autonomous daemon, and create/check structured research plans',
            'tools': [
                'get_background_tasks',
                'queue_for_sara',
                'create_research_plan', 'research_plan_status',
            ]
        },
        'fleet': {
            'description': "Check the health of David's machines (his fleet) and run read-only diagnostics on any agent-equipped box — CPU/memory/disk/temp, open alerts, and safe commands like df/journalctl/top",
            'tools': [
                'fleet_status',
                'fleet_diag',
            ]
        },
        'health': {
            'description': 'Access health metrics, trends, insights, and alerts from HealthKit data',
            'tools': [
                'health_status', 'health_trend'
            ]
        },
        'authoring': {
            'description': 'Generate real downloadable Word/PDF files from markdown, and read artifacts to revise them. Only on explicit request.',
            'tools': ['document_generate', 'artifact_read']
        },
        'surfaces': {
            'description': 'Build ephemeral interactive UI — live checklists, recipe cook-mode with steps/timers, file-pickup windows, quick forms. Only on explicit request.',
            'tools': ['surface_create', 'surface_update', 'surface_teardown', 'workspace_job_run']
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
            'description': 'Control connected desktop agents - send notifications, open URLs, show notes, take screenshots, open workspace, write clipboard, focus windows, and type into named windows on user devices. The clipboard/focus/typing tools only run when the user explicitly asks for them.',
            'tools': [
                'device_list', 'device_send_notification', 'device_open_url',
                'device_show_note', 'device_take_screenshot', 'device_open_workspace',
                'device_write_clipboard', 'device_focus_window', 'device_type_into_window',
                'device_open_overlay', 'device_record_voice_note',
            ]
        },
        'workspace': {
            'description': 'Control the workbench-canvas workspace - open windows, arrange layout, manage notes in the infinite canvas. Use workspace_list_windows to see what windows are open before focusing or closing.',
            'tools': [
                'workspace_list_windows', 'workspace_open_window', 'workspace_open_note',
                'workspace_close_window', 'workspace_save_state', 'workspace_arrange',
                'workspace_focus_window', 'workspace_find_and_open', 'workspace_open_from_last_results'
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
        },
        'email': {
            'description': 'Search, read, and get summaries of emails from synced mailboxes',
            'tools': ['email_search', 'email_read', 'email_recent', 'email_attachment_read']
        },
        'soul': {
            'description': "View and propose changes to Sara's core identity, operating principles, boundaries, and growth areas. The Soul is Sara's persistent self-definition.",
            'tools': [
                'view_soul', 'propose_soul_change', 'list_soul_proposals'
            ]
        },
        'heartbeat': {
            'description': "View Sara's heartbeat checklist — active monitors and the HEARTBEAT.md natural language rules file.",
            'tools': [
                'list_heartbeat_items', 'read_heartbeat_file'
            ]
        },
        'behavior': {
            'description': "Route behavior intents to the appropriate system (Soul, Skills, Automation, or Heartbeat) using intelligent classification. Also view unified behavioral configuration.",
            'tools': ['route_behavior', 'show_behavior_config']
        },
        'personal_knowledge': {
            'description': "Query and store personal knowledge about David — preferences, routines, goals, interests, health, relationships, and places.",
            'tools': ['query_david_knowledge', 'remember_about_david']
        },
        'standing_orders': {
            'description': "Manage standing orders — pre-authorized autonomous actions Sara can execute without asking. Also view/undo recent autonomous actions.",
            'tools': [
                'standing_order_list', 'standing_order_create',
                'standing_order_modify', 'action_ledger_recent', 'action_undo'
            ]
        },
        'inbox': {
            'description': "Search and read items from David's content inbox — saved URLs, Reddit posts, PDFs, articles, and text snippets.",
            'tools': ['inbox_search', 'inbox_read']
        },
        'notifications': {
            'description': "Read the notifications Sara has sent David, acknowledge his replies, and CLEAR inbox items he addresses (attention items, clarifications, captures, notifications). Use when David asks \"what's the notification?\"/\"did I miss anything?\", opens his inbox, or responds to items ('saw your messages', 'yes to the first two, skip the gym thing', 'handle these').",
            'tools': ['get_recent_notifications', 'acknowledge_notifications', 'clear_inbox_items']
        },
        'diagnostics': {
            'description': "Read-only self-diagnostics — Sara's own health. Failing background tasks, error events, an explanation of any single event, and a handoff report for Claude Code. Use when David asks \"what's broken?\", \"are you okay?\", \"why did that fail?\", or \"is anything failing?\"",
            'tools': [
                'diagnostics_overview', 'diagnostics_failures', 'diagnostics_events',
                'diagnostics_explain', 'diagnostics_report',
            ]
        },
        'interests': {
            'description': "Record David's reaction to a topic Sara keeps surfacing. Use when he pushes back — \"stop bringing up X\", \"I don't care about Y\", \"quit updating me on Z\". Two strikes auto-mutes the interest (reversible).",
            'tools': ['react_to_interest']
        },
        'scratchpad': {
            'description': "Pin standing context David wants kept front-of-mind for a while — meal-prep status, recurring plans, temporary schedule changes ('smoothie every morning', 'meal prepped this week', 'off Thursday'). Read/clear it too.",
            'tools': ['scratchpad_write', 'scratchpad_read', 'scratchpad_clear']
        },
        'day_type': {
            'description': "Mark today (or a date) as a rest or training day, flipping the nutrition targets. Use when David skips or adds a workout, or asks to switch to a rest day.",
            'tools': ['set_day_type']
        },
        'quiet_mode': {
            'description': "Turn quiet/guest mode on or off — suspends Sara's proactive outreach and autonomous home actions. Use for 'be quiet', 'do not disturb', 'guests over'.",
            'tools': ['set_quiet_mode']
        },
        'directives': {
            'description': "Standing rules David gives Sara ('never bring up X', 'always use ET', 'don't ping me before 9'). Save/list/remove. Propose saving a directive whenever David corrects a recurring behavior.",
            'tools': ['save_directive', 'list_directives', 'remove_directive']
        },
        'vm_agents': {
            'description': "Dispatch background tasks (research, code, setup) to agents, check status, resume sessions, and propose candidate skills. Use dispatch_and_monitor for tasks where David should be notified on completion.",
            'tools': [
                'dispatch_agent_task', 'dispatch_and_monitor',
                'get_agent_status', 'resume_agent_session',
                'submit_candidate_skill', 'cancel_agent_task',
            ]
        },
        'shell': {
            'description': 'Execute shell commands, read and write files on the server. Use for code execution, scripting, system administration, file manipulation.',
            'tools': ['run_command', 'read_file', 'write_file']
        },
        'recipes': {
            'description': "Create, search, edit, and log David's recipes — structured ingredients, steps, servings, prep/cook time, macros. Use these instead of notes for any cooking recipe.",
            'tools': [
                'recipes_create', 'recipes_search', 'recipes_get',
                'recipes_list', 'recipes_edit', 'recipes_delete',
                'recipes_log_made'
            ]
        },
        'location': {
            'description': "Save named places (home, work, gym, client sites) and set location-triggered reminders that fire when David arrives at or leaves a place — 'remind me to X when I get home/leave here'.",
            'tools': [
                'places_save', 'places_list', 'places_delete',
                'location_reminder_create', 'location_reminder_list', 'location_reminder_cancel',
            ]
        },
        'people': {
            'description': "Answer questions about who David has been interacting with — who he's overdue to reconnect with, who's new, recent contacts — from the real person table (built from email + chat mentions).",
            'tools': ['list_people']
        },
        'goals': {
            'description': "Create, advance, or complete a persistent goal that survives across days (not just this conversation) — 'let's make X a goal', tracking progress, marking a goal done.",
            'tools': ['manage_goal']
        },
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
            NotesFindSimilarTool(),
            NotesMergeTool(),
            NotesListFoldersTool(),
            NotesCreateFolderTool(),
            
            # Reminders
            RemindersCreateTool(),
            RemindersListTool(),
            RemindersCancelTool(),

            # Location — location-triggered reminders + saved places
            LocationReminderCreateTool(),
            LocationReminderListTool(),
            LocationReminderCancelTool(),
            PlacesSaveTool(),
            PlacesListTool(),
            PlacesDeleteTool(),

            # Daily Tasks
            DailyTaskCreateTool(),
            DailyTaskListTool(),
            DailyTaskCompleteTool(),
            
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

            # Training Schedule (swap days, toggle dates)
            TrainingScheduleTool(),

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
            LearningTangentCaptureTool(),
            LearningTangentListTool(),
            LearningKnownDomainsTool(),
            LearningFindAnchorsTool(),

            # Morning Brief & Weather Tools
            MorningBriefTool(),
            WeatherTool(),

            # Project Tracker Tools
            *PROJECT_TOOLS,

            # Home Control Tools
            *HOME_TOOLS,

            # Agent Handoff Tools
            GetBackgroundTasksTool(),

            # Health Monitoring Tools
            *HEALTH_TOOLS,

            # Canvas Control Tools
            CanvasOpenTool(),
            CanvasUpdateTool(),
            CanvasCloseTool(),
            CanvasOpenNoteTool(),
            CanvasSaveAsNoteTool(),

            # Authoring Tools (Sara-built downloadable Word/PDF files)
            *AUTHORING_TOOLS,

            # Surface Tools (ephemeral interactive UI — checklists, cook-mode)
            *SURFACE_TOOLS,

            # Workspace Job Tools (bounded pipelines → file_list surfaces)
            *WORKSPACE_JOB_TOOLS,

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

            # Email Tools
            *EMAIL_TOOLS,

            # Soul Tools (Sara's identity and self-modification)
            *SOUL_TOOLS,

            # Heartbeat Tools (dynamic monitoring checklist)
            *HEARTBEAT_TOOLS,

            # Behavior Router Tools (intelligent routing to appropriate system)
            *BEHAVIOR_ROUTER_TOOLS,

            # Personal Knowledge Graph Tools (query/remember about David)
            *PKG_TOOLS,

            # Standing Order Tools (pre-authorized autonomous actions)
            *STANDING_ORDER_TOOLS,

            # Content Inbox Tools (search/read saved content)
            *CONTENT_INBOX_TOOLS,

            # VM Agent Dispatch Tools (sandbox VM agent orchestration)
            *AGENT_DISPATCH_TOOLS,

            # Shell Tools (local command execution, file I/O)
            *SHELL_TOOLS,

            # Hand-off to the autonomous mind (ACS daemon inbox → goals)
            QueueForSaraTool(),

            # Notification history ("what's the notification?" / badge explainer)
            *NOTIFICATION_TOOLS,

            # Read-only self-diagnostics ("Sara, what's wrong?")
            *DIAGNOSTICS_TOOLS,

            # Interest feedback — "stop bringing up X" -> two-strikes auto-mute
            *INTEREST_TOOLS,

            # Standing-context scratchpad — David pins things Sara keeps front-of-mind
            *SCRATCHPAD_TOOLS,

            # Situational: flip a day to rest/training (nutrition targets follow)
            *DAY_TYPE_TOOLS,

            # Quiet / guest mode kill switch
            *QUIET_TOOLS,

            # Directives — David's standing rules with permanent teeth
            *DIRECTIVE_TOOLS,

            # Acknowledge notifications David is replying to in chat (Phase 12K)
            *NOTIFICATION_ACK_TOOLS,

            # Research Plan Tools (delegate research to dedicated agent)
            CreateResearchPlanTool(),
            ResearchPlanStatusTool(),

            # Meeting prep ("who am I meeting with / prep me for my 2pm")
            MeetingPrepTool(),

            # Personal lists (grocery by default) — plain DB, not Home Assistant
            *LIST_TOOLS,

            # Recipe Tools (structured cooking recipes — not notes)
            *RECIPE_TOOLS,

            # People ("who am I overdue with?") — person table, Phase 2
            ListPeopleTool(),

            # Goals ("let's make X a goal") — sara_goal, Phase 3
            ManageGoalTool(),

            # Fleet ("how's the fleet", "why is the sara VM's disk full") — read-only
            FleetStatusTool(),
            FleetDiagTool(),
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

    def get_tools_by_names(self, names: List[str]) -> List[Dict[str, Any]]:
        """Get OpenAI function calling schemas for explicitly named tools —
        for callers that need surgical, individual-tool granularity rather
        than whole categories (SARA_ALIVE_BUILD_PLAN Arc 3.4: the presence
        tool payload diet picks specific tools like `calendar_list`, not
        the 13-tool `time` category that contains it)."""
        schemas = []
        for tool_name in names:
            tool = self.tools.get(tool_name)
            if not tool:
                logger.warning(f"Tool '{tool_name}' not found in registry")
                continue
            schema = tool.to_openai_schema()
            params = schema.get('function', {}).get('parameters', {})
            if 'required' in params and len(params['required']) == 0:
                del params['required']
            schemas.append(schema)
        return schemas

    def _context_kwargs_for(self, name: str, tool: BaseTool):
        """Which injected context kwargs this tool's execute() can accept.

        Returns "**" if execute() takes **kwargs (accepts anything), else the
        set of explicitly declared parameter names. Cached per tool name.
        """
        cache = getattr(self, "_ctx_kwargs_cache", None)
        if cache is None:
            cache = self._ctx_kwargs_cache = {}
        if name not in cache:
            import inspect
            try:
                sig = inspect.signature(tool.execute)
                if any(p.kind == inspect.Parameter.VAR_KEYWORD
                       for p in sig.parameters.values()):
                    cache[name] = "**"
                else:
                    cache[name] = set(sig.parameters.keys())
            except (TypeError, ValueError):
                cache[name] = "**"  # can't introspect — preserve old behavior
        return cache[name]

    async def execute_tool(
        self, name: str, user_id: str, parameters: Dict[str, Any],
        context: Dict[str, Any] = None,
    ) -> ToolResult:
        """Execute a tool by name.

        Args:
            context: Optional execution context (e.g. {"task_id": "..."} for shell tools).
        """
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

        # Origin gate: actuators that require a user-originated chat turn cannot
        # be invoked by the autonomous loop. Default origin is "chat" because the
        # tool_registry is currently only reached from the chat dispatch site; any
        # future caller (e.g. ACS daemon) must pass an explicit origin.
        origin = (context or {}).get("origin", "chat")
        if getattr(tool, "requires_user_origin", False) and origin != "chat":
            logger.warning(
                f"Refusing tool '{name}' from origin '{origin}' "
                f"(requires user-originated chat turn)"
            )
            return ToolResult(
                success=False,
                message=(
                    f"Tool '{name}' can only be invoked from a user chat turn, "
                    f"not from origin '{origin}'."
                ),
            )

        # Inject context into parameters for tools that need it (e.g. shell tools).
        # Surface/workspace tools scope their rows to the conversation so the
        # client can re-inject them when the chat reloads. Only tools whose
        # execute() declares the kwarg (or takes **kwargs) receive it — most
        # tools have rigid signatures and would raise TypeError otherwise.
        if context:
            injectable = {}
            if context.get("task_id"):
                injectable["_task_id"] = context["task_id"]
            if context.get("conversation_id"):
                injectable["_conversation_id"] = context["conversation_id"]
            if injectable:
                accepted = self._context_kwargs_for(name, tool)
                extras = {k: v for k, v in injectable.items()
                          if accepted == "**" or k in accepted}
                if extras:
                    parameters = {**parameters, **extras}

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
