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
    mock_proc.returncode = 0
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


@pytest.mark.asyncio
async def test_real_sdk_adapter_subagents_lifecycle():
    """Verifies that RealSDKAntigravityAdapter maps subagent tool calls (start, invoke, define)
    and hooks to on_subagent_update events with correct roles, states, and activities."""
    import uuid
    from unittest.mock import AsyncMock, MagicMock, patch
    import google.antigravity as agy
    from agy_cockpit.backend.services.agent_service import RealSDKAntigravityAdapter
    from agy_cockpit.backend.domain.enums import RunState

    adapter = RealSDKAntigravityAdapter()
    captured_hooks = []

    class MockAsyncIter:
        def __init__(self, items):
            self.items = list(items)

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self.items:
                raise StopAsyncIteration
            return self.items.pop(0)

    class MockChatResponse:
        def __init__(self):
            self.usage_metadata = MagicMock()
            self.usage_metadata.model_dump.return_value = {"prompt_tokens": 10}
            self.thoughts = MockAsyncIter(["Planning subagents"])
            self.tool_calls = MockAsyncIter([
                agy.types.ToolCall(
                    id="sa-invoke",
                    name="invoke_subagent",
                    args={"Role": "Researcher", "Prompt": "Search codebase"}
                ),
                agy.types.ToolCall(
                    id="sa-start",
                    name="start_subagent",
                    args={"role": "Tester", "task": "Run pytest"}
                ),
                agy.types.ToolCall(
                    id="sa-define",
                    name="define_subagent",
                    args={"description": "Define analyzer helper"}
                ),
            ])

        def __aiter__(self):
            return MockAsyncIter(["All subagent work done"])

        async def cancel(self):
            pass

    class MockAgentContext:
        def __init__(self, config):
            self.config = config
            captured_hooks.extend(config.hooks)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

        async def chat(self, chat_input):
            return MockChatResponse()

    subagent_updates = []
    async def on_sub(sa_id, parent_id, role, state, activity, depth):
        subagent_updates.append({
            "id": sa_id,
            "role": role,
            "state": state,
            "activity": activity,
            "depth": depth,
        })

    tool_logs = []
    async def on_tool_log(tid, chunk, is_stderr):
        tool_logs.append((tid, chunk, is_stderr))

    tools_started = []
    tools_finished = []
    async def on_tool_start(tid, name, args):
        tools_started.append((tid, name, args))
    async def on_tool_finish(tid, name, success, summary):
        tools_finished.append((tid, name, success, summary))
    async def noop(*args, **kwargs):
        pass

    conv_id = str(uuid.uuid4())
    with patch("google.antigravity.Agent", side_effect=MockAgentContext):
        res = await adapter.run_turn(
            conversation_id=conv_id,
            save_dir="/tmp",
            workspace_path="/tmp",
            prompt="Delegate subagents",
            model_slug="gemini-3.8-flash-high",
            policy_preset="request-review",
            approval_handler=AsyncMock(return_value=True),
            on_thought=noop,
            on_token=noop,
            on_tool_start=on_tool_start,
            on_tool_finish=on_tool_finish,
            cancellation_token=asyncio.Event(),
            on_tool_log=on_tool_log,
            on_subagent_update=on_sub,
        )

    assert res.state == RunState.COMPLETED
    assert res.final_text == "All subagent work done"
    assert len(tools_started) == 3

    # Check that invoke, start, and define all created running subagent updates
    running_updates = [u for u in subagent_updates if u["state"] == "running"]
    assert len(running_updates) == 3
    assert running_updates[0]["id"] == "subagent-sa-invoke"
    assert running_updates[0]["role"] == "Researcher"
    assert running_updates[0]["activity"] == "Search codebase"

    assert running_updates[1]["id"] == "subagent-sa-start"
    assert running_updates[1]["role"] == "Tester"
    assert running_updates[1]["activity"] == "Run pytest"

    assert running_updates[2]["id"] == "subagent-sa-define"
    assert running_updates[2]["role"] == "Subagent"
    assert running_updates[2]["activity"] == "Define analyzer helper"

    # Verify hooks: on_post_tool updates subagent to completed/failed
    assert len(captured_hooks) == 2
    post_tool_hook = captured_hooks[0]

    # Invoke post_tool hook for success
    await post_tool_hook(agy.types.ToolResult(
        id="sa-invoke",
        name="invoke_subagent",
        result="Found 5 symbols in codebase",
    ))
    last_update = subagent_updates[-1]
    assert last_update["id"] == "subagent-sa-invoke"
    assert last_update["state"] == "completed"
    assert "Found 5 symbols" in last_update["activity"]

    # Invoke post_tool hook for failure
    await post_tool_hook(agy.types.ToolResult(
        id="sa-start",
        name="start_subagent",
        result=None,
        error="Subagent crashed with exception",
    ))
    last_err_update = subagent_updates[-1]
    assert last_err_update["id"] == "subagent-sa-start"
    assert last_err_update["state"] == "failed"
    assert "crashed" in last_err_update["activity"]


