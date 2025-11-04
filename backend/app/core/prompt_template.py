"""
Generic System Variable Templating

Provides a flexible templating system for rendering prompts with dynamic variables.
Can be used across the entire application for any system prompt customization.

Usage:
    from app.core.prompt_template import render_prompt_template

    template = "Today is {{SYSTEM_DATE}} and the time is {{SYSTEM_TIME}}"
    rendered = render_prompt_template(template, user=current_user)
    # Output: "Today is 2025-10-28 and the time is 14:30:00"

Available System Variables:
    {{SYSTEM_DATE}} - Current date (YYYY-MM-DD)
    {{SYSTEM_TIME}} - Current time (HH:MM:SS)
    {{SYSTEM_DAY_OF_WEEK}} - Day name (Monday, Tuesday, etc.)
    {{SYSTEM_MONTH}} - Month name (January, February, etc.)
    {{SYSTEM_YEAR}} - Current year (YYYY)
    {{USER_NAME}} - User's name
    {{USER_EMAIL}} - User's email

Custom variables can be passed as kwargs and accessed as {{CUSTOM_VAR}}
"""

from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional, Dict, Any
import re
import os


class PromptTemplateRenderer:
    """Renders prompt templates with system and custom variables"""

    @staticmethod
    def _get_tz_aware_datetime():
        """Get timezone-aware datetime using TZ environment variable"""
        tz = os.getenv("TZ", "America/New_York")
        return datetime.now(ZoneInfo(tz))

    # System variables are computed functions that don't require user context
    SYSTEM_VARIABLES = {
        "SYSTEM_DATE": lambda: PromptTemplateRenderer._get_tz_aware_datetime().strftime("%Y-%m-%d"),
        "SYSTEM_TIME": lambda: PromptTemplateRenderer._get_tz_aware_datetime().strftime("%H:%M:%S"),
        "SYSTEM_DATETIME": lambda: PromptTemplateRenderer._get_tz_aware_datetime().strftime("%Y-%m-%d %H:%M:%S"),
        "SYSTEM_DAY_OF_WEEK": lambda: PromptTemplateRenderer._get_tz_aware_datetime().strftime("%A"),
        "SYSTEM_DAY_SHORT": lambda: PromptTemplateRenderer._get_tz_aware_datetime().strftime("%a"),
        "SYSTEM_MONTH": lambda: PromptTemplateRenderer._get_tz_aware_datetime().strftime("%B"),
        "SYSTEM_MONTH_SHORT": lambda: PromptTemplateRenderer._get_tz_aware_datetime().strftime("%b"),
        "SYSTEM_YEAR": lambda: PromptTemplateRenderer._get_tz_aware_datetime().strftime("%Y"),
        "SYSTEM_HOUR": lambda: PromptTemplateRenderer._get_tz_aware_datetime().strftime("%H"),
        "SYSTEM_MINUTE": lambda: PromptTemplateRenderer._get_tz_aware_datetime().strftime("%M"),
        "SYSTEM_SECOND": lambda: PromptTemplateRenderer._get_tz_aware_datetime().strftime("%S"),
        "SYSTEM_TIMEZONE": lambda: PromptTemplateRenderer._get_tz_aware_datetime().strftime("%Z"),
        "SYSTEM_TIMESTAMP": lambda: str(int(PromptTemplateRenderer._get_tz_aware_datetime().timestamp())),
    }

    @classmethod
    def render(cls, template: str, user: Optional[Any] = None, **custom_vars) -> str:
        """
        Render a template string with system and custom variables.

        Args:
            template: Template string with {{VARIABLE}} placeholders
            user: Optional user object with name and email attributes
            **custom_vars: Additional custom variables to render

        Returns:
            Rendered string with all variables replaced

        Example:
            >>> render("Today is {{SYSTEM_DATE}}", custom_greeting="Hello")
            "Today is 2025-10-28"
        """
        if not template:
            return ""

        result = template

        # 1. Replace system variables
        for var_name, var_func in cls.SYSTEM_VARIABLES.items():
            pattern = r"\{\{" + var_name + r"\}\}"
            try:
                value = var_func()
                result = re.sub(pattern, str(value), result)
            except Exception:
                # If variable computation fails, leave placeholder
                continue

        # 2. Replace user variables if user object provided
        if user:
            user_vars = {
                "USER_NAME": getattr(user, "name", getattr(user, "email", "User")),
                "USER_EMAIL": getattr(user, "email", ""),
                "USER_ID": getattr(user, "id", ""),
            }
            for var_name, value in user_vars.items():
                pattern = r"\{\{" + var_name + r"\}\}"
                result = re.sub(pattern, str(value), result)

        # 3. Replace custom variables
        for var_name, value in custom_vars.items():
            pattern = r"\{\{" + var_name + r"\}\}"
            result = re.sub(pattern, str(value), result)

        return result

    @classmethod
    def get_available_variables(cls, user: Optional[Any] = None) -> Dict[str, str]:
        """
        Get a dictionary of all available variables with example values.

        Args:
            user: Optional user object for user-specific variables

        Returns:
            Dict mapping variable names to example values
        """
        variables = {}

        # System variables
        for var_name, var_func in cls.SYSTEM_VARIABLES.items():
            try:
                variables[var_name] = var_func()
            except Exception:
                variables[var_name] = "<error computing value>"

        # User variables
        if user:
            variables["USER_NAME"] = getattr(user, "name", getattr(user, "email", "User"))
            variables["USER_EMAIL"] = getattr(user, "email", "user@example.com")
            variables["USER_ID"] = getattr(user, "id", "user-id")
        else:
            variables["USER_NAME"] = "<requires user context>"
            variables["USER_EMAIL"] = "<requires user context>"
            variables["USER_ID"] = "<requires user context>"

        return variables

    @classmethod
    def preview_template(cls, template: str, user: Optional[Any] = None, **custom_vars) -> Dict[str, Any]:
        """
        Preview a template rendering with details about what was replaced.

        Args:
            template: Template string
            user: Optional user object
            **custom_vars: Custom variables

        Returns:
            Dict with 'rendered', 'original', and 'variables_used'
        """
        rendered = cls.render(template, user, **custom_vars)

        # Find which variables were used
        variables_used = []
        for var_name in re.findall(r"\{\{(\w+)\}\}", template):
            if var_name in cls.SYSTEM_VARIABLES:
                variables_used.append(var_name)
            elif user and var_name in ["USER_NAME", "USER_EMAIL", "USER_ID"]:
                variables_used.append(var_name)
            elif var_name in custom_vars:
                variables_used.append(var_name)

        return {
            "original": template,
            "rendered": rendered,
            "variables_used": list(set(variables_used)),
        }


