"""Tests validating defect remediation and hardening across agy-cockpit."""

import asyncio
import io
import json
import os
import tempfile
import uuid
import pytest
from unittest.mock import AsyncMock
from types import SimpleNamespace
from fastapi.testclient import TestClient

from agy_cockpit.backend.app import create_app
from agy_cockpit.backend.config import AppConfig
from agy_cockpit.backend.db.connection import get_db_connection, init_db
from agy_cockpit.backend.db.repositories import (
    ConversationRepository,
    MessageRepository,
    RunRepository,
    WorkspaceRepository,
)
from agy_cockpit.backend.domain.enums import ArtifactKind, MessageRole, RunState
from agy_cockpit.backend.domain.models import Conversation, Message, Run, Workspace
from agy_cockpit.backend.services.diff_service import is_git_workspace
from agy_cockpit.backend.ws.protocol import PROTOCOL_VERSION


@pytest.mark.asyncio
async def test_new_conversation_uses_saved_default_model():
    from agy_cockpit.backend.ws.router import WebSocketRouter
    from agy_cockpit.backend.ws.protocol import ClientCommand
    conv = SimpleNamespace(id="conversation", model_dump=lambda: {"id": "conversation"})
    service = SimpleNamespace(create_conversation=AsyncMock(return_value=conv))
    settings = SimpleNamespace(get_settings=AsyncMock(return_value=SimpleNamespace(default_model="gemini-3.8-flash-low")))
    router = WebSocketRouter(conversation_service=service, settings_service=settings)
    session = SimpleNamespace(session_id="test", send_event=AsyncMock())
    cmd = ClientCommand(type="create_conversation", request_id="test", session_id="test", payload={"workspace_id": "workspace"})
    await router._handle_create_conversation(session, cmd)
    assert service.create_conversation.call_args.kwargs["model_slug"] == "gemini-3.8-flash-low"


@pytest.mark.asyncio
async def test_tool_start_replay_is_idempotent(db_conn, tmp_path):
    from agy_cockpit.backend.domain.models import ToolExecution
    from agy_cockpit.backend.db.repositories.tool_repository import ToolRepository
    from agy_cockpit.backend.domain.enums import ToolExecutionState
    await WorkspaceRepository(db_conn).create(Workspace(id='tool-ws', canonical_path=str(tmp_path), display_name='workspace'))
    await ConversationRepository(db_conn).create(Conversation(id='c' * 32, workspace_id='tool-ws', title='Test'))
    await MessageRepository(db_conn).create(Message(id='tool-msg', conversation_id='c' * 32, role=MessageRole.USER, content='test'))
    await RunRepository(db_conn).create(Run(id='tool-run', conversation_id='c' * 32, user_message_id='tool-msg', state=RunState.QUEUED))
    tool = ToolExecution(id='sdk-tool', run_id='tool-run', sdk_tool_name='view_file', args_json='{}', state=ToolExecutionState.STARTED)
    repo = ToolRepository(db_conn)
    await repo.create(tool)
    await asyncio.gather(repo.create(tool), repo.create(tool))
    assert len(await repo.list_by_run('tool-run')) == 1


def test_missing_tool_ids_do_not_collide():
    from agy_cockpit.backend.services.tool_identity import ToolIdentityRegistry
    registry = ToolIdentityRegistry()
    first = registry.start(None, 'view_file')
    assert registry.finish(None, 'view_file') == first
    second = registry.start(None, 'view_file')
    assert first != second
    registry.start(None, 'view_file')
    with pytest.raises(ValueError, match='safely'):
        registry.finish(None, 'view_file')


def test_archived_conversation_wire_flag_matches_persistence():
    conversation = Conversation(workspace_id='workspace', title='Archived', archived_at='2026-10-19T00:00:00Z')
    assert conversation.model_dump()['is_archived'] is True
    conversation.archived_at = None
    assert conversation.model_dump()['is_archived'] is False


@pytest.fixture
def remediation_setup():
    with tempfile.TemporaryDirectory() as tmpdir:
        ws_dir = os.path.join(tmpdir, "workspace")
        os.makedirs(ws_dir, exist_ok=True)
        cfg = AppConfig(
            data_dir=tmpdir,
            token="remediation-secret-token",
            allowed_origins=["http://127.0.0.1:8080"],
        )
        yield cfg, ws_dir


