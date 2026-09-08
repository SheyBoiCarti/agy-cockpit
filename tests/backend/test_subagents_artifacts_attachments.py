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


def test_artifact_path_traversal_forbidden(phase7_setup):
    """Verifies that an artifact pointing outside allowed dirs is rejected with 403."""
    cfg, ws_dir = phase7_setup
    app = create_app(config=cfg, agent_adapter=MockAntigravityAdapter())

    with TestClient(app) as client:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            from agy_cockpit.backend.services.artifact_service import ArtifactService
            from agy_cockpit.backend.db.repositories.run_repository import RunRepository
            from agy_cockpit.backend.db.repositories.message_repository import MessageRepository
            from agy_cockpit.backend.db.repositories.workspace_repository import WorkspaceRepository
            from agy_cockpit.backend.domain.models import Run, Message, Workspace, Conversation
            from agy_cockpit.backend.domain.enums import RunState, MessageRole
            from agy_cockpit.backend.db.connection import get_db_connection

            async def _reg_evil():
                conn = await get_db_connection(cfg.db_path)
                ws_repo = WorkspaceRepository(conn)
                msg_repo = MessageRepository(conn)
                run_repo = RunRepository(conn)

                from agy_cockpit.backend.db.repositories.conversation_repository import ConversationRepository
                conv_repo = ConversationRepository(conn)
                ws = Workspace(canonical_path=ws_dir, display_name="test_ws")
                await ws_repo.create(ws)

                conv = Conversation(workspace_id=ws.id, title="Test Conv")
                await conv_repo.create(conv)

                user_msg = Message(
                    conversation_id=conv.id,
                    role=MessageRole.USER,
                    content="Hello",
                )
                await msg_repo.create(user_msg)

                real_run = Run(
                    conversation_id=conv.id,
                    user_message_id=user_msg.id,
                    state=RunState.COMPLETED,
                    started_at="2026-01-01T00:00:00Z",
                )
                await run_repo.create(real_run)

                svc = ArtifactService(conn)
                evil_art = await svc.register_artifact(
                    run_id=real_run.id,
                    name="passwd",
                    path_or_storage_key="/etc/passwd",
                    kind=ArtifactKind.FILE,
                    mime_type="text/plain",
                    preview_supported=True,
                )
                await conn.close()
                return evil_art

            evil_art = loop.run_until_complete(_reg_evil())
        finally:
            loop.close()

        # GET content should fail with 403 Forbidden
        resp = client.get(f"/api/artifacts/{evil_art.id}/content")
        assert resp.status_code == 403
        assert "outside allowed directories" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_cli_subscription_adapter_stream_parsing():
    """Verifies that CLISubscriptionAdapter correctly parses stream-json events from agy CLI."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from agy_cockpit.backend.services.agent_service import CLISubscriptionAdapter

    adapter = CLISubscriptionAdapter(agy_binary_path="/mock/bin/agy")

    ndjson_output = (
        '{"type":"init","session_id":"cli-conv-1"}\n'
        '{"type":"step_update","delta":{"thinking":"Planning steps..."}}\n'
        '{"type":"step_update","delta":{"tool_calls":[{"name":"run_command","args":{"command":"echo hello"},"id":"tc1"}]}}\n'
        '{"type":"step_update","delta":{"text":"Hello"}}\n'
        '{"type":"step_update","delta":{"text":" world!"}}\n'
        '{"type":"result","status":"completed","error_message":null}\n'
    ).encode("utf-8")

    mock_proc = MagicMock()
    mock_proc.stdout = asyncio.StreamReader()
    mock_proc.stdout.feed_data(ndjson_output)
    mock_proc.stdout.feed_eof()
    mock_proc.stderr = asyncio.StreamReader()
    mock_proc.stderr.feed_eof()
    mock_proc.wait = AsyncMock(return_value=0)

    thoughts = []
    tokens = []
    tools_started = []

    async def async_thought(t): thoughts.append(t)
    async def async_token(t): tokens.append(t)
    async def async_tool_start(tid, name, args): tools_started.append((tid, name, args))
    async def noop(*args, **kwargs): return True

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        cancel_token = asyncio.Event()
        result = await adapter.run_turn(
            conversation_id="conv-1",
            save_dir="/tmp",
            workspace_path="/tmp",
            prompt="say hello",
            model_slug="gemini-3.8-flash-high",
            policy_preset="always-proceed",
            approval_handler=noop,
            on_thought=async_thought,
            on_token=async_token,
            on_tool_start=async_tool_start,
            on_tool_finish=noop,
            cancellation_token=cancel_token,
        )

    assert result.final_text == "Hello world!"
    assert "".join(thoughts) == "Planning steps..."
    assert len(tools_started) == 1
    assert tools_started[0][1] == "run_command"
    assert tools_started[0][2] == {"command": "echo hello"}
    assert result.error_message is None


def test_unified_antigravity_adapter_selection():
    """Verifies that UnifiedAntigravityAdapter selects CLI when available."""
    import shutil
    from unittest.mock import patch
    from agy_cockpit.backend.services.agent_service import UnifiedAntigravityAdapter

    with patch.dict(os.environ, {}, clear=True):
        with patch("shutil.which", return_value="/mock/bin/agy"):
            adapter = UnifiedAntigravityAdapter()
            assert adapter._should_use_cli() is True


def test_ws_upload_attachment_and_get_artifact(phase7_setup):
    """Verifies that upload_attachment and get_artifact work over WebSocket protocol."""
    import base64
    from agy_cockpit.backend.domain.enums import ArtifactKind
    from agy_cockpit.backend.services.artifact_service import ArtifactService

    cfg, ws_dir = phase7_setup
    app = create_app(config=cfg, agent_adapter=MockAntigravityAdapter())

    with TestClient(app) as client:
        # Pre-create artifact in database before connecting websocket
        art_id = None
        loop = asyncio.new_event_loop()
        try:
            from agy_cockpit.backend.db.connection import get_db_connection
            from agy_cockpit.backend.db.repositories.workspace_repository import WorkspaceRepository
            from agy_cockpit.backend.db.repositories.conversation_repository import ConversationRepository
            from agy_cockpit.backend.db.repositories.message_repository import MessageRepository
            from agy_cockpit.backend.db.repositories.run_repository import RunRepository
            from agy_cockpit.backend.domain.models import Workspace, Conversation, Message, Run
            from agy_cockpit.backend.domain.enums import RunState, MessageRole

            async def _create_art():
                conn = await get_db_connection(cfg.db_path)
                ws = Workspace(canonical_path=ws_dir, display_name="art_ws")
                await WorkspaceRepository(conn).create(ws)
                conv = Conversation(workspace_id=ws.id, title="Art Conv")
                await ConversationRepository(conn).create(conv)
                user_msg = Message(conversation_id=conv.id, role=MessageRole.USER, content="Generate report")
                await MessageRepository(conn).create(user_msg)
                run = Run(conversation_id=conv.id, user_message_id=user_msg.id, state=RunState.COMPLETED, started_at="2026-01-01T00:00:00Z")
                await RunRepository(conn).create(run)

                art_file = os.path.join(ws_dir, "report.md")
                with open(art_file, "w") as f:
                    f.write("# Final Report\nAll good.")
                svc = ArtifactService(conn)
                art = await svc.register_artifact(
                    run_id=run.id,
                    name="report.md",
                    path_or_storage_key=art_file,
                    kind=ArtifactKind.REPORT,
                    mime_type="text/markdown",
                )
                art_id = art.id
                await conn.close()
                return conv.id, art_id
            conv_id, art_id = loop.run_until_complete(_create_art())
        finally:
            loop.close()

        with client.websocket_connect(
            f"/ws?token={cfg.token}",
            headers={"Origin": "http://127.0.0.1:8080"},
        ) as ws:
            # 0. Handshake
            ws.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "hello",
                "request_id": "r0",
                "session_id": "s1",
                "payload": {},
            }))
            ack = json.loads(ws.receive_text())
            assert ack["type"] == "hello_ack"

            # 1. Test upload_attachment
            raw_content = b"key: value\nfoo: bar"
            b64_content = base64.b64encode(raw_content).decode("ascii")

            ws.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "upload_attachment",
                "request_id": "r_up",
                "session_id": "s1",
                "conversation_id": conv_id,
                "payload": {
                    "filename": "test.yaml",
                    "mime_type": "application/x-yaml",
                    "data_base64": b64_content,
                },
            }))

            evt1 = json.loads(ws.receive_text())
            evt2 = json.loads(ws.receive_text())

            events = [evt1, evt2]
            types = [e["type"] for e in events]
            assert "attachment_ready" in types
            assert "command_result" in types

            # 2. Test get_artifact
            ws.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "get_artifact",
                "request_id": "r_art",
                "session_id": "s1",
                "payload": {
                    "artifact_id": art_id,
                },
            }))

            art_res = json.loads(ws.receive_text())
            assert art_res["type"] == "command_result"
            assert art_res["payload"]["success"] is True
            assert art_res["payload"]["artifact"]["id"] == art_id
            assert "# Final Report" in art_res["payload"]["artifact"]["content"]


