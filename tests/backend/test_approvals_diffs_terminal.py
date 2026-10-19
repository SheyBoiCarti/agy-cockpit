"""Phase 6 Integration Tests: Approvals, Diffs, and Terminal Output."""

import asyncio
import json
import os
import tempfile
import pytest
from fastapi.testclient import TestClient

from agy_cockpit.backend.app import create_app
from agy_cockpit.backend.config import AppConfig
from agy_cockpit.backend.domain.enums import ApprovalDecision
from agy_cockpit.backend.services.agent_service import MockAntigravityAdapter
from agy_cockpit.backend.services.diff_service import DiffService
from agy_cockpit.backend.ws.protocol import PROTOCOL_VERSION


@pytest.fixture
def phase6_setup():
    with tempfile.TemporaryDirectory() as tmpdir:
        ws_dir = os.path.join(tmpdir, "workspace")
        os.makedirs(ws_dir, exist_ok=True)
        # Create an existing file
        with open(os.path.join(ws_dir, "app.py"), "w") as f:
            f.write("def main():\n    print('initial')\n")

        cfg = AppConfig(
            data_dir=tmpdir,
            token="sec-token",
            allowed_origins=["http://127.0.0.1:8080"],
        )
        yield cfg, ws_dir


def test_tool_approval_approved_path(phase6_setup):
    """Verifies that approval_required blocks until action_approval is sent, and approved proceeds."""
    cfg, ws_dir = phase6_setup

    mock_adapter = MockAntigravityAdapter(
        thoughts=["I will run a command"],
        tokens=["Command executed."],
        tools=[{
            "id": "cmd-1",
            "name": "run_command",
            "args": {"command": "echo 'safe'"},
            "requires_approval": True,
        }],
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

            # Prompt
            ws.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "send_prompt",
                "request_id": "r3",
                "session_id": "s1",
                "conversation_id": conv_id,
                "payload": {"prompt": "Run the command"},
            }))

            # Listen for approval_required
            approval_id = None
            for _ in range(10):
                raw = ws.receive_text()
                evt = json.loads(raw)
                if evt["type"] == "approval_required":
                    approval_id = evt["payload"]["approval_request_id"]
                    assert evt["payload"]["sdk_tool_name"] == "run_command"
                    assert evt["payload"]["args"]["command"] == "echo 'safe'"
                    break

            assert approval_id is not None, "Did not receive approval_required event"

            # Send action_approval: approved
            ws.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "action_approval",
                "request_id": "r4",
                "session_id": "s1",
                "conversation_id": conv_id,
                "payload": {
                    "approval_request_id": approval_id,
                    "decision": "approved",
                },
            }))

            # Observe approval_resolved, tool execution, and completion
            resolved_seen = False
            tool_finished_seen = False
            for _ in range(15):
                raw = ws.receive_text()
                evt = json.loads(raw)
                if evt["type"] == "approval_resolved":
                    resolved_seen = True
                    assert evt["payload"]["decision"] == "approved"
                if evt["type"] == "tool_finished":
                    tool_finished_seen = True
                    assert evt["payload"]["success"] is True
                if evt["type"] == "run_completed":
                    break

            assert resolved_seen
            assert tool_finished_seen


def test_tool_approval_rejected_path(phase6_setup):
    """Verifies that rejecting an approval stops tool execution."""
    cfg, ws_dir = phase6_setup

    mock_adapter = MockAntigravityAdapter(
        thoughts=["I will format drive"],
        tokens=["Operation finished."],
        tools=[{
            "id": "cmd-danger",
            "name": "run_command",
            "args": {"command": "rm -rf /"},
            "requires_approval": True,
        }],
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
                "payload": {"prompt": "Run danger"},
            }))

            approval_id = None
            for _ in range(10):
                evt = json.loads(ws.receive_text())
                if evt["type"] == "approval_required":
                    approval_id = evt["payload"]["approval_request_id"]
                    break

            assert approval_id is not None

            # Reject
            ws.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "action_approval",
                "request_id": "r4",
                "session_id": "s1",
                "conversation_id": conv_id,
                "payload": {
                    "approval_request_id": approval_id,
                    "decision": "rejected",
                },
            }))

            rejected_tool_seen = False
            for _ in range(15):
                evt = json.loads(ws.receive_text())
                if evt["type"] == "tool_finished":
                    assert evt["payload"]["success"] is False
                    rejected_tool_seen = True
                if evt["type"] == "run_completed":
                    break

            assert rejected_tool_seen


