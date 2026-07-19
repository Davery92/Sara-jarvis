"""
Training Program and Phase Tools
Tools for managing workout programs and training phases
"""
from app.tools.base import BaseTool, ToolResult
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.db.session import get_db
from datetime import date, datetime, timedelta
from app.core.timezone import naive_local_now
import uuid
import json


# ============================================
# PROGRAM TOOLS
# ============================================

class ProgramListTool(BaseTool):
    """List all training programs"""

    @property
    def name(self) -> str:
        return "program_list"

    @property
    def description(self) -> str:
        return "List all training programs. Shows program name, goal, dates, and active status."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "active_only": {
                    "type": "boolean",
                    "description": "If true, only return the active program"
                }
            }
        }

    async def execute(self, user_id: str, active_only: bool = False, **kwargs) -> ToolResult:
        db: Session = next(get_db())
        try:
            if active_only:
                query = text("""
                    SELECT id, name, goal, start_date, end_date, is_active, notes, created_at
                    FROM fitness_program
                    WHERE user_id = :user_id AND is_active = true
                    LIMIT 1
                """)
            else:
                query = text("""
                    SELECT id, name, goal, start_date, end_date, is_active, notes, created_at
                    FROM fitness_program
                    WHERE user_id = :user_id
                    ORDER BY is_active DESC, start_date DESC NULLS LAST, created_at DESC
                """)

            result = db.execute(query, {"user_id": user_id})
            programs = []
            for row in result:
                row_dict = dict(row._mapping)
                if row_dict.get('start_date'):
                    row_dict['start_date'] = str(row_dict['start_date'])
                if row_dict.get('end_date'):
                    row_dict['end_date'] = str(row_dict['end_date'])
                if row_dict.get('created_at'):
                    row_dict['created_at'] = row_dict['created_at'].isoformat()
                programs.append(row_dict)

            if not programs:
                return ToolResult(
                    success=True,
                    message="No programs found",
                    data={"programs": [], "count": 0}
                )

            return ToolResult(
                success=True,
                message=f"Found {len(programs)} program(s)",
                data={"programs": programs, "count": len(programs)}
            )

        except Exception as e:
            return ToolResult(success=False, message=f"Failed to list programs: {str(e)}", data=None)
        finally:
            db.close()


class ProgramGetTool(BaseTool):
    """Get details of a specific program with its phases"""

    @property
    def name(self) -> str:
        return "program_get"

    @property
    def description(self) -> str:
        return "Get detailed information about a specific training program including all its phases and their templates."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "program_id": {
                    "type": "string",
                    "description": "The ID of the program to retrieve"
                },
                "program_name": {
                    "type": "string",
                    "description": "Alternatively, the name of the program (partial match)"
                }
            }
        }

    async def execute(self, user_id: str, program_id: str = None, program_name: str = None, **kwargs) -> ToolResult:
        db: Session = next(get_db())
        try:
            if program_id:
                query = text("""
                    SELECT id, name, goal, start_date, end_date, is_active, notes, created_at
                    FROM fitness_program
                    WHERE user_id = :user_id AND id = :program_id
                """)
                program = db.execute(query, {"user_id": user_id, "program_id": program_id}).fetchone()
            elif program_name:
                query = text("""
                    SELECT id, name, goal, start_date, end_date, is_active, notes, created_at
                    FROM fitness_program
                    WHERE user_id = :user_id AND LOWER(name) LIKE LOWER(:pattern)
                    LIMIT 1
                """)
                program = db.execute(query, {"user_id": user_id, "pattern": f"%{program_name}%"}).fetchone()
            else:
                return ToolResult(success=False, message="Either program_id or program_name required", data=None)

            if not program:
                return ToolResult(success=False, message="Program not found", data=None)

            program_dict = dict(program._mapping)
            if program_dict.get('start_date'):
                program_dict['start_date'] = str(program_dict['start_date'])
            if program_dict.get('end_date'):
                program_dict['end_date'] = str(program_dict['end_date'])
            if program_dict.get('created_at'):
                program_dict['created_at'] = program_dict['created_at'].isoformat()

            # Get phases for this program
            phases_query = text("""
                SELECT id, name, goal, order_index, duration_weeks, start_date, end_date,
                       calories_target, protein_target, carbs_target, fat_target,
                       training_days_per_week, deload_week, status, notes
                FROM fitness_phase
                WHERE user_id = :user_id AND program_id = :program_id
                ORDER BY order_index ASC, start_date ASC NULLS LAST
            """)
            phases_result = db.execute(phases_query, {"user_id": user_id, "program_id": program_dict['id']})
            phases = []
            for row in phases_result:
                phase_dict = dict(row._mapping)
                if phase_dict.get('start_date'):
                    phase_dict['start_date'] = str(phase_dict['start_date'])
                if phase_dict.get('end_date'):
                    phase_dict['end_date'] = str(phase_dict['end_date'])
                phases.append(phase_dict)

            return ToolResult(
                success=True,
                message=f"Retrieved program '{program_dict['name']}' with {len(phases)} phase(s)",
                data={"program": program_dict, "phases": phases}
            )

        except Exception as e:
            return ToolResult(success=False, message=f"Failed to get program: {str(e)}", data=None)
        finally:
            db.close()


