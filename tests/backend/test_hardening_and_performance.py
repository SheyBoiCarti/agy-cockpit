"""Security hardening, performance limits, and edge case acceptance tests."""

import asyncio
import io
import json
import os
import tempfile
import time
import pytest
from fastapi.testclient import TestClient

from agy_cockpit.backend.app import create_app
from agy_cockpit.backend.config import AppConfig
from agy_cockpit.backend.domain.workspace import WorkspaceSecurityError, resolve_safe_path
from agy_cockpit.backend.services.agent_service import MockAntigravityAdapter
from agy_cockpit.backend.ws.protocol import PROTOCOL_VERSION, ProtocolErrorCode


@pytest.fixture
def hardening_env():
    with tempfile.TemporaryDirectory() as tmpdir:
        ws_dir = os.path.join(tmpdir, "workspace")
        os.makedirs(ws_dir, exist_ok=True)
        # Create nested file
        nested_dir = os.path.join(ws_dir, "nested")
        os.makedirs(nested_dir, exist_ok=True)
        with open(os.path.join(nested_dir, "app.py"), "w") as f:
            f.write("x = 42\n")

        # Create secret file OUTSIDE workspace
        secret_file = os.path.join(tmpdir, "secret.key")
        with open(secret_file, "w") as f:
            f.write("SECRET_KEY_12345")

        cfg = AppConfig(
            data_dir=tmpdir,
            token="secure-token-1234",
            allowed_origins=["http://127.0.0.1:8080"],
            max_attachment_bytes=1024,  # Small limit for test
        )
        yield cfg, ws_dir, secret_file


def test_path_traversal_and_symlink_escape_rejection(hardening_env):
    """Verifies that resolve_safe_path forbids directory traversal and symlink escapes."""
    cfg, ws_dir, secret_file = hardening_env

    # 1. Directory traversal relative path
    with pytest.raises(WorkspaceSecurityError):
        resolve_safe_path(ws_dir, "../secret.key")

    with pytest.raises(WorkspaceSecurityError):
        resolve_safe_path(ws_dir, "../../etc/passwd")

    # 2. Malicious symlink pointing outside workspace
    escape_symlink = os.path.join(ws_dir, "symlink_escape")
    try:
        os.symlink(secret_file, escape_symlink)
    except (OSError, NotImplementedError) as e:
        if getattr(e, "winerror", None) == 1314 or isinstance(e, PermissionError):
            pytest.skip("Symlink creation requires elevated privileges on Windows (winerror 1314)")
        raise

    with pytest.raises(WorkspaceSecurityError):
        resolve_safe_path(ws_dir, "symlink_escape")


def test_attachment_oversized_rejection(hardening_env):
    """Verifies that attachments exceeding max_bytes are rejected with HTTP 400."""
    cfg, ws_dir, _ = hardening_env
    app = create_app(config=cfg)

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

        # Attempt to upload 2048 bytes when max is 1024 bytes
        big_content = b"A" * 2048
        resp = client.post(
            "/api/attachments",
            data={"conversation_id": conv_id},
            files={"file": ("large.txt", io.BytesIO(big_content), "text/plain")},
        )
        assert resp.status_code == 400
        assert "exceeds maximum allowed size" in resp.json()["detail"]


def test_high_volume_token_streaming_performance(hardening_env):
    """Simulates high-throughput streaming (500 tokens) to ensure no dropped sequences or lag."""
    cfg, ws_dir, _ = hardening_env

    # 500 tokens
    tokens = [f"tok_{i} " for i in range(500)]
    adapter = MockAntigravityAdapter(
        thoughts=["Warmup"],
        tokens=tokens,
        delay=0.0,  # fast streaming
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

            t0 = time.perf_counter()
            ws.send_text(json.dumps({
                "protocol_version": PROTOCOL_VERSION,
                "type": "send_prompt",
                "request_id": "r3",
                "session_id": "s1",
                "conversation_id": conv_id,
                "payload": {"prompt": "Benchmark stream"},
            }))

            received_tokens = []
            completed = False
            while not completed:
                msg = json.loads(ws.receive_text())
                if msg.get("type") == "token_delta":
                    received_tokens.append(msg["payload"]["delta"])
                elif msg.get("type") == "run_completed":
                    completed = True

            elapsed = time.perf_counter() - t0
            assert completed is True
            assert len(received_tokens) == 500
            # Ensure throughput is high (< 5 seconds for 500 tokens)
            assert elapsed < 5.0


def test_terminal_spooled_bounded_log_chunks(hardening_env):
    """Simulates 100 tool log chunks streamed without blocking or memory blowup."""
    cfg, ws_dir, _ = hardening_env

    log_chunks = [f"[log-line-{i}] Output line from test build\n" for i in range(100)]
    adapter = MockAntigravityAdapter(
        thoughts=["Compiling..."],
        tokens=["Build done."],
        tools=[
            {
                "id": "build-tool-1",
                "name": "run_command",
                "args": {"command": "cargo build"},
            }
        ],
        tool_logs={"build-tool-1": log_chunks},
        delay=0.0,
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
                "payload": {"prompt": "Run build"},
            }))

            collected_logs = []
            while True:
                msg = json.loads(ws.receive_text())
                if msg.get("type") == "tool_log":
                    collected_logs.append(msg["payload"]["chunk"])
                elif msg.get("type") == "run_completed":
                    break

            assert len(collected_logs) == 100
            assert "[log-line-0]" in collected_logs[0]
            assert "[log-line-99]" in collected_logs[99]
