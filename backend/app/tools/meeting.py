"""Meeting prep chat tool — "who am I meeting with / prep me for my 2pm"."""

import logging
from datetime import timedelta
from typing import Any, Dict

from sqlalchemy import text

from app.tools.base import BaseTool, ToolResult
from app.core.timezone import now as local_now
from app.services import meeting_research as mr

logger = logging.getLogger(__name__)


def _get_db():
    from app.db.session import get_db
    return next(get_db())


async def _start_company_research(user_id: str, company: str, event_title: str) -> bool:
    """Hand a company off to the background research agent (reuses research_plan)."""
    try:
        from app.tools.research_plan import CreateResearchPlanTool
        tool = CreateResearchPlanTool()
        res = await tool.execute(
            user_id,
            title=f"{company} — meeting prep",
            objective=(
                f"Brief David before his meeting ('{event_title}') with {company}: "
                f"what the company does, who their leadership is, recent news, and "
                f"anything relevant to a sales or partnership conversation."
            ),
            steps=[
                {"title": "Company overview",
                 "description": f"What does {company} do — industry, size, products, business model. Find their website/domain."},
                {"title": "Leadership & people",
                 "description": f"Key executives and decision-makers at {company}."},
                {"title": "Recent news",
                 "description": f"News, funding, or announcements about {company} in the last 6 months."},
            ],
            auto_start=True,
        )
        return bool(getattr(res, "success", False))
    except Exception as e:
        logger.error("Failed to start company research for %s: %s", company, e)
        return False


class MeetingPrepTool(BaseTool):
    """Prep David for an upcoming business meeting/demo."""

    @property
    def name(self) -> str:
        return "meeting_prep"

    @property
    def description(self) -> str:
        return (
            "Prep David for an upcoming meeting or demo. Use when he asks 'who am I "
            "meeting with', 'prep me for my next meeting', 'what do I need to know "
            "before my 2pm', or about an upcoming call with a company or person. "
            "Identifies the counterparty company (from the event title and matched "
            "meeting-invite emails), surfaces the last email thread, and — for an "
            "external business meeting with no background yet — kicks off company "
            "research in the background. Covers only David's own business meetings, "
            "never gym, family, or personal events."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Optional words matching the specific event title (e.g. 'IRMI', 'Amplo'). Omit for the next upcoming business meeting.",
                },
                "within_days": {
                    "type": "integer",
                    "description": "How many days ahead to search (default 14).",
                    "default": 14,
                },
                "research": {
                    "type": "boolean",
                    "description": "Kick off background company research if none exists yet (default true).",
                    "default": True,
                },
            },
            "required": [],
        }

    async def execute(self, user_id: str, **kwargs) -> ToolResult:
        query = (kwargs.get("query") or "").strip()
        within_days = int(kwargs.get("within_days") or 14)
        do_research = kwargs.get("research", True)

        db = _get_db()
        try:
            now = local_now().replace(tzinfo=None)
            rows = db.execute(
                text("""
                    SELECT id, title, description, location, start_time, ios_calendar_name
                    FROM calendar_event
                    WHERE user_id = :uid
                      AND start_time > :now
                      AND start_time < :end
                    ORDER BY start_time ASC
                    LIMIT 50
                """),
                {"uid": user_id, "now": now, "end": now + timedelta(days=within_days)},
            ).mappings().all()

            if not rows:
                return ToolResult(
                    success=True,
                    message=f"No upcoming events in the next {within_days} days.",
                )

            # Pick the event: explicit query match first, else the next event
            # that reads as a business meeting, else just the next event.
            chosen = None
            if query:
                qtokens = mr._tokens(query)
                for r in rows:
                    if qtokens & mr._tokens(r["title"]):
                        chosen = dict(r)
                        break
            if not chosen:
                for r in rows:
                    related = mr.find_related_invite(db, user_id, r["title"], r["start_time"])
                    if mr.is_business_meeting(r["title"], r["ios_calendar_name"], related):
                        chosen = dict(r)
                        break
            if not chosen:
                chosen = dict(rows[0])

            prep = mr.build_prep(db, user_id, chosen)
            message = mr.format_prep(prep)

            triggered = []
            if do_research and prep["is_business_meeting"]:
                already = {r["company"].lower() for r in prep["research"]}
                for company in prep["companies"][:2]:
                    if company.lower() in already or mr.recent_research(db, user_id, company):
                        continue
                    if await _start_company_research(user_id, company, chosen["title"]):
                        triggered.append(company)
            if triggered:
                message += (
                    "\n\nKicked off background research on: "
                    + ", ".join(triggered)
                    + ". I'll have findings ready shortly."
                )

            return ToolResult(success=True, data=prep, message=message)
        except Exception as e:
            logger.error("meeting_prep failed: %s", e, exc_info=True)
            return ToolResult(success=False, message=f"Couldn't build meeting prep: {e}")
        finally:
            db.close()