class ProgramCreateTool(BaseTool):
    """Create a new training program"""

    @property
    def name(self) -> str:
        return "program_create"

    @property
    def description(self) -> str:
        return """Create a new training program. Programs are the top-level container for organizing training.

        Example goals: 'strength', 'hypertrophy', 'fat_loss', 'recomp', 'maintenance', 'powerlifting', 'bodybuilding'

        A program contains phases, and each phase contains workout templates."""

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name of the program (e.g., '12-Week Strength Program', 'Summer Cut 2024')"
                },
                "goal": {
                    "type": "string",
                    "description": "Primary goal: strength, hypertrophy, fat_loss, recomp, maintenance, powerlifting, bodybuilding"
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format (optional)"
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format (optional)"
                },
                "notes": {
                    "type": "string",
                    "description": "Optional notes about this program"
                }
            },
            "required": ["name", "goal"]
        }

    async def execute(self, user_id: str, name: str, goal: str,
                      start_date: str = None, end_date: str = None,
                      notes: str = None, **kwargs) -> ToolResult:
        db: Session = next(get_db())
        try:
            program_id = str(uuid.uuid4())

            query = text("""
                INSERT INTO fitness_program (id, user_id, name, goal, start_date, end_date, is_active, notes)
                VALUES (:id, :user_id, :name, :goal, :start_date, :end_date, false, :notes)
                RETURNING id, name
            """)

            db.execute(query, {
                "id": program_id,
                "user_id": user_id,
                "name": name,
                "goal": goal,
                "start_date": start_date,
                "end_date": end_date,
                "notes": notes
            })
            db.commit()

            return ToolResult(
                success=True,
                message=f"Created program '{name}' with goal '{goal}'",
                data={
                    "program_id": program_id,
                    "name": name,
                    "goal": goal,
                    "start_date": start_date,
                    "end_date": end_date
                }
            )

        except Exception as e:
            db.rollback()
            return ToolResult(success=False, message=f"Failed to create program: {str(e)}", data=None)
        finally:
            db.close()


class ProgramUpdateTool(BaseTool):
    """Update an existing program"""

    @property
    def name(self) -> str:
        return "program_update"

    @property
    def description(self) -> str:
        return "Update an existing training program. Only provide the fields you want to change."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "program_id": {
                    "type": "string",
                    "description": "ID of the program to update"
                },
                "program_name": {
                    "type": "string",
                    "description": "Alternatively, name of program to update (partial match)"
                },
                "name": {
                    "type": "string",
                    "description": "New name for the program"
                },
                "goal": {
                    "type": "string",
                    "description": "New goal"
                },
                "start_date": {
                    "type": "string",
                    "description": "New start date (YYYY-MM-DD)"
                },
                "end_date": {
                    "type": "string",
                    "description": "New end date (YYYY-MM-DD)"
                },
                "notes": {
                    "type": "string",
                    "description": "New notes"
                }
            }
        }

    async def execute(self, user_id: str, program_id: str = None, program_name: str = None,
                      name: str = None, goal: str = None, start_date: str = None,
                      end_date: str = None, notes: str = None, **kwargs) -> ToolResult:
        db: Session = next(get_db())
        try:
            # Find program
            if program_id:
                find_query = text("SELECT id, name FROM fitness_program WHERE user_id = :user_id AND id = :id")
                existing = db.execute(find_query, {"user_id": user_id, "id": program_id}).fetchone()
            elif program_name:
                find_query = text("SELECT id, name FROM fitness_program WHERE user_id = :user_id AND LOWER(name) LIKE LOWER(:pattern) LIMIT 1")
                existing = db.execute(find_query, {"user_id": user_id, "pattern": f"%{program_name}%"}).fetchone()
            else:
                return ToolResult(success=False, message="Either program_id or program_name required", data=None)

            if not existing:
                return ToolResult(success=False, message="Program not found", data=None)

            program_id = existing.id
            old_name = existing.name

            # Build update
            updates = []
            params = {"user_id": user_id, "id": program_id}

            if name is not None:
                updates.append("name = :name")
                params["name"] = name
            if goal is not None:
                updates.append("goal = :goal")
                params["goal"] = goal
            if start_date is not None:
                updates.append("start_date = :start_date")
                params["start_date"] = start_date
            if end_date is not None:
                updates.append("end_date = :end_date")
                params["end_date"] = end_date
            if notes is not None:
                updates.append("notes = :notes")
                params["notes"] = notes

            if not updates:
                return ToolResult(success=False, message="No updates provided", data=None)

            updates.append("updated_at = CURRENT_TIMESTAMP")
            query = text(f"UPDATE fitness_program SET {', '.join(updates)} WHERE user_id = :user_id AND id = :id")
            db.execute(query, params)
            db.commit()

            return ToolResult(
                success=True,
                message=f"Updated program '{old_name}'",
                data={"program_id": program_id}
            )

        except Exception as e:
            db.rollback()
            return ToolResult(success=False, message=f"Failed to update program: {str(e)}", data=None)
        finally:
            db.close()


