"""
Soul Layer tools.

These tools allow Sara to view and propose changes to her own identity document.
Changes require David's approval before being applied.
"""
from typing import Dict, Any
from datetime import datetime, timezone
from app.tools.base import BaseTool, ToolResult
from app.db.session import get_db
from sqlalchemy.orm import Session
from sqlalchemy import text


class ViewSoulTool(BaseTool):
    """Tool for viewing Sara's current Soul configuration"""

    @property
    def name(self) -> str:
        return "view_soul"

    @property
    def description(self) -> str:
        return """View Sara's current Soul configuration. Use when discussing identity, operating principles,
or how Sara should behave. The Soul contains Sara's core identity document with sections:
- identity: Who Sara is, her voice and personality
- principles: Operating principles and behavioral rules
- boundaries: Things Sara won't do or lines she won't cross
- growth: Current growth areas and learning focus
- evolution_log: History of changes to the Soul"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "enum": ["all", "identity", "principles", "boundaries", "growth", "evolution_log"],
                    "description": "Which section to view. Use 'all' to see the complete Soul."
                }
            },
            "required": ["section"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """View Sara's Soul configuration"""

        section = kwargs.get("section", "all")

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            if section == "all":
                # Get all sections
                result = db.execute(text("""
                    SELECT section, content, version, updated_at, updated_by
                    FROM sara_soul
                    ORDER BY CASE section
                        WHEN 'identity' THEN 1
                        WHEN 'principles' THEN 2
                        WHEN 'boundaries' THEN 3
                        WHEN 'growth' THEN 4
                        WHEN 'evolution_log' THEN 5
                    END
                """)).fetchall()

                if not result:
                    return ToolResult(
                        success=True,
                        data={"sections": []},
                        message="Soul has not been initialized yet."
                    )

                sections = []
                for row in result:
                    sections.append({
                        "section": row.section,
                        "content": row.content,
                        "version": row.version,
                        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                        "updated_by": row.updated_by
                    })

                return ToolResult(
                    success=True,
                    data={"sections": sections},
                    message=f"Retrieved {len(sections)} Soul sections"
                )
            else:
                # Get specific section
                result = db.execute(text("""
                    SELECT section, content, version, updated_at, updated_by
                    FROM sara_soul
                    WHERE section = :section
                """), {"section": section}).fetchone()

                if not result:
                    return ToolResult(
                        success=False,
                        message=f"Soul section '{section}' not found"
                    )

                return ToolResult(
                    success=True,
                    data={
                        "section": result.section,
                        "content": result.content,
                        "version": result.version,
                        "updated_at": result.updated_at.isoformat() if result.updated_at else None,
                        "updated_by": result.updated_by
                    },
                    message=f"Retrieved Soul section: {section}"
                )

        except Exception as e:
            return ToolResult(
                success=False,
                message=f"Failed to view Soul: {str(e)}"
            )
        finally:
            db.close()


