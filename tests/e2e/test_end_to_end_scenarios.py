"""End-to-End acceptance tests certifying all 12 operational scenarios.

Scenario Coverage:
1. launch with workspace
2. create conversation
3. send prompt
4. view reasoning/output
5. approve a command
6. watch terminal output
7. edit file and inspect diff
8. spawn subagent and inspect tree
9. upload supported attachment
10. disconnect/reconnect mid-run
11. cancel another run
12. restart backend and resume conversation
"""

import asyncio
import io
import json
import os
import tempfile
import pytest
from fastapi.testclient import TestClient

from agy_cockpit.backend.app import create_app
from agy_cockpit.backend.config import AppConfig
from agy_cockpit.backend.domain.enums import MessageRole, RunState
from agy_cockpit.backend.domain.models import Message, Run
from agy_cockpit.backend.services.agent_service import MockAntigravityAdapter
from agy_cockpit.backend.ws.protocol import PROTOCOL_VERSION


@pytest.fixture
def e2e_environment():
    with tempfile.TemporaryDirectory() as tmpdir:
        ws_dir = os.path.join(tmpdir, "my_project")
        os.makedirs(ws_dir, exist_ok=True)
        init_file = os.path.join(ws_dir, "script.py")
        with open(init_file, "w") as f:
            f.write("print('original version')\n")

        cfg = AppConfig(
            data_dir=tmpdir,
            token="e2e-secret-launch-token",
            allowed_origins=["http://127.0.0.1:8080", "http://localhost:8080"],
        )
        yield cfg, ws_dir