class ProgramActivateTool(BaseTool):
    """Activate a training program"""

    @property
    def name(self) -> str:
        return "program_activate"

    @property
    def description(self) -> str:
        return "Activate a training program. This deactivates any other active program. Only one program can be active at a time."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "program_id": {
                    "type": "string",
                    "description": "ID of the program to activate"
                },
                "program_name": {
                    "type": "string",
                    "description": "Alternatively, name of program to activate (partial match)"
                }
            }
        }

    async def execute(self, user_id: str, program_id: str = None, program_name: str = None, **kwargs) -> ToolResult:
        db: Session = next(get_db())
        try:
            # Find program
            if program_id:
                find_query = text("SELECT id, name FROM fitness_program WHERE user_id = :user_id AND id = :id")
                existing = db.execute(find_query, {"user_id": user_id, "id": program_id}).fetchone()
            elif program_name:
                find_query = text("SELECT id, name FROM fitness_program WHERE user_id = :user_id AND LOWER(name) LIKE LOWER(:pattern) LIMIT 1")
                existing = db.execute(find_query, {"user_id": user_id, "pattern": f"%{program_name}%"}).fetchone()
            else:
                return ToolResult(success=False, message="Either program_id or program_name required", data=None)

            if not existing:
                return ToolResult(success=False, message="Program not found", data=None)

            program_id = existing.id
            program_name = existing.name

            # Deactivate all programs
            db.execute(text("""
                UPDATE fitness_program SET is_active = false, updated_at = CURRENT_TIMESTAMP
                WHERE user_id = :user_id AND is_active = true
            """), {"user_id": user_id})

            # Activate this program
            db.execute(text("""
                UPDATE fitness_program SET is_active = true, updated_at = CURRENT_TIMESTAMP
                WHERE id = :program_id AND user_id = :user_id
            """), {"program_id": program_id, "user_id": user_id})

            db.commit()

            return ToolResult(
                success=True,
                message=f"Activated program '{program_name}'",
                data={"program_id": program_id, "name": program_name}
            )

        except Exception as e:
            db.rollback()
            return ToolResult(success=False, message=f"Failed to activate program: {str(e)}", data=None)
        finally:
            db.close()


class ProgramDeleteTool(BaseTool):
    """Delete a training program"""

    @property
    def name(self) -> str:
        return "program_delete"

    @property
    def description(self) -> str:
        return "Delete a training program. Phases will be unlinked (not deleted) from this program."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "program_id": {
                    "type": "string",
                    "description": "ID of the program to delete"
                },
                "program_name": {
                    "type": "string",
                    "description": "Alternatively, name of program to delete (partial match)"
                }
            }
        }

    async def execute(self, user_id: str, program_id: str = None, program_name: str = None, **kwargs) -> ToolResult:
        db: Session = next(get_db())
        try:
            # Find program
            if program_id:
                find_query = text("SELECT id, name FROM fitness_program WHERE user_id = :user_id AND id = :id")
                existing = db.execute(find_query, {"user_id": user_id, "id": program_id}).fetchone()
            elif program_name:
                find_query = text("SELECT id, name FROM fitness_program WHERE user_id = :user_id AND LOWER(name) LIKE LOWER(:pattern) LIMIT 1")
                existing = db.execute(find_query, {"user_id": user_id, "pattern": f"%{program_name}%"}).fetchone()
            else:
                return ToolResult(success=False, message="Either program_id or program_name required", data=None)

            if not existing:
                return ToolResult(success=False, message="Program not found", data=None)

            program_id = existing.id
            program_name = existing.name

            # Unlink phases (don't delete them)
            db.execute(text("""
                UPDATE fitness_phase SET program_id = NULL
                WHERE program_id = :program_id AND user_id = :user_id
            """), {"program_id": program_id, "user_id": user_id})

            # Delete program
            db.execute(text("""
                DELETE FROM fitness_program WHERE id = :program_id AND user_id = :user_id
            """), {"program_id": program_id, "user_id": user_id})

            db.commit()

            return ToolResult(
                success=True,
                message=f"Deleted program '{program_name}'",
                data={"program_id": program_id, "name": program_name}
            )

        except Exception as e:
            db.rollback()
            return ToolResult(success=False, message=f"Failed to delete program: {str(e)}", data=None)
        finally:
            db.close()


