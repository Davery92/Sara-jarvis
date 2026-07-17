"""
Skill Loader Service

Handles loading, parsing, validation, and caching of SKILL.md files.
Skills are instruction documents that inject domain expertise into the system prompt.
"""

import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from app.skills.models import Skill, SkillMetadata, SkillRequirements

logger = logging.getLogger(__name__)


class SkillLoader:
    """
    Loads and caches skills from SKILL.md files.

    Responsibilities:
    - Scan skills directories on startup
    - Parse YAML frontmatter + markdown content
    - Apply gating rules (requirements, enabled flag)
    - Cache loaded skills in memory
    - Provide skills for a given context
    """

    # Regex to parse YAML frontmatter (--- delimited)
    FRONTMATTER_PATTERN = re.compile(
        r'^---\s*\n(.*?)\n---\s*\n(.*)$',
        re.DOTALL
    )

    def __init__(self, skill_dirs: Optional[List[Path]] = None):
        """
        Initialize the SkillLoader.

        Args:
            skill_dirs: List of directories to scan for skills.
                       If None, uses default from config.
        """
        self._skill_dirs = skill_dirs or []
        self._skills: Dict[str, Skill] = {}  # name -> Skill
        self._initialized = False

    def set_skill_dirs(self, dirs: List[Path]) -> None:
        """Set skill directories (used for late initialization from config)"""
        self._skill_dirs = dirs

    def load_all(self) -> None:
        """
        Load all skills from configured directories.
        Called at startup.
        """
        self._skills.clear()
        loaded_count = 0
        skipped_count = 0

        for skill_dir in self._skill_dirs:
            skill_path = Path(skill_dir)
            if not skill_path.exists():
                logger.warning(f"[Skills] Directory does not exist: {skill_path}")
                continue

            # Scan for SKILL.md files in subdirectories
            for skill_folder in skill_path.iterdir():
                if not skill_folder.is_dir():
                    continue

                skill_file = skill_folder / "SKILL.md"
                if not skill_file.exists():
                    continue

                try:
                    skill = self._load_skill_file(skill_file)
                    if skill and self._passes_gates(skill):
                        self._skills[skill.metadata.name] = skill
                        loaded_count += 1
                        logger.info(
                            f"[Skills] Loaded: {skill.metadata.name} "
                            f"(contexts={skill.metadata.contexts}, priority={skill.metadata.priority})"
                        )
                    else:
                        skipped_count += 1
                except Exception as e:
                    logger.error(f"[Skills] Failed to load {skill_file}: {e}")
                    skipped_count += 1

        self._initialized = True
        logger.info(f"[Skills] Initialization complete: {loaded_count} loaded, {skipped_count} skipped")

    def _load_skill_file(self, file_path: Path) -> Optional[Skill]:
        """
        Parse a SKILL.md file and return a Skill object.

        Args:
            file_path: Path to the SKILL.md file

        Returns:
            Skill object or None if parsing fails
        """
        try:
            content = file_path.read_text(encoding='utf-8')
        except Exception as e:
            logger.error(f"[Skills] Could not read {file_path}: {e}")
            return None

        # Parse frontmatter
        match = self.FRONTMATTER_PATTERN.match(content)
        if not match:
            logger.warning(f"[Skills] No valid frontmatter in {file_path}")
            return None

        frontmatter_str, instructions = match.groups()

        try:
            frontmatter_data = yaml.safe_load(frontmatter_str)
        except yaml.YAMLError as e:
            logger.error(f"[Skills] Invalid YAML in {file_path}: {e}")
            return None

        if not frontmatter_data:
            logger.warning(f"[Skills] Empty frontmatter in {file_path}")
            return None

        # Parse requirements if present
        requires_data = frontmatter_data.pop('requires', {})
        requirements = SkillRequirements(**requires_data) if requires_data else SkillRequirements()
        frontmatter_data['requires'] = requirements

        try:
            metadata = SkillMetadata(**frontmatter_data)
        except Exception as e:
            logger.error(f"[Skills] Invalid metadata in {file_path}: {e}")
            return None

        # Get file modification time
        stat = file_path.stat()
        last_modified = datetime.fromtimestamp(stat.st_mtime)

        return Skill(
            metadata=metadata,
            instructions=instructions.strip(),
            file_path=file_path,
            last_modified=last_modified
        )

    def _passes_gates(self, skill: Skill) -> bool:
        """
        Check if a skill passes all gating requirements.

        Gating rules:
        1. enabled: false -> skip
        2. requires.env -> check os.environ
        3. requires.config -> check settings (future)

        Args:
            skill: The skill to check

        Returns:
            True if skill passes all gates
        """
        # Check enabled flag
        if not skill.metadata.enabled:
            logger.debug(f"[Skills] Skipping disabled skill: {skill.metadata.name}")
            return False

        # Check required environment variables
        for env_var in skill.metadata.requires.env:
            if not os.environ.get(env_var):
                logger.debug(
                    f"[Skills] Skipping {skill.metadata.name}: "
                    f"missing env var {env_var}"
                )
                return False

        # Future: Check config requirements
        # for config_key in skill.metadata.requires.config:
        #     if not hasattr(settings, config_key):
        #         return False

        return True

    def reload_skill(self, file_path: Path) -> Optional[Skill]:
        """
        Reload a specific skill from its file.
        Used for hot reload when file changes.

        Args:
            file_path: Path to the SKILL.md file

        Returns:
            Reloaded Skill or None if reload fails
        """
        skill = self._load_skill_file(file_path)
        if skill and self._passes_gates(skill):
            old_skill = self._skills.get(skill.metadata.name)
            self._skills[skill.metadata.name] = skill
            if old_skill:
                logger.info(f"[Skills] Hot reloaded: {skill.metadata.name}")
            else:
                logger.info(f"[Skills] Hot loaded new skill: {skill.metadata.name}")
            return skill
        return None

    def remove_skill(self, file_path: Path) -> None:
        """
        Remove a skill when its file is deleted.

        Args:
            file_path: Path to the deleted SKILL.md file
        """
        # Find skill by file path
        skill_to_remove = None
        for name, skill in self._skills.items():
            if skill.file_path == file_path:
                skill_to_remove = name
                break

        if skill_to_remove:
            del self._skills[skill_to_remove]
            logger.info(f"[Skills] Removed: {skill_to_remove}")

    def get_skills_for_context(self, context: str) -> List[Skill]:
        """
        Get all skills applicable to a given context.

        Skills with empty contexts list apply to all contexts.

        Args:
            context: The current context (e.g., 'fitness', 'learning', 'general')

        Returns:
            List of applicable skills, sorted by priority (descending)
        """
        applicable = []
        for skill in self._skills.values():
            # Empty contexts = applies to all
            if not skill.metadata.contexts or context in skill.metadata.contexts:
                applicable.append(skill)

        # Sort by priority (descending - higher priority first)
        applicable.sort(key=lambda s: s.metadata.priority, reverse=True)
        return applicable

    def get_all_enabled_skills(self) -> List[Skill]:
        """
        Get all currently loaded and enabled skills.

        Returns:
            List of all skills, sorted by priority
        """
        skills = list(self._skills.values())
        skills.sort(key=lambda s: s.metadata.priority, reverse=True)
        return skills

    def get_skill_by_name(self, name: str) -> Optional[Skill]:
        """
        Get a specific skill by name.

        Args:
            name: The skill name

        Returns:
            Skill or None if not found
        """
        return self._skills.get(name)

    @property
    def is_initialized(self) -> bool:
        """Check if loader has been initialized"""
        return self._initialized

    @property
    def skill_count(self) -> int:
        """Get the number of loaded skills"""
        return len(self._skills)

    def create_skill_file(
        self,
        name: str,
        description: str,
        contexts: List[str],
        instructions: str,
        priority: int = 5,
        enabled: bool = True,
        user_invocable: bool = False,
    ) -> Optional[Path]:
        """
        Create a new skill file programmatically.

        This method creates a new skill directory and SKILL.md file with the
        provided parameters. The skill is automatically loaded after creation.

        Args:
            name: Unique skill identifier (kebab-case recommended)
            description: Human-readable description
            contexts: List of contexts where skill applies (empty = all)
            instructions: The markdown instruction content
            priority: Higher priority = injected first (default 5)
            enabled: Whether skill is active (default True)
            user_invocable: If user can invoke via /skill-name (default False)

        Returns:
            Path to the created SKILL.md file, or None if creation failed
        """
        if not self._skill_dirs:
            logger.error("[Skills] No skill directories configured")
            return None

        # Use the first skill directory
        base_dir = self._skill_dirs[0]

        # Create skill directory
        skill_dir = base_dir / name
        try:
            skill_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.error(f"[Skills] Failed to create directory {skill_dir}: {e}")
            return None

        # Format contexts for YAML
        contexts_yaml = ", ".join(contexts) if contexts else ""

        # Build SKILL.md content
        skill_content = f"""---
name: {name}
description: {description}
contexts: [{contexts_yaml}]
enabled: {str(enabled).lower()}
priority: {priority}
requires:
  env: []
  config: []
user_invocable: {str(user_invocable).lower()}
---

{instructions}
"""

        # Write the file
        skill_file = skill_dir / "SKILL.md"
        try:
            skill_file.write_text(skill_content, encoding='utf-8')
            logger.info(f"[Skills] Created skill file: {skill_file}")
        except Exception as e:
            logger.error(f"[Skills] Failed to write {skill_file}: {e}")
            return None

        # Reload the skill
        skill = self.reload_skill(skill_file)
        if skill:
            logger.info(f"[Skills] Successfully created and loaded: {name}")
            return skill_file
        else:
            logger.warning(f"[Skills] Created file but failed to load: {name}")
            return skill_file  # Still return path even if load failed

    def append_to_skill_file(
        self,
        name: str,
        additional_instructions: str,
        section_header: Optional[str] = None,
    ) -> Optional[Path]:
        """
        Append instructions to an existing skill file.

        This is additive-only - it cannot delete or modify existing content,
        only add new sections. This makes it safe for the AI to use without
        risking accidental overwrites.

        Args:
            name: Name of the existing skill to append to
            additional_instructions: Markdown content to append
            section_header: Optional header for the new section (e.g., "## Additional Guidelines")

        Returns:
            Path to the modified SKILL.md file, or None if the skill doesn't exist
        """
        # Find the existing skill
        skill = self._skills.get(name)
        if not skill:
            logger.error(f"[Skills] Cannot append - skill '{name}' not found")
            return None

        skill_file = skill.file_path

        try:
            # Read existing content
            content = skill_file.read_text(encoding='utf-8')

            # Build the addition
            addition = "\n\n"
            if section_header:
                addition += f"{section_header}\n\n"
            addition += additional_instructions.strip()
            addition += "\n"

            # Append to the file
            new_content = content.rstrip() + addition
            skill_file.write_text(new_content, encoding='utf-8')

            logger.info(f"[Skills] Appended to skill file: {skill_file}")

            # Reload the skill
            self.reload_skill(skill_file)

            return skill_file

        except Exception as e:
            logger.error(f"[Skills] Failed to append to {skill_file}: {e}")
            return None
