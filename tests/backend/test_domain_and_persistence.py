"""Tests for Phase 2: Domain Model, State Machine, Path Safety, and SQLite Persistence."""

import os
import pathlib
import tempfile
import uuid
import pytest
import aiosqlite

from agy_cockpit.backend.db.connection import get_db_connection, init_db
from agy_cockpit.backend.db.repositories import (
    ApprovalRepository,
    ArtifactRepository,
    AttachmentRepository,
    ConversationRepository,
    EventRepository,
    FileChangeRepository,
    MessageRepository,
    RunRepository,
    SettingsRepository,
    SubagentRepository,
    ToolRepository,
    WorkspaceRepository,
)
from agy_cockpit.backend.domain.enums import (
    ApprovalDecision,
    ArtifactKind,
    FileChangeStatus,
    InvalidStateTransitionError,
    MessageRole,
    RunState,
    SubagentState,
    ToolExecutionState,
    validate_run_state_transition,
)
from agy_cockpit.backend.domain.models import (
    ApprovalRequest,
    Artifact,
    Attachment,
    Conversation,
    EventRecord,
    FileChange,
    Message,
    Run,
    Settings,
    SubagentNode,
    ToolExecution,
    Workspace,
)
from agy_cockpit.backend.domain.workspace import (
    WorkspaceSecurityError,
    canonicalize_workspace_path,
    get_relative_workspace_path,
    resolve_safe_path,
)


# --- 1. Schema Initialization and Idempotency ---

@pytest.mark.asyncio
async def test_schema_initialization_and_idempotency():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_file = os.path.join(tmpdir, "test.db")
        # Empty directory init
        await init_db(db_file)
        assert os.path.exists(db_file)

        # Repeated init must be idempotent
        await init_db(db_file)
        await init_db(db_file)

        # Verify tables exist
        conn = await get_db_connection(db_file)
        try:
            async with conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ) as cursor:
                tables = {row[0] for row in await cursor.fetchall()}
                expected = {
                    "workspaces", "conversations", "messages", "runs",
                    "tool_executions", "approval_requests", "file_changes",
                    "subagents", "artifacts", "attachments", "events",
                    "settings", "schema_migrations",
                }
                assert expected.issubset(tables)
        finally:
            await conn.close()


# --- 2. Conversation ID Validation ---

def test_conversation_id_validation():
    # Valid UUIDv4 (36 chars)
    valid_id = str(uuid.uuid4())
    c = Conversation(
        id=valid_id,
        workspace_id=str(uuid.uuid4()),
        title="Test Conversation",
    )
    assert c.id == valid_id

    # Invalid: < 32 characters
    with pytest.raises(ValueError, match="at least 32 characters"):
        Conversation(
            id="conv-short-123",
            workspace_id=str(uuid.uuid4()),
            title="Short ID",
        )

    # Invalid: non-alphanumeric/hyphen character
    with pytest.raises(ValueError, match="only contain alphanumeric"):
        Conversation(
            id="3e2be1b1-e1b4-40fd-b14e-d89dfbac0816_invalid",
            workspace_id=str(uuid.uuid4()),
            title="Underscore ID",
        )


# --- 3. Run State Machine Transitions ---

def test_run_state_transitions():
    # Valid normal flow
    validate_run_state_transition(RunState.QUEUED, RunState.THINKING)
    validate_run_state_transition(RunState.THINKING, RunState.STREAMING)
    validate_run_state_transition(RunState.STREAMING, RunState.COMPLETED)

    # Valid tool flow
    validate_run_state_transition(RunState.THINKING, RunState.RUNNING_TOOL)
    validate_run_state_transition(RunState.RUNNING_TOOL, RunState.STREAMING)

    # Valid approval flow
    validate_run_state_transition(RunState.THINKING, RunState.WAITING_APPROVAL)
    validate_run_state_transition(RunState.WAITING_APPROVAL, RunState.RUNNING_TOOL)

    # Valid cancellations
    validate_run_state_transition(RunState.QUEUED, RunState.CANCELLED)
    validate_run_state_transition(RunState.THINKING, RunState.CANCELLED)
    validate_run_state_transition(RunState.STREAMING, RunState.CANCELLED)
    validate_run_state_transition(RunState.WAITING_APPROVAL, RunState.CANCELLED)
    validate_run_state_transition(RunState.RUNNING_TOOL, RunState.CANCELLED)

    # Invalid transitions from terminal states
    for term in [RunState.COMPLETED, RunState.CANCELLED, RunState.FAILED, RunState.INTERRUPTED]:
        with pytest.raises(InvalidStateTransitionError):
            validate_run_state_transition(term, RunState.THINKING)
        with pytest.raises(InvalidStateTransitionError):
            validate_run_state_transition(term, RunState.QUEUED)


