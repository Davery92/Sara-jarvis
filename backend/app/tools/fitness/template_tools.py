"""
Workout Template Tools
Tools for accessing and managing workout templates
"""
from app.tools.base import BaseTool, ToolResult
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.db.session import get_db
import json

class TemplateListTool(BaseTool):
    """List all workout templates"""
    
    @property
    def name(self) -> str:
        return "template_list"
    
    @property
    def description(self) -> str:
        return "List all workout templates with their scheduled days and exercises"
    
    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "phase_id": {
                    "type": "string",
                    "description": "Optional: Filter templates by training phase ID"
                }
            }
        }
    
    async def execute(self, user_id: str, phase_id: str = None, **kwargs) -> ToolResult:
        """List workout templates"""
        db: Session = next(get_db())
        try:
            if phase_id:
                query = text("""
                    SELECT id, name, phase_id, scheduled_days, exercises, notes, created_at
                    FROM fitness_template
                    WHERE user_id = :user_id AND phase_id = :phase_id
                    ORDER BY order_in_phase, created_at
                """)
                result = db.execute(query, {"user_id": user_id, "phase_id": phase_id})
            else:
                query = text("""
                    SELECT id, name, phase_id, scheduled_days, exercises, notes, created_at
                    FROM fitness_template
                    WHERE user_id = :user_id
                    ORDER BY created_at DESC
                """)
                result = db.execute(query, {"user_id": user_id})
            
            templates = []
            for row in result:
                row_dict = dict(row._mapping)

                # Parse exercises if it's JSON string
                if isinstance(row_dict['exercises'], str):
                    try:
                        row_dict['exercises'] = json.loads(row_dict['exercises'])
                    except:
                        pass

                # Parse scheduled_days if it's JSON string
                if isinstance(row_dict['scheduled_days'], str):
                    try:
                        row_dict['scheduled_days'] = json.loads(row_dict['scheduled_days'])
                    except:
                        pass

                # Convert datetime objects to strings for JSON serialization
                if row_dict.get('created_at'):
                    row_dict['created_at'] = row_dict['created_at'].isoformat()
                if row_dict.get('updated_at'):
                    row_dict['updated_at'] = row_dict['updated_at'].isoformat()

                templates.append(row_dict)
            
            if not templates:
                return ToolResult(
                    success=True,
                    message="No templates found",
                    data={"templates": [], "count": 0}
                )
            
            return ToolResult(
                success=True,
                message=f"Found {len(templates)} template(s)",
                data={"templates": templates, "count": len(templates)}
            )
            
        except Exception as e:
            return ToolResult(
                success=False,
                message=f"Failed to list templates: {str(e)}",
                data=None
            )
        finally:
            db.close()


class TemplateGetTool(BaseTool):
    """Get detailed information about a specific template"""
    
    @property
    def name(self) -> str:
        return "template_get"
    
    @property
    def description(self) -> str:
        return "Get detailed information about a specific workout template including all exercises, sets, reps, and RPE targets"
    
    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "template_id": {
                    "type": "string",
                    "description": "The ID of the template to retrieve"
                },
                "template_name": {
                    "type": "string",
                    "description": "Alternatively, the name of the template (case-insensitive partial match)"
                }
            }
        }
    
    async def execute(self, user_id: str, template_id: str = None, template_name: str = None, **kwargs) -> ToolResult:
        """Get template details"""
        db: Session = next(get_db())
        try:
            if template_id:
                query = text("""
                    SELECT id, name, phase_id, scheduled_days, exercises, notes, order_in_phase, created_at, updated_at
                    FROM fitness_template
                    WHERE user_id = :user_id AND id = :template_id
                """)
                result = db.execute(query, {"user_id": user_id, "template_id": template_id}).fetchone()
            elif template_name:
                query = text("""
                    SELECT id, name, phase_id, scheduled_days, exercises, notes, order_in_phase, created_at, updated_at
                    FROM fitness_template
                    WHERE user_id = :user_id AND LOWER(name) LIKE LOWER(:name_pattern)
                    LIMIT 1
                """)
                result = db.execute(query, {"user_id": user_id, "name_pattern": f"%{template_name}%"}).fetchone()
            else:
                return ToolResult(
                    success=False,
                    message="Either template_id or template_name must be provided",
                    data=None
                )
            
            if not result:
                return ToolResult(
                    success=False,
                    message=f"Template not found",
                    data=None
                )
            
            template = dict(result._mapping)
            
            # Parse exercises if it's JSON string
            if isinstance(template['exercises'], str):
                try:
                    template['exercises'] = json.loads(template['exercises'])
                except:
                    pass

            # Parse scheduled_days if it's JSON string
            if isinstance(template['scheduled_days'], str):
                try:
                    template['scheduled_days'] = json.loads(template['scheduled_days'])
                except:
                    pass

            # Convert datetime objects to strings for JSON serialization
            if template.get('created_at'):
                template['created_at'] = template['created_at'].isoformat()
            if template.get('updated_at'):
                template['updated_at'] = template['updated_at'].isoformat()

            return ToolResult(
                success=True,
                message=f"Retrieved template '{template['name']}'",
                data=template
            )
            
        except Exception as e:
            return ToolResult(
                success=False,
                message=f"Failed to get template: {str(e)}",
                data=None
            )
        finally:
            db.close()


