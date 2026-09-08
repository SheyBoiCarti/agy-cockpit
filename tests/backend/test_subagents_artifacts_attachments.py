import asyncio
import io
import json
import os
import tempfile
import pytest
from fastapi.testclient import TestClient

from agy_cockpit.backend.app import create_app
from agy_cockpit.backend.config import AppConfig
from agy_cockpit.backend.domain.enums import ArtifactKind
from agy_cockpit.backend.domain.models import Artifact
from agy_cockpit.backend.services.agent_service import MockAntigravityAdapter
from agy_cockpit.backend.ws.protocol import PROTOCOL_VERSION


@pytest.fixture
def phase7_setup():
    with tempfile.TemporaryDirectory() as tmpdir:
        ws_dir = os.path.join(tmpdir, "workspace")
        os.makedirs(ws_dir, exist_ok=True)
        with open(os.path.join(ws_dir, "code.py"), "w") as f:
            f.write("# Python code")

        cfg = AppConfig(
            data_dir=tmpdir,
            token="sec-token",
            allowed_origins=["http://127.0.0.1:8080"],
        )
        yield cfg, ws_dir


def test_subagent_hierarchy_and_events(phase7_setup):
    """Verifies that subagents emit sequenced updates with hierarchy (parent_id, depth)."""
    cfg, ws_dir = phase7_setup

    mock_adapter = MockAntigravityAdapter(
        thoughts=["I will delegate to a subagent"],
        tokens=["Subagent finished."],
        subagents=[
            {
                "id": "subagent-parent",
                "parent_id": None,
                "name_or_role": "Architect",
                "state": "running",
                "current_activity": "Designing system...",
                "depth": 1,
            },
            {
                "id": "subagent-child",
                "parent_id": "subagent-parent",
                "name_or_role": "Code Researcher",
                "state": "running",
                "current_activity": "Searching codebase...",
                "depth": 2,
            },
            {
                "id": "subagent-child",
                "parent_id": "subagent-parent",
                "name_or_role": "Code Researcher",
                "state": "completed",
                "current_activity": "Done researching.",
                "depth": 2,
            },
        ],
        delay=0.01,
    )

    app = create_app(config=cfg, agent_adapter=mock_adapter)
    with TestClient(app) as client:
        with client.websocket_connect(f"/ws?token={cfg.token}", headers={"Origin": "http://127.0.0.1:8080"}) as ws:
            ws.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "open_workspace",
                "request_id": "r1",
                "session_id": "s1",
                "payload": {"canonical_path": ws_dir},
            }))
            ws_id = json.loads(ws.receive_text())["payload"]["workspace"]["id"]

            ws.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "create_conversation",
                "request_id": "r2",
                "session_id": "s1",
                "payload": {"workspace_id": ws_id},
            }))
            conv_id = json.loads(ws.receive_text())["payload"]["conversation"]["id"]

            ws.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "send_prompt",
                "request_id": "r3",
                "session_id": "s1",
                "conversation_id": conv_id,
                "payload": {"prompt": "Run subagents"},
            }))

            subagent_events = []
            for _ in range(20):
                evt = json.loads(ws.receive_text())
                if evt["type"] == "subagent_update":
                    subagent_events.append(evt["payload"])
                if evt["type"] == "run_completed":
                    break

            assert len(subagent_events) == 3
            assert subagent_events[0]["name_or_role"] == "Architect"
            assert subagent_events[0]["depth"] == 1
            assert subagent_events[1]["parent_id"] == "subagent-parent"
            assert subagent_events[1]["depth"] == 2
            assert subagent_events[2]["state"] == "completed"


