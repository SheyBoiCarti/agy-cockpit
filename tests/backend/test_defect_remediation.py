"""Tests validating defect remediation and hardening across agy-cockpit."""

import asyncio
import io
import json
import os
import tempfile
import uuid
import pytest
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
        conv = await conv_repo.create(Conversation(id=str(uuid.uuid4()), workspace_id=ws.id, title="Recovery Conv"))
        msg = await msg_repo.create(Message(conversation_id=conv.id, role=MessageRole.USER, content="Run task"))

        run1 = await run_repo.create(Run(conversation_id=conv.id, user_message_id=msg.id, state=RunState.RUNNING_TOOL))
        run2 = await run_repo.create(Run(conversation_id=conv.id, user_message_id=msg.id, state=RunState.THINKING))
        run3 = await run_repo.create(Run(conversation_id=conv.id, user_message_id=msg.id, state=RunState.QUEUED))
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