def test_file_diff_service_direct(phase6_setup):
    """Tests DiffService directly for non-git file edit, creation, and binary detection."""
    cfg, ws_dir = phase6_setup
    diff_svc = DiffService()

    # 1. Edit existing app.py
    rel_p = "app.py"
    diff_svc.capture_pre_edit_snapshot(ws_dir, rel_p)

    # Modify file on disk
    abs_p = os.path.join(ws_dir, rel_p)
    with open(abs_p, "w") as f:
        f.write("def main():\n    print('updated')\n")

    diff = diff_svc.get_file_diff(ws_dir, rel_p)
    assert diff.status == "modified"
    assert "print('initial')" in diff.original_content
    assert "print('updated')" in diff.modified_content
    assert diff.language == "python"
    assert diff.is_binary is False

    # 2. Create new file
    new_p = "src/index.ts"
    diff_svc.capture_pre_edit_snapshot(ws_dir, new_p)
    abs_new = os.path.join(ws_dir, new_p)
    os.makedirs(os.path.dirname(abs_new), exist_ok=True)
    with open(abs_new, "w") as f:
        f.write("const a: number = 42;")

    diff_new = diff_svc.get_file_diff(ws_dir, new_p)
    assert diff_new.status == "added"
    assert diff_new.original_content == ""
    assert "const a: number = 42;" in diff_new.modified_content
    assert diff_new.language == "typescript"

    # 3. Binary file detection
    bin_p = "data.bin"
    abs_bin = os.path.join(ws_dir, bin_p)
    with open(abs_bin, "wb") as f:
        f.write(b"\x00\x01\x02\x03\x04")

    diff_bin = diff_svc.get_file_diff(ws_dir, bin_p)
    assert diff_bin.is_binary is True


def test_file_change_and_diff_via_websocket(phase6_setup):
    """Tests file_changed event emission during run and get_file_diff retrieval."""
    cfg, ws_dir = phase6_setup

    mock_adapter = MockAntigravityAdapter(
        thoughts=["Updating app.py"],
        tokens=["File updated."],
        tools=[{
            "id": "t-edit",
            "name": "edit_file",
            "args": {
                "file_path": "app.py",
                "content": "def main():\n    print('via websocket')\n",
            },
        }],
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

            # Prompt
            ws.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "send_prompt",
                "request_id": "r3",
                "session_id": "s1",
                "conversation_id": conv_id,
                "payload": {"prompt": "Update file"},
            }))

            file_changed_seen = False
            for _ in range(15):
                evt = json.loads(ws.receive_text())
                if evt["type"] == "file_changed":
                    file_changed_seen = True
                    assert evt["payload"]["file_path"] == "app.py"
                    assert evt["payload"]["status"] == "modified"
                if evt["type"] == "run_completed":
                    break

            assert file_changed_seen, "Expected file_changed event"

            # Request diff over websocket
            ws.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "get_file_diff",
                "request_id": "r4",
                "session_id": "s1",
                "conversation_id": conv_id,
                "payload": {"file_path": "app.py"},
            }))

            diff_evt = json.loads(ws.receive_text())
            assert diff_evt["type"] == "file_diff_data"
            assert diff_evt["payload"]["file_path"] == "app.py"
            assert "via websocket" in diff_evt["payload"]["modified_content"]
            assert "initial" in diff_evt["payload"]["original_content"]