def test_attachment_upload_and_security_controls(phase7_setup):
    """Verifies attachment upload, hash calculation, and type/size limits."""
    cfg, ws_dir = phase7_setup
    app = create_app(config=cfg)

    with TestClient(app) as client:
        # Create a conversation first
        with client.websocket_connect(f"/ws?token={cfg.token}", headers={"Origin": "http://127.0.0.1:8080"}) as ws:
            ws.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "open_workspace",
                "request_id": "r1",
                "session_id": "s1",
                "payload": {"canonical_path": ws_dir},
            }))
            ws_id = json.loads(ws.receive_text())["payload"]["workspace"]["id"]

            ws.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "create_conversation",
                "request_id": "r2",
                "session_id": "s1",
                "payload": {"workspace_id": ws_id},
            }))
            conv_id = json.loads(ws.receive_text())["payload"]["conversation"]["id"]

        # 1. Valid text upload
        content = b"Hello, this is an attached document."
        resp = client.post(
            "/api/attachments",
            data={"conversation_id": conv_id},
            files={"file": ("notes.txt", io.BytesIO(content), "text/plain")},
        )
        assert resp.status_code == 200
        att_data = resp.json()["attachment"]
        att_id = att_data["id"]
        assert att_data["filename"] == "notes.txt"
        assert att_data["size_bytes"] == len(content)
        assert len(att_data["sha256"]) == 64

        # Check retrieval endpoint
        get_resp = client.get(f"/api/attachments/{att_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["attachment"]["id"] == att_id

        # 2. Reject malicious executable MIME
        resp_bad_mime = client.post(
            "/api/attachments",
            data={"conversation_id": conv_id},
            files={"file": ("malware.exe", io.BytesIO(b"MZ\x00\x00"), "application/x-dosexec")},
        )
        assert resp_bad_mime.status_code == 400

        # 3. Path traversal in original filename does not affect storage path
        resp_trav = client.post(
            "/api/attachments",
            data={"conversation_id": conv_id},
            files={"file": ("../../etc/passwd", io.BytesIO(b"root"), "text/plain")},
        )
        assert resp_trav.status_code == 200
        trav_att = resp_trav.json()["attachment"]
        # Storage path is a random UUID inside data_dir
        assert ".." not in trav_att["storage_path"]
        assert os.path.exists(trav_att["storage_path"])


def test_attachment_in_send_prompt_validation(phase7_setup):
    """Asserts that invalid attachment_ids in send_prompt are rejected with protocol_error."""
    cfg, ws_dir = phase7_setup
    app = create_app(config=cfg)

    with TestClient(app) as client:
        with client.websocket_connect(f"/ws?token={cfg.token}", headers={"Origin": "http://127.0.0.1:8080"}) as ws:
            ws.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "open_workspace",
                "request_id": "r1",
                "session_id": "s1",
                "payload": {"canonical_path": ws_dir},
            }))
            ws_id = json.loads(ws.receive_text())["payload"]["workspace"]["id"]

            ws.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "create_conversation",
                "request_id": "r2",
                "session_id": "s1",
                "payload": {"workspace_id": ws_id},
            }))
            conv_id = json.loads(ws.receive_text())["payload"]["conversation"]["id"]

            # Prompt with non-existent attachment
            ws.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "send_prompt",
                "request_id": "r3",
                "session_id": "s1",
                "conversation_id": conv_id,
                "payload": {
                    "prompt": "Inspect attachment",
                    "attachment_ids": ["non-existent-uuid-1234"],
                },
            }))

            err = json.loads(ws.receive_text())
            assert err["type"] == "protocol_error"
            assert "Attachment" in err["payload"]["message"]


def test_artifact_registration_and_sandboxed_preview(phase7_setup):
    """Tests artifact creation and sandboxed preview headers for HTML."""
    cfg, ws_dir = phase7_setup
    app = create_app(config=cfg)

    html_file = os.path.join(ws_dir, "preview.html")
    with open(html_file, "w") as f:
        f.write("<html><body><h1>Sandboxed Preview</h1><script>alert(1)</script></body></html>")

    with TestClient(app) as client:
        # Create a conversation and run so run_id exists
        with client.websocket_connect(f"/ws?token={cfg.token}", headers={"Origin": "http://127.0.0.1:8080"}) as ws:
            ws.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "open_workspace",
                "request_id": "r1",
                "session_id": "s1",
                "payload": {"canonical_path": ws_dir},
            }))
            ws_id = json.loads(ws.receive_text())["payload"]["workspace"]["id"]

            ws.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "create_conversation",
                "request_id": "r2",
                "session_id": "s1",
                "payload": {"workspace_id": ws_id},
            }))
            conv_id = json.loads(ws.receive_text())["payload"]["conversation"]["id"]

        # Run registration on loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            from agy_cockpit.backend.services.artifact_service import ArtifactService
            from agy_cockpit.backend.db.repositories.run_repository import RunRepository
            from agy_cockpit.backend.db.repositories.message_repository import MessageRepository
            from agy_cockpit.backend.domain.models import Run, Message
            from agy_cockpit.backend.domain.enums import RunState, MessageRole
            from agy_cockpit.backend.db.connection import get_db_connection

            async def _reg():
                conn = await get_db_connection(cfg.db_path)
                msg_repo = MessageRepository(conn)
                run_repo = RunRepository(conn)

                user_msg = Message(
                    conversation_id=conv_id,
                    role=MessageRole.USER,
                    content="Hello",
                )
                await msg_repo.create(user_msg)

                real_run = Run(
                    conversation_id=conv_id,
                    user_message_id=user_msg.id,
                    state=RunState.COMPLETED,
                    started_at="2026-01-01T00:00:00Z",
                )
                await run_repo.create(real_run)

                svc = ArtifactService(conn)
                res = await svc.register_artifact(
                    run_id=real_run.id,
                    name="preview.html",
                    path_or_storage_key=html_file,
                    kind=ArtifactKind.FILE,
                    mime_type="text/html",
                    preview_supported=True,
                )
                await conn.close()
                return res

            art = loop.run_until_complete(_reg())
        finally:
            loop.close()

        # GET metadata
        resp = client.get(f"/api/artifacts/{art.id}")
        assert resp.status_code == 200
        assert resp.json()["artifact"]["name"] == "preview.html"

        # GET content with security headers
        content_resp = client.get(f"/api/artifacts/{art.id}/content")
        assert content_resp.status_code == 200
        assert "text/html" in content_resp.headers["content-type"]
        assert "Sandboxed Preview" in content_resp.text
        # Security sandbox header
        csp = content_resp.headers.get("content-security-policy", "")
        assert "sandbox" in csp
        assert "default-src 'none'" in csp
