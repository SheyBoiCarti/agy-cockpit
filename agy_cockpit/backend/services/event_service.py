"""Event Service for allocating sequence numbers, persistence, and event broadcasting."""

import asyncio
from datetime import datetime, timezone
import json
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set
import uuid

import aiosqlite

from agy_cockpit.backend.db.repositories.event_repository import EventRepository
from agy_cockpit.backend.domain.models import EventRecord
from agy_cockpit.backend.ws.protocol import ServerEvent, create_server_event


ListenerCallback = Callable[[ServerEvent], Coroutine[Any, Any, None]]


class EventService:
    """Manages monotonic run sequences, event persistence, and broadcasting."""

    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn
        self.repo = EventRepository(conn)
        self._locks: Dict[str, asyncio.Lock] = {}
        self._run_sequences: Dict[str, int] = {}
        self._listeners: Set[ListenerCallback] = set()

    def _get_lock(self, run_id: str) -> asyncio.Lock:
        if run_id not in self._locks:
            self._locks[run_id] = asyncio.Lock()
        return self._locks[run_id]

    async def get_next_sequence(self, run_id: str) -> int:
        """Allocates the next monotonic sequence number for a run."""
        lock = self._get_lock(run_id)
        async with lock:
            if run_id not in self._run_sequences:
                max_seq = await self.repo.get_max_sequence(run_id)
                self._run_sequences[run_id] = max_seq

            self._run_sequences[run_id] += 1
            return self._run_sequences[run_id]

    async def emit_event(
        self,
        event_type: str,
        session_id: str,
        payload: Dict[str, Any],
        conversation_id: Optional[str] = None,
        run_id: Optional[str] = None,
        replayable: bool = True,
    ) -> ServerEvent:
        """Creates, sequences, persists, and broadcasts a server event."""
        sequence = None
        if run_id:
            sequence = await self.get_next_sequence(run_id)

        event = create_server_event(
            event_type=event_type,
            session_id=session_id,
            payload=payload,
            conversation_id=conversation_id,
            run_id=run_id,
            sequence=sequence,
        )

        # Persist event if replayable
        if replayable and (run_id or conversation_id):
            record = EventRecord(
                event_id=event.event_id,
                run_id=run_id,
                conversation_id=conversation_id,
                sequence=sequence,
                type=event.type,
                payload_json=json.dumps(event.payload),
                timestamp=event.timestamp,
                replayable=replayable,
            )
            await self.repo.create(record)

        # Broadcast to listeners
        await self.broadcast(event)
        return event

    def subscribe(self, callback: ListenerCallback) -> None:
        """Subscribes a listener to live broadcast events."""
        self._listeners.add(callback)

    def unsubscribe(self, callback: ListenerCallback) -> None:
        """Unsubscribes a listener."""
        self._listeners.discard(callback)

    async def broadcast(self, event: ServerEvent) -> None:
        """Broadcasts an event to all active listeners."""
        for listener in list(self._listeners):
            try:
                await listener(event)
            except Exception:
                # Listener failures must not block other listeners
                pass