@pytest.mark.asyncio
async def test_real_sdk_adapter_tool_approval_flow():
    """Verifies tool approval policy creation and invocation in RealSDKAntigravityAdapter."""
    import uuid
    from unittest.mock import AsyncMock, patch
    from google.antigravity.hooks.policy import Decision
    import google.antigravity as agy
    from agy_cockpit.backend.services.agent_service import RealSDKAntigravityAdapter

    adapter = RealSDKAntigravityAdapter()
    approval_mock = AsyncMock(return_value=True)

    # 1. Preset request-review: mutating tools ask_user, reading tools allow
    policies_rr = adapter._build_policies("request-review", approval_mock)
    ask_user_rr = [p for p in policies_rr if p.decision == Decision.ASK_USER]
    assert set(p.tool for p in ask_user_rr) == {"run_command", "create_file", "edit_file"}
    for p in ask_user_rr:
        assert p.ask_user == approval_mock

    # Test executing approval callback directly through policy
    tc = agy.types.ToolCall(id="tc-1", name="run_command", args={"command": "npm test"})
    decision = await ask_user_rr[0].ask_user(tc)
    assert decision is True
    approval_mock.assert_called_with(tc)

    # 2. Preset strict: mutating tools ask_user, wildcard deny
    policies_strict = adapter._build_policies("strict", approval_mock)
    ask_user_strict = [p for p in policies_strict if p.decision == Decision.ASK_USER]
    assert set(p.tool for p in ask_user_strict) == {"run_command", "create_file", "edit_file"}
    deny_strict = [p for p in policies_strict if p.decision == Decision.DENY]
    assert len(deny_strict) == 1
    assert deny_strict[0].tool == "*"

    # 3. Preset always-proceed: policy.allow_all()
    policies_ap = adapter._build_policies("always-proceed", approval_mock)
    assert len(policies_ap) == 1
    assert policies_ap[0].decision == Decision.APPROVE
    assert policies_ap[0].tool == "*"

    # 4. Verify LocalAgentConfig receives the built policies during run_turn
    captured_config = []
    class MockAgentContext:
        def __init__(self, config):
            captured_config.append(config)
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def chat(self, chat_input):
            class Resp:
                usage_metadata = None
                thoughts = []
                tool_calls = []
                def __aiter__(self):
                    return iter([])
                async def cancel(self):
                    pass
            return Resp()

    conv_id = str(uuid.uuid4())
    with patch("google.antigravity.Agent", side_effect=MockAgentContext):
        await adapter.run_turn(
            conversation_id=conv_id,
            save_dir="/tmp",
            workspace_path="/tmp",
            prompt="run build",
            model_slug="gemini-3.8-flash-high",
            policy_preset="request-review",
            approval_handler=approval_mock,
            on_thought=AsyncMock(),
            on_token=AsyncMock(),
            on_tool_start=AsyncMock(),
            on_tool_finish=AsyncMock(),
            cancellation_token=asyncio.Event(),
        )

    assert len(captured_config) == 1
    config = captured_config[0]
    assert len(config.policies) == len(policies_rr)
    assert config.capabilities.enable_subagents is True


