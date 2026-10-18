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


@pytest.mark.asyncio
async def test_cli_adapter_non_zero_exit_fails_run(tmp_path):
    from agy_cockpit.backend.services.agent_service import CLISubscriptionAdapter
    from agy_cockpit.backend.domain.enums import RunState
    import sys

    # Python script that writes to stderr and exits 1
    script = tmp_path / "mock_fail.py"
    script.write_text(
        "import sys\n"
        "sys.stderr.write('Fatal crash in CLI\\n')\n"
        "sys.exit(1)\n"
    )

    adapter = CLISubscriptionAdapter(agy_binary_path=sys.executable)
    # Monkey-patch command generation to pass script
    adapter._build_cmd = lambda *args, **kwargs: [sys.executable, str(script)]

    result = await adapter.run_turn(
        conversation_id="c1",
        save_dir=str(tmp_path),
        workspace_path=str(tmp_path),
        prompt="hello",
        model_slug="gemini-2.5-pro",
        policy_preset="always-proceed",
        approval_handler=None,
        on_thought=lambda t: None,
        on_token=lambda t: None,
        on_tool_start=lambda *a: None,
        on_tool_finish=lambda *a: None,
        cancellation_token=asyncio.Event(),
    )

    assert result.state == RunState.FAILED
    assert "Fatal crash in CLI" in (result.error_message or "")


@pytest.fixture
async def test_orchestration_setup(tmp_path):
    import aiosqlite
    from agy_cockpit.backend.db.connection import init_db
    from agy_cockpit.backend.db.repositories.conversation_repository import ConversationRepository
    from agy_cockpit.backend.db.repositories.run_repository import RunRepository
    from agy_cockpit.backend.db.repositories.workspace_repository import WorkspaceRepository
    from agy_cockpit.backend.services.event_service import EventService
    from agy_cockpit.backend.services.approval_service import ApprovalService
    from agy_cockpit.backend.services.run_service import RunService
    from agy_cockpit.backend.domain.models import Workspace, Conversation

    db_path = str(tmp_path / "test.db")
    from agy_cockpit.backend.db.connection import init_db, get_db_connection
    await init_db(db_path)
    conn = await get_db_connection(db_path)

    ws_dir = str(tmp_path / "workspace")
    os.makedirs(ws_dir, exist_ok=True)
    ws_repo = WorkspaceRepository(conn)
    ws = Workspace(id="ws-1", canonical_path=ws_dir, display_name="test_ws")
    await ws_repo.create(ws)

    conv_repo = ConversationRepository(conn)
    conv = Conversation.model_construct(id="c1", workspace_id=ws.id, title="Test Conv", model_slug="gemini-3.8-flash-high")
    await conv_repo.create(conv)

    run_repo = RunRepository(conn)
    event_service = EventService(conn)
    approval_service = ApprovalService(conn, event_service)
    run_service = RunService(conn, event_service, approval_service)

    yield run_service, conv_repo, run_repo
    await conn.close()


@pytest.mark.asyncio
async def test_run_service_shutdown_cancels_active_runs(test_orchestration_setup):
    run_service, conv_repo, run_repo = test_orchestration_setup
    # Simulate a long-running turn
    cancel_evt = asyncio.Event()
    run_service._cancel_tokens["run-test-shutdown"] = cancel_evt

    async def mock_task():
        await cancel_evt.wait()

    t = asyncio.create_task(mock_task())
    run_service._active_tasks["run-test-shutdown"] = t

    await run_service.shutdown(timeout=1.0)

    assert cancel_evt.is_set()
    assert t.done()


@pytest.mark.asyncio
async def test_concurrent_prompts_race_condition(test_orchestration_setup):
    run_service, conv_repo, run_repo = test_orchestration_setup
    from agy_cockpit.backend.domain.enums import RunAlreadyActiveError

    # Submit two prompts concurrently to the same conversation
    task1 = asyncio.create_task(run_service.start_run("s1", "c1", "prompt 1"))
    task2 = asyncio.create_task(run_service.start_run("s1", "c1", "prompt 2"))

    results = await asyncio.gather(task1, task2, return_exceptions=True)
    successes = [r for r in results if not isinstance(r, Exception)]
    failures = [r for r in results if isinstance(r, RunAlreadyActiveError)]

    assert len(successes) == 1
    assert len(failures) == 1



