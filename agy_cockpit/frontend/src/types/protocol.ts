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
  | 'workspace_search_results'
  | 'settings_updated'
  | 'command_result'
  | 'pong'
  | 'protocol_error';

// --- Client Command Payloads ---

export interface HelloCommandPayload {
  client_name?: string;
  client_version?: string;
  last_session_id?: string;
}

export interface ListWorkspacesCommandPayload {}

export interface OpenWorkspaceCommandPayload {
  canonical_path?: string;
  workspace_id?: string;
}

export interface ListConversationsCommandPayload {
  workspace_id: string;
  include_archived?: boolean;
}

export interface CreateConversationCommandPayload {
  workspace_id: string;
  title?: string;
  model_slug?: string;
}

export interface OpenConversationCommandPayload {
  conversation_id: string;
}

export interface RenameConversationCommandPayload {
  conversation_id: string;
  title: string;
}

export interface ArchiveConversationCommandPayload {
  conversation_id: string;
}

export interface SendPromptCommandPayload {
  prompt: string;
  attachment_ids?: string[];
  model_slug?: string;
}

export interface CancelRunCommandPayload {
  run_id: string;
}

export interface ResumeRunStreamPayload {
  run_id: string;
  last_seen_sequence: number;
  after_sequence?: number;
  conversation_id?: string;
}

export type ResumeRunStreamCommandPayload = ResumeRunStreamPayload;

export interface ActionApprovalCommandPayload {
  approval_request_id: string;
  decision: 'approved' | 'rejected' | string;
  note?: string;
}

export interface GetFileDiffCommandPayload {
  file_path: string;
  run_id?: string;
  workspace_id?: string;
}

export interface SearchWorkspaceCommandPayload {
  query?: string;
  limit?: number;
  include_hidden?: boolean;
}

export interface UploadAttachmentCommandPayload {
  filename: string;
  mime_type: string;
  data_base64: string;
  conversation_id?: string;
}

export interface GetArtifactCommandPayload {
  artifact_id: string;
}

export interface UpdateSettingsCommandPayload {
  default_model?: string;
  policy_preset?: string;
  theme?: string;
}

export interface PingCommandPayload {}

// --- Server Event Payloads ---

export interface HelloAckPayload {
  session_id: string;
  version: number;
  server_time: string;
  default_model: string;
  policy_preset: string;
}

export interface WorkspaceListPayload {
  workspaces: Array<{
    id: string;
    canonical_path: string;
    display_name?: string;
    name?: string;
    is_git?: boolean;
    is_active?: boolean;
    created_at?: string;
    last_opened_at?: string;
  }>;
}

export interface WorkspaceOpenedPayload {
  workspace: {
    id: string;
    canonical_path: string;
    display_name?: string;
    name?: string;
    is_git?: boolean;
    is_active?: boolean;
    created_at?: string;
    last_opened_at?: string;
  };
}

export interface ConversationListPayload {
  conversations: Array<{
    id: string;
    workspace_id: string;
    title: string;
    model_slug: string;
    is_archived: boolean;
    created_at: string;
    updated_at: string;
  }>;
}

export interface ConversationCreatedPayload {
  conversation: {
    id: string;
    workspace_id: string;
    title: string;
    model_slug: string;
    is_archived: boolean;
    created_at: string;
    updated_at: string;
  };
}

export interface ConversationSnapshotPayload {
  conversation: {
    id: string;
    workspace_id: string;
    title: string;
    model_slug: string;
    is_archived: boolean;
    created_at: string;
    updated_at: string;
    [key: string]: unknown;
  };
  messages: Array<Record<string, unknown>>;
  active_run?: Record<string, unknown> | null;
}

export interface RunStartedPayload {
  run_id: string;
  conversation_id: string;
  user_message_id?: string;
  started_at: string;
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
  state: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled' | string;
  current_activity?: string;
  depth?: number;
}

export interface ArtifactData {
  id: string;
  run_id?: string;
  kind?: string;
  name?: string;
  mime_type?: string;
  path_or_storage_key?: string;
  preview_supported?: boolean;
  created_at?: string;
  updated_at?: string;
  size_bytes?: number;
  content?: string;
}

export interface ArtifactCreatedPayload extends Partial<ArtifactData> {
  artifact?: ArtifactData;
  artifact_id?: string;
}

export interface ArtifactUpdatedPayload extends Partial<ArtifactData> {
  artifact?: ArtifactData;
  artifact_id?: string;
}

export interface AttachmentReadyPayload {
  attachment: {
    id: string;
    conversation_id: string;
    filename: string;
    mime_type: string;
    size_bytes: number;
    created_at: string;
  };
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
  } | null;
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

export interface WorkspaceSearchResultsPayload {
  results: Array<{
    path: string;
    is_directory?: boolean;
    type?: string;
  }>;
}

export interface SettingsUpdatedPayload {
  settings: Record<string, unknown>;
}

export interface CommandResultPayload {
  request_id?: string;
  success: boolean;
  attachment?: Record<string, unknown>;
  artifact?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface PongPayload {}

export interface ProtocolErrorPayload {
  request_id?: string;
  error_code: ProtocolErrorCode;
  message: string;
}