def test_tool_log_streaming_chunks(phase6_setup):
    """Tests streaming command tool logs."""
    cfg, ws_dir = phase6_setup

    mock_adapter = MockAntigravityAdapter(
        thoughts=["Running build"],
        tokens=["Build succeeded."],
        tools=[{
            "id": "t-cmd",
            "name": "run_command",
            "args": {"command": "npm run build"},
        }],
        tool_logs={
            "t-cmd": [
                "vite building...\n",
                "transforming (1/10)...\n",
                "✓ built in 120ms\n",
            ]
        },
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
                "payload": {"prompt": "Build project"},
            }))

            logs_received = []
            for _ in range(20):
                evt = json.loads(ws.receive_text())
                if evt["type"] == "tool_log":
                    logs_received.append(evt["payload"]["chunk"])
                if evt["type"] == "run_completed":
                    break

            assert len(logs_received) == 3
            assert "vite building..." in logs_received[0]
            assert "built in 120ms" in logs_received[2]


@pytest.mark.asyncio
async def test_cli_adapter_without_native_hook_fails_closed(tmp_path):
    """ACTIVE telemetry must never be mistaken for a pre-execution approval."""
    from agy_cockpit.backend.services.agent_service import CLISubscriptionAdapter
    from agy_cockpit.backend.domain.enums import RunState
    import sys
    import tempfile
    import stat

    # Create a mock agy script that emits a tool ACTIVE step
    mock_script = tmp_path / "mock_agy.py"
    mock_script.write_text(
        "import sys, time\n"
        "sys.stdout.write('{\"event\":\"step_update\",\"step_update\":{\"step_type\":\"tool\",\"tool_name\":\"run_command\",\"state\":\"ACTIVE\",\"tool_info\":{\"parameters\":{\"command\":\"echo dangerous\"}}}}\\n')\n"
        "sys.stdout.flush()\n"
        "time.sleep(5)\n"
    )

    adapter = CLISubscriptionAdapter(agy_binary_path=sys.executable)
    orig_build_cmd = adapter._build_cmd
    adapter._build_cmd = lambda *args, **kwargs: [sys.executable, str(mock_script)]
    cancel_token = asyncio.Event()

    async def reject_handler(tc):
        return False

    async def noop(*args, **kwargs):
        pass

    result = await adapter.run_turn(
        conversation_id="c1",
        save_dir=str(tmp_path),
        workspace_path=str(tmp_path),
        prompt="run something",
        model_slug="gemini-2.5-pro",
        policy_preset="ask-destructive",
        approval_handler=reject_handler,
        on_thought=noop,
        on_token=noop,
        on_tool_start=noop,
        on_tool_finish=noop,
        cancellation_token=cancel_token,
    )

    assert result.state == RunState.FAILED
    assert 'permission hook did not initialize' in result.error_message


@pytest.mark.asyncio
async def test_workspace_filesystem_watcher(tmp_path):
    """Verifies that WorkspaceService live watcher detects filesystem changes using watchfiles."""
    from agy_cockpit.backend.services.workspace_service import WorkspaceService
    from agy_cockpit.backend.db.connection import get_db_connection, init_db

    db_path = str(tmp_path / "test.db")
    ws_dir = str(tmp_path / "ws")
    os.makedirs(ws_dir, exist_ok=True)

    await init_db(db_path)
    conn = await get_db_connection(db_path)
    changes_detected = []
    change_event = asyncio.Event()

    async def on_change(ws_id, rel_path, status):
        changes_detected.append((rel_path, status))
        change_event.set()

    svc = WorkspaceService(conn, on_file_change=on_change)
    ws = await svc.open_workspace(ws_dir)
    await asyncio.sleep(0.2)

    try:
        # Create a file in workspace
        new_file = os.path.join(ws_dir, "hello.txt")
        with open(new_file, "w") as f:
            f.write("hello world")

        # Wait for watcher to pick it up (with timeout)
        try:
            await asyncio.wait_for(change_event.wait(), timeout=3.0)
        except asyncio.TimeoutError:
            pass

        assert len(changes_detected) > 0
        assert any(c[0] == "hello.txt" for c in changes_detected)
    finally:
        svc.stop_all_watchers()
        await conn.close()