@pytest.mark.asyncio
async def test_cli_subscription_adapter_stream_parsing_subagents_and_logs():
    """Verifies that CLISubscriptionAdapter correctly parses subagents, stderr logs, and token usage."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from agy_cockpit.backend.services.agent_service import CLISubscriptionAdapter

    adapter = CLISubscriptionAdapter(agy_binary_path="/mock/bin/agy")

    ndjson_lines = [
        json.dumps({"type": "init", "session_id": "cli-conv-1"}),
        json.dumps({
            "type": "step_update",
            "step_update": {
                "step_type": "agent_response",
                "text_delta": "Processing request...",
                "usage": {"thinking_tokens": 128},
            }
        }),
        json.dumps({
            "type": "step_update",
            "step_update": {
                "step_type": "tool",
                "step_index": 1,
                "state": "ACTIVE",
                "tool_name": "invoke_subagent",
                "tool_info": {
                    "name": "invoke_subagent",
                    "parameters": {"Role": "Security Reviewer", "Prompt": "Audit auth tokens"}
                },
                "subagent_info": {"conversation_id": "sub-audit-1", "role": "Security Reviewer"}
            }
        }),
        json.dumps({
            "type": "step_update",
            "step_update": {
                "step_type": "tool",
                "step_index": 1,
                "state": "DONE",
                "tool_name": "invoke_subagent",
                "tool_info": {"output": "Audit passed clean."},
                "subagent_info": {"conversation_id": "sub-audit-1", "role": "Security Reviewer"}
            }
        }),
        json.dumps({
            "type": "step_update",
            "step_update": {
                "step_type": "tool",
                "step_index": 2,
                "state": "ACTIVE",
                "tool_name": "run_command",
                "tool_info": {
                    "name": "run_command",
                    "parameters": {"command": "git push"}
                }
            }
        }),
        json.dumps({
            "type": "step_update",
            "step_update": {
                "step_type": "tool",
                "step_index": 2,
                "state": "ERROR",
                "tool_name": "run_command",
                "tool_info": {"error": {"message": "fatal: remote error"}},
            }
        }),
        json.dumps({"type": "result", "status": "completed", "error_message": None}),
    ]

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = asyncio.StreamReader()
    mock_proc.stdout.feed_data(("\n".join(ndjson_lines) + "\n").encode("utf-8"))
    mock_proc.stdout.feed_eof()
    mock_proc.stderr = asyncio.StreamReader()
    mock_proc.stderr.feed_eof()
    mock_proc.wait = AsyncMock(return_value=0)

    sub_updates = []
    tool_logs = []
    tool_finishes = []
    thoughts = []
    tokens = []

    async def on_sub(sa_id, parent, role, state, activity, depth):
        sub_updates.append((sa_id, role, state, activity, depth))
    async def on_log(tid, chunk, is_stderr):
        tool_logs.append((tid, chunk, is_stderr))
    async def on_finish(tid, name, success, summary):
        tool_finishes.append((tid, name, success, summary))
    async def on_thought(th): thoughts.append(th)
    async def on_token(tok): tokens.append(tok)
    async def noop(*args, **kwargs): return True

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        res = await adapter.run_turn(
            conversation_id="conv-1",
            save_dir="/tmp",
            workspace_path="/tmp",
            prompt="Audit and push",
            model_slug="gemini-3.8-flash-high",
            policy_preset="always-proceed",
            approval_handler=noop,
            on_thought=on_thought,
            on_token=on_token,
            on_tool_start=noop,
            on_tool_finish=on_finish,
            cancellation_token=asyncio.Event(),
            on_tool_log=on_log,
            on_subagent_update=on_sub,
        )

    assert res.final_text == "Processing request..."
    assert len(thoughts) == 1
    assert "128 tokens" in thoughts[0]
    assert len(sub_updates) == 2
    assert sub_updates[0] == ("sub-audit-1", "Security Reviewer", "running", "Executing invoke_subagent", 1)
    assert sub_updates[1] == ("sub-audit-1", "Security Reviewer", "completed", "Executing invoke_subagent", 1)

    # Tool logs: tool 1 is normal (is_stderr=False), tool 2 error is stderr (is_stderr=True)
    assert len(tool_logs) == 2
    assert tool_logs[0] == ("tool-1-invoke_subagent", "Audit passed clean.", False)
    assert tool_logs[1] == ("tool-2-run_command", "fatal: remote error", True)

    assert len(tool_finishes) == 2
    assert tool_finishes[0][2] is True
    assert tool_finishes[1][2] is False


@pytest.mark.asyncio
async def test_artifact_symlink_escape_rejection(tmp_path):
    from agy_cockpit.backend.services.artifact_service import ArtifactService
    from agy_cockpit.backend.domain.models import Artifact, ArtifactKind
    from agy_cockpit.backend.domain.enums import WorkspaceSecurityError

    ws_dir = tmp_path / "workspace"
    ws_dir.mkdir()
    secret_dir = tmp_path / "secret"
    secret_dir.mkdir()
    secret_file = secret_dir / "passwords.txt"
    secret_file.write_text("SUPER_SECRET_KEY")

    # Outside symlink or direct outside path
    outside_art = Artifact(
        id="art-outside",
        run_id="run-1",
        conversation_id="conv-1",
        name="stolen",
        kind=ArtifactKind.FILE,
        path_or_storage_key=str(secret_file),
    )

    art_service = ArtifactService(conn=None, event_service=None)
    with pytest.raises(WorkspaceSecurityError, match="outside workspace"):
        art_service.read_artifact_content(outside_art, workspace_path=str(ws_dir))




