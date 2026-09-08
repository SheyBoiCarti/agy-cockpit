"""SQLite database schema definitions and migration bootstrap."""

SCHEMA_V1 = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workspaces (
    id TEXT PRIMARY KEY,
    canonical_path TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_opened_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    title TEXT NOT NULL,
    model_slug TEXT NOT NULL,
    sdk_save_dir TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archived_at TEXT,
    FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL,
    author_time TEXT NOT NULL,
    content TEXT NOT NULL,
    reasoning TEXT NOT NULL DEFAULT '',
    attachment_ids TEXT NOT NULL DEFAULT '[]',
    FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    user_message_id TEXT NOT NULL,
    state TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    cancel_requested_at TEXT,
    last_sequence INTEGER NOT NULL DEFAULT 0,
    error_code TEXT,
    error_message TEXT,
    FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
    FOREIGN KEY(user_message_id) REFERENCES messages(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tool_executions (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    sdk_tool_name TEXT NOT NULL,
    args_json TEXT NOT NULL DEFAULT '{}',
    state TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    success INTEGER,
    output_summary TEXT,
    FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS approval_requests (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    tool_execution_id TEXT,
    sdk_tool_name TEXT NOT NULL,
    args_json TEXT NOT NULL DEFAULT '{}',
    reason TEXT,
    decision TEXT,
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS file_changes (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    file_path TEXT NOT NULL,
    status TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS subagents (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    parent_id TEXT,
    name_or_role TEXT NOT NULL,
    state TEXT NOT NULL,
    depth INTEGER NOT NULL DEFAULT 0,
    current_activity TEXT,
    started_at TEXT,
    finished_at TEXT,
    FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    path_or_storage_key TEXT NOT NULL,
    preview_supported INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS attachments (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    run_id TEXT,
    conversation_id TEXT,
    sequence INTEGER,
    type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    replayable INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE,
    FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS settings (
    id TEXT PRIMARY KEY,
    default_model TEXT NOT NULL,
    policy_preset TEXT NOT NULL,
    theme TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Indexes for efficient queries
CREATE INDEX IF NOT EXISTS idx_conversations_workspace ON conversations(workspace_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, author_time);
CREATE INDEX IF NOT EXISTS idx_runs_conversation ON runs(conversation_id, started_at);
CREATE INDEX IF NOT EXISTS idx_events_run_seq ON events(run_id, sequence);
CREATE INDEX IF NOT EXISTS idx_tool_executions_run ON tool_executions(run_id);
CREATE INDEX IF NOT EXISTS idx_file_changes_run ON file_changes(run_id);
CREATE INDEX IF NOT EXISTS idx_subagents_run_parent ON subagents(run_id, parent_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_run ON artifacts(run_id);
CREATE INDEX IF NOT EXISTS idx_attachments_conv ON attachments(conversation_id);
"""
