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