def test_attachment_preserves_file_extension(remediation_setup):
    """Verifies that uploaded attachments preserve original file extensions on disk."""
    cfg, ws_dir = remediation_setup
    app = create_app(cfg)
    with TestClient(app) as client:
        with client.websocket_connect(f"/ws?token={cfg.token}", headers={"Origin": "http://127.0.0.1:8080"}) as ws:
            ws.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "open_workspace",
                "request_id": "r1",
                "session_id": "s1",
                "payload": {"canonical_path": ws_dir},
            }))
            ws_resp = json.loads(ws.receive_text())
            ws_id = ws_resp["payload"]["workspace"]["id"]

            ws.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "create_conversation",
                "request_id": "r2",
                "session_id": "s1",
                "payload": {"workspace_id": ws_id, "title": "Attachment Ext Test"},
            }))
            c_resp = json.loads(ws.receive_text())
            conv_id = c_resp["payload"]["conversation"]["id"]

        png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        upload_resp = client.post(
            "/api/attachments",
            headers={"x-antigravity-token": cfg.token},
            data={"conversation_id": conv_id},
            files={"file": ("screenshot.png", io.BytesIO(png_bytes), "image/png")},
        )
        assert upload_resp.status_code == 200
        att_data = upload_resp.json()["attachment"]
        storage_path = att_data["storage_path"]
        assert storage_path.endswith(".png")
        assert os.path.exists(storage_path)


@pytest.mark.asyncio
async def test_orphaned_runs_cleanup_on_startup(remediation_setup):
    """Verifies that in-flight runs are cleanly transitioned to INTERRUPTED when server boots."""
    cfg, ws_dir = remediation_setup
    await init_db(cfg.db_path)
    conn = await get_db_connection(cfg.db_path)
    try:
        ws_repo = WorkspaceRepository(conn)
        conv_repo = ConversationRepository(conn)
        msg_repo = MessageRepository(conn)
        run_repo = RunRepository(conn)

        ws = await ws_repo.create(Workspace(canonical_path=ws_dir, display_name="TestWS"))
        conv1 = await conv_repo.create(Conversation(id=str(uuid.uuid4()), workspace_id=ws.id, title="Recovery Conv 1"))
        conv2 = await conv_repo.create(Conversation(id=str(uuid.uuid4()), workspace_id=ws.id, title="Recovery Conv 2"))
        conv3 = await conv_repo.create(Conversation(id=str(uuid.uuid4()), workspace_id=ws.id, title="Recovery Conv 3"))
        msg1 = await msg_repo.create(Message(conversation_id=conv1.id, role=MessageRole.USER, content="Run task 1"))
        msg2 = await msg_repo.create(Message(conversation_id=conv2.id, role=MessageRole.USER, content="Run task 2"))
        msg3 = await msg_repo.create(Message(conversation_id=conv3.id, role=MessageRole.USER, content="Run task 3"))

        run1 = await run_repo.create(Run(conversation_id=conv1.id, user_message_id=msg1.id, state=RunState.RUNNING_TOOL))
        run2 = await run_repo.create(Run(conversation_id=conv2.id, user_message_id=msg2.id, state=RunState.THINKING))
        run3 = await run_repo.create(Run(conversation_id=conv3.id, user_message_id=msg3.id, state=RunState.QUEUED))
    finally:
        await conn.close()

    app = create_app(cfg)
    with TestClient(app) as client:
        conn2 = await get_db_connection(cfg.db_path)
        try:
            r_repo = RunRepository(conn2)
            db_run1 = await r_repo.get_by_id(run1.id)
            db_run2 = await r_repo.get_by_id(run2.id)
            db_run3 = await r_repo.get_by_id(run3.id)
            assert db_run1.state == RunState.INTERRUPTED
            assert db_run2.state == RunState.INTERRUPTED
            assert db_run3.state == RunState.INTERRUPTED
        finally:
            await conn2.close()