def test_scenarios_1_to_8_full_turn_lifecycle(e2e_environment):
    """Executes Scenarios 1 through 8 in an integrated turn:
    1. launch with workspace
    2. create conversation
    3. send prompt
    4. view reasoning/output
    5. approve a command
    6. watch terminal output
    7. edit file and inspect diff
    8. spawn subagent and inspect tree
    """
    cfg, ws_dir = e2e_environment

    adapter = MockAntigravityAdapter(
        thoughts=["Investigating project files...", "Found script.py, preparing update."],
        tokens=["I have completed ", "updating script.py ", "and ran tests."],
        subagents=[
            {
                "id": "sa-root",
                "parent_id": None,
                "name_or_role": "Lead Architect",
                "state": "running",
                "current_activity": "Orchestrating test plan",
                "depth": 1,
            },
            {
                "id": "sa-leaf",
                "parent_id": "sa-root",
                "name_or_role": "Test Runner",
                "state": "completed",
                "current_activity": "Executed unit tests",
                "depth": 2,
            },
        ],
        tools=[
            {
                "id": "tool-cmd-1",
                "name": "run_command",
                "args": {"command": "pytest -v"},
                "requires_approval": True,
            },
            {
                "id": "tool-edit-1",
                "name": "edit_file",
                "args": {
                    "file_path": "script.py",
                    "content": "print('modified version for e2e')\n",
                },
                "requires_approval": False,
            },
        ],
        tool_logs={
            "tool-cmd-1": [
                "platform linux -- pytest\n",
                "tests/test_script.py .. [100%]\n",
                "2 passed in 0.05s\n",
            ]
        },
        delay=0.01,
    )

    app = create_app(config=cfg, agent_adapter=adapter)
    with TestClient(app) as client:
        with client.websocket_connect(
            f"/ws?token={cfg.token}",
            headers={"Origin": "http://127.0.0.1:8080"},
        ) as ws:
            # 1. Launch with workspace
            ws.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "open_workspace",
                "request_id": "req-open-ws",
                "session_id": "s1",
                "payload": {"canonical_path": ws_dir},
            }))
            ws_res = json.loads(ws.receive_text())
            assert ws_res["type"] == "workspace_opened"
            workspace_id = ws_res["payload"]["workspace"]["id"]
            assert ws_res["payload"]["workspace"]["canonical_path"] == ws_dir

            # 2. Create conversation
            ws.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "create_conversation",
                "request_id": "req-create-conv",
                "session_id": "s1",
                "payload": {"workspace_id": workspace_id, "title": "E2E Master Chat"},
            }))
            conv_res = json.loads(ws.receive_text())
            assert conv_res["type"] == "conversation_created"
            conv_id = conv_res["payload"]["conversation"]["id"]
            assert len(conv_id) >= 32

            # 3. Send prompt
            ws.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "send_prompt",
                "request_id": "req-send-prompt",
                "session_id": "s1",
                "conversation_id": conv_id,
                "payload": {"prompt": "Please run tests and update script.py"},
            }))

            run_start = json.loads(ws.receive_text())
            assert run_start["type"] == "run_started"
            run_id = run_start["payload"]["run_id"]

            reasoning_chunks = []
            token_chunks = []
            tool_logs_received = []
            subagents_received = []
            approval_received = False
            file_changed_received = False
            run_completed = False

            while not run_completed:
                raw = ws.receive_text()
                evt = json.loads(raw)
                evt_type = evt.get("type")

                # 4. View reasoning & output
                if evt_type == "reasoning_delta":
                    reasoning_chunks.append(evt["payload"]["delta"])
                elif evt_type == "token_delta":
                    token_chunks.append(evt["payload"]["delta"])

                # 8. Spawn subagent and inspect tree
                elif evt_type == "subagent_update":
                    subagents_received.append(evt["payload"])

                # 5. Approve a command
                elif evt_type == "approval_required":
                    approval_received = True
                    assert evt["payload"]["sdk_tool_name"] == "run_command"
                    approval_id = evt["payload"]["approval_request_id"]
                    # Respond with approved decision
                    ws.send_text(json.dumps({
                        "protocol_version": PROTOCOL_VERSION,
                        "type": "action_approval",
                        "request_id": "req-approve",
                        "session_id": "s1",
                        "conversation_id": conv_id,
                        "run_id": run_id,
                        "payload": {
                            "approval_request_id": approval_id,
                            "decision": "approved",
                        },
                    }))

                elif evt_type == "approval_resolved":
                    assert evt["payload"]["decision"] == "approved"

                # 6. Watch terminal output
                elif evt_type == "tool_log":
                    tool_logs_received.append(evt["payload"]["chunk"])

                # 7. Edit file and inspect diff
                elif evt_type == "file_changed":
                    file_changed_received = True
                    assert evt["payload"]["file_path"] == "script.py"

                elif evt_type == "run_completed":
                    run_completed = True
                    assert evt["payload"]["usage"] is not None

            # Assertions for Scenarios 4, 5, 6, 7, 8
            assert len(reasoning_chunks) >= 2
            assert "Investigating project files..." in "".join(reasoning_chunks)
            assert len(token_chunks) >= 3
            assert "updating script.py" in "".join(token_chunks)
            assert approval_received is True
            assert len(tool_logs_received) >= 3
            assert any("pytest" in chunk for chunk in tool_logs_received)
            assert file_changed_received is True
            assert len(subagents_received) == 2
            assert subagents_received[0]["depth"] == 1
            assert subagents_received[1]["depth"] == 2
            assert subagents_received[1]["parent_id"] == "sa-root"

            # Verify Diff inspection via get_file_diff command
            ws.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "get_file_diff",
                "request_id": "req-get-diff",
                "session_id": "s1",
                "conversation_id": conv_id,
                "payload": {"file_path": "script.py"},
            }))
            diff_evt = json.loads(ws.receive_text())
            assert diff_evt["type"] == "file_diff_data"
            assert diff_evt["payload"]["file_path"] == "script.py"
            assert "original version" in diff_evt["payload"]["original_content"]
            assert "modified version for e2e" in diff_evt["payload"]["modified_content"]


