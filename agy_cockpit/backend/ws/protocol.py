"""WebSocket Protocol v1 models and schemas for Antigravity Cockpit."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Union
import uuid

from pydantic import BaseModel, Field, field_validator


PROTOCOL_VERSION = 1


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- Error Codes (Authoritative from 00-main-design Section 13) ---

class ProtocolErrorCode(str, Enum):
    PROTOCOL_VERSION_UNSUPPORTED = "PROTOCOL_VERSION_UNSUPPORTED"
    INVALID_MESSAGE = "INVALID_MESSAGE"
    UNAUTHORIZED = "UNAUTHORIZED"
    ORIGIN_REJECTED = "ORIGIN_REJECTED"
    WORKSPACE_NOT_ALLOWED = "WORKSPACE_NOT_ALLOWED"
    CONVERSATION_NOT_FOUND = "CONVERSATION_NOT_FOUND"
    RUN_ALREADY_ACTIVE = "RUN_ALREADY_ACTIVE"
    RUN_NOT_FOUND = "RUN_NOT_FOUND"
    SDK_INITIALIZATION_FAILED = "SDK_INITIALIZATION_FAILED"
    SDK_TOOL_FAILED = "SDK_TOOL_FAILED"
    APPROVAL_TIMEOUT = "APPROVAL_TIMEOUT"
    ATTACHMENT_TOO_LARGE = "ATTACHMENT_TOO_LARGE"
    DIFF_UNAVAILABLE = "DIFF_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"


# --- Universal Base Envelopes ---

class ClientCommand(BaseModel):
    """Universal client command envelope."""
    protocol_version: int = PROTOCOL_VERSION
    type: str
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    conversation_id: Optional[str] = None
    run_id: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("protocol_version")
    @classmethod
    def validate_version(cls, v: int) -> int:
        if v != PROTOCOL_VERSION:
            raise ValueError(f"Unsupported protocol version: {v}. Expected: {PROTOCOL_VERSION}")
        return v


class ServerEvent(BaseModel):
    """Universal server event envelope."""
    protocol_version: int = PROTOCOL_VERSION
    type: str
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    conversation_id: Optional[str] = None
    run_id: Optional[str] = None
    sequence: Optional[int] = None
    timestamp: str = Field(default_factory=utc_now_iso)
    payload: Dict[str, Any] = Field(default_factory=dict)


# --- Typed Client Command Payloads ---

class HelloCommandPayload(BaseModel):
    client_name: Optional[str] = "agy-cockpit-web"
    client_version: Optional[str] = "0.1.0"
    last_session_id: Optional[str] = None


class ListWorkspacesCommandPayload(BaseModel):
    pass


class OpenWorkspaceCommandPayload(BaseModel):
    canonical_path: Optional[str] = None
    workspace_id: Optional[str] = None


class ListConversationsCommandPayload(BaseModel):
    workspace_id: str
    include_archived: bool = False


class CreateConversationCommandPayload(BaseModel):
    workspace_id: str
    title: Optional[str] = "New Conversation"
    model_slug: Optional[str] = None


class OpenConversationCommandPayload(BaseModel):
    conversation_id: str


class RenameConversationCommandPayload(BaseModel):
    conversation_id: str
    title: str


class ArchiveConversationCommandPayload(BaseModel):
    conversation_id: str


class SendPromptCommandPayload(BaseModel):
    council_action: Optional[Dict[str, str]] = None
    prompt: str
    attachment_ids: List[str] = Field(default_factory=list)
    model_slug: Optional[str] = None


class CancelRunCommandPayload(BaseModel):
    run_id: str


class ResumeRunStreamCommandPayload(BaseModel):
    run_id: str
    last_seen_sequence: int = 0


class ActionApprovalCommandPayload(BaseModel):
    approval_request_id: str
    decision: str  # "approved" or "rejected"
    note: Optional[str] = None


class GetFileDiffCommandPayload(BaseModel):
    file_path: str
    run_id: Optional[str] = None


class SearchWorkspaceCommandPayload(BaseModel):
    query: str = ""
    limit: int = 50
    include_hidden: bool = False


class UploadAttachmentCommandPayload(BaseModel):
    filename: str
    mime_type: str
    data_base64: str


class GetArtifactCommandPayload(BaseModel):
    artifact_id: str


class UpdateSettingsCommandPayload(BaseModel):
    default_model: Optional[str] = None
    policy_preset: Optional[str] = None
    theme: Optional[str] = None


class PingCommandPayload(BaseModel):
    pass


# Map of command types to payload models
COMMAND_PAYLOAD_MAP = {
    "hello": HelloCommandPayload,
    "list_workspaces": ListWorkspacesCommandPayload,
    "open_workspace": OpenWorkspaceCommandPayload,
    "list_conversations": ListConversationsCommandPayload,
    "create_conversation": CreateConversationCommandPayload,
    "open_conversation": OpenConversationCommandPayload,
    "rename_conversation": RenameConversationCommandPayload,
    "archive_conversation": ArchiveConversationCommandPayload,
    "send_prompt": SendPromptCommandPayload,
    "cancel_run": CancelRunCommandPayload,
    "resume_run_stream": ResumeRunStreamCommandPayload,
    "action_approval": ActionApprovalCommandPayload,
    "get_file_diff": GetFileDiffCommandPayload,
    "search_workspace": SearchWorkspaceCommandPayload,
    "upload_attachment": UploadAttachmentCommandPayload,
    "get_artifact": GetArtifactCommandPayload,
    "update_settings": UpdateSettingsCommandPayload,
    "ping": PingCommandPayload,
}


def parse_client_command(data: Union[str, bytes, dict]) -> ClientCommand:
    """Parses raw JSON string or dict into a ClientCommand envelope."""
    if isinstance(data, (str, bytes)):
        import json
        parsed = json.loads(data)
    elif isinstance(data, dict):
        parsed = data
    else:
        raise ValueError(f"Expected str, bytes, or dict, got {type(data)}")

    return ClientCommand(**parsed)


def create_server_event(
    event_type: str,
    session_id: str,
    payload: Dict[str, Any],
    conversation_id: Optional[str] = None,
    run_id: Optional[str] = None,
    sequence: Optional[int] = None,
    event_id: Optional[str] = None,
) -> ServerEvent:
    """Creates a strongly-typed ServerEvent."""
    return ServerEvent(
        protocol_version=PROTOCOL_VERSION,
        type=event_type,
        event_id=event_id or str(uuid.uuid4()),
        session_id=session_id,
        conversation_id=conversation_id,
        run_id=run_id,
        sequence=sequence,
        timestamp=utc_now_iso(),
        payload=payload,
    )


def create_protocol_error(
    session_id: str,
    error_code: ProtocolErrorCode,
    message: str,
    request_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    run_id: Optional[str] = None,
) -> ServerEvent:
    """Creates a protocol_error server event."""
    return create_server_event(
        event_type="protocol_error",
        session_id=session_id,
        conversation_id=conversation_id,
        run_id=run_id,
        payload={
            "request_id": request_id,
            "error_code": error_code.value,
            "message": message,
        },
    )
