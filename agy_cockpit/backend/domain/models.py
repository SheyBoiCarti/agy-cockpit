"""Domain models for Antigravity Cockpit."""

from datetime import datetime, timezone
import json
import re
from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, Field, field_validator, computed_field

from agy_cockpit.backend.domain.enums import (
    ApprovalDecision,
    ArtifactKind,
    FileChangeStatus,
    MessageRole,
    RunState,
    SubagentState,
    ToolExecutionState,
)


def utc_now_iso() -> str:
    """Returns current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


def validate_sdk_conversation_id(v: str) -> str:
    """Validates that conversation_id is SDK-compatible (>=32 chars, alphanumeric and hyphens)."""
    if not isinstance(v, str):
        raise ValueError("conversation_id must be a string")
    if len(v) < 32:
        raise ValueError(f"conversation_id must be at least 32 characters long, got {len(v)}")
    if not re.match(r"^[a-zA-Z0-9\-]+$", v):
        raise ValueError("conversation_id must only contain alphanumeric characters and hyphens")
    return v


class Workspace(BaseModel):
    """A project directory workspace."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    canonical_path: str
    display_name: str
    created_at: str = Field(default_factory=utc_now_iso)
    last_opened_at: str = Field(default_factory=utc_now_iso)

    @property
    def path(self) -> str:
        return self.canonical_path


class Conversation(BaseModel):
    """A long-lived conversational session with an SDK agent."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    workspace_id: str
    title: str
    model_slug: str = "gemini-3.8-flash-high"
    sdk_save_dir: Optional[str] = None
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)
    archived_at: Optional[str] = None

    @computed_field
    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None

    @field_validator("id")
    @classmethod
    def check_conversation_id(cls, v: str) -> str:
        return validate_sdk_conversation_id(v)


class Message(BaseModel):
    """A message in the chat timeline."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    conversation_id: str
    role: MessageRole
    author_time: str = Field(default_factory=utc_now_iso)
    content: str
    reasoning: Optional[str] = ""
    attachment_ids: List[str] = Field(default_factory=list)


class Run(BaseModel):
    """An agent turn triggered by a user prompt."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    conversation_id: str
    user_message_id: str
    state: RunState = RunState.QUEUED
    started_at: str = Field(default_factory=utc_now_iso)
    completed_at: Optional[str] = None
    cancel_requested_at: Optional[str] = None
    last_sequence: int = 0
    error_code: Optional[str] = None
    error_message: Optional[str] = None


class ToolExecution(BaseModel):
    """Execution record for an SDK tool call."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str
    sdk_tool_name: str
    args_json: str = "{}"
    state: ToolExecutionState = ToolExecutionState.STARTED
    started_at: str = Field(default_factory=utc_now_iso)
    finished_at: Optional[str] = None
    success: Optional[bool] = None
    output_summary: Optional[str] = None

    @property
    def parsed_args(self) -> Dict[str, Any]:
        try:
            return json.loads(self.args_json)
        except Exception:
            return {}


class ApprovalRequest(BaseModel):
    """An approval request raised by SDK policy bridge."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str
    tool_execution_id: Optional[str] = None
    sdk_tool_name: str
    args_json: str = "{}"
    reason: Optional[str] = None
    decision: Optional[ApprovalDecision] = None
    created_at: str = Field(default_factory=utc_now_iso)
    resolved_at: Optional[str] = None

    @property
    def parsed_args(self) -> Dict[str, Any]:
        try:
            return json.loads(self.args_json)
        except Exception:
            return {}


class FileChange(BaseModel):
    """A file modified or created during a run."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str
    file_path: str
    status: FileChangeStatus = FileChangeStatus.MODIFIED
    timestamp: str = Field(default_factory=utc_now_iso)


class SubagentNode(BaseModel):
    """A subagent in the execution hierarchy."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str
    parent_id: Optional[str] = None
    name_or_role: str
    state: SubagentState = SubagentState.PENDING
    depth: int = 0
    current_activity: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


class Artifact(BaseModel):
    """An artifact produced during a run."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str
    conversation_id: Optional[str] = None
    kind: ArtifactKind = ArtifactKind.FILE
    name: str
    mime_type: str = "text/plain"
    path_or_storage_key: str
    preview_supported: bool = True
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class Attachment(BaseModel):
    """An uploaded file attachment."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    conversation_id: str
    filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    storage_path: str
    created_at: str = Field(default_factory=utc_now_iso)


class EventRecord(BaseModel):
    """A persisted event record for reconnect/replay."""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    run_id: Optional[str] = None
    conversation_id: Optional[str] = None
    sequence: Optional[int] = None
    type: str
    payload_json: str = "{}"
    timestamp: str = Field(default_factory=utc_now_iso)
    replayable: bool = True


class Settings(BaseModel):
    """Global cockpit settings."""
    id: str = "global"
    default_model: str = "gemini-3.8-flash-high"
    policy_preset: str = "request-review"
    theme: str = "dark"
    updated_at: str = Field(default_factory=utc_now_iso)
