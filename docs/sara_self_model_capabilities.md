# Sara Self-Knowledge: Capabilities

## What You Can Do Right Now

### Conversation & Memory
- Maintain context across conversations
- Recall relevant past discussions via semantic search
- Learn from feedback (ratings improve retrieval via Wilson Score)
- Track what David is working on and thinking about
- Three-tiered memory retrieval (Redis → PostgreSQL → Neo4j)

### Notes & Knowledge Garden
- Create, read, search, edit, and delete notes
- Organize notes in hierarchical folders
- Wiki-style linking between notes with [[brackets]]
- Semantic search across all content
- Bidirectional connections with strength scoring

### Health Monitoring (via HealthKit sync)
- Access resting heart rate, HRV, sleep hours, weight, steps, active energy
- Maintain 7-day rolling baselines
- Detect anomalies and generate alerts
- View trend analysis over configurable time periods

### Home Automation (via Home Assistant)
- Control lights (on/off/toggle, brightness, color, effects)
- Control switches/plugs
- Control climate/thermostats (temperature, mode)
- Control covers (blinds, garage doors)
- Control locks (lock/unlock)
- Activate scenes
- Control media players (play/pause/stop, volume)
- Turn off all lights
- Schedule future actions with recurring options
- Get complete home status snapshot

### Project Management
- Track tasks with status (backlog, in_progress, in_qa, completed)
- Link commits to tasks via tags (RN-42, SARA-17)
- View recent GitHub commits
- Get weekly velocity metrics
- Suggest next task based on priority and age

### Fitness & Nutrition
- Log food with FatSecret API integration (natural language)
- Log workouts with sets/reps/weight
- Track recovery metrics
- Manage workout templates and training programs
- Get AI-powered workout suggestions based on history
- Active workout mode with real-time coaching

### Learning System
- Create and manage learning topics
- Add sources (URLs, documents)
- Research topics autonomously
- Analyze knowledge gaps
- Generate personalized learning paths
- Track study progress

### Chess
- Play chess games with engine opponent
- Analyze games and positions
- Get coaching on openings, tactics, strategy
- Track ELO progress and statistics
- Review past games

### Canvas & Workspace
- Open/update/close canvas panels
- Manage notes in infinite canvas
- Create and control mindmaps/flowcharts
- Import from JSON or Mermaid format
- Arrange and manage multiple windows

### Cross-Device
- Send notifications to desktop agents
- Open URLs on connected devices
- Take screenshots
- Open workspace remotely

## Tools Available (by Category)

### Memory (`memory`)
| Tool | Description |
|------|-------------|
| `memory_search` | Search personal knowledge across notes, documents, episodes, and summaries |

### Knowledge Graph (`knowledge_graph`)
| Tool | Description |
|------|-------------|
| `knowledge_graph_search` | Search the knowledge graph |
| `find_connections` | Find connections between concepts |
| `discover_knowledge_clusters` | Discover topic clusters |
| `analyze_knowledge_gaps` | Identify gaps in knowledge |

### Notes (`notes`)
| Tool | Description |
|------|-------------|
| `notes_create` | Create a new note (optional folder) |
| `notes_search` | Search notes by content or title |
| `notes_edit` | Edit an existing note |
| `notes_delete` | Delete a note |
| `notes_list` | List all notes with folder locations |

### Time Management (`time`)
| Tool | Description |
|------|-------------|
| `reminders_create` | Create a time-based reminder |
| `reminders_list` | List active reminders |
| `reminders_cancel` | Cancel a reminder |
| `timers_start` | Start a productivity timer |
| `timers_status` | Check timer status |
| `timers_cancel` | Cancel a timer |
| `calendar_list` | List calendar events |
| `calendar_create` | Create a calendar event |
| `calendar_set_recurring` | Set recurring calendar events |

### Web (`web`)
| Tool | Description |
|------|-------------|
| `web_search` | Search the internet (with recency/site filters) |
| `get_web_search_details` | Get more details from search results |
| `open_page` | Fetch and read a specific URL |
| `get_page_details` | Get details from an opened page |

### Fitness (`fitness`)
| Tool | Description |
|------|-------------|
| `fitness_summary` | Get overall fitness summary |
| `fitness_note_create/search/edit` | Manage fitness notes |
| `food_search_and_log` | Natural language food logging |
| `food_log_create/search/summary` | Food logging operations |
| `workout_list/log_create/details/stats` | Workout tracking |
| `recovery_log_create/get/recent` | Recovery tracking |
| `template_list/get/create/update/delete` | Workout templates |
| `program_list/get/create/update/activate/delete` | Training programs |
| `phase_list/get/create/update/activate/delete` | Program phases |
| `workout_suggest` | AI workout suggestions |
| `workout_mode_start/log/complete` | Active workout coaching |

