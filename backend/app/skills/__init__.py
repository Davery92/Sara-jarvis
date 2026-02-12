"""
Skills System

A markdown-based skills layer that provides instruction-based capabilities
alongside code-based tools. Skills are curated documents that inject domain
expertise, workflows, and behavioral guidance into the system prompt.

Key Principle: Skills provide *instructions the AI interprets*.
              Tools provide *code the system executes*.

Usage:
    from app.skills import skill_loader, skill_injector, skill_watcher, initialize_skills

    # Initialize at startup
    initialize_skills()

    # Inject skills into system prompt
    enhanced_prompt = skill_injector.inject(base_prompt, context='fitness')
"""

import logging
from pathlib import Path
from typing import List, Optional

from app.skills.models import Skill, SkillMetadata, SkillRequirements
from app.skills.loader import SkillLoader
from app.skills.injector import SkillInjector
from app.skills.watcher import SkillWatcher

logger = logging.getLogger(__name__)

# Singleton instances - initialized lazily
_skill_loader: Optional[SkillLoader] = None
_skill_injector: Optional[SkillInjector] = None
_skill_watcher: Optional[SkillWatcher] = None


def get_skill_loader() -> SkillLoader:
    """Get the singleton SkillLoader instance"""
    global _skill_loader
    if _skill_loader is None:
        _skill_loader = SkillLoader()
    return _skill_loader


def get_skill_injector() -> SkillInjector:
    """Get the singleton SkillInjector instance"""
    global _skill_injector
    if _skill_injector is None:
        _skill_injector = SkillInjector(get_skill_loader())
    return _skill_injector


def get_skill_watcher() -> SkillWatcher:
    """Get the singleton SkillWatcher instance"""
    global _skill_watcher
    if _skill_watcher is None:
        _skill_watcher = SkillWatcher()
        _skill_watcher.set_loader(get_skill_loader())
    return _skill_watcher


def _resolve_skill_paths(configured_dirs: List[str]) -> List[Path]:
    """
    Resolve skill directory paths, trying multiple locations.

    This handles running from different working directories:
    - Repo root: backend/skills
    - Backend dir: skills or ../backend/skills
    - Absolute paths: used as-is
    """
    resolved = []

    for dir_str in configured_dirs:
        path = Path(dir_str)

        # If absolute and exists, use it
        if path.is_absolute() and path.exists():
            resolved.append(path)
            continue

        # Try the path as-is first (relative to cwd)
        if path.exists():
            resolved.append(path.resolve())
            continue

        # Try relative to this file's location (app/skills/__init__.py)
        # Skills are at backend/skills, we're at backend/app/skills
        package_dir = Path(__file__).parent  # app/skills
        backend_dir = package_dir.parent.parent  # backend
        skills_in_backend = backend_dir / "skills"
        if skills_in_backend.exists():
            resolved.append(skills_in_backend.resolve())
            continue

        # Try just "skills" if we're in backend dir
        simple_skills = Path("skills")
        if simple_skills.exists():
            resolved.append(simple_skills.resolve())
            continue

        # Log warning but don't fail - directory might be created later
        logger.warning(f"[Skills] Could not resolve path: {dir_str}")

    return resolved


def initialize_skills(skill_dirs: Optional[List[str]] = None, hot_reload: bool = True) -> bool:
    """
    Initialize the skills system.

    Should be called at application startup.

    Args:
        skill_dirs: List of directory paths to load skills from.
                   Defaults to configuration if not specified.
        hot_reload: Whether to enable hot reload watching (default True)

    Returns:
        True if initialization succeeded
    """
    try:
        # Import config here to avoid circular imports
        from app.core.config import settings

        # Determine skill directories
        if skill_dirs is None:
            skill_dirs = getattr(settings, 'skills_dirs', ['backend/skills'])

        # Resolve paths (handles different working directories)
        paths = _resolve_skill_paths(skill_dirs)

        if not paths:
            logger.warning("[Skills] No valid skill directories found")
            return False

        # Get loader and set directories
        loader = get_skill_loader()
        loader.set_skill_dirs(paths)

        # Check if skills are enabled
        skills_enabled = getattr(settings, 'skills_enabled', True)
        if not skills_enabled:
            logger.info("[Skills] Skills system disabled in configuration")
            return False

        # Load all skills
        loader.load_all()

        # Start hot reload watcher if enabled
        should_hot_reload = hot_reload and getattr(settings, 'skills_hot_reload', True)
        if should_hot_reload:
            watcher = get_skill_watcher()
            watcher.set_skill_dirs(paths)
            watcher.start()

        logger.info(
            f"[Skills] Initialized with {loader.skill_count} skills "
            f"(hot_reload={'enabled' if should_hot_reload else 'disabled'})"
        )
        return True

    except Exception as e:
        logger.error(f"[Skills] Initialization failed: {e}")
        return False


def shutdown_skills() -> None:
    """
    Shutdown the skills system.

    Should be called at application shutdown.
    """
    global _skill_watcher
    if _skill_watcher is not None:
        _skill_watcher.stop()
        logger.info("[Skills] Shutdown complete")


# Convenience aliases for direct import
skill_loader = get_skill_loader
skill_injector = get_skill_injector
skill_watcher = get_skill_watcher


__all__ = [
    # Models
    'Skill',
    'SkillMetadata',
    'SkillRequirements',
    # Classes
    'SkillLoader',
    'SkillInjector',
    'SkillWatcher',
    # Singleton getters
    'get_skill_loader',
    'get_skill_injector',
    'get_skill_watcher',
    # Lifecycle functions
    'initialize_skills',
    'shutdown_skills',
    # Convenience aliases
    'skill_loader',
    'skill_injector',
    'skill_watcher',
]