# --- 4. Workspace Path Safety ---

def test_workspace_path_safety():
    with tempfile.TemporaryDirectory() as tmpdir:
        ws_root = canonicalize_workspace_path(tmpdir)

        # Safe relative path
        safe1 = resolve_safe_path(ws_root, "src/main.py")
        assert safe1 == os.path.join(ws_root, "src/main.py")

        # Safe absolute path inside workspace
        safe2 = resolve_safe_path(ws_root, os.path.join(ws_root, "docs/index.md"))
        assert safe2 == os.path.join(ws_root, "docs/index.md")

        # Traversal attempt: ../
        with pytest.raises(WorkspaceSecurityError, match="outside workspace"):
            resolve_safe_path(ws_root, "../secret.txt")

        # Nested traversal attempt: foo/../../secret.txt
        with pytest.raises(WorkspaceSecurityError, match="outside workspace"):
            resolve_safe_path(ws_root, "subdir/../../secret.txt")

        # Traversal with Windows backslashes
        with pytest.raises(WorkspaceSecurityError, match="outside workspace"):
            resolve_safe_path(ws_root, "..\\secret.txt")

        # Outside absolute path rejected
        with pytest.raises(WorkspaceSecurityError, match="outside workspace"):
            resolve_safe_path(ws_root, "/etc/passwd")

        # Relative calculation helper
        rel = get_relative_workspace_path(ws_root, os.path.join(ws_root, "nested/file.txt"))
        assert rel == "nested/file.txt"


# --- 5. Entity CRUD and Cascade Deletes ---