def test_scenario_9_attachment_multimodal_flow(e2e_environment):
    """Scenario 9: Upload supported attachment and pass to prompt."""
    cfg, ws_dir = e2e_environment
    adapter = MockAntigravityAdapter(tokens=["Inspected yaml successfully."])
    app = create_app(config=cfg, agent_adapter=adapter)

    with TestClient(app) as client:
        # Create workspace and conversation
        with client.websocket_connect(
            f"/ws?token={cfg.token}",
            headers={"Origin": "http://127.0.0.1:8080"},
        ) as ws:
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

        # Upload attachment via HTTP endpoint
        file_bytes = b"Config options:\nport: 8080\n"
        upload_resp = client.post(
            "/api/attachments",
            data={"conversation_id": conv_id},
            files={"file": ("config.yaml", io.BytesIO(file_bytes), "application/x-yaml")},
        )
        assert upload_resp.status_code == 200
        att = upload_resp.json()["attachment"]
        att_id = att["id"]
        assert att["filename"] == "config.yaml"
        assert att["size_bytes"] == len(file_bytes)

        # GET attachment metadata
        get_resp = client.get(f"/api/attachments/{att_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["attachment"]["id"] == att_id

        # Send prompt referencing valid attachment
        with client.websocket_connect(
            f"/ws?token={cfg.token}",
            headers={"Origin": "http://127.0.0.1:8080"},
        ) as ws:
            ws.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "send_prompt",
                "request_id": "r3",
                "session_id": "s1",
                "conversation_id": conv_id,
                "payload": {
                    "prompt": "Analyze attached config",
                    "attachment_ids": [att_id],
                },
            }))
            start_evt = json.loads(ws.receive_text())
            assert start_evt["type"] == "run_started"


def test_scenario_10_disconnect_reconnect_mid_run(e2e_environment):
    """Scenario 10: Disconnect mid-run, reconnect with session_id, and resume stream."""
    cfg, ws_dir = e2e_environment

    adapter = MockAntigravityAdapter(
        thoughts=["Thinking slow 1...", "Thinking slow 2..."],
        tokens=[f"tok-{i} " for i in range(15)],
        delay=0.03,
    )
    app = create_app(config=cfg, agent_adapter=adapter)

    with TestClient(app) as client:
        # 1. Connect and start run
        with client.websocket_connect(
            f"/ws?token={cfg.token}&session_id=persist-sess-10",
            headers={"Origin": "http://127.0.0.1:8080"},
        ) as ws1:
            ws1.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "open_workspace",
                "request_id": "r1",
                "session_id": "persist-sess-10",
                "payload": {"canonical_path": ws_dir},
            }))
            ws_id = json.loads(ws1.receive_text())["payload"]["workspace"]["id"]

            ws1.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "create_conversation",
                "request_id": "r2",
                "session_id": "persist-sess-10",
                "payload": {"workspace_id": ws_id},
            }))
            conv_id = json.loads(ws1.receive_text())["payload"]["conversation"]["id"]

            ws1.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "send_prompt",
                "request_id": "r3",
                "session_id": "persist-sess-10",
                "conversation_id": conv_id,
                "payload": {"prompt": "Generate stream"},
            }))

            start_evt = json.loads(ws1.receive_text())
            assert start_evt["type"] == "run_started"
            run_id = start_evt["payload"]["run_id"]

            # Read only 3 events then disconnect
            last_seq = 0
            for _ in range(3):
                e = json.loads(ws1.receive_text())
                if "sequence" in e:
                    last_seq = e["sequence"]

        # Reconnect with resume_run_stream
        with client.websocket_connect(
            f"/ws?token={cfg.token}&session_id=persist-sess-10",
            headers={"Origin": "http://127.0.0.1:8080"},
        ) as ws2:
            ws2.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "resume_run_stream",
                "request_id": "r-resume",
                "session_id": "persist-sess-10",
                "conversation_id": conv_id,
                "run_id": run_id,
                "payload": {
                    "conversation_id": conv_id,
                    "run_id": run_id,
                    "last_seen_sequence": last_seq,
                },
            }))

            # Collect rest of run
            resumed_tokens = []
            completed = False
            for _ in range(50):
                msg = json.loads(ws2.receive_text())
                if msg.get("type") == "token_delta":
                    resumed_tokens.append(msg["payload"]["delta"])
                elif msg.get("type") == "run_completed":
                    completed = True
                    break

            assert completed is True
            assert len(resumed_tokens) > 0