class ProposeSoulChangeTool(BaseTool):
    """Tool for proposing changes to Sara's Soul"""

    @property
    def name(self) -> str:
        return "propose_soul_change"

    @property
    def description(self) -> str:
        return """Propose a change to Sara's own operating principles, boundaries, or identity.
Use when you've observed a pattern worth codifying or received feedback that should become permanent.
The proposal will be surfaced to David for approval - Sara should mention the proposal naturally in conversation.

Examples of when to use:
- Noticed David prefers bullet points for fitness summaries → propose adding to principles
- David said 'never guilt me about workouts' → propose adding to boundaries
- Learned a new skill or capability → propose adding to growth areas"""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "enum": ["identity", "principles", "boundaries", "growth"],
                    "description": "Which section of the Soul to modify"
                },
                "proposed_change": {
                    "type": "string",
                    "description": "The specific change to make. This should be the NEW content for the section (or addition to it)."
                },
                "rationale": {
                    "type": "string",
                    "description": "Why this change makes sense based on observations or feedback"
                }
            },
            "required": ["section", "proposed_change", "rationale"]
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """Create a Soul change proposal"""

        section = kwargs.get("section")
        proposed_change = kwargs.get("proposed_change")
        rationale = kwargs.get("rationale")

        if not section or not proposed_change or not rationale:
            return ToolResult(
                success=False,
                message="Section, proposed_change, and rationale are all required"
            )

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            # Get current content for this section
            current = db.execute(text("""
                SELECT content FROM sara_soul WHERE section = :section
            """), {"section": section}).fetchone()

            current_content = current.content if current else None

            # Check for existing pending proposal for same section
            existing = db.execute(text("""
                SELECT id FROM soul_change_proposals
                WHERE section = :section AND status = 'pending'
            """), {"section": section}).fetchone()

            if existing:
                return ToolResult(
                    success=False,
                    message=f"There's already a pending proposal for the '{section}' section. Wait for it to be resolved first."
                )

            # Create the proposal
            db.execute(text("""
                INSERT INTO soul_change_proposals (section, current_content, proposed_content, rationale, status, proposed_at)
                VALUES (:section, :current_content, :proposed_content, :rationale, 'pending', NOW())
            """), {
                "section": section,
                "current_content": current_content,
                "proposed_content": proposed_change,
                "rationale": rationale
            })

            db.commit()

            return ToolResult(
                success=True,
                data={
                    "section": section,
                    "current_content": current_content,
                    "proposed_content": proposed_change,
                    "rationale": rationale,
                    "status": "pending"
                },
                message=f"Created Soul change proposal for '{section}' section. Surface this to David for approval."
            )

        except Exception as e:
            db.rollback()
            return ToolResult(
                success=False,
                message=f"Failed to create Soul proposal: {str(e)}"
            )
        finally:
            db.close()


class ListSoulProposalsTool(BaseTool):
    """Tool for listing pending Soul change proposals"""

    @property
    def name(self) -> str:
        return "list_soul_proposals"

    @property
    def description(self) -> str:
        return "List pending Soul change proposals that need David's approval."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["pending", "approved", "rejected", "all"],
                    "description": "Filter by status. Default is 'pending'."
                }
            }
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        """List Soul change proposals"""

        status = kwargs.get("status", "pending")

        db_gen = get_db()
        db: Session = next(db_gen)

        try:
            if status == "all":
                result = db.execute(text("""
                    SELECT id, section, current_content, proposed_content, rationale,
                           status, rejection_reason, proposed_at, resolved_at
                    FROM soul_change_proposals
                    ORDER BY proposed_at DESC
                    LIMIT 20
                """)).fetchall()
            else:
                result = db.execute(text("""
                    SELECT id, section, current_content, proposed_content, rationale,
                           status, rejection_reason, proposed_at, resolved_at
                    FROM soul_change_proposals
                    WHERE status = :status
                    ORDER BY proposed_at DESC
                    LIMIT 20
                """), {"status": status}).fetchall()

            proposals = []
            for row in result:
                proposals.append({
                    "id": row.id,
                    "section": row.section,
                    "current_content": row.current_content[:200] + "..." if row.current_content and len(row.current_content) > 200 else row.current_content,
                    "proposed_content": row.proposed_content[:200] + "..." if len(row.proposed_content) > 200 else row.proposed_content,
                    "rationale": row.rationale,
                    "status": row.status,
                    "rejection_reason": row.rejection_reason,
                    "proposed_at": row.proposed_at.isoformat() if row.proposed_at else None,
                    "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None
                })

            return ToolResult(
                success=True,
                data={"proposals": proposals},
                message=f"Found {len(proposals)} {status} proposal(s)"
            )

        except Exception as e:
            return ToolResult(
                success=False,
                message=f"Failed to list Soul proposals: {str(e)}"
            )
        finally:
            db.close()


# Export tools
SOUL_TOOLS = [
    ViewSoulTool(),
    ProposeSoulChangeTool(),
    ListSoulProposalsTool(),
]