class TemplateCreateTool(BaseTool):
    """Create a new workout template"""

    @property
    def name(self) -> str:
        return "template_create"

    @property
    def description(self) -> str:
        return """Create a new workout template with exercises, sets, reps, and RPE targets.

        Example exercises format:
        [
            {"name": "Bench Press", "sets": 4, "reps": "6-8", "rpe_target": 8},
            {"name": "Incline DB Press", "sets": 3, "reps": "8-10", "rpe_target": 7},
            {"name": "Cable Fly", "sets": 3, "reps": "12-15", "rpe_target": 7}
        ]

        scheduled_days can be: ["monday"], ["monday", "thursday"], etc."""

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name of the template (e.g., 'Push Day A', 'Upper Body', 'Leg Day')"
                },
                "exercises": {
                    "type": "array",
                    "description": "List of exercises with sets, reps, and RPE targets",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Exercise name"},
                            "sets": {"type": "integer", "description": "Number of sets"},
                            "reps": {"type": "string", "description": "Rep range (e.g., '8-10', '5', '12-15')"},
                            "rpe_target": {"type": "number", "description": "Target RPE (1-10)"},
                            "notes": {"type": "string", "description": "Optional notes for this exercise"}
                        },
                        "required": ["name", "sets", "reps"]
                    }
                },
                "scheduled_days": {
                    "type": "array",
                    "description": "Days of the week this template is scheduled (e.g., ['monday', 'thursday'])",
                    "items": {"type": "string"}
                },
                "notes": {
                    "type": "string",
                    "description": "Optional notes about this template"
                },
                "phase_id": {
                    "type": "string",
                    "description": "Optional: ID of the training phase this template belongs to"
                }
            },
            "required": ["name", "exercises"]
        }

    async def execute(self, user_id: str, name: str, exercises: list,
                      scheduled_days: list = None, notes: str = None,
                      phase_id: str = None, **kwargs) -> ToolResult:
        """Create a new workout template"""
        import uuid
        db: Session = next(get_db())
        try:
            template_id = str(uuid.uuid4())

            query = text("""
                INSERT INTO fitness_template
                (id, user_id, name, exercises, scheduled_days, notes, phase_id, created_at, updated_at)
                VALUES (:id, :user_id, :name, :exercises, :scheduled_days, :notes, :phase_id, NOW(), NOW())
                RETURNING id, name
            """)

            result = db.execute(query, {
                "id": template_id,
                "user_id": user_id,
                "name": name,
                "exercises": json.dumps(exercises),
                "scheduled_days": json.dumps(scheduled_days) if scheduled_days else None,
                "notes": notes,
                "phase_id": phase_id
            })
            db.commit()

            row = result.fetchone()

            return ToolResult(
                success=True,
                message=f"Created workout template '{name}' with {len(exercises)} exercises",
                data={
                    "template_id": template_id,
                    "name": name,
                    "exercise_count": len(exercises),
                    "scheduled_days": scheduled_days
                }
            )

        except Exception as e:
            db.rollback()
            return ToolResult(
                success=False,
                message=f"Failed to create template: {str(e)}",
                data=None
            )
        finally:
            db.close()


