"""Domain enumerations and state machine rules for Antigravity Cockpit."""

from enum import Enum
from typing import Set, Dict


class DomainError(Exception):
    """Base domain exception."""
    pass


class InvalidStateTransitionError(DomainError):
    """Raised when an invalid state transition is attempted."""
    def __init__(self, from_state: "RunState", to_state: "RunState"):
        super().__init__(f"Invalid run state transition from '{from_state.value}' to '{to_state.value}'")
        self.from_state = from_state
        self.to_state = to_state


class RunState(str, Enum):
    """Allowed states for an agent Run."""
    QUEUED = "queued"
    THINKING = "thinking"
    STREAMING = "streaming"
    WAITING_APPROVAL = "waiting_approval"
    RUNNING_TOOL = "running_tool"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"
    INTERRUPTED = "interrupted"

    @property
    def is_terminal(self) -> bool:
        return self in (
            RunState.COMPLETED,
            RunState.CANCELLED,
            RunState.FAILED,
            RunState.INTERRUPTED,
        )


# Valid run state transitions map
VALID_TRANSITIONS: Dict[RunState, Set[RunState]] = {
    RunState.QUEUED: {
        RunState.THINKING,
        RunState.STREAMING,
        RunState.RUNNING_TOOL,
        RunState.CANCELLED,
        RunState.FAILED,
        RunState.INTERRUPTED,
    },
    RunState.THINKING: {
        RunState.STREAMING,
        RunState.RUNNING_TOOL,
        RunState.WAITING_APPROVAL,
        RunState.COMPLETED,
        RunState.CANCELLED,
        RunState.FAILED,
        RunState.INTERRUPTED,
    },
    RunState.STREAMING: {
        RunState.THINKING,
        RunState.RUNNING_TOOL,
        RunState.WAITING_APPROVAL,
        RunState.COMPLETED,
        RunState.CANCELLED,
        RunState.FAILED,
        RunState.INTERRUPTED,
    },
    RunState.WAITING_APPROVAL: {
        RunState.RUNNING_TOOL,
        RunState.THINKING,
        RunState.STREAMING,
        RunState.CANCELLED,
        RunState.FAILED,
        RunState.INTERRUPTED,
    },
    RunState.RUNNING_TOOL: {
        RunState.THINKING,
        RunState.STREAMING,
        RunState.WAITING_APPROVAL,
        RunState.RUNNING_TOOL,  # subsequent tool
        RunState.COMPLETED,
        RunState.CANCELLED,
        RunState.FAILED,
        RunState.INTERRUPTED,
    },
    # Terminal states have no valid subsequent transitions
    RunState.COMPLETED: set(),
    RunState.CANCELLED: set(),
    RunState.FAILED: set(),
    RunState.INTERRUPTED: set(),
}


def validate_run_state_transition(from_state: RunState, to_state: RunState) -> None:
    """Validates that transition from from_state to to_state is allowed.

    Raises:
        InvalidStateTransitionError: If the transition is prohibited.
    """
    if from_state == to_state:
        return
    allowed = VALID_TRANSITIONS.get(from_state, set())
    if to_state not in allowed:
        raise InvalidStateTransitionError(from_state, to_state)


class MessageRole(str, Enum):
    """Role of a message author."""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ToolExecutionState(str, Enum):
    """Lifecycle state of a tool execution."""
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"


class ApprovalDecision(str, Enum):
    """Decision on an approval request."""
    APPROVED = "approved"
    REJECTED = "rejected"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class FileChangeStatus(str, Enum):
    """Status of a file change."""
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"


class SubagentState(str, Enum):
    """State of a subagent."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ArtifactKind(str, Enum):
    """Type of an artifact."""
    FILE = "file"
    DIFF = "diff"
    PLAN = "plan"
    REPORT = "report"
    IMAGE = "image"
    CUSTOM = "custom"