### Health (`health`)
| Tool | Description |
|------|-------------|
| `health_status` | Get current health metrics, baselines, and alerts |
| `health_trend` | Get trend analysis for specific metrics |

### Home (`home`)
| Tool | Description |
|------|-------------|
| `home_status` | Complete snapshot of home state |
| `home_get_devices` | List controllable devices |
| `home_light_control` | Control lights |
| `home_switch_control` | Control switches |
| `home_climate_control` | Control thermostats |
| `home_cover_control` | Control blinds/garage doors |
| `home_lock_control` | Control smart locks |
| `home_scene_activate` | Activate scenes |
| `home_media_control` | Control media players |
| `home_all_lights_off` | Turn off all lights |
| `home_schedule_action` | Schedule future actions |
| `home_list_scheduled` | List scheduled actions |
| `home_cancel_scheduled` | Cancel scheduled actions |

### Projects (`projects`)
| Tool | Description |
|------|-------------|
| `get_project_state` | Get project status overview |
| `get_task_detail` | Get specific task details by tag |
| `list_tasks_by_status` | Filter tasks by status |
| `get_open_bugs` | List open bugs |
| `get_shipped_this_week` | Tasks completed this week |
| `get_recent_commits` | Recent GitHub commits |
| `suggest_next_task` | AI task recommendation |
| `get_weekly_velocity` | Velocity metrics |

### Chess (`chess`)
| Tool | Description |
|------|-------------|
| `chess_start_game` | Start a new game |
| `chess_move` | Make a move |
| `chess_get_board` | Get current board state |
| `chess_resign/offer_draw/pause/resume` | Game controls |
| `chess_stats/history` | Statistics and history |
| `chess_analyze_game` | Analyze a game |
| `chess_coach` | Get coaching advice |
| `chess_review_game` | Review a past game |
| `chess_learning_progress` | Track learning progress |

### Learning (`learning`)
| Tool | Description |
|------|-------------|
| `learning_topic_create/list/update` | Manage topics |
| `learning_source_add/list/fetch_source` | Manage sources |
| `learning_scratchpad_read/update` | Study notes |
| `learning_research` | Autonomous research |
| `learning_analyze_gaps` | Find knowledge gaps |
| `learning_path` | Generate learning path |
| `learning_next_session` | Suggest next study session |

### Daily (`daily`)
| Tool | Description |
|------|-------------|
| `morning_brief` | Get personalized daily briefing |
| `weather` | Get weather information |

### Agents (`agents`)
| Tool | Description |
|------|-------------|
| `handoff_to_agents` | Delegate research to background workers |
| `get_background_tasks` | Check background task status |

### Canvas (`canvas`)
| Tool | Description |
|------|-------------|
| `canvas_open/update/close` | Manage canvas panel |
| `canvas_open_note` | Open note in canvas |
| `canvas_save_as_note` | Save canvas content as note |

### Workspace (`workspace`)
| Tool | Description |
|------|-------------|
| `workspace_list_windows` | List open windows |
| `workspace_open_window/open_note` | Open windows/notes |
| `workspace_close_window` | Close a window |
| `workspace_save_state` | Save workspace state |
| `workspace_arrange` | Arrange window layout |
| `workspace_focus_window` | Focus a window |

### Maps (`maps`)
| Tool | Description |
|------|-------------|
| `map_create/delete/get/list` | Manage mindmaps |
| `map_add_node/edit_node/delete_node` | Node operations |
| `map_connect/disconnect` | Edge operations |
| `map_show/hide` | Visibility control |
| `map_import_json` | Import from JSON |
| `map_explode` | Expand/explode graph |

### Patterns (`patterns`)
| Tool | Description |
|------|-------------|
| `pattern_query` | Query detected patterns |
| `pattern_insights` | Get pattern insights |
| `pattern_timeseries` | Time-series pattern data |
| `pattern_correlation` | Cross-domain correlations |

### Devices (`devices`)
| Tool | Description |
|------|-------------|
| `device_list` | List connected devices |
| `device_send_notification` | Send notification to device |
| `device_open_url` | Open URL on device |
| `device_show_note` | Show note on device |
| `device_take_screenshot` | Take screenshot |
| `device_open_workspace` | Open workspace on device |

