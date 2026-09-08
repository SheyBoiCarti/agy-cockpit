"""WebSocket connection and session manager with security and backpressure."""

import asyncio
import json
import logging
from typing import Any, Dict, Optional, Set
import uuid

from fastapi import WebSocket, WebSocketDisconnect, status

from agy_cockpit.backend.config import AppConfig, get_config
from agy_cockpit.backend.ws.protocol import (
    ClientCommand,
    ProtocolErrorCode,
    ServerEvent,
    create_protocol_error,
    parse_client_command,
)

logger = logging.getLogger(__name__)


class ConnectionSecurityError(Exception):
    """Raised when an Origin or Token check fails."""
    def __init__(self, code: ProtocolErrorCode, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class ClientSession:
    """Manages an individual WebSocket client session with bounded outbound queue."""

    def __init__(
        self,
        websocket: WebSocket,
        session_id: str,
        config: AppConfig,
        queue_size: int = 1000,
    ):
        self.websocket = websocket
        self.session_id = session_id
        self.config = config
        self.outbound_queue: asyncio.Queue[Optional[ServerEvent]] = asyncio.Queue(maxsize=queue_size)
        self.active_conversation_id: Optional[str] = None
        self.active_run_id: Optional[str] = None
        self.writer_task: Optional[asyncio.Task] = None
        self.is_closed = False

    def start_writer(self) -> None:
        self.writer_task = asyncio.create_task(self._writer_loop())

    async def _writer_loop(self) -> None:
        """Continuously pulls events from outbound_queue and sends over WebSocket."""
        try:
            while not self.is_closed:
                event = await self.outbound_queue.get()
                if event is None:
                    break
                # Serialize and send
                text = event.model_dump_json()
                await self.websocket.send_text(text)
                self.outbound_queue.task_done()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug("Session %s writer loop stopped: %s", self.session_id, e)
        finally:
            self.is_closed = True

    async def send_event(self, event: ServerEvent) -> bool:
        """Enqueues an event for delivery. Drops low-value events if queue full to prevent OOM."""
        if self.is_closed:
            return False

        try:
            self.outbound_queue.put_nowait(event)
            return True
        except asyncio.QueueFull:
            # Drop low-value streaming deltas or log chunks if client is too slow
            if event.type in ("token_delta", "reasoning_delta", "tool_log"):
                logger.warning("Dropping event %s for slow client session %s", event.type, self.session_id)
                return False
            else:
                # Durable state event: await queue with timeout
                try:
                    await asyncio.wait_for(self.outbound_queue.put(event), timeout=2.0)
                    return True
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    logger.error("Outbound queue full for session %s; closing slow connection", self.session_id)
                    await self.close(code=status.WS_1008_POLICY_VIOLATION)
                    return False

    async def close(self, code: int = status.WS_1000_NORMAL_CLOSURE, reason: str = "") -> None:
        if self.is_closed:
            return
        self.is_closed = True
        if self.writer_task and not self.writer_task.done():
            self.writer_task.cancel()
        try:
            await self.websocket.close(code=code, reason=reason)
        except Exception:
            pass


class ConnectionManager:
    """Tracks active connections, enforces security boundaries and origin validation."""

    def __init__(self, config: Optional[AppConfig] = None):
        self.config = config or get_config()
        self.active_sessions: Dict[str, ClientSession] = {}

    def validate_handshake(self, websocket: WebSocket) -> str:
        """Validates Origin and launch token from websocket headers/query params.

        Returns:
            A new or resumed session_id.
        """
        # 1. Validate Origin
        origin = websocket.headers.get("origin")
        if origin:
            # If origin is provided, must be in allowed_origins or loopback
            allowed = self.config.allowed_origins
            if origin not in allowed:
                # Check for standard loopback patterns
                is_loopback = (
                    origin.startswith("http://127.0.0.1")
                    or origin.startswith("http://localhost")
                )
                if not is_loopback:
                    logger.warning("Rejected connection from untrusted origin: %s", origin)
                    raise ConnectionSecurityError(
                        ProtocolErrorCode.ORIGIN_REJECTED,
                        f"Origin '{origin}' is not allowed.",
                    )

        # 2. Validate token
        # Token can be passed in query params ?token=... or header X-Antigravity-Token
        token = websocket.query_params.get("token") or websocket.headers.get("x-antigravity-token")
        if self.config.token:
            if not token or token != self.config.token:
                logger.warning("Rejected connection with invalid or missing token.")
                raise ConnectionSecurityError(
                    ProtocolErrorCode.UNAUTHORIZED,
                    "Invalid or missing launch authorization token.",
                )

        # Return session_id if provided by client or generate new
        session_id = websocket.query_params.get("session_id") or str(uuid.uuid4())
        return session_id

    async def register(self, websocket: WebSocket, session_id: str) -> ClientSession:
        """Registers and starts a new client session."""
        session = ClientSession(websocket, session_id, self.config)
        session.start_writer()
        self.active_sessions[session_id] = session
        logger.info("Session %s registered (total active: %d)", session_id, len(self.active_sessions))
        return session

    async def unregister(self, session_id: str) -> None:
        """Unregisters and closes a client session."""
        session = self.active_sessions.pop(session_id, None)
        if session:
            await session.close()
            logger.info("Session %s unregistered (total active: %d)", session_id, len(self.active_sessions))

    def get_session(self, session_id: str) -> Optional[ClientSession]:
        return self.active_sessions.get(session_id)

    async def broadcast_event(self, event: ServerEvent) -> None:
        """Delivers event to appropriate sessions (scoped by conversation/run or broadcast)."""
        for session in list(self.active_sessions.values()):
            # If event is conversation-scoped, deliver to sessions focused on that conversation
            if event.conversation_id:
                if (
                    session.active_conversation_id is None
                    or session.active_conversation_id == event.conversation_id
                ):
                    await session.send_event(event)
            else:
                # Global event, deliver to all
                await session.send_event(event)
