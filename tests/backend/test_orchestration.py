"""Phase 4 Integration Tests: Agent Orchestration, Streaming, and Lifecycle."""

import asyncio
import json
import os
import tempfile
import uuid
import pytest
from fastapi.testclient import TestClient

from agy_cockpit.backend.app import create_app
from agy_cockpit.backend.config import AppConfig
from agy_cockpit.backend.domain.enums import RunState
from agy_cockpit.backend.services.agent_service import MockAntigravityAdapter
from agy_cockpit.backend.ws.protocol import PROTOCOL_VERSION


@pytest.fixture
def test_setup():
    with tempfile.TemporaryDirectory() as tmpdir:
        ws_dir = os.path.join(tmpdir, "my_workspace")
        os.makedirs(ws_dir, exist_ok=True)
        # Create some files for search
        os.makedirs(os.path.join(ws_dir, "src"), exist_ok=True)
        with open(os.path.join(ws_dir, "src", "index.ts"), "w") as f:
            f.write("console.log('hi');")
        with open(os.path.join(ws_dir, "README.md"), "w") as f:
            f.write("# Hello")

        # Ignore folder
        os.makedirs(os.path.join(ws_dir, ".git"), exist_ok=True)
        with open(os.path.join(ws_dir, ".git", "config"), "w") as f:
            f.write("gitconfig")

        cfg = AppConfig(
            data_dir=tmpdir,
            token="secret-token-1234",
            allowed_origins=["http://127.0.0.1:8080"],
        )
        yield cfg, ws_dir


def test_full_turn_streaming_lifecycle(test_setup):
    """Tests opening workspace, creating conversation, sending prompt, receiving

    streamed reasoning, tools, and token deltas, followed by run_completed.
    """
    cfg, ws_dir = test_setup

    mock_adapter = MockAntigravityAdapter(
        thoughts=["I need to check the files.", "Files found."],
        tokens=["Here is the ", "file list."],
        tools=[{
            "id": "t1",
            "name": "list_directory",
            "args": {"directory_path": "."},
            "requires_approval": False,
        }],
        delay=0.01,
    )

    app = create_app(config=cfg, agent_adapter=mock_adapter)
    with TestClient(app) as client:
        with client.websocket_connect(
            f"/ws?token={cfg.token}",
            headers={"Origin": "http://127.0.0.1:8080"},
        ) as ws:
            # 1. Hello
            ws.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "hello",
                "request_id": "req-1",
                "session_id": "sess-1",
                "payload": {},
            }))
            ack = json.loads(ws.receive_text())
            assert ack["type"] == "hello_ack"

            # 2. Open Workspace
            ws.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "open_workspace",
                "request_id": "req-2",
                "session_id": "sess-1",
                "payload": {"canonical_path": ws_dir},
            }))
            ws_opened = json.loads(ws.receive_text())
            assert ws_opened["type"] == "workspace_opened"
            workspace_id = ws_opened["payload"]["workspace"]["id"]

            # 3. Create Conversation
            ws.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "create_conversation",
                "request_id": "req-3",
                "session_id": "sess-1",
                "payload": {"workspace_id": workspace_id, "title": "My Test Chat"},
            }))
            conv_created = json.loads(ws.receive_text())
            assert conv_created["type"] == "conversation_created"
            conv_id = conv_created["payload"]["conversation"]["id"]
            assert len(conv_id) >= 32

            # 4. Send Prompt
            ws.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "send_prompt",
                "request_id": "req-4",
                "session_id": "sess-1",
                "conversation_id": conv_id,
                "payload": {"prompt": "List files"},
            }))

            # Observe events in order: run_started, reasoning_deltas, tool_started, tool_finished, token_deltas, run_completed
            events = []
            while True:
                raw = ws.receive_text()
                evt = json.loads(raw)
                events.append(evt)
                if evt["type"] in ("run_completed", "run_failed", "run_cancelled"):
                    break

            types_received = [e["type"] for e in events]
            assert "run_started" in types_received
            assert "reasoning_delta" in types_received
            assert "tool_started" in types_received
            assert "tool_finished" in types_received
            assert "token_delta" in types_received
            assert "run_completed" in types_received

            # Check sequence monotonicity
            sequences = [e["sequence"] for e in events if e.get("sequence") is not None]
            assert sequences == sorted(sequences)
            assert len(sequences) == len(set(sequences))  # No duplicate sequences!