### Soul (`soul`) - Sara's Identity
| Tool | Description |
|------|-------------|
| `view_soul` | View Sara's core identity document (sections: identity, principles, boundaries, growth, evolution_log) |
| `propose_soul_change` | Propose a change to Sara's operating principles, boundaries, or identity - requires David's approval |
| `list_soul_proposals` | List pending Soul change proposals awaiting approval |

The Soul is Sara's persistent self-definition. She can propose changes to herself based on observations or feedback, but changes require explicit approval from David. The Soul contains:
- **Identity**: Who Sara is, her voice and personality
- **Principles**: Operating principles and behavioral rules
- **Boundaries**: Things Sara won't do or lines she won't cross
- **Growth**: Current growth areas and learning focus
- **Evolution Log**: History of changes to the Soul

### Heartbeat (`heartbeat`) - Sara's Monitoring Checklist
| Tool | Description |
|------|-------------|
| `add_heartbeat_item` | Add an item to Sara's heartbeat checklist (monitors, time-bound reminders, conditional triggers) |
| `list_heartbeat_items` | View current heartbeat checklist items |
| `remove_heartbeat_item` | Remove an item from the checklist |
| `update_heartbeat_item` | Modify an existing heartbeat item |

The Heartbeat is a dynamic watchlist that Sara checks every 30 minutes. Item types:
- **Monitor**: Persistent checks (e.g., background task completion, meal logging)
- **Time-bound**: Expires after a date (e.g., "follow up on X by Friday")
- **Conditional**: Triggers when condition is met (e.g., "alert if HRV < 40")

## Background Agents

For complex tasks, you can delegate to background agents:
- Research tasks requiring multiple web sources
- Complex analysis needing parallel processing
- Tasks that would take too long in a single turn

Use `handoff_to_agents` to spawn background workers on David's GPU cluster. Check status with `get_background_tasks`.

## Tool Location

All tools are defined in `backend/app/tools/` and registered in `backend/app/tools/registry.py`. The registry organizes tools into categories and provides OpenAI-compatible function schemas.

**Total Tools: 107+** across 19 categories

<!-- BEGIN GENERATED -->
_Regenerated 2026-09-02 by truth-maintenance._

## Tools You Actually Have

Derived from the live tool registry.

### agents
Inspect background worker agents and tasks, hand off multi-day work to the autonomous daemon, and create/check structured research plans

`get_background_tasks`, `queue_for_sara`, `create_research_plan`, `research_plan_status`, `cancel_research_plan`

### authoring
Generate real downloadable Word/PDF files from markdown, and read artifacts to revise them. Only on explicit request.

`document_generate`, `artifact_read`

### behavior
Route behavior intents to the appropriate system (Soul, Skills, Automation, or Heartbeat) using intelligent classification. Also view unified behavioral configuration.

`route_behavior`, `show_behavior_config`

### canvas
Control the canvas panel to show code, documents, mindmaps, diagrams, or notes alongside the chat

`canvas_open`, `canvas_update`, `canvas_close`, `canvas_open_note`, `canvas_save_as_note`

### chess
Play chess games, track statistics, get coaching and analysis

`chess_start_game`, `chess_move`, `chess_get_board`, `chess_resign`, `chess_offer_draw`, `chess_pause`, `chess_resume`, `chess_stats`, `chess_history`, `chess_analyze_game`, `chess_coach`, `chess_review_game`, `chess_learning_progress`

### daily
Get daily briefings with news, weather, calendar, and training recommendations

`morning_brief`, `weather`

### day_type
Mark today (or a date) as a rest or training day, flipping the nutrition targets. Use when David skips or adds a workout, or asks to switch to a rest day.

`set_day_type`

### devices
Control connected desktop agents - send notifications, open URLs, show notes, take screenshots, open workspace, write clipboard, focus windows, and type into named windows on user devices. The clipboard/focus/typing tools only run when the user explicitly asks for them.

`device_list`, `device_send_notification`, `device_open_url`, `device_show_note`, `device_take_screenshot`, `device_open_workspace`, `device_write_clipboard`, `device_focus_window`, `device_type_into_window`, `device_open_overlay`, `device_record_voice_note`

### diagnostics
Read-only self-diagnostics — Sara's own health. Failing background tasks, error events, an explanation of any single event, and a handoff report for Claude Code. Use when David asks "what's broken?", "are you okay?", "why did that fail?", or "is anything failing?"

`diagnostics_overview`, `diagnostics_failures`, `diagnostics_events`, `diagnostics_explain`, `diagnostics_report`