@pytest.mark.asyncio
async def test_entity_crud_and_cascades():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_file = os.path.join(tmpdir, "test.db")
        await init_db(db_file)
        conn = await get_db_connection(db_file)
        try:
            ws_repo = WorkspaceRepository(conn)
            conv_repo = ConversationRepository(conn)
            msg_repo = MessageRepository(conn)
            run_repo = RunRepository(conn)
            tool_repo = ToolRepository(conn)
            appr_repo = ApprovalRepository(conn)
            fc_repo = FileChangeRepository(conn)
            sub_repo = SubagentRepository(conn)
            art_repo = ArtifactRepository(conn)
            att_repo = AttachmentRepository(conn)
            event_repo = EventRepository(conn)
            settings_repo = SettingsRepository(conn)

            # 1. Create Workspace
            ws = Workspace(canonical_path="/home/user/project", display_name="project")
            await ws_repo.create(ws)
            ws_fetched = await ws_repo.get_by_id(ws.id)
            assert ws_fetched is not None
            assert ws_fetched.canonical_path == "/home/user/project"

            # 2. Create Conversation
            conv_id = str(uuid.uuid4())
            conv = Conversation(
                id=conv_id,
                workspace_id=ws.id,
                title="First Chat",
                sdk_save_dir=os.path.join(tmpdir, "sessions", conv_id),
            )
            await conv_repo.create(conv)
            conv_fetched = await conv_repo.get_by_id(conv_id)
            assert conv_fetched is not None
            assert conv_fetched.title == "First Chat"
            assert conv_fetched.sdk_save_dir == conv.sdk_save_dir

            # 3. Create Messages
            msg1 = Message(
                conversation_id=conv_id,
                role=MessageRole.USER,
                content="Hello agent",
                attachment_ids=["att-1"],
            )
            await msg_repo.create(msg1)
            msgs = await msg_repo.list_by_conversation(conv_id)
            assert len(msgs) == 1
            assert msgs[0].attachment_ids == ["att-1"]

            # 4. Create Run
            run = Run(
                conversation_id=conv_id,
                user_message_id=msg1.id,
                state=RunState.QUEUED,
            )
            await run_repo.create(run)
            run_fetched = await run_repo.get_by_id(run.id)
            assert run_fetched is not None
            assert run_fetched.state == RunState.QUEUED

            # Update run state through valid transitions
            await run_repo.update_state(run.id, RunState.THINKING)
            await run_repo.update_state(run.id, RunState.RUNNING_TOOL)
            await run_repo.update_state(run.id, RunState.STREAMING)
            await run_repo.update_state(run.id, RunState.COMPLETED, completed_at="2026-09-08T00:00:00Z")
            run_completed = await run_repo.get_by_id(run.id)
            assert run_completed.state == RunState.COMPLETED
            assert run_completed.completed_at == "2026-09-08T00:00:00Z"

            # 5. Create ToolExecution
            tool = ToolExecution(
                run_id=run.id,
                sdk_tool_name="list_directory",
                args_json='{"directory_path": "."}',
                state=ToolExecutionState.STARTED,
            )
            await tool_repo.create(tool)
            await tool_repo.complete(tool.id, ToolExecutionState.COMPLETED, "2026-09-08T00:00:01Z", True, "done")
            tool_fetched = await tool_repo.get_by_id(tool.id)
            assert tool_fetched.state == ToolExecutionState.COMPLETED
            assert tool_fetched.success is True

            # 6. Create ApprovalRequest
            appr = ApprovalRequest(
                run_id=run.id,
                tool_execution_id=tool.id,
                sdk_tool_name="run_command",
                args_json='{"command": "pytest"}',
                reason="Execute tests",
            )
            await appr_repo.create(appr)
            pending = await appr_repo.get_pending_for_run(run.id)
            assert pending is not None
            assert pending.id == appr.id
            await appr_repo.resolve(appr.id, ApprovalDecision.APPROVED, "2026-09-08T00:00:02Z")
            resolved = await appr_repo.get_by_id(appr.id)
            assert resolved.decision == ApprovalDecision.APPROVED

            # 7. Create FileChange
            fc = FileChange(run_id=run.id, file_path="main.py", status=FileChangeStatus.MODIFIED)
            await fc_repo.create(fc)
            changes = await fc_repo.list_by_run(run.id)
            assert len(changes) == 1

            # 8. Create Subagent
            sub = SubagentNode(
                run_id=run.id,
                name_or_role="researcher",
                state=SubagentState.RUNNING,
            )
            await sub_repo.create(sub)
            subs = await sub_repo.list_by_run(run.id)
            assert len(subs) == 1

            # 9. Create Artifact
            art = Artifact(
                run_id=run.id,
                kind=ArtifactKind.FILE,
                name="report.txt",
                path_or_storage_key="/tmp/report.txt",
            )
            await art_repo.create(art)
            arts = await art_repo.list_by_run(run.id)
            assert len(arts) == 1

            # 10. Create Attachment
            att = Attachment(
                conversation_id=conv_id,
                filename="data.csv",
                mime_type="text/csv",
                size_bytes=1024,
                sha256="abc123",
                storage_path="/tmp/data.csv",
            )
            await att_repo.create(att)
            atts = await att_repo.list_by_conversation(conv_id)
            assert len(atts) == 1

            # 11. Create Events and Replay Query
            e1 = EventRecord(run_id=run.id, sequence=1, type="token_delta", payload_json='{"t":"hello"}')
            e2 = EventRecord(run_id=run.id, sequence=2, type="token_delta", payload_json='{"t":" world"}')
            e3 = EventRecord(run_id=run.id, sequence=3, type="token_delta", payload_json='{"t":"!"}')
            await event_repo.create(e1)
            await event_repo.create(e2)
            await event_repo.create(e3)

            # Replay since sequence 1 -> returns events 2 and 3 in ascending order
            replay = await event_repo.get_events_since(run.id, last_sequence=1)
            assert [e.sequence for e in replay] == [2, 3]
            max_seq = await event_repo.get_max_sequence(run.id)
            assert max_seq == 3

            # 12. Settings
            st = await settings_repo.get()
            assert st.id == "global"
            st.theme = "light"
            await settings_repo.save(st)
            st_updated = await settings_repo.get()
            assert st_updated.theme == "light"

            # 13. Cascade Delete: Delete Workspace should delete Conversation and child Run, Message, etc.
            await ws_repo.delete(ws.id)
            assert await conv_repo.get_by_id(conv_id) is None
            assert await msg_repo.get_by_id(msg1.id) is None
            assert await run_repo.get_by_id(run.id) is None
        finally:
            await conn.close()
