"""
Calendar Monitor

This monitor checks for calendar issues:
- Double-bookings and overlaps
- Unrealistic travel times
- Missing location information
- Long meetings without breaks
"""

from typing import List, Dict, Any
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy import or_
import logging

from app.models.calendar_event import CalendarEvent
from app.models.jarvis_inbox import InboxKind
from app.services.jarvis_inbox_service import inbox_service

logger = logging.getLogger(__name__)


class CalendarMonitor:
    """Calendar monitoring for proactive issue detection"""

    def __init__(self):
        self.enabled = True
        self.check_interval_minutes = 30
        self.lookahead_hours = 4  # Check next 4 hours
        self.min_travel_gap_minutes = 15  # Minimum time between events at different locations
        self.marathon_threshold_hours = 2  # Meetings >= 2 hours flagged as marathon
    
    async def run_checks(self, db: Session, user_id: int) -> Dict[str, Any]:
        """
        Run all calendar checks and create inbox items for issues.

        Checks:
        - Double-bookings and overlaps
        - Travel time conflicts
        - Long meetings without breaks
        - Missing locations for upcoming events

        Returns:
            Summary of issues found and actions taken
        """
        if not self.enabled:
            logger.debug("Calendar monitor is disabled")
            return {'status': 'disabled', 'issues_found': 0}

        issues = []

        # Run all checks
        try:
            overlaps = self._check_overlaps(db, user_id)
            issues.extend(overlaps)

            travel_issues = self._check_travel_times(db, user_id)
            issues.extend(travel_issues)

            marathon_issues = self._check_marathon_meetings(db, user_id)
            issues.extend(marathon_issues)

            location_issues = self._check_missing_locations(db, user_id)
            issues.extend(location_issues)

            # Create inbox item if issues found
            if issues:
                await self._create_calendar_inbox_item(db, user_id, issues)
                logger.info(f"📅 Calendar monitor found {len(issues)} issues for user {user_id}")

        except Exception as e:
            logger.error(f"Calendar monitor error: {e}")
            return {'status': 'error', 'error': str(e), 'issues_found': 0}

        return {
            'status': 'completed',
            'issues_found': len(issues),
            'issues': issues,
            'checks_run': ['overlaps', 'travel', 'marathon', 'locations']
        }
    
    def _check_overlaps(self, db: Session, user_id: int) -> List[Dict]:
        """Check for overlapping calendar events in the lookahead window"""
        now = datetime.now(timezone.utc)
        future = now + timedelta(hours=self.lookahead_hours)

        events = db.query(CalendarEvent).filter(
            CalendarEvent.user_id == user_id,
            CalendarEvent.start_time >= now,
            CalendarEvent.start_time <= future
        ).order_by(CalendarEvent.start_time).all()

        issues = []
        for i, event in enumerate(events):
            for other in events[i + 1:]:
                # Check overlap: event ends after other starts
                if event.end_time and event.end_time > other.start_time:
                    issues.append({
                        "type": "overlap",
                        "severity": "high",
                        "event1": {"id": event.id, "title": event.title, "start": event.start_time.isoformat()},
                        "event2": {"id": other.id, "title": other.title, "start": other.start_time.isoformat()},
                        "message": f"'{event.title}' overlaps with '{other.title}'"
                    })

        return issues

    def _check_travel_times(self, db: Session, user_id: int) -> List[Dict]:
        """Check for unrealistic travel times between consecutive events with different locations"""
        now = datetime.now(timezone.utc)
        future = now + timedelta(hours=self.lookahead_hours)

        # Get events with locations, ordered by start time
        events = db.query(CalendarEvent).filter(
            CalendarEvent.user_id == user_id,
            CalendarEvent.start_time >= now,
            CalendarEvent.start_time <= future,
            CalendarEvent.location.isnot(None),
            CalendarEvent.location != ""
        ).order_by(CalendarEvent.start_time).all()

        issues = []
        for i in range(len(events) - 1):
            current = events[i]
            next_event = events[i + 1]

            # Skip if no end time on current event
            if not current.end_time:
                continue

            gap_minutes = (next_event.start_time - current.end_time).total_seconds() / 60

            # If different locations and gap is less than minimum travel time
            if current.location != next_event.location and gap_minutes < self.min_travel_gap_minutes:
                issues.append({
                    "type": "travel_time",
                    "severity": "medium",
                    "from_event": {"id": current.id, "title": current.title, "location": current.location},
                    "to_event": {"id": next_event.id, "title": next_event.title, "location": next_event.location},
                    "gap_minutes": round(gap_minutes, 1),
                    "message": f"Only {gap_minutes:.0f}min between '{current.title}' and '{next_event.title}' at different locations"
                })

        return issues

    def _check_marathon_meetings(self, db: Session, user_id: int) -> List[Dict]:
        """Check for long meetings that might need breaks"""
        now = datetime.now(timezone.utc)
        future = now + timedelta(hours=self.lookahead_hours)

        events = db.query(CalendarEvent).filter(
            CalendarEvent.user_id == user_id,
            CalendarEvent.start_time >= now,
            CalendarEvent.start_time <= future
        ).all()

        issues = []
        for event in events:
            if not event.end_time:
                continue

            duration_hours = (event.end_time - event.start_time).total_seconds() / 3600

            if duration_hours >= self.marathon_threshold_hours:
                issues.append({
                    "type": "marathon_meeting",
                    "severity": "low",
                    "event": {"id": event.id, "title": event.title, "start": event.start_time.isoformat()},
                    "duration_hours": round(duration_hours, 1),
                    "message": f"'{event.title}' is {duration_hours:.1f} hours - consider adding breaks"
                })

        return issues

    def _check_missing_locations(self, db: Session, user_id: int) -> List[Dict]:
        """Check for events starting soon that are missing location information"""
        now = datetime.now(timezone.utc)
        soon = now + timedelta(hours=1)  # Only check next hour for urgency

        events = db.query(CalendarEvent).filter(
            CalendarEvent.user_id == user_id,
            CalendarEvent.start_time >= now,
            CalendarEvent.start_time <= soon,
            or_(CalendarEvent.location == None, CalendarEvent.location == "")
        ).all()

        issues = []
        for event in events:
            starts_in_minutes = (event.start_time - now).total_seconds() / 60
            issues.append({
                "type": "missing_location",
                "severity": "medium",
                "event": {"id": event.id, "title": event.title, "start": event.start_time.isoformat()},
                "starts_in_minutes": round(starts_in_minutes, 0),
                "message": f"'{event.title}' starting in {starts_in_minutes:.0f}min has no location"
            })

        return issues
    
    async def _create_calendar_inbox_item(self, db: Session, user_id: int, issues: List[Dict]):
        """Create inbox item summarizing calendar issues with priority based on severity"""
        # Count by severity
        high_count = sum(1 for i in issues if i.get("severity") == "high")
        medium_count = sum(1 for i in issues if i.get("severity") == "medium")

        # Priority based on severity (higher = more urgent)
        priority = 5
        if high_count > 0:
            priority = 9
        elif medium_count > 0:
            priority = 7

        # Build descriptive title
        issue_types = list(set(i.get("type") for i in issues))
        type_labels = {
            "overlap": "conflicts",
            "travel_time": "travel issues",
            "marathon_meeting": "long meetings",
            "missing_location": "missing locations"
        }
        type_summary = ", ".join(type_labels.get(t, t) for t in issue_types[:2])

        title = f"Calendar: {len(issues)} issue{'s' if len(issues) != 1 else ''} - {type_summary}"

        # Build body with issue summaries
        body_lines = [f"Found {len(issues)} calendar issues for the next {self.lookahead_hours} hours:"]
        for issue in issues[:5]:  # Limit to first 5 in body
            body_lines.append(f"• {issue.get('message', 'Unknown issue')}")
        if len(issues) > 5:
            body_lines.append(f"... and {len(issues) - 5} more")

        body = "\n".join(body_lines)

        inbox_service.create_inbox_item(
            db=db,
            user_id=user_id,
            kind=InboxKind.ALERT,
            title=title,
            body=body,
            source="calendar_monitor",
            payload={"issues": issues, "high_severity": high_count, "medium_severity": medium_count},
            priority=priority,
            dedupe_key=f"calendar_issues_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
        )


# Global instance
calendar_monitor = CalendarMonitor()