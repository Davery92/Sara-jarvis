from enum import Enum


class WorkoutState(str, Enum):
    idle = "idle"
    warmup = "warmup"
    working_set = "working_set"
    resting = "resting"
    summary = "summary"
    completed = "completed"


class WorkoutStateMachine:
    """Server-side state transitions for in-workout flow."""

    def __init__(self) -> None:
        self.state = WorkoutState.idle

    def transition(self, event: str) -> WorkoutState:
        # Placeholder: implement transitions per spec
        return self.state