class TemplateUpdateTool(BaseTool):
    """Update an existing workout template"""

    @property
    def name(self) -> str:
        return "template_update"

    @property
    def description(self) -> str:
        return """Update an existing workout template. Can update name, exercises, scheduled days, or notes.
        Only provide the fields you want to update."""

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "template_id": {
                    "type": "string",
                    "description": "ID of the template to update"
                },
                "template_name": {
                    "type": "string",
                    "description": "Alternatively, name of template to update (partial match)"
                },
                "name": {
                    "type": "string",
                    "description": "New name for the template"
                },
                "exercises": {
                    "type": "array",
                    "description": "New list of exercises (replaces existing)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "sets": {"type": "integer"},
                            "reps": {"type": "string"},
                            "rpe_target": {"type": "number"},
                            "notes": {"type": "string"}
                        }
                    }
                },
                "scheduled_days": {
                    "type": "array",
                    "description": "New scheduled days",
                    "items": {"type": "string"}
                },
                "notes": {
                    "type": "string",
                    "description": "New notes"
                }
            }
        }

    async def execute(self, user_id: str, template_id: str = None, template_name: str = None,
                      name: str = None, exercises: list = None, scheduled_days: list = None,
                      notes: str = None, **kwargs) -> ToolResult:
        """Update a workout template"""
        db: Session = next(get_db())
        try:
            # Find template by ID or name
            if template_id:
                find_query = text("SELECT id, name FROM fitness_template WHERE user_id = :user_id AND id = :id")
                existing = db.execute(find_query, {"user_id": user_id, "id": template_id}).fetchone()
            elif template_name:
                find_query = text("SELECT id, name FROM fitness_template WHERE user_id = :user_id AND LOWER(name) LIKE LOWER(:pattern) LIMIT 1")
                existing = db.execute(find_query, {"user_id": user_id, "pattern": f"%{template_name}%"}).fetchone()
            else:
                return ToolResult(success=False, message="Either template_id or template_name required", data=None)

            if not existing:
                return ToolResult(success=False, message="Template not found", data=None)

            template_id = existing.id
            old_name = existing.name

            # Build update query dynamically
            updates = []
            params = {"user_id": user_id, "id": template_id}

            if name is not None:
                updates.append("name = :name")
                params["name"] = name
            if exercises is not None:
                updates.append("exercises = :exercises")
                params["exercises"] = json.dumps(exercises)
            if scheduled_days is not None:
                updates.append("scheduled_days = :scheduled_days")
                params["scheduled_days"] = json.dumps(scheduled_days)
            if notes is not None:
                updates.append("notes = :notes")
                params["notes"] = notes

            if not updates:
                return ToolResult(success=False, message="No updates provided", data=None)

            updates.append("updated_at = NOW()")

            query = text(f"UPDATE fitness_template SET {', '.join(updates)} WHERE user_id = :user_id AND id = :id")
            db.execute(query, params)
            db.commit()

            return ToolResult(
                success=True,
                message=f"Updated template '{old_name}'",
                data={"template_id": template_id, "updated_fields": list(params.keys())}
            )

        except Exception as e:
            db.rollback()
            return ToolResult(success=False, message=f"Failed to update template: {str(e)}", data=None)
        finally:
            db.close()


class TemplateDeleteTool(BaseTool):
    """Delete a workout template"""

    @property
    def name(self) -> str:
        return "template_delete"

    @property
    def description(self) -> str:
        return "Delete a workout template by ID or name"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "template_id": {
                    "type": "string",
                    "description": "ID of the template to delete"
                },
                "template_name": {
                    "type": "string",
                    "description": "Alternatively, name of template to delete (partial match)"
                }
            }
        }

    async def execute(self, user_id: str, template_id: str = None, template_name: str = None, **kwargs) -> ToolResult:
        """Delete a workout template"""
        db: Session = next(get_db())
        try:
            # Find template
            if template_id:
                find_query = text("SELECT id, name FROM fitness_template WHERE user_id = :user_id AND id = :id")
                existing = db.execute(find_query, {"user_id": user_id, "id": template_id}).fetchone()
            elif template_name:
                find_query = text("SELECT id, name FROM fitness_template WHERE user_id = :user_id AND LOWER(name) LIKE LOWER(:pattern) LIMIT 1")
                existing = db.execute(find_query, {"user_id": user_id, "pattern": f"%{template_name}%"}).fetchone()
            else:
                return ToolResult(success=False, message="Either template_id or template_name required", data=None)

            if not existing:
                return ToolResult(success=False, message="Template not found", data=None)

            template_id = existing.id
            template_name = existing.name

            # Delete the template
            delete_query = text("DELETE FROM fitness_template WHERE user_id = :user_id AND id = :id")
            db.execute(delete_query, {"user_id": user_id, "id": template_id})
            db.commit()

            return ToolResult(
                success=True,
                message=f"Deleted template '{template_name}'",
                data={"template_id": template_id, "name": template_name}
            )

        except Exception as e:
            db.rollback()
            return ToolResult(success=False, message=f"Failed to delete template: {str(e)}", data=None)
        finally:
            db.close()