# ============================================
# PHASE TOOLS
# ============================================

class PhaseListTool(BaseTool):
    """List all training phases"""

    @property
    def name(self) -> str:
        return "phase_list"

    @property
    def description(self) -> str:
        return "List all training phases. Can filter by program or show only active phases."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "program_id": {
                    "type": "string",
                    "description": "Optional: Filter phases by program ID"
                },
                "active_only": {
                    "type": "boolean",
                    "description": "If true, only return active phases"
                }
            }
        }

    async def execute(self, user_id: str, program_id: str = None, active_only: bool = False, **kwargs) -> ToolResult:
        db: Session = next(get_db())
        try:
            conditions = ["user_id = :user_id"]
            params = {"user_id": user_id}

            if program_id:
                conditions.append("program_id = :program_id")
                params["program_id"] = program_id
            if active_only:
                conditions.append("status = 'active'")

            query = text(f"""
                SELECT id, name, goal, program_id, order_index, duration_weeks,
                       start_date, end_date, calories_target, protein_target,
                       carbs_target, fat_target, training_days_per_week,
                       deload_week, status, notes, created_at
                FROM fitness_phase
                WHERE {' AND '.join(conditions)}
                ORDER BY program_id NULLS LAST, order_index ASC, start_date DESC NULLS LAST
            """)

            result = db.execute(query, params)
            phases = []
            for row in result:
                phase_dict = dict(row._mapping)
                if phase_dict.get('start_date'):
                    phase_dict['start_date'] = str(phase_dict['start_date'])
                if phase_dict.get('end_date'):
                    phase_dict['end_date'] = str(phase_dict['end_date'])
                if phase_dict.get('created_at'):
                    phase_dict['created_at'] = phase_dict['created_at'].isoformat()
                phases.append(phase_dict)

            if not phases:
                return ToolResult(
                    success=True,
                    message="No phases found",
                    data={"phases": [], "count": 0}
                )

            return ToolResult(
                success=True,
                message=f"Found {len(phases)} phase(s)",
                data={"phases": phases, "count": len(phases)}
            )

        except Exception as e:
            return ToolResult(success=False, message=f"Failed to list phases: {str(e)}", data=None)
        finally:
            db.close()


