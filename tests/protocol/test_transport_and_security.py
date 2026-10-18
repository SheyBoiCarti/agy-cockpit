"""Phase 3 Tests: Protocol v1, Connection Security, Replay, and Snapshot Recovery."""

import asyncio
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
    ApprovalRepository,
    ConversationRepository,
    EventRepository,
    MessageRepository,
    RunRepository,
    WorkspaceRepository,
)
from agy_cockpit.backend.domain.enums import (
    ApprovalDecision,
    MessageRole,
    RunState,
)
from agy_cockpit.backend.domain.models import (
    ApprovalRequest,
    Conversation,
    EventRecord,
    Message,
    Run,
    Workspace,
)
from agy_cockpit.backend.ws.protocol import (
    PROTOCOL_VERSION,
    ProtocolErrorCode,
    create_server_event,
)


@pytest.fixture
def temp_config():
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = AppConfig(
            data_dir=tmpdir,
            token="test-secret-token-12345",
            allowed_origins=["http://127.0.0.1:8080", "http://localhost:8080"],
            max_payload_bytes=1024 * 1024,  # 1MB
        )
        yield cfg


# --- Security Tests ---

def test_health_check(temp_config):
    app = create_app(temp_config)
    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"


def test_origin_validation(temp_config):
    app = create_app(temp_config)
    with TestClient(app) as client:
        # 1. Allowed origin -> connect successfully
        with client.websocket_connect(
            f"/ws?token={temp_config.token}",
            headers={"Origin": "http://127.0.0.1:8080"},
        ) as ws:
            ws.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "ping",
                "request_id": "r1",
                "session_id": "s1",
                "payload": {},
            }))
            data = json.loads(ws.receive_text())
            assert data["type"] == "pong"

        # 2. Untrusted origin -> rejected
        with pytest.raises(Exception):
            with client.websocket_connect(
                f"/ws?token={temp_config.token}",
                headers={"Origin": "http://evil-attacker.com"},
            ) as ws:
                ws.receive_text()

        # 3. Spoofed subdomain of loopback -> rejected
        with pytest.raises(Exception):
            with client.websocket_connect(
                f"/ws?token={temp_config.token}",
                headers={"Origin": "http://127.0.0.1.attacker.com:8080"},
            ) as ws:
                ws.receive_text()

        with pytest.raises(Exception):
            with client.websocket_connect(
                f"/ws?token={temp_config.token}",
                headers={"Origin": "http://localhost.attacker.com"},
            ) as ws:
                ws.receive_text()


def test_token_authentication(temp_config):
    app = create_app(temp_config)
    with TestClient(app) as client:
        # Invalid token -> rejected
        with pytest.raises(Exception):
            with client.websocket_connect(
                "/ws?token=wrong-token",
                headers={"Origin": "http://127.0.0.1:8080"},
            ) as ws:
                ws.receive_text()

        # Missing token -> rejected
        with pytest.raises(Exception):
            with client.websocket_connect(
                "/ws",
                headers={"Origin": "http://127.0.0.1:8080"},
            ) as ws:
                ws.receive_text()


def test_malformed_and_oversized_messages(temp_config):
    app = create_app(temp_config)
    with TestClient(app) as client:
        with client.websocket_connect(
            f"/ws?token={temp_config.token}",
            headers={"Origin": "http://127.0.0.1:8080"},
        ) as ws:
            # 1. Malformed JSON string
            ws.send_text("this is not valid json")
            resp = json.loads(ws.receive_text())
            assert resp["type"] == "protocol_error"
            assert resp["payload"]["error_code"] == ProtocolErrorCode.INVALID_MESSAGE.value

            # 2. Unsupported protocol version
            ws.send_text(json.dumps({
                "protocol_version": 999,
                "type": "ping",
                "request_id": "r2",
                "session_id": "s1",
                "payload": {},
            }))
            resp = json.loads(ws.receive_text())
            assert resp["type"] == "protocol_error"
            assert resp["payload"]["error_code"] == ProtocolErrorCode.PROTOCOL_VERSION_UNSUPPORTED.value

            # 3. Connection is still alive and responds to ping
            ws.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "ping",
                "request_id": "r3",
                "session_id": "s1",
                "payload": {},
            }))
            resp = json.loads(ws.receive_text())
            assert resp["type"] == "pong"


# --- Recovery Tests ---