def test_concurrency_rejection(test_setup):
    """Asserts that starting a prompt while another foreground run is active

    returns RUN_ALREADY_ACTIVE error.
    """
    cfg, ws_dir = test_setup
    mock_adapter = MockAntigravityAdapter(
        thoughts=["Thinking for a long time..."],
        tokens=["Done"],
        delay=0.5,  # Long turn
    )

    app = create_app(config=cfg, agent_adapter=mock_adapter)
    with TestClient(app) as client:
        with client.websocket_connect(
            f"/ws?token={cfg.token}",
            headers={"Origin": "http://127.0.0.1:8080"},
        ) as ws:
            # Open workspace & create conversation
            ws.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "open_workspace",
                "request_id": "req-1",
                "session_id": "sess-1",
                "payload": {"canonical_path": ws_dir},
            }))
            ws_opened = json.loads(ws.receive_text())
            workspace_id = ws_opened["payload"]["workspace"]["id"]

            ws.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "create_conversation",
                "request_id": "req-2",
                "session_id": "sess-1",
                "payload": {"workspace_id": workspace_id, "title": "Concurrency Chat"},
            }))
            conv_id = json.loads(ws.receive_text())["payload"]["conversation"]["id"]

            # Start run 1
            ws.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "send_prompt",
                "request_id": "req-prompt-1",
                "session_id": "sess-1",
                "conversation_id": conv_id,
                "payload": {"prompt": "Prompt 1"},
            }))

            # Immediately send prompt 2
            ws.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "send_prompt",
                "request_id": "req-prompt-2",
                "session_id": "sess-1",
                "conversation_id": conv_id,
                "payload": {"prompt": "Prompt 2"},
            }))

            # Read events until we see protocol_error with RUN_ALREADY_ACTIVE
            error_found = False
            for _ in range(15):
                evt = json.loads(ws.receive_text())
                if evt["type"] == "protocol_error" and evt["payload"]["error_code"] == "RUN_ALREADY_ACTIVE":
                    error_found = True
                    break

            assert error_found, "Expected RUN_ALREADY_ACTIVE protocol_error"


def test_turn_cancellation(test_setup):
    """Tests cancelling an active run."""
    cfg, ws_dir = test_setup
    mock_adapter = MockAntigravityAdapter(
        thoughts=["Thinking..."],
        wait_for_cancel=True,
    )

    app = create_app(config=cfg, agent_adapter=mock_adapter)
    with TestClient(app) as client:
        with client.websocket_connect(
            f"/ws?token={cfg.token}",
            headers={"Origin": "http://127.0.0.1:8080"},
        ) as ws:
            # Setup
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
                "payload": {"prompt": "Long task"},
            }))

            run_started = json.loads(ws.receive_text())
            assert run_started["type"] == "run_started"
            run_id = run_started["payload"]["run_id"]

            # Send cancel_run
            ws.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "cancel_run",
                "request_id": "r4",
                "session_id": "s1",
                "run_id": run_id,
                "payload": {"run_id": run_id},
            }))

            cancelled_received = False
            for _ in range(15):
                evt = json.loads(ws.receive_text())
                if evt["type"] == "run_cancelled":
                    cancelled_received = True
                    break
                elif evt["type"] in ("run_completed", "run_failed"):
                    break

            assert cancelled_received, "Expected run_cancelled event"


def test_workspace_search_and_ignore_rules(test_setup):
    """Tests searching workspace files and verifies .git is ignored."""
    cfg, ws_dir = test_setup
    app = create_app(config=cfg)
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

            # Search workspace
            ws.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "search_workspace",
                "request_id": "r2",
                "session_id": "s1",
                "payload": {"workspace_id": ws_id, "query": "index"},
            }))

            res = json.loads(ws.receive_text())
            assert res["type"] == "workspace_search_results"
            results = res["payload"]["results"]
            assert any(r["path"] == "src/index.ts" for r in results)

            # Assert .git is NOT in search results
            ws.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "search_workspace",
                "request_id": "r3",
                "session_id": "s1",
                "payload": {"workspace_id": ws_id, "query": "git"},
            }))
            res_git = json.loads(ws.receive_text())
            assert not any(".git" in r["path"] for r in res_git["payload"]["results"])


def test_backend_restart_and_conversation_resumption(test_setup):
    """Tests that conversation state and messages survive application restart."""
    cfg, ws_dir = test_setup

    mock_adapter = MockAntigravityAdapter(
        thoughts=["Thinking"],
        tokens=["Hello from turn 1"],
        delay=0.01,
    )

    # 1. Run app instance 1
    app1 = create_app(config=cfg, agent_adapter=mock_adapter)
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
                "payload": {"workspace_id": ws_id, "title": "Persistent Conversation"},
            }))
            conv_id = json.loads(ws1.receive_text())["payload"]["conversation"]["id"]

            ws1.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "send_prompt",
                "request_id": "r3",
                "session_id": "s1",
                "conversation_id": conv_id,
                "payload": {"prompt": "First message"},
            }))
            # Drain until complete
            while True:
                evt = json.loads(ws1.receive_text())
                if evt["type"] == "run_completed":
                    break

    # 2. Simulate complete backend restart (new app instance pointing to same data_dir)
    app2 = create_app(config=cfg, agent_adapter=mock_adapter)
    with TestClient(app2) as client2:
        with client2.websocket_connect(
            f"/ws?token={cfg.token}",
            headers={"Origin": "http://127.0.0.1:8080"},
        ) as ws2:
            # Reopen the saved conversation
            ws2.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "open_conversation",
                "request_id": "r4",
                "session_id": "s2",
                "payload": {"conversation_id": conv_id},
            }))
            snapshot = json.loads(ws2.receive_text())
            assert snapshot["type"] == "conversation_snapshot"
            assert snapshot["payload"]["conversation"]["id"] == conv_id
            assert snapshot["payload"]["conversation"]["title"] == "Persistent Conversation"
            # Both user and assistant messages should be restored
            messages = snapshot["payload"]["messages"]
            assert len(messages) == 2
            assert messages[0]["content"] == "First message"
            assert messages[1]["content"] == "Hello from turn 1"