class PhaseGetTool(BaseTool):
    """Get details of a specific phase with its templates"""

    @property
    def name(self) -> str:
        return "phase_get"

    @property
    def description(self) -> str:
        return "Get detailed information about a specific training phase including all its workout templates."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "phase_id": {
                    "type": "string",
                    "description": "The ID of the phase to retrieve"
                },
                "phase_name": {
                    "type": "string",
                    "description": "Alternatively, the name of the phase (partial match)"
                }
            }
        }

    async def execute(self, user_id: str, phase_id: str = None, phase_name: str = None, **kwargs) -> ToolResult:
        db: Session = next(get_db())
        try:
            import json

            if phase_id:
                query = text("""
                    SELECT id, name, goal, program_id, order_index, duration_weeks,
                           start_date, end_date, calories_target, protein_target,
                           carbs_target, fat_target, training_days_per_week,
                           deload_week, status, notes, created_at
                    FROM fitness_phase
                    WHERE user_id = :user_id AND id = :phase_id
                """)
                phase = db.execute(query, {"user_id": user_id, "phase_id": phase_id}).fetchone()
            elif phase_name:
                query = text("""
                    SELECT id, name, goal, program_id, order_index, duration_weeks,
                           start_date, end_date, calories_target, protein_target,
                           carbs_target, fat_target, training_days_per_week,
                           deload_week, status, notes, created_at
                    FROM fitness_phase
                    WHERE user_id = :user_id AND LOWER(name) LIKE LOWER(:pattern)
                    LIMIT 1
                """)
                phase = db.execute(query, {"user_id": user_id, "pattern": f"%{phase_name}%"}).fetchone()
            else:
                return ToolResult(success=False, message="Either phase_id or phase_name required", data=None)

            if not phase:
                return ToolResult(success=False, message="Phase not found", data=None)

            phase_dict = dict(phase._mapping)
            if phase_dict.get('start_date'):
                phase_dict['start_date'] = str(phase_dict['start_date'])
            if phase_dict.get('end_date'):
                phase_dict['end_date'] = str(phase_dict['end_date'])
            if phase_dict.get('created_at'):
                phase_dict['created_at'] = phase_dict['created_at'].isoformat()

            # Get templates for this phase
            templates_query = text("""
                SELECT id, name, scheduled_days, exercises, notes, order_in_phase
                FROM fitness_template
                WHERE user_id = :user_id AND phase_id = :phase_id
                ORDER BY order_in_phase ASC, created_at ASC
            """)
            templates_result = db.execute(templates_query, {"user_id": user_id, "phase_id": phase_dict['id']})
            templates = []
            for row in templates_result:
                t_dict = dict(row._mapping)
                if isinstance(t_dict.get('exercises'), str):
                    try:
                        t_dict['exercises'] = json.loads(t_dict['exercises'])
                    except:
                        pass
                if isinstance(t_dict.get('scheduled_days'), str):
                    try:
                        t_dict['scheduled_days'] = json.loads(t_dict['scheduled_days'])
                    except:
                        pass
                templates.append(t_dict)

            return ToolResult(
                success=True,
                message=f"Retrieved phase '{phase_dict['name']}' with {len(templates)} template(s)",
                data={"phase": phase_dict, "templates": templates}
            )

        except Exception as e:
            return ToolResult(success=False, message=f"Failed to get phase: {str(e)}", data=None)
        finally:
            db.close()


class PhaseCreateTool(BaseTool):
    """Create a new training phase"""

    @property
    def name(self) -> str:
        return "phase_create"

    @property
    def description(self) -> str:
        return """Create a new training phase. Phases belong to programs and contain workout templates.

        Example phase names: 'Hypertrophy Block', 'Strength Block', 'Peaking Phase', 'Deload Week'

        Can include nutrition targets (calories, protein, carbs, fat) and training parameters."""

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name of the phase (e.g., 'Hypertrophy Block 1', 'Strength Phase')"
                },
                "program_id": {
                    "type": "string",
                    "description": "Optional: ID of the program this phase belongs to"
                },
                "goal": {
                    "type": "string",
                    "description": "Phase goal (e.g., 'hypertrophy', 'strength', 'power', 'deload')"
                },
                "order_index": {
                    "type": "integer",
                    "description": "Order within the program (0-based)"
                },
                "duration_weeks": {
                    "type": "integer",
                    "description": "Duration in weeks"
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date (YYYY-MM-DD)"
                },
                "end_date": {
                    "type": "string",
                    "description": "End date (YYYY-MM-DD)"
                },
                "calories_target": {
                    "type": "integer",
                    "description": "Daily calorie target"
                },
                "protein_target": {
                    "type": "integer",
                    "description": "Daily protein target in grams"
                },
                "carbs_target": {
                    "type": "integer",
                    "description": "Daily carbs target in grams"
                },
                "fat_target": {
                    "type": "integer",
                    "description": "Daily fat target in grams"
                },
                "training_days_per_week": {
                    "type": "integer",
                    "description": "Number of training days per week"
                },
                "deload_week": {
                    "type": "integer",
                    "description": "Which week is the deload (e.g., 4 means week 4 is deload)"
                },
                "notes": {
                    "type": "string",
                    "description": "Notes about this phase"
                }
            },
            "required": ["name"]
        }

    async def execute(self, user_id: str, name: str, program_id: str = None,
                      goal: str = None, order_index: int = 0, duration_weeks: int = None,
                      start_date: str = None, end_date: str = None,
                      calories_target: int = None, protein_target: int = None,
                      carbs_target: int = None, fat_target: int = None,
                      training_days_per_week: int = None, deload_week: int = None,
                      notes: str = None, **kwargs) -> ToolResult:
        db: Session = next(get_db())
        try:
            phase_id = str(uuid.uuid4())

            query = text("""
                INSERT INTO fitness_phase (
                    id, user_id, name, goal, program_id, order_index, duration_weeks,
                    start_date, end_date, calories_target, protein_target, carbs_target, fat_target,
                    training_days_per_week, deload_week, status, notes
                )
                VALUES (
                    :id, :user_id, :name, :goal, :program_id, :order_index, :duration_weeks,
                    :start_date, :end_date, :calories_target, :protein_target, :carbs_target, :fat_target,
                    :training_days_per_week, :deload_week, 'planned', :notes
                )
            """)

            db.execute(query, {
                "id": phase_id,
                "user_id": user_id,
                "name": name,
                "goal": goal,
                "program_id": program_id,
                "order_index": order_index or 0,
                "duration_weeks": duration_weeks,
                "start_date": start_date,
                "end_date": end_date,
                "calories_target": calories_target,
                "protein_target": protein_target,
                "carbs_target": carbs_target,
                "fat_target": fat_target,
                "training_days_per_week": training_days_per_week,
                "deload_week": deload_week,
                "notes": notes
            })
            db.commit()

            return ToolResult(
                success=True,
                message=f"Created phase '{name}'" + (f" in program" if program_id else ""),
                data={
                    "phase_id": phase_id,
                    "name": name,
                    "goal": goal,
                    "program_id": program_id,
                    "duration_weeks": duration_weeks
                }
            )

        except Exception as e:
            db.rollback()
            return ToolResult(success=False, message=f"Failed to create phase: {str(e)}", data=None)
        finally:
            db.close()


