export interface Workspace {
  id: string;
  canonical_path: string;
  display_name: string;
  is_git: boolean;
  last_opened_at: string;
  created_at: string;
}

export interface Conversation {
  id: string;
  workspace_id: string;
  title: string;
  model_slug: string;
  is_archived: boolean;
  created_at: string;
  updated_at: string;
}

export interface Message {
  id: string;
  conversation_id: string;
  role: 'user' | 'assistant' | 'system';
  author_time: string;
  content: string;
  attachment_ids: string[];
}

export type RunState =
  | 'queued'
  | 'thinking'
  | 'streaming'
  | 'waiting_approval'
  | 'running_tool'
  | 'completed'
  | 'cancelled'
  | 'failed'
  | 'interrupted';

export interface Run {
  id: string;
  conversation_id: string;
  user_message_id: string;
  state: RunState;
  started_at: string;
  completed_at?: string;
  cancel_requested_at?: string;
  last_sequence?: number;
  error_code?: string;
  error_message?: string;
  usage?: Record<string, unknown>;
}

export interface ToolExecution {
  id: string;
  run_id: string;
  sdk_tool_name: string;
  args: Record<string, unknown>;
  state: 'started' | 'completed' | 'failed';
  started_at: string;
  finished_at?: string;
  success?: boolean;
  output_summary?: string;
  logs: string[];
}

export interface ApprovalRequest {
  id: string;
  run_id: string;
  sdk_tool_name: string;
  args: Record<string, unknown>;
  reason?: string;
}

export interface ChangedFile {
  path: string;
  status: 'added' | 'modified' | 'deleted' | 'renamed';
  run_id: string;
}

export interface Subagent {
  id: string;
  parent_id?: string;
  name_or_role: string;
  state: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';
  current_activity?: string;
  depth?: number;
}

export interface Artifact {
  id: string;
  kind: string;
  name: string;
  mime_type: string;
  preview_supported: boolean;
  created_at?: string;
  size_bytes?: number;
}

export interface Settings {
  policy_preset: string;
  default_model: string;
  allowed_workspaces: string[];
}

export interface ModelOption {
  slug: string;
  label: string;
  description?: string;
}
