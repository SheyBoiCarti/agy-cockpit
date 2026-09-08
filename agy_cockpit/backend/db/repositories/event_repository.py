"""Event repository for sequenced run replay."""

from typing import List, Optional
import aiosqlite

from agy_cockpit.backend.domain.models import EventRecord


class EventRepository:
    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn

    async def create(self, event: EventRecord) -> EventRecord:
        await self.conn.execute(
            """
            INSERT INTO events (
                event_id, run_id, conversation_id, sequence, type,
                payload_json, timestamp, replayable
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.run_id,
                event.conversation_id,
                event.sequence,
                event.type,
                event.payload_json,
                event.timestamp,
                1 if event.replayable else 0,
            ),
        )
        await self.conn.commit()
        return event

    async def get_by_id(self, event_id: str) -> Optional[EventRecord]:
        async with self.conn.execute(
            "SELECT * FROM events WHERE event_id = ?", (event_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            data = dict(row)
            data["replayable"] = bool(data["replayable"])
            return EventRecord(**data)

    async def get_events_since(
        self, run_id: str, last_sequence: int = 0, replayable_only: bool = True
    ) -> List[EventRecord]:
        """Fetches events for a run with sequence > last_sequence, ordered ascending by sequence."""
        query = "SELECT * FROM events WHERE run_id = ? AND sequence > ?"
        params = [run_id, last_sequence]
        if replayable_only:
            query += " AND replayable = 1"
        query += " ORDER BY sequence ASC"

        async with self.conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            result = []
            for r in rows:
                data = dict(r)
                data["replayable"] = bool(data["replayable"])
                result.append(EventRecord(**data))
            return result

    async def get_max_sequence(self, run_id: str) -> int:
        """Returns the highest allocated sequence for a run (or 0 if none)."""
        async with self.conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) FROM events WHERE run_id = ?",
            (run_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return int(row[0]) if row else 0

    async def delete_by_run(self, run_id: str) -> int:
        cursor = await self.conn.execute("DELETE FROM events WHERE run_id = ?", (run_id,))
        await self.conn.commit()
        return cursor.rowcount