class PhaseUpdateTool(BaseTool):
    """Update an existing phase"""

    @property
    def name(self) -> str:
        return "phase_update"

    @property
    def description(self) -> str:
        return "Update an existing training phase. Only provide the fields you want to change."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "phase_id": {
                    "type": "string",
                    "description": "ID of the phase to update"
                },
                "phase_name": {
                    "type": "string",
                    "description": "Alternatively, name of phase to update (partial match)"
                },
                "name": {"type": "string", "description": "New name"},
                "goal": {"type": "string", "description": "New goal"},
                "program_id": {"type": "string", "description": "New program ID (or null to unlink)"},
                "order_index": {"type": "integer", "description": "New order index"},
                "duration_weeks": {"type": "integer", "description": "New duration"},
                "start_date": {"type": "string", "description": "New start date"},
                "end_date": {"type": "string", "description": "New end date"},
                "calories_target": {"type": "integer", "description": "New calorie target"},
                "protein_target": {"type": "integer", "description": "New protein target"},
                "carbs_target": {"type": "integer", "description": "New carbs target"},
                "fat_target": {"type": "integer", "description": "New fat target"},
                "training_days_per_week": {"type": "integer", "description": "New training days"},
                "deload_week": {"type": "integer", "description": "New deload week"},
                "notes": {"type": "string", "description": "New notes"}
            }
        }

    async def execute(self, user_id: str, phase_id: str = None, phase_name: str = None,
                      name: str = None, goal: str = None, program_id: str = None,
                      order_index: int = None, duration_weeks: int = None,
                      start_date: str = None, end_date: str = None,
                      calories_target: int = None, protein_target: int = None,
                      carbs_target: int = None, fat_target: int = None,
                      training_days_per_week: int = None, deload_week: int = None,
                      notes: str = None, **kwargs) -> ToolResult:
        db: Session = next(get_db())
        try:
            # Find phase
            if phase_id:
                find_query = text("SELECT id, name FROM fitness_phase WHERE user_id = :user_id AND id = :id")
                existing = db.execute(find_query, {"user_id": user_id, "id": phase_id}).fetchone()
            elif phase_name:
                find_query = text("SELECT id, name FROM fitness_phase WHERE user_id = :user_id AND LOWER(name) LIKE LOWER(:pattern) LIMIT 1")
                existing = db.execute(find_query, {"user_id": user_id, "pattern": f"%{phase_name}%"}).fetchone()
            else:
                return ToolResult(success=False, message="Either phase_id or phase_name required", data=None)

            if not existing:
                return ToolResult(success=False, message="Phase not found", data=None)

            phase_id = existing.id
            old_name = existing.name

            # Build update
            updates = []
            params = {"user_id": user_id, "id": phase_id}

            field_map = {
                "name": name, "goal": goal, "program_id": program_id,
                "order_index": order_index, "duration_weeks": duration_weeks,
                "start_date": start_date, "end_date": end_date,
                "calories_target": calories_target, "protein_target": protein_target,
                "carbs_target": carbs_target, "fat_target": fat_target,
                "training_days_per_week": training_days_per_week,
                "deload_week": deload_week, "notes": notes
            }

            for field, value in field_map.items():
                if value is not None:
                    updates.append(f"{field} = :{field}")
                    params[field] = value

            if not updates:
                return ToolResult(success=False, message="No updates provided", data=None)

            updates.append("updated_at = CURRENT_TIMESTAMP")
            query = text(f"UPDATE fitness_phase SET {', '.join(updates)} WHERE user_id = :user_id AND id = :id")
            db.execute(query, params)
            db.commit()

            return ToolResult(
                success=True,
                message=f"Updated phase '{old_name}'",
                data={"phase_id": phase_id}
            )

        except Exception as e:
            db.rollback()
            return ToolResult(success=False, message=f"Failed to update phase: {str(e)}", data=None)
        finally:
            db.close()