def test_scenario_11_cancel_another_run(e2e_environment):
    """Scenario 11: Cancel an active run and verify terminal state."""
    cfg, ws_dir = e2e_environment

    adapter = MockAntigravityAdapter(
        thoughts=["Entering long-running task..."],
        tokens=["This will not complete."],
        delay=0.01,
        wait_for_cancel=True,
    )
    app = create_app(config=cfg, agent_adapter=adapter)

    with TestClient(app) as client:
        with client.websocket_connect(
            f"/ws?token={cfg.token}",
            headers={"Origin": "http://127.0.0.1:8080"},
        ) as ws:
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
                "payload": {"prompt": "Run forever until cancelled"},
            }))

            run_start = json.loads(ws.receive_text())
            assert run_start["type"] == "run_started"
            run_id = run_start["payload"]["run_id"]

            # Read thought
            th = json.loads(ws.receive_text())
            assert th["type"] == "reasoning_delta"

            # Cancel run
            ws.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "cancel_run",
                "request_id": "r-cancel",
                "session_id": "s1",
                "conversation_id": conv_id,
                "payload": {"run_id": run_id},
            }))

            cancel_evt = json.loads(ws.receive_text())
            assert cancel_evt["type"] == "run_cancelled"
            assert cancel_evt["payload"]["run_id"] == run_id


def test_scenario_12_backend_restart_and_conversation_resumption(e2e_environment):
    """Scenario 12: Restart backend, reconnect, and resume persistent conversation."""
    cfg, ws_dir = e2e_environment

    # Server instance 1: Run a complete turn
    adapter1 = MockAntigravityAdapter(tokens=["Turn 1 response."])
    app1 = create_app(config=cfg, agent_adapter=adapter1)
    conv_id = None

    with TestClient(app1) as client1:
        with client1.websocket_connect(
            f"/ws?token={cfg.token}",
            headers={"Origin": "http://127.0.0.1:8080"},
        ) as ws1:
            ws1.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "open_workspace",
                "request_id": "r1",
                "session_id": "s1",
                "payload": {"canonical_path": ws_dir},
            }))
            ws_id = json.loads(ws1.receive_text())["payload"]["workspace"]["id"]

            ws1.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "create_conversation",
                "request_id": "r2",
                "session_id": "s1",
                "payload": {"workspace_id": ws_id, "title": "Persistent Turn Chat"},
            }))
            conv_id = json.loads(ws1.receive_text())["payload"]["conversation"]["id"]

            ws1.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "send_prompt",
                "request_id": "r3",
                "session_id": "s1",
                "conversation_id": conv_id,
                "payload": {"prompt": "Initial turn message"},
            }))

            # Drain until run_completed
            while True:
                evt = json.loads(ws1.receive_text())
                if evt.get("type") == "run_completed":
                    break

    # Simulate full backend shutdown, then restart server instance 2 pointing to same database
    adapter2 = MockAntigravityAdapter()
    app2 = create_app(config=cfg, agent_adapter=adapter2)
    with TestClient(app2) as client2:
        with client2.websocket_connect(
            f"/ws?token={cfg.token}",
            headers={"Origin": "http://127.0.0.1:8080"},
        ) as ws2:
            # Re-open conversation
            ws2.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "open_conversation",
                "request_id": "r-resume-after-restart",
                "session_id": "s2",
                "conversation_id": conv_id,
                "payload": {"conversation_id": conv_id},
            }))

            snapshot = json.loads(ws2.receive_text())
            assert snapshot["type"] == "conversation_snapshot"
            assert snapshot["payload"]["conversation"]["id"] == conv_id
            assert snapshot["payload"]["conversation"]["title"] == "Persistent Turn Chat"
            messages = snapshot["payload"]["messages"]
            assert len(messages) >= 2
            assert messages[0]["content"] == "Initial turn message"
            assert messages[1]["role"] == "assistant"
