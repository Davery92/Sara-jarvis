"""
Archiver - Daily brief archival and pattern analysis
Archives day layers nightly for historical analysis.
"""
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)

# Base directory for brief files
BRIEFS_DIR = Path("/home/david/jarvis/data/briefs")


class Archiver:
    """
    Handles archival of daily briefs for pattern analysis.
    Archives are organized by date: archive/YYYY/MM/DD/
    """

    def __init__(self):
        self.briefs_dir = BRIEFS_DIR

    def _get_archive_dir(self, user_id: str, date: datetime) -> Path:
        """Get archive directory for a specific date."""
        archive_dir = (
            self.briefs_dir / user_id / "archive" /
            date.strftime("%Y") / date.strftime("%m") / date.strftime("%d")
        )
        archive_dir.mkdir(parents=True, exist_ok=True)
        return archive_dir

    async def archive_day_layer(
        self,
        user_id: str,
        content: str,
        archive_date: Optional[datetime] = None
    ):
        """
        Archive a day layer to the archive directory.
        Called when day rolls over or manually.
        """
        archive_date = archive_date or (datetime.now() - timedelta(days=1))
        archive_dir = self._get_archive_dir(user_id, archive_date)

        # Write day layer content
        day_path = archive_dir / "day.md"
        day_path.write_text(content)

        # Write metadata
        metadata = {
            "archived_at": datetime.now().isoformat(),
            "archive_date": archive_date.strftime("%Y-%m-%d"),
            "content_length": len(content),
            "type": "day_layer"
        }
        metadata_path = archive_dir / "metadata.json"
        metadata_path.write_text(json.dumps(metadata, indent=2))

        logger.info(f"📦 Archived day layer for {user_id[:8]} to {archive_date.date()}")

    async def archive_compiled_brief(
        self,
        user_id: str,
        content: str,
        archive_date: Optional[datetime] = None
    ):
        """
        Archive the compiled brief for a specific date.
        Called during nightly processing.
        """
        archive_date = archive_date or datetime.now()
        archive_dir = self._get_archive_dir(user_id, archive_date)

        compiled_path = archive_dir / "compiled.md"
        compiled_path.write_text(content)

        logger.info(f"📦 Archived compiled brief for {user_id[:8]} to {archive_date.date()}")

    def get_recent_archives(
        self,
        user_id: str,
        days: int = 7
    ) -> List[Dict]:
        """
        Get archived day layers from the past N days.
        Returns list of {date, content} dicts.
        """
        archives = []
        user_archive_dir = self.briefs_dir / user_id / "archive"

        if not user_archive_dir.exists():
            return []

        # Check each of the past N days
        for i in range(days):
            check_date = datetime.now() - timedelta(days=i + 1)
            archive_dir = (
                user_archive_dir /
                check_date.strftime("%Y") /
                check_date.strftime("%m") /
                check_date.strftime("%d")
            )

            day_path = archive_dir / "day.md"
            if day_path.exists():
                archives.append({
                    "date": check_date.strftime("%Y-%m-%d"),
                    "content": day_path.read_text(),
                    "day_of_week": check_date.strftime("%A")
                })

        return archives

    def get_weekly_summary_content(self, user_id: str) -> str:
        """
        Get formatted content from the past week's archives.
        Used for weekly stable layer synthesis.
        """
        archives = self.get_recent_archives(user_id, days=7)

        if not archives:
            return "No archived content from the past week."

        summary_parts = []
        for archive in reversed(archives):  # Chronological order
            summary_parts.append(f"### {archive['day_of_week']}, {archive['date']}\n{archive['content']}")

        return "\n\n".join(summary_parts)

    async def cleanup_old_archives(
        self,
        user_id: str,
        keep_days: int = 90
    ):
        """
        Remove archives older than keep_days.
        Called periodically to manage disk space.
        """
        user_archive_dir = self.briefs_dir / user_id / "archive"

        if not user_archive_dir.exists():
            return

        cutoff_date = datetime.now() - timedelta(days=keep_days)
        removed_count = 0

        # Walk through year/month/day directories
        for year_dir in user_archive_dir.iterdir():
            if not year_dir.is_dir():
                continue

            try:
                year = int(year_dir.name)
            except ValueError:
                continue

            for month_dir in year_dir.iterdir():
                if not month_dir.is_dir():
                    continue

                try:
                    month = int(month_dir.name)
                except ValueError:
                    continue

                for day_dir in month_dir.iterdir():
                    if not day_dir.is_dir():
                        continue

                    try:
                        day = int(day_dir.name)
                        archive_date = datetime(year, month, day)

                        if archive_date < cutoff_date:
                            # Remove old archive
                            import shutil
                            shutil.rmtree(day_dir)
                            removed_count += 1

                    except (ValueError, Exception) as e:
                        logger.warning(f"Error processing archive dir {day_dir}: {e}")
                        continue

        if removed_count > 0:
            logger.info(f"🧹 Cleaned up {removed_count} old archives for user {user_id[:8]}")

    def get_archive_stats(self, user_id: str) -> Dict:
        """Get statistics about user's archives."""
        user_archive_dir = self.briefs_dir / user_id / "archive"

        if not user_archive_dir.exists():
            return {"total_archives": 0, "oldest": None, "newest": None}

        dates = []
        total_size = 0

        for year_dir in user_archive_dir.iterdir():
            if not year_dir.is_dir():
                continue
            for month_dir in year_dir.iterdir():
                if not month_dir.is_dir():
                    continue
                for day_dir in month_dir.iterdir():
                    if not day_dir.is_dir():
                        continue
                    try:
                        date_str = f"{year_dir.name}-{month_dir.name}-{day_dir.name}"
                        dates.append(date_str)
                        # Sum file sizes
                        for f in day_dir.iterdir():
                            if f.is_file():
                                total_size += f.stat().st_size
                    except Exception:
                        continue

        dates.sort()

        return {
            "total_archives": len(dates),
            "oldest": dates[0] if dates else None,
            "newest": dates[-1] if dates else None,
            "total_size_kb": total_size // 1024
        }


# Singleton instance
archiver = Archiver()