class PhaseActivateTool(BaseTool):
    """Activate a training phase"""

    @property
    def name(self) -> str:
        return "phase_activate"

    @property
    def description(self) -> str:
        return """Activate a training phase. This:
        - Deactivates any other active phase
        - Creates calendar events for all linked templates based on their scheduled_days
        - Creates workout sessions in 'planned' status
        - Sets this phase's status to 'active'"""

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "phase_id": {
                    "type": "string",
                    "description": "ID of the phase to activate"
                },
                "phase_name": {
                    "type": "string",
                    "description": "Alternatively, name of phase to activate (partial match)"
                }
            }
        }

    async def execute(self, user_id: str, phase_id: str = None, phase_name: str = None, **kwargs) -> ToolResult:
        from datetime import datetime, timedelta
        import json

        db: Session = next(get_db())
        try:
            # Find phase
            if phase_id:
                find_query = text("""
                    SELECT id, name, status, start_date, end_date, duration_weeks
                    FROM fitness_phase WHERE user_id = :user_id AND id = :id
                """)
                existing = db.execute(find_query, {"user_id": user_id, "id": phase_id}).fetchone()
            elif phase_name:
                find_query = text("""
                    SELECT id, name, status, start_date, end_date, duration_weeks
                    FROM fitness_phase WHERE user_id = :user_id AND LOWER(name) LIKE LOWER(:pattern) LIMIT 1
                """)
                existing = db.execute(find_query, {"user_id": user_id, "pattern": f"%{phase_name}%"}).fetchone()
            else:
                return ToolResult(success=False, message="Either phase_id or phase_name required", data=None)

            if not existing:
                return ToolResult(success=False, message="Phase not found", data=None)

            phase_dict = dict(existing._mapping)
            phase_id = phase_dict['id']
            phase_name = phase_dict['name']

            if phase_dict['status'] == 'active':
                return ToolResult(success=True, message=f"Phase '{phase_name}' is already active", data={"phase_id": phase_id})

            # Deactivate all active phases
            db.execute(text("""
                UPDATE fitness_phase SET status = 'inactive', updated_at = CURRENT_TIMESTAMP
                WHERE user_id = :user_id AND status = 'active'
            """), {"user_id": user_id})

            # Determine date range
            start_date = phase_dict.get('start_date')
            end_date = phase_dict.get('end_date')
            duration_weeks = phase_dict.get('duration_weeks') or 4

            if not start_date:
                start_date = naive_local_now().date()
            if not end_date:
                end_date = start_date + timedelta(weeks=duration_weeks)

            # Update phase with dates
            db.execute(text("""
                UPDATE fitness_phase SET start_date = :start_date, end_date = :end_date
                WHERE id = :phase_id AND user_id = :user_id
            """), {"phase_id": phase_id, "user_id": user_id, "start_date": start_date, "end_date": end_date})

            # Fetch templates for this phase
            templates = db.execute(text("""
                SELECT id, name, scheduled_days, exercises
                FROM fitness_template
                WHERE phase_id = :phase_id AND user_id = :user_id
            """), {"phase_id": phase_id, "user_id": user_id}).fetchall()

            created_events = []
            day_map = {
                'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
                'friday': 4, 'saturday': 5, 'sunday': 6
            }

            if templates:
                for template_row in templates:
                    template = dict(template_row._mapping)
                    template_id = template['id']
                    template_name = template['name']
                    scheduled_days_json = template['scheduled_days']

                    try:
                        scheduled_days = json.loads(scheduled_days_json) if scheduled_days_json else []
                    except:
                        scheduled_days = []

                    if not scheduled_days:
                        continue

                    scheduled_day_nums = [day_map[d.lower().strip()] for d in scheduled_days if d.lower().strip() in day_map]
                    if not scheduled_day_nums:
                        continue

                    # Generate calendar events
                    current_date = start_date if isinstance(start_date, date) else start_date
                    end = end_date if isinstance(end_date, date) else end_date

                    while current_date <= end:
                        if current_date.weekday() in scheduled_day_nums:
                            event_id = str(uuid.uuid4())
                            event_start = datetime.combine(current_date, datetime.min.time().replace(hour=13, minute=0))
                            event_end = datetime.combine(current_date, datetime.min.time().replace(hour=14, minute=30))

                            db.execute(text("""
                                INSERT INTO calendar_event (id, user_id, title, start_time, end_time, description, location, source)
                                VALUES (:id, :user_id, :title, :start_time, :end_time, :description, :location, 'sara')
                            """), {
                                "id": event_id,
                                "user_id": user_id,
                                "title": f"🏋️ {template_name}",
                                "start_time": event_start,
                                "end_time": event_end,
                                "description": f"Workout: {template_name}\nPhase: {phase_name}",
                                "location": ""
                            })

                            # Create workout session
                            session_id = str(uuid.uuid4())
                            db.execute(text("""
                                INSERT INTO workout_session (id, user_id, template_id, session_date, status, calendar_event_id)
                                VALUES (:id, :user_id, :template_id, :session_date, :status, :calendar_event_id)
                            """), {
                                "id": session_id,
                                "user_id": user_id,
                                "template_id": template_id,
                                "session_date": current_date,
                                "status": "planned",
                                "calendar_event_id": event_id
                            })

                            created_events.append({
                                "template": template_name,
                                "date": str(current_date)
                            })

                        current_date += timedelta(days=1)

            # Activate the phase
            db.execute(text("""
                UPDATE fitness_phase SET status = 'active', updated_at = CURRENT_TIMESTAMP
                WHERE id = :phase_id AND user_id = :user_id
            """), {"phase_id": phase_id, "user_id": user_id})

            db.commit()

            msg = f"Activated phase '{phase_name}'"
            if created_events:
                msg += f" and created {len(created_events)} calendar events"
            else:
                msg += " (no templates with scheduled_days - add templates to auto-schedule workouts)"

            return ToolResult(
                success=True,
                message=msg,
                data={
                    "phase_id": phase_id,
                    "name": phase_name,
                    "start_date": str(start_date),
                    "end_date": str(end_date),
                    "events_created": len(created_events)
                }
            )

        except Exception as e:
            db.rollback()
            return ToolResult(success=False, message=f"Failed to activate phase: {str(e)}", data=None)
        finally:
            db.close()


