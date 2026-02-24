"""
Task runner package status.

This namespace is intentionally disabled until a concrete Phase 6
implementation is delivered and wired into production entrypoints.
"""

TASK_RUNNER_ENABLED = False
TASK_RUNNER_STATUS = "deprecated_placeholder_removed"
TASK_RUNNER_NOTE = "No runtime task runner is currently shipped."

__all__ = [
    "TASK_RUNNER_ENABLED",
    "TASK_RUNNER_STATUS",
    "TASK_RUNNER_NOTE",
]