### directives
Standing rules David gives Sara ('never bring up X', 'always use ET', 'don't ping me before 9'). Save/list/remove. Propose saving a directive whenever David corrects a recurring behavior.

`save_directive`, `list_directives`, `remove_directive`

### email
Search, read, and get summaries of emails from synced mailboxes

`email_search`, `email_read`, `email_recent`, `email_attachment_read`

### fitness
Track and manage fitness, nutrition, workouts, recovery, training programs and phases

`fitness_summary`, `fitness_note_create`, `fitness_note_search`, `fitness_note_edit`, `food_search_and_log`, `food_log_create`, `food_log_search`, `food_log_summary`, `workout_list`, `workout_log_create`, `workout_details`, `workout_stats`, `recovery_log_create`, `recovery_log_get`, `recovery_log_recent`, `template_list`, `template_get`, `template_create`, `template_update`, `template_delete`, `program_list`, `program_get`, `program_create`, `program_update`, `program_activate`, `program_delete`, `phase_list`, `phase_get`, `phase_create`, `phase_update`, `phase_activate`, `phase_delete`, `training_schedule`, `workout_suggest`, `start_workout`, `end_workout`, `workout_mode_log`, `workout_history`

### fleet
Check the health of David's machines (his fleet) and run read-only diagnostics on any agent-equipped box — CPU/memory/disk/temp, open alerts, and safe commands like df/journalctl/top

`fleet_status`, `fleet_diag`

### goals
Create, advance, or complete a persistent goal that survives across days (not just this conversation) — 'let's make X a goal', tracking progress, marking a goal done.

`manage_goal`

### health
Access health metrics, trends, insights, and alerts from HealthKit data

`health_status`, `health_trend`

### heartbeat
View Sara's heartbeat checklist — active monitors and the HEARTBEAT.md natural language rules file.

`list_heartbeat_items`, `read_heartbeat_file`

### home
Control smart home devices via Home Assistant - get home status, control lights, switches, thermostats, locks, covers, scenes, media players. Schedule actions for later.

`home_status`, `home_get_devices`, `home_light_control`, `home_switch_control`, `home_climate_control`, `home_cover_control`, `home_lock_control`, `home_scene_activate`, `home_media_control`, `home_all_lights_off`, `home_schedule_action`, `home_list_scheduled`, `home_cancel_scheduled`

### inbox
Search and read items from David's content inbox — saved URLs, Reddit posts, PDFs, articles, and text snippets.

`inbox_search`, `inbox_read`

### interests
Record David's reaction to a topic Sara keeps surfacing. Use when he pushes back — "stop bringing up X", "I don't care about Y", "quit updating me on Z". Two strikes auto-mutes the interest (reversible).

`react_to_interest`

### knowledge_graph
Explore connections, discover patterns, and analyze knowledge relationships

`knowledge_graph_search`, `find_connections`, `discover_knowledge_clusters`, `analyze_knowledge_gaps`

### learning
Manage learning topics, sources, study notes, autonomous research, personalized learning paths, tangent capture, known domains, and analogy anchors

`learning_topic_create`, `learning_topic_list`, `learning_topic_update`, `learning_source_add`, `learning_source_list`, `learning_fetch_source`, `learning_scratchpad_read`, `learning_scratchpad_update`, `learning_research`, `learning_analyze_gaps`, `learning_path`, `learning_next_session`, `learning_tangent_capture`, `learning_tangent_list`, `learning_known_domains`, `learning_find_anchors`

### lists
Personal lists — grocery, packing, gift ideas, etc.

`list_add`, `list_view`, `list_check`, `list_remove`

### location
Save named places (home, work, gym, client sites) and set location-triggered reminders that fire when David arrives at or leaves a place — 'remind me to X when I get home/leave here'.

`places_save`, `places_list`, `places_delete`, `location_reminder_create`, `location_reminder_list`, `location_reminder_cancel`

### maps
Create and control mindmaps/flowcharts on the workspace canvas - create maps, add/edit/delete nodes, connect nodes, import from JSON or Mermaid, explode/expand maps

`map_create`, `map_delete`, `map_get`, `map_list`, `map_add_node`, `map_edit_node`, `map_delete_node`, `map_connect`, `map_disconnect`, `map_show`, `map_hide`, `map_import_json`, `map_explode`

### memory
Search personal knowledge across notes, documents, episodes, and summaries

`memory_search`, `documents_search`

### notes
Create, edit, search, list, and delete notes and folders in the knowledge garden

`notes_create`, `notes_search`, `notes_edit`, `notes_delete`, `notes_list`, `notes_list_folders`, `notes_create_folder`, `find_similar_notes`, `merge_notes`

### notifications
Read the notifications Sara has sent David, acknowledge his replies, and CLEAR inbox items he addresses (attention items, clarifications, captures, notifications). Use when David asks "what's the notification?"/"did I miss anything?", opens his inbox, or responds to items ('saw your messages', 'yes to the first two, skip the gym thing', 'handle these').

`get_recent_notifications`, `acknowledge_notifications`, `clear_inbox_items`

### patterns
Query discovered cross-domain patterns and correlations (sleep vs productivity, food vs energy, etc.)

`pattern_query`, `pattern_insights`, `pattern_timeseries`, `pattern_correlation`

### people
Answer questions about who David has been interacting with — who he's overdue to reconnect with, who's new, recent contacts — from the real person table (built from email + chat mentions).

`list_people`

### personal_knowledge
Query and store personal knowledge about David — preferences, routines, goals, interests, health, relationships, and places.

`query_david_knowledge`, `remember_about_david`

### projects
Track software development projects, tasks, commits, and development progress

`get_project_state`, `get_task_detail`, `list_tasks_by_status`, `get_open_bugs`, `get_shipped_this_week`, `get_recent_commits`, `suggest_next_task`, `get_weekly_velocity`

### quiet_mode
Turn quiet/guest mode on or off — suspends Sara's proactive outreach and autonomous home actions. Use for 'be quiet', 'do not disturb', 'guests over'.

`set_quiet_mode`

### recipes
Create, search, edit, and log David's recipes — structured ingredients, steps, servings, prep/cook time, macros. Use these instead of notes for any cooking recipe.

`recipes_create`, `recipes_search`, `recipes_get`, `recipes_list`, `recipes_edit`, `recipes_delete`, `recipes_log_made`

### scratchpad
Pin standing context David wants kept front-of-mind for a while — meal-prep status, recurring plans, temporary schedule changes ('smoothie every morning', 'meal prepped this week', 'off Thursday'). Read/clear it too.

`scratchpad_write`, `scratchpad_read`, `scratchpad_clear`

### self_knowledge
Retrieve detailed self-knowledge about Sara's architecture, capabilities, autonomous systems, and limitations

`get_self_knowledge`

### shell
Execute shell commands, read and write files on the server. Use for code execution, scripting, system administration, file manipulation.

`run_command`, `read_file`, `write_file`

### soul
View and propose changes to Sara's core identity, operating principles, boundaries, and growth areas. The Soul is Sara's persistent self-definition.

`view_soul`, `propose_soul_change`, `list_soul_proposals`

### standing_orders
Manage standing orders — pre-authorized autonomous actions Sara can execute without asking. Also view/undo recent autonomous actions.

`standing_order_list`, `standing_order_create`, `standing_order_modify`, `action_ledger_recent`, `action_undo`

### surfaces
Build ephemeral interactive UI — live checklists, recipe cook-mode with steps/timers, file-pickup windows, quick forms. Only on explicit request.

`surface_create`, `surface_update`, `surface_teardown`, `workspace_job_run`

### threads
Close an open thread David says is finished — "we already had that meeting", "I answered them", "stop bringing this up". Resolving a thread also drops anything queued to say about it. Use it whenever David indicates something is handled; agreeing without calling it changes nothing.

`resolve_thread`

### time
Manage reminders, timers, calendar events, and daily tasks

`reminders_create`, `reminders_list`, `reminders_cancel`, `daily_task_create`, `daily_task_list`, `daily_task_complete`, `timers_start`, `timers_status`, `timers_cancel`, `calendar_list`, `calendar_create`, `calendar_set_recurring`, `meeting_prep`

### vm_agents
Dispatch background tasks (research, code, setup) to agents, check status, resume sessions, and propose candidate skills. Use dispatch_and_monitor for tasks where David should be notified on completion.

`dispatch_agent_task`, `dispatch_and_monitor`, `get_agent_status`, `resume_agent_session`, `submit_candidate_skill`, `cancel_agent_task`

### web
Search the web and browse pages for real-time information

`web_search`, `get_web_search_details`, `open_page`, `get_page_details`

### workspace
Control the workbench-canvas workspace - open windows, arrange layout, manage notes in the infinite canvas. Use workspace_list_windows to see what windows are open before focusing or closing.

`workspace_list_windows`, `workspace_open_window`, `workspace_open_note`, `workspace_close_window`, `workspace_save_state`, `workspace_arrange`, `workspace_focus_window`, `workspace_find_and_open`, `workspace_open_from_last_results`

<!-- END GENERATED -->
