"""Which tools change something, and which only look.

The chat turn has a wall-clock deadline (`CHAT_TURN_DEADLINE_S`). When it
expires with tool calls already chosen by the model, the reads can be dropped —
the model can ask again, and nothing is lost but time. A write cannot. On
2026-09-15 Sara offered to log a rough night in the recovery log, David said
yes, and the turn spent two rounds discovering it had not been handed a
recovery tool (`notes_search` → `find_tools`). It then called
`recovery_log_create` at 69.2s, nine seconds past the deadline, and the guard
dropped it along with everything else. Nothing was written, and the reply said
she had "run out of room" — so David had no reason to think the entry was
missing.

Membership rule: a name belongs here if skipping the call loses something —
persisted data, a message that was supposed to go out, or a real-world action.
Pure reads stay out. Transient UI navigation (opening or focusing a window,
showing a map node) stays out too: re-issuing it costs nothing.

Deliberately an explicit list rather than a name heuristic. A regex over
`_create|_add|_log|_update|…` matches 62 of the 255 registered tools but also
catches `recovery_log_get`, `recovery_log_recent`, `food_log_search` and
`food_log_summary`, where "log" is the noun in the store's name and not a verb.

Anything unknown — including every tool added after this list was written —
answers False and keeps the old skip-it behaviour. That is the safe direction
for an unrecognised name: it can cost a re-ask, never a silent double-write.
"""

from typing import Any, Dict, Optional

# Tools whose call must survive the turn deadline.
WRITE_TOOLS = frozenset({
    # Notifications / inbox state
    "acknowledge_notifications",
    "clear_inbox_items",
    "resolve_thread",
    # Undo is itself a mutation
    "action_undo",
    # Calendar
    "calendar_create",
    "calendar_set_recurring",
    # Canvas / surfaces / artifacts
    "canvas_save_as_note",
    "canvas_update",
    "surface_create",
    "surface_teardown",
    "surface_update",
    "document_generate",
    "files_to_studio",
    "workspace_save_state",
    "workspace_job_run",
    # Background work — starting or stopping it is a real action
    "cancel_agent_task",
    "cancel_research_plan",
    "create_research_plan",
    "dispatch_agent_task",
    "dispatch_and_monitor",
    "resume_agent_session",
    "queue_for_sara",
    "submit_candidate_skill",
    # Chess game state
    "chess_move",
    "chess_offer_draw",
    "chess_pause",
    "chess_resign",
    "chess_resume",
    "chess_start_game",
    # Tasks / lists / reminders / timers
    "daily_task_complete",
    "daily_task_create",
    "list_add",
    "list_remove",
    "location_reminder_cancel",
    "location_reminder_create",
    "reminders_cancel",
    "reminders_create",
    "timers_cancel",
    "timers_start",
    "manage_goal",
    "standing_order_create",
    "standing_order_modify",
    # Device actions that leave a trace or reach the outside world
    "device_record_voice_note",
    "device_send_notification",
    "device_show_note",
    "device_type_into_window",
    "device_write_clipboard",
    # Home automation — physical state
    "home_all_lights_off",
    "home_cancel_scheduled",
    "home_climate_control",
    "home_cover_control",
    "home_light_control",
    "home_lock_control",
    "home_media_control",
    "home_scene_activate",
    "home_schedule_action",
    "home_switch_control",
    # Fitness: logs, programs, phases, templates
    "end_workout",
    "fitness_note_create",
    "fitness_note_edit",
    "food_log_create",
    "food_search_and_log",
    "nutrition_guide_update",
    "phase_activate",
    "phase_create",
    "phase_delete",
    "phase_end_block",
    "phase_insert_block",
    "phase_update",
    "program_activate",
    "program_create",
    "program_delete",
    "program_update",
    "recovery_log_create",
    "set_day_type",
    "start_workout",
    "template_create",
    "template_delete",
    "template_update",
    "workout_log_create",
    "workout_mode_log",
    # Notes / knowledge
    "merge_notes",
    "notes_create",
    "notes_create_folder",
    "notes_delete",
    "notes_edit",
    "remember_about_david",
    # Maps
    "map_add_node",
    "map_connect",
    "map_create",
    "map_delete",
    "map_delete_node",
    "map_disconnect",
    "map_edit_node",
    "map_import_json",
    # Learning
    "learning_scratchpad_update",
    "learning_source_add",
    "learning_tangent_capture",
    "learning_topic_create",
    "learning_topic_update",
    # Recipes / places
    "places_delete",
    "places_save",
    "recipes_create",
    "recipes_delete",
    "recipes_edit",
    "recipes_log_made",
    # Sara's own configuration
    "propose_soul_change",
    "react_to_interest",
    "remove_directive",
    "route_behavior",
    "save_directive",
    "scratchpad_clear",
    "scratchpad_write",
    "set_quiet_mode",
    # Filesystem / shell
    "run_command",
    "write_file",
})


def is_write_tool(name: Optional[str]) -> bool:
    """True when dropping a call to `name` would lose data or an action."""
    return bool(name) and name in WRITE_TOOLS


def tool_call_name(tool_call: Dict[str, Any]) -> str:
    """Name out of an OpenAI-shaped tool call, '' when it is malformed."""
    if not isinstance(tool_call, dict):
        return ""
    fn = tool_call.get("function")
    if not isinstance(fn, dict):
        return ""
    return fn.get("name") or ""


def partition_by_effect(tool_calls) -> tuple:
    """Split calls into (writes, reads), each in its original order."""
    writes, reads = [], []
    for tc in tool_calls or []:
        (writes if is_write_tool(tool_call_name(tc)) else reads).append(tc)
    return writes, reads


def tool_success_state(payload: Dict[str, Any]) -> Optional[bool]:
    """Harness/thinking/personality plan, Phase 3: a write's outcome is one
    of three states, not two. `payload.get("success") is not False` (the
    check this replaces, at both call sites in main_simple.py) collapses
    `True` and anything-that-isn't-literally-`False` — including `None`,
    a missing key, or a string like `"unknown"` — into the SAME bucket. A
    tool honestly reporting `{"success": None, "message": "timed out,
    outcome unknown"}` was therefore recorded as a confirmed success, and
    `_last_resort_reply` would tell David "That's saved" on a write nobody
    actually confirmed. Explicit tri-state: `True` (confirmed done),
    `False` (confirmed failed), `None` (genuinely unknown — the timeout/
    ambiguous-outcome case Phase 4's "uncertain external writes" concerns
    itself with)."""
    if not isinstance(payload, dict):
        return None
    value = payload.get("success")
    if value is True:
        return True
    if value is False:
        return False
    return None
