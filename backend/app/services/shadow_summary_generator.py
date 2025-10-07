"""
Shadow Summary Generator
Generates end-of-session summaries using LLM
"""
import logging
import json
from typing import Dict, List, Any, Optional
from datetime import datetime
from sqlalchemy.orm import Session

from app.models.shadow import ShadowSession, ShadowEvent, ShadowNote, ShadowSummary
from app.db.session import SessionLocal
from app.services.shadow_classifier import shadow_classifier
from app.core.config import settings
import httpx

logger = logging.getLogger(__name__)


class ShadowSummaryGenerator:
    """Generate intelligent session summaries"""

    def __init__(self):
        self.llm_base_url = settings.openai_base_url
        self.llm_model = settings.openai_model
        logger.info("📊 ShadowSummaryGenerator initialized")

    async def generate_summary(self, session_id: str) -> ShadowSummary:
        """
        Generate comprehensive summary for a wrapped session
        Returns ShadowSummary object
        """
        db = SessionLocal()
        try:
            # Get session with all events and notes
            session = db.query(ShadowSession).filter(ShadowSession.id == session_id).first()
            if not session:
                raise ValueError(f"Session {session_id} not found")

            if session.status != "wrapped":
                raise ValueError(f"Can only generate summary for wrapped sessions (current: {session.status})")

            # Check if summary already exists
            existing_summary = db.query(ShadowSummary).filter(
                ShadowSummary.session_id == session_id
            ).first()

            if existing_summary:
                logger.info(f"Summary already exists for session {session_id}, returning existing")
                return existing_summary

            # Gather all events and notes
            events = db.query(ShadowEvent).filter(
                ShadowEvent.session_id == session_id
            ).order_by(ShadowEvent.timestamp).all()

            notes = db.query(ShadowNote).filter(
                ShadowNote.session_id == session_id
            ).order_by(ShadowNote.timestamp).all()

            # Classify events if not already classified
            for event in events:
                if not event.classified_as:
                    event.classified_as = shadow_classifier.classify_event(
                        event.event_type,
                        event.event_metadata or {}
                    )
                    event.tags = shadow_classifier.extract_tags(
                        str(event.event_metadata),
                        event.event_type
                    )

            db.commit()

            # Aggregate into summary sections
            summary_data = await self._aggregate_summary(session, events, notes)

            # Generate timeline
            timeline = self._generate_timeline(events, notes)

            # Generate changeset
            changeset = self._generate_changeset(events)

            # Generate full text markdown summary
            full_text = await self._generate_markdown_summary(
                session, summary_data, timeline, changeset
            )

            # Create summary record
            summary = ShadowSummary(
                session_id=session_id,
                decisions=summary_data["decisions"],
                tasks=summary_data["tasks"],
                questions=summary_data["questions"],
                ideas=summary_data["ideas"],
                refs=summary_data["references"],
                timeline=timeline,
                changeset=changeset,
                full_text=full_text,
                committed=False
            )

            db.add(summary)
            db.commit()
            db.refresh(summary)

            logger.info(f"📊 Generated summary for session {session_id}: {len(summary_data['tasks'])} tasks, {len(summary_data['decisions'])} decisions")
            return summary

        finally:
            db.close()

    async def _aggregate_summary(
        self, session: ShadowSession, events: List[ShadowEvent], notes: List[ShadowNote]
    ) -> Dict[str, List]:
        """Aggregate events and notes into summary categories"""

        summary = {
            "decisions": [],
            "tasks": [],
            "questions": [],
            "ideas": [],
            "references": []
        }

        # Process user notes (high priority)
        for note in notes:
            item = {
                "content": note.content,
                "source": "note",
                "timestamp": note.timestamp.isoformat()
            }

            if note.note_type == "task" and note.due_date:
                item["due"] = note.due_date.isoformat()

            category_map = {
                "task": "tasks",
                "decision": "decisions",
                "question": "questions",
                "idea": "ideas",
                "bookmark": "references"
            }

            category = category_map.get(note.note_type, "references")
            summary[category].append(item)

        # Process classified events
        event_groups = {
            "task": [],
            "decision": [],
            "question": [],
            "idea": [],
            "reference": []
        }

        for event in events:
            if event.classified_as:
                event_groups[event.classified_as].append(event)

        # Add significant events to summary
        for event in event_groups["decision"]:
            if event.event_metadata:
                content = self._extract_event_description(event)
                if content:
                    summary["decisions"].append({
                        "content": content,
                        "source": "event",
                        "timestamp": event.timestamp.isoformat()
                    })

        # Add reference items (files, URLs)
        unique_refs = set()
        for event in event_groups["reference"]:
            ref_item = self._extract_reference(event)
            if ref_item:
                ref_key = (ref_item["type"], ref_item.get("path") or ref_item.get("url"))
                if ref_key not in unique_refs:
                    unique_refs.add(ref_key)
                    summary["references"].append(ref_item)

        return summary

    def _extract_event_description(self, event: ShadowEvent) -> Optional[str]:
        """Extract human-readable description from event metadata"""
        metadata = event.event_metadata or {}

        if event.event_type == "terminal":
            command = metadata.get("command", "")
            if "git commit" in command:
                commit_msg = metadata.get("commit_message", "")
                return f"Committed: {commit_msg}" if commit_msg else None

        elif event.event_type == "editor":
            file_path = metadata.get("file_path", "")
            action = metadata.get("action", "")
            if action == "save":
                return f"Modified {file_path}"

        return None

    def _extract_reference(self, event: ShadowEvent) -> Optional[Dict[str, str]]:
        """Extract reference item from event"""
        metadata = event.event_metadata or {}

        if event.event_type == "browser":
            return {
                "type": "url",
                "url": metadata.get("url", ""),
                "title": metadata.get("title", "")
            }

        elif event.event_type == "editor":
            file_path = metadata.get("file_path", "")
            if file_path:
                return {
                    "type": "file",
                    "path": file_path
                }

        return None

    def _generate_timeline(self, events: List[ShadowEvent], notes: List[ShadowNote]) -> List[Dict]:
        """Generate compressed timeline (2-5 minute windows)"""
        # Simple implementation: group by 5-minute windows
        timeline = []
        window_minutes = 5

        # Combine and sort events
        all_items = []
        for event in events:
            all_items.append({
                "timestamp": event.timestamp,
                "type": "event",
                "description": self._extract_event_description(event) or f"{event.event_type} activity"
            })

        for note in notes:
            all_items.append({
                "timestamp": note.timestamp,
                "type": "note",
                "description": f"{note.note_type}: {note.content[:50]}"
            })

        all_items.sort(key=lambda x: x["timestamp"])

        # Group into windows
        current_window = None
        current_activities = []

        for item in all_items:
            window_key = item["timestamp"].replace(
                minute=(item["timestamp"].minute // window_minutes) * window_minutes,
                second=0,
                microsecond=0
            )

            if current_window is None or window_key != current_window:
                if current_activities:
                    timeline.append({
                        "time": current_window.strftime("%H:%M"),
                        "activities": current_activities[:3]  # Max 3 per window
                    })
                current_window = window_key
                current_activities = []

            current_activities.append(item["description"])

        # Add final window
        if current_activities:
            timeline.append({
                "time": current_window.strftime("%H:%M"),
                "activities": current_activities[:3]
            })

        return timeline

    def _generate_changeset(self, events: List[ShadowEvent]) -> Dict[str, List]:
        """Generate changeset (files modified, commits)"""
        files_modified = set()
        commits = []

        for event in events:
            metadata = event.event_metadata or {}

            if event.event_type == "editor" and metadata.get("action") == "save":
                file_path = metadata.get("file_path")
                if file_path:
                    files_modified.add(file_path)

            elif event.event_type == "terminal" and "git commit" in metadata.get("command", ""):
                commit_msg = metadata.get("commit_message")
                if commit_msg:
                    commits.append({
                        "message": commit_msg,
                        "timestamp": event.timestamp.isoformat()
                    })

        return {
            "files": list(files_modified),
            "commits": commits
        }

    async def _generate_markdown_summary(
        self,
        session: ShadowSession,
        summary_data: Dict,
        timeline: List,
        changeset: Dict
    ) -> str:
        """Generate full markdown summary (simple template for MVP)"""

        # For MVP, use simple template instead of LLM
        # Can enhance with LLM later for better prose

        lines = []
        lines.append(f"# Shadow Session Summary")
        lines.append(f"")
        lines.append(f"**Date:** {session.started_at.strftime('%Y-%m-%d %H:%M')}")
        lines.append(f"**Duration:** {int((session.ended_at - session.started_at).total_seconds() / 60)} minutes")
        if session.context:
            lines.append(f"**Context:** {session.context}")
        lines.append(f"")

        # Decisions
        if summary_data["decisions"]:
            lines.append(f"## Decisions")
            for item in summary_data["decisions"]:
                lines.append(f"- {item['content']}")
            lines.append(f"")

        # Tasks
        if summary_data["tasks"]:
            lines.append(f"## Tasks")
            for item in summary_data["tasks"]:
                task_line = f"- {item['content']}"
                if item.get("due"):
                    task_line += f" (due: {item['due'][:10]})"
                lines.append(task_line)
            lines.append(f"")

        # Questions
        if summary_data["questions"]:
            lines.append(f"## Questions")
            for item in summary_data["questions"]:
                lines.append(f"- {item['content']}")
            lines.append(f"")

        # Ideas
        if summary_data["ideas"]:
            lines.append(f"## Ideas")
            for item in summary_data["ideas"]:
                lines.append(f"- {item['content']}")
            lines.append(f"")

        # References
        if summary_data["references"]:
            lines.append(f"## References")
            for item in summary_data["references"]:
                if item["type"] == "url":
                    lines.append(f"- [{item.get('title', 'Link')}]({item['url']})")
                elif item["type"] == "file":
                    lines.append(f"- File: `{item['path']}`")
            lines.append(f"")

        # Changeset
        if changeset["files"] or changeset["commits"]:
            lines.append(f"## Changes")
            if changeset["files"]:
                lines.append(f"**Files modified:** {len(changeset['files'])}")
                for file in changeset["files"][:10]:  # Max 10
                    lines.append(f"- `{file}`")
            if changeset["commits"]:
                lines.append(f"**Commits:** {len(changeset['commits'])}")
                for commit in changeset["commits"]:
                    lines.append(f"- {commit['message']}")
            lines.append(f"")

        return "\n".join(lines)


# Global service instance
shadow_summary_generator = ShadowSummaryGenerator()
