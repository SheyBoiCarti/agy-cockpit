/**
 * Protocol v1 TypeScript definitions for Antigravity Cockpit.
 * Matches backend Pydantic models in ws/protocol.py.
 */

export const PROTOCOL_VERSION = 1;

export type ProtocolErrorCode =
  | 'PROTOCOL_VERSION_UNSUPPORTED'
  | 'INVALID_MESSAGE'
  | 'UNAUTHORIZED'
  | 'ORIGIN_REJECTED'
  | 'WORKSPACE_NOT_ALLOWED'
  | 'CONVERSATION_NOT_FOUND'
  | 'RUN_ALREADY_ACTIVE'
  | 'RUN_NOT_FOUND'
  | 'SDK_INITIALIZATION_FAILED'
  | 'SDK_TOOL_FAILED'
  | 'APPROVAL_TIMEOUT'
  | 'ATTACHMENT_TOO_LARGE'
  | 'DIFF_UNAVAILABLE'
  | 'INTERNAL_ERROR'
  | 'NOT_IMPLEMENTED';

export interface ClientCommand<T = Record<string, unknown>> {
  protocol_version: number;
  type: string;
  request_id: string;
  session_id: string;
  conversation_id?: string;
  run_id?: string;
  payload: T;
}

export interface ServerEvent<T = Record<string, unknown>> {
  protocol_version: number;
  type: string;
  event_id: string;
  session_id: string;
  conversation_id?: string;
  run_id?: string;
  sequence?: number;
  timestamp: string;
  payload: T;
}

// Client Command Types
export type CommandType =
  | 'hello'
  | 'list_workspaces'
  | 'open_workspace'
  | 'list_conversations'
  | 'create_conversation'
  | 'open_conversation'
  | 'rename_conversation'
  | 'archive_conversation'
  | 'send_prompt'
  | 'cancel_run'
  | 'resume_run_stream'
  | 'action_approval'
  | 'get_file_diff'
  | 'search_workspace'
  | 'upload_attachment'
  | 'get_artifact'
  | 'update_settings'
  | 'ping';

// Server Event Types
export type EventType =
  | 'hello_ack'
  | 'workspace_list'
  | 'workspace_opened'
  | 'conversation_list'
  | 'conversation_created'
  | 'conversation_snapshot'
  | 'run_started'
  | 'reasoning_delta'
  | 'token_delta'
  | 'tool_started'
  | 'tool_log'
  | 'tool_finished'
  | 'approval_required'
  | 'approval_resolved'
  | 'file_changed'
  | 'file_diff_data'
  | 'subagent_update'
  | 'artifact_created'
  | 'artifact_updated'
  | 'attachment_ready'
  | 'run_completed'
  | 'run_cancelled'
  | 'run_failed'
  | 'sync_state'
  | 'pong'
  | 'protocol_error';

// Specific Payloads
export interface HelloAckPayload {
  session_id: string;
  version: number;
  server_time: string;
  default_model: string;
  policy_preset: string;
}

export interface ReasoningDeltaPayload {
  delta: string;
}

export interface TokenDeltaPayload {
  delta: string;
}

export interface ToolStartedPayload {
  tool_execution_id: string;
  sdk_tool_name: string;
  args: Record<string, unknown>;
}

export interface ToolLogPayload {
  tool_execution_id: string;
  chunk: string;
  is_stderr?: boolean;
}

export interface ToolFinishedPayload {
  tool_execution_id: string;
  sdk_tool_name: string;
  success: boolean;
  output_summary?: string;
}

export interface ApprovalRequiredPayload {
  approval_request_id: string;
  sdk_tool_name: string;
  args: Record<string, unknown>;
  reason?: string;
}

export interface ApprovalResolvedPayload {
  approval_request_id: string;
  decision: string;
}

export interface FileChangedPayload {
  file_path: string;
  status: 'added' | 'modified' | 'deleted' | 'renamed';
  run_id: string;
}

export interface FileDiffDataPayload {
  file_path: string;
  status: string;
  original_content: string;
  modified_content: string;
  language: string;
  is_binary: boolean;
  truncated: boolean;
}

export interface SubagentUpdatePayload {
  id: string;
  parent_id?: string;
  name_or_role: string;
  state: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';
  current_activity?: string;
  depth?: number;
}

export interface RunCompletedPayload {
  run_id: string;
  completed_at: string;
  usage?: Record<string, unknown>;
}

export interface RunCancelledPayload {
  run_id: string;
  cancelled_at: string;
}

export interface RunFailedPayload {
  run_id: string;
  error_code: string;
  error_message: string;
  failed_at: string;
}

export interface SyncStatePayload {
  run_id: string;
  state: string;
  reasoning: string;
  output: string;
  tools: Array<{
    id: string;
    sdk_tool_name: string;
    args: Record<string, unknown>;
    state: string;
    success?: boolean;
    output_summary?: string;
  }>;
  pending_approval?: {
    id: string;
    sdk_tool_name: string;
    args: Record<string, unknown>;
    reason?: string;
  };
  changed_files: string[];
  subagents: Array<{
    id: string;
    parent_id?: string;
    name_or_role: string;
    state: string;
    current_activity?: string;
    depth: number;
  }>;
  artifacts: Array<{
    id: string;
    kind: string;
    name: string;
    mime_type: string;
    preview_supported: boolean;
  }>;
  last_sequence: number;
}

export interface ProtocolErrorPayload {
  request_id?: string;
  error_code: ProtocolErrorCode;
  message: string;
}
