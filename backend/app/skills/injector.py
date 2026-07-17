"""
Skill Injector Service

Handles formatting and injection of skills into the system prompt.
"""

import logging
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from app.skills.loader import SkillLoader
    from app.skills.models import Skill

logger = logging.getLogger(__name__)


class SkillInjector:
    """
    Injects skills into the system prompt.

    Responsibilities:
    - Format skills for injection
    - Respect priority ordering
    - Build the skills section of the prompt
    """

    def __init__(self, loader: "SkillLoader"):
        """
        Initialize the SkillInjector.

        Args:
            loader: The SkillLoader instance to get skills from
        """
        self._loader = loader

    def inject(
        self,
        base_prompt: str,
        context: str,
        max_skills: Optional[int] = None
    ) -> str:
        """
        Inject applicable skills into the system prompt.

        Args:
            base_prompt: The base system prompt to enhance
            context: The current context (e.g., 'fitness', 'learning', 'general')
            max_skills: Maximum number of skills to inject (None = no limit)

        Returns:
            Enhanced system prompt with skills section
        """
        skills = self._loader.get_skills_for_context(context)

        if not skills:
            return base_prompt

        # Limit if specified
        if max_skills is not None:
            skills = skills[:max_skills]

        # Build skills section
        skill_section = self._format_skills_section(skills)

        # Log what we're injecting
        skill_names = [s.metadata.name for s in skills]
        logger.info(f"[Skills] Injecting {len(skills)} skills for context '{context}': {skill_names}")

        return base_prompt + skill_section

    def _format_skills_section(self, skills: List["Skill"]) -> str:
        """
        Format skills into a prompt section.

        Args:
            skills: List of skills to format (already sorted by priority)

        Returns:
            Formatted skills section string
        """
        if not skills:
            return ""

        lines = [
            "\n\n---",
            "\n## Active Skills",
            "\n*These are specialized capabilities active for this context.*\n"
        ]

        for skill in skills:
            lines.append(f"\n### {skill.metadata.name}")
            if skill.metadata.description:
                lines.append(f"*{skill.metadata.description}*\n")
            lines.append(skill.instructions)
            lines.append("")  # Blank line between skills

        return "\n".join(lines)

    def get_skill_summary(self, context: str) -> str:
        """
        Get a brief summary of skills active for a context.
        Useful for logging or debugging.

        Args:
            context: The context to check

        Returns:
            Summary string
        """
        skills = self._loader.get_skills_for_context(context)
        if not skills:
            return f"No skills active for context '{context}'"

        skill_info = [
            f"  - {s.metadata.name} (priority={s.metadata.priority})"
            for s in skills
        ]
        return f"Skills for '{context}':\n" + "\n".join(skill_info)