@pytest.mark.asyncio
async def test_reconnect_replay_monotonic_100_events(temp_config):
    """Emits 100 sequenced events, disconnects after event 40, reconnects,

    requests replay starting after 40, and asserts exactly events 41..100 are received.
    """
    await init_db(temp_config.db_path)
    conn = await get_db_connection(temp_config.db_path)
    try:
        ws_repo = WorkspaceRepository(conn)
        conv_repo = ConversationRepository(conn)
        msg_repo = MessageRepository(conn)
        run_repo = RunRepository(conn)
        event_repo = EventRepository(conn)

        ws = await ws_repo.create(Workspace(canonical_path="/fake/path", display_name="test"))
        conv_id = str(uuid.uuid4())
        conv = await conv_repo.create(Conversation(id=conv_id, workspace_id=ws.id, title="Replay Test"))
        msg = await msg_repo.create(Message(conversation_id=conv.id, role=MessageRole.USER, content="Generate"))
        run = await run_repo.create(Run(conversation_id=conv.id, user_message_id=msg.id, state=RunState.STREAMING))

        # Insert 100 sequenced events
        for seq in range(1, 101):
            rec = EventRecord(
                event_id=f"evt-{seq}",
                run_id=run.id,
                conversation_id=conv.id,
                sequence=seq,
                type="token_delta",
                payload_json=json.dumps({"delta": f"token_{seq}"}),
                replayable=True,
            )
            await event_repo.create(rec)
    finally:
        await conn.close()

    # Now connect client and request resume_run_stream starting after seq 40
    app = create_app(temp_config)
    with TestClient(app) as client:
        with client.websocket_connect(
            f"/ws?token={temp_config.token}",
            headers={"Origin": "http://127.0.0.1:8080"},
        ) as ws:
            # Send resume_run_stream
            ws.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "resume_run_stream",
                "request_id": "req-resume",
                "session_id": "session-test",
                "run_id": run.id,
                "payload": {
                    "run_id": run.id,
                    "last_seen_sequence": 40,
                },
            }))

            replayed_sequences = []
            # Read 60 replayed events (41..100)
            for _ in range(60):
                msg = json.loads(ws.receive_text())
                assert msg["type"] == "token_delta"
                assert msg["run_id"] == run.id
                replayed_sequences.append(msg["sequence"])

            assert replayed_sequences == list(range(41, 101))


@pytest.mark.asyncio
async def test_reconnect_during_pending_approval_snapshot(temp_config):
    """Disconnects while approval is pending, reconnects, requests sync_state

    snapshot and asserts pending approval is present in canonical state.
    """
    await init_db(temp_config.db_path)
    conn = await get_db_connection(temp_config.db_path)
    try:
        ws_repo = WorkspaceRepository(conn)
        conv_repo = ConversationRepository(conn)
        msg_repo = MessageRepository(conn)
        run_repo = RunRepository(conn)
        appr_repo = ApprovalRepository(conn)

        ws = await ws_repo.create(Workspace(canonical_path="/fake/path", display_name="test"))
        conv_id = str(uuid.uuid4())
        conv = await conv_repo.create(Conversation(id=conv_id, workspace_id=ws.id, title="Approval Test"))
        msg = await msg_repo.create(Message(conversation_id=conv.id, role=MessageRole.USER, content="Run bash"))
        run = await run_repo.create(Run(conversation_id=conv.id, user_message_id=msg.id, state=RunState.WAITING_APPROVAL))

        appr = await appr_repo.create(ApprovalRequest(
            run_id=run.id,
            sdk_tool_name="run_command",
            args_json='{"command": "rm -rf /"}',
            reason="Dangerous command",
        ))
    finally:
        await conn.close()

    # Query snapshot via replay service without restarting the app
    app = create_app(temp_config)
    with TestClient(app) as client:
        # Re-set run and approval in DB to simulate active approval while server is running
        conn2 = await get_db_connection(temp_config.db_path)
        try:
            await conn2.execute(
                "UPDATE runs SET state = ? WHERE id = ?",
                (RunState.WAITING_APPROVAL.value, run.id),
            )
            await conn2.execute(
                "UPDATE approval_requests SET decision = NULL, resolved_at = NULL WHERE id = ?",
                (appr.id,),
            )
            await conn2.commit()
        finally:
            await conn2.close()

        replay_service = app.state.replay_service
        snapshot = await replay_service.build_sync_state_payload(run.id)
        assert snapshot is not None
        assert snapshot["state"] == RunState.WAITING_APPROVAL.value
        assert snapshot["pending_approval"] is not None
        assert snapshot["pending_approval"]["sdk_tool_name"] == "run_command"
        assert snapshot["pending_approval"]["reason"] == "Dangerous command"