# Convenience function for quick usage
def render_prompt_template(template: str, user: Optional[Any] = None, **custom_vars) -> str:
    """
    Convenience function to render a prompt template.

    See PromptTemplateRenderer.render() for full documentation.
    """
    return PromptTemplateRenderer.render(template, user, **custom_vars)


def get_available_variables(user: Optional[Any] = None) -> Dict[str, str]:
    """
    Get all available template variables with example values.

    See PromptTemplateRenderer.get_available_variables() for full documentation.
    """
    return PromptTemplateRenderer.get_available_variables(user)


def preview_template(template: str, user: Optional[Any] = None, **custom_vars) -> Dict[str, Any]:
    """
    Preview template rendering.

    See PromptTemplateRenderer.preview_template() for full documentation.
    """
    return PromptTemplateRenderer.preview_template(template, user, **custom_vars)


# Example usage and tests
if __name__ == "__main__":
    # Example 1: Basic system variables
    template1 = "Today is {{SYSTEM_DAY_OF_WEEK}}, {{SYSTEM_DATE}} at {{SYSTEM_TIME}}"
    print("Example 1:", render_prompt_template(template1))

    # Example 2: Custom variables
    template2 = "Hello {{USER_NAME}}, your last workout was {{LAST_WORKOUT}}."
    print("Example 2:", render_prompt_template(template2, LAST_WORKOUT="Monday - Push Day"))

    # Example 3: Preview
    preview = preview_template(template1)
    print("\nPreview:")
    print(f"  Original: {preview['original']}")
    print(f"  Rendered: {preview['rendered']}")
    print(f"  Variables: {preview['variables_used']}")

    # Example 4: Available variables
    print("\nAvailable variables:")
    for var, value in get_available_variables().items():
        print(f"  {{{{{var}}}}} = {value}")
