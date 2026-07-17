"""
Skill Hot Reload Watcher

Uses watchdog to monitor skill directories for changes and trigger reloads.
This enables rapid iteration - edit SKILL.md and see changes on next chat.
"""

import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileModifiedEvent, FileCreatedEvent, FileDeletedEvent
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    Observer = None
    FileSystemEventHandler = object

if TYPE_CHECKING:
    from app.skills.loader import SkillLoader

logger = logging.getLogger(__name__)


class SkillFileHandler(FileSystemEventHandler if WATCHDOG_AVAILABLE else object):
    """
    Handles file system events for SKILL.md files.
    """

    def __init__(self, loader: "SkillLoader"):
        if WATCHDOG_AVAILABLE:
            super().__init__()
        self._loader = loader

    def on_modified(self, event):
        """Handle file modification events"""
        if event.is_directory:
            return

        file_path = Path(event.src_path)
        if file_path.name == "SKILL.md":
            logger.info(f"[Skills] Detected modification: {file_path}")
            self._loader.reload_skill(file_path)

    def on_created(self, event):
        """Handle file creation events"""
        if event.is_directory:
            return

        file_path = Path(event.src_path)
        if file_path.name == "SKILL.md":
            logger.info(f"[Skills] Detected new skill: {file_path}")
            self._loader.reload_skill(file_path)

    def on_deleted(self, event):
        """Handle file deletion events"""
        if event.is_directory:
            return

        file_path = Path(event.src_path)
        if file_path.name == "SKILL.md":
            logger.info(f"[Skills] Detected deletion: {file_path}")
            self._loader.remove_skill(file_path)


class SkillWatcher:
    """
    Watches skill directories for changes and triggers reloads.

    Uses watchdog library for efficient file system monitoring.
    Runs in a background thread.
    """

    def __init__(self, skill_dirs: Optional[List[Path]] = None, loader: Optional["SkillLoader"] = None):
        """
        Initialize the SkillWatcher.

        Args:
            skill_dirs: Directories to watch for changes
            loader: SkillLoader instance to notify of changes
        """
        self._skill_dirs = skill_dirs or []
        self._loader = loader
        self._observer: Optional[Observer] = None
        self._running = False
        self._lock = threading.Lock()

    def set_skill_dirs(self, dirs: List[Path]) -> None:
        """Set skill directories (used for late initialization)"""
        self._skill_dirs = dirs

    def set_loader(self, loader: "SkillLoader") -> None:
        """Set the loader instance"""
        self._loader = loader

    def start(self) -> bool:
        """
        Start watching skill directories.

        Returns:
            True if watcher started successfully, False otherwise
        """
        if not WATCHDOG_AVAILABLE:
            logger.warning("[Skills] Watchdog not available - hot reload disabled")
            return False

        if self._loader is None:
            logger.error("[Skills] Cannot start watcher: no loader set")
            return False

        with self._lock:
            if self._running:
                logger.warning("[Skills] Watcher already running")
                return True

            self._observer = Observer()
            handler = SkillFileHandler(self._loader)

            watched_paths = []
            for skill_dir in self._skill_dirs:
                dir_path = Path(skill_dir)
                if dir_path.exists():
                    # Watch recursively to catch changes in subdirectories
                    self._observer.schedule(handler, str(dir_path), recursive=True)
                    watched_paths.append(str(dir_path))
                else:
                    logger.warning(f"[Skills] Skipping non-existent directory: {dir_path}")

            if not watched_paths:
                logger.warning("[Skills] No valid directories to watch")
                return False

            try:
                self._observer.start()
                self._running = True
                logger.info(f"[Skills] Hot reload watcher started for: {watched_paths}")
                return True
            except Exception as e:
                logger.error(f"[Skills] Failed to start watcher: {e}")
                return False

    def stop(self) -> None:
        """Stop watching for changes"""
        with self._lock:
            if not self._running or self._observer is None:
                return

            try:
                self._observer.stop()
                self._observer.join(timeout=5.0)
                logger.info("[Skills] Hot reload watcher stopped")
            except Exception as e:
                logger.error(f"[Skills] Error stopping watcher: {e}")
            finally:
                self._running = False
                self._observer = None

    @property
    def is_running(self) -> bool:
        """Check if watcher is currently running"""
        return self._running