def test_binary_artifact_content_preservation(remediation_setup):
    """Verifies that binary image artifacts are not corrupted by text decoding."""
    cfg, ws_dir = remediation_setup
    app = create_app(cfg)
    with TestClient(app) as client:
        with client.websocket_connect(f"/ws?token={cfg.token}", headers={"Origin": "http://127.0.0.1:8080"}) as ws:
            ws.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "open_workspace",
                "request_id": "r1",
                "session_id": "s1",
                "payload": {"canonical_path": ws_dir},
            }))
            ws_resp = json.loads(ws.receive_text())
            ws_id = ws_resp["payload"]["workspace"]["id"]

            ws.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "create_conversation",
                "request_id": "r2",
                "session_id": "s1",
                "payload": {"workspace_id": ws_id, "title": "Binary Artifact Test"},
            }))
            c_resp = json.loads(ws.receive_text())
            conv_id = c_resp["payload"]["conversation"]["id"]

        img_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\xff\xfe\xfd\x00\x01\x02\x03\x04"
        img_path = os.path.join(ws_dir, "diagram.png")
        with open(img_path, "wb") as f:
            f.write(img_data)

        msg_repo = MessageRepository(app.state.db_conn)
        run_repo = RunRepository(app.state.db_conn)
        artifact_service = app.state.artifact_service

        async def setup_artifact():
            m = await msg_repo.create(Message(conversation_id=conv_id, role=MessageRole.USER, content="draw diagram"))
            r = await run_repo.create(Run(conversation_id=conv_id, user_message_id=m.id, state=RunState.COMPLETED))
            return await artifact_service.register_artifact(
                run_id=r.id,
                name="diagram.png",
                path_or_storage_key=img_path,
                kind=ArtifactKind.IMAGE,
                mime_type="image/png",
            )

        art = asyncio.run(setup_artifact())

        resp = client.get(
            f"/api/artifacts/{art.id}/content",
            headers={"x-antigravity-token": cfg.token},
        )
        assert resp.status_code == 200
        assert resp.content == img_data
        assert resp.headers["content-type"] == "image/png"


def test_api_token_enforcement(remediation_setup):
    """Verifies that invalid security tokens on /api/* return 401."""
    cfg, ws_dir = remediation_setup
    app = create_app(cfg)
    with TestClient(app) as client:
        # Invalid token in header
        resp_bad = client.get("/api/models", headers={"x-antigravity-token": "wrong-token"})
        assert resp_bad.status_code == 401

        # Valid token in header
        resp_good = client.get("/api/models", headers={"x-antigravity-token": cfg.token})
        assert resp_good.status_code == 200
        assert "models" in resp_good.json()

        # Valid token in query param
        resp_query = client.get(f"/api/models?token={cfg.token}")
        assert resp_query.status_code == 200


def test_diff_service_git_worktree_detection(remediation_setup):
    """Verifies that DiffService recognises git worktrees where .git is a file."""
    cfg, ws_dir = remediation_setup
    worktree_dir = os.path.join(ws_dir, "worktree-repo")
    os.makedirs(worktree_dir, exist_ok=True)
    git_file = os.path.join(worktree_dir, ".git")
    with open(git_file, "w") as f:
        f.write("gitdir: /path/to/main/.git/worktrees/worktree-repo\n")

    assert os.path.isfile(git_file)
    assert is_git_workspace(worktree_dir) is True


@pytest.mark.asyncio
async def test_startup_cleanup_recovers_all_non_terminal_states(db_conn):
    from agy_cockpit.backend.db.repositories.run_repository import RunRepository
    from agy_cockpit.backend.domain.enums import RunState
    from agy_cockpit.backend.domain.models import Run

    from agy_cockpit.backend.db.repositories.workspace_repository import WorkspaceRepository
    from agy_cockpit.backend.db.repositories.conversation_repository import ConversationRepository
    from agy_cockpit.backend.db.repositories.message_repository import MessageRepository
    from agy_cockpit.backend.domain.models import Workspace, Conversation, Message
    from agy_cockpit.backend.domain.enums import MessageRole

    ws = Workspace(id="ws1", canonical_path="/tmp/ws", display_name="ws")
    await WorkspaceRepository(db_conn).create(ws)

    repo = RunRepository(db_conn)
    conv_repo = ConversationRepository(db_conn)
    msg_repo = MessageRepository(db_conn)

    states = [RunState.STREAMING, RunState.WAITING_APPROVAL, RunState.THINKING]
    for idx, state in enumerate(states):
        cid = f"c{idx+1}"
        mid = f"m{idx+1}"
        conv = Conversation.model_construct(id=cid, workspace_id="ws1", title=cid)
        await conv_repo.create(conv)
        msg = Message(id=mid, conversation_id=cid, role=MessageRole.USER, content="hi")
        await msg_repo.create(msg)
        r = Run(id=f"run-{state.value}", conversation_id=cid, user_message_id=mid, state=state)
        await repo.create(r)

    interrupted_count = await repo.interrupt_orphaned_runs()
    assert interrupted_count >= 3

    for state in states:
        updated = await repo.get_by_id(f"run-{state.value}")
        assert updated.state == RunState.INTERRUPTED