class PhaseDeleteTool(BaseTool):
    """Delete a training phase"""

    @property
    def name(self) -> str:
        return "phase_delete"

    @property
    def description(self) -> str:
        return "Delete a training phase. Templates linked to this phase will have their phase_id set to null."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "phase_id": {
                    "type": "string",
                    "description": "ID of the phase to delete"
                },
                "phase_name": {
                    "type": "string",
                    "description": "Alternatively, name of phase to delete (partial match)"
                }
            }
        }

    async def execute(self, user_id: str, phase_id: str = None, phase_name: str = None, **kwargs) -> ToolResult:
        db: Session = next(get_db())
        try:
            # Find phase
            if phase_id:
                find_query = text("SELECT id, name FROM fitness_phase WHERE user_id = :user_id AND id = :id")
                existing = db.execute(find_query, {"user_id": user_id, "id": phase_id}).fetchone()
            elif phase_name:
                find_query = text("SELECT id, name FROM fitness_phase WHERE user_id = :user_id AND LOWER(name) LIKE LOWER(:pattern) LIMIT 1")
                existing = db.execute(find_query, {"user_id": user_id, "pattern": f"%{phase_name}%"}).fetchone()
            else:
                return ToolResult(success=False, message="Either phase_id or phase_name required", data=None)

            if not existing:
                return ToolResult(success=False, message="Phase not found", data=None)

            phase_id = existing.id
            phase_name = existing.name

            # Unlink templates
            db.execute(text("""
                UPDATE fitness_template SET phase_id = NULL
                WHERE phase_id = :phase_id AND user_id = :user_id
            """), {"phase_id": phase_id, "user_id": user_id})

            # Delete phase
            db.execute(text("""
                DELETE FROM fitness_phase WHERE id = :phase_id AND user_id = :user_id
            """), {"phase_id": phase_id, "user_id": user_id})

            db.commit()

            return ToolResult(
                success=True,
                message=f"Deleted phase '{phase_name}'",
                data={"phase_id": phase_id, "name": phase_name}
            )

        except Exception as e:
            db.rollback()
            return ToolResult(success=False, message=f"Failed to delete phase: {str(e)}", data=None)
        finally:
            db.close()
