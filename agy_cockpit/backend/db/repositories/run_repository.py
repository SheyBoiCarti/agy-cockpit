"""Run repository."""

from typing import List, Optional
import aiosqlite

from agy_cockpit.backend.domain.models import Run
from agy_cockpit.backend.domain.enums import RunState, validate_run_state_transition


class RunRepository:
    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn

    async def create(self, run: Run) -> Run:
        await self.conn.execute(
            """
            INSERT INTO runs (
                id, conversation_id, user_message_id, state, started_at,
                completed_at, cancel_requested_at, last_sequence, error_code, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run.id,
                run.conversation_id,
                run.user_message_id,
                run.state.value if isinstance(run.state, RunState) else str(run.state),
                run.started_at,
                run.completed_at,
                run.cancel_requested_at,
                run.last_sequence,
                run.error_code,
                run.error_message,
            ),
        )
        await self.conn.commit()
        return run

    async def get_by_id(self, run_id: str) -> Optional[Run]:
        async with self.conn.execute(
            "SELECT * FROM runs WHERE id = ?", (run_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return Run(**dict(row))

    async def get_active_for_conversation(self, conv_id: str) -> Optional[Run]:
        """Returns the currently active (non-terminal) run for the conversation, if any."""
        terminal_states = [s.value for s in [RunState.COMPLETED, RunState.CANCELLED, RunState.FAILED, RunState.INTERRUPTED]]
        placeholders = ",".join("?" for _ in terminal_states)
        query = f"SELECT * FROM runs WHERE conversation_id = ? AND state NOT IN ({placeholders}) LIMIT 1"
        params = [conv_id] + terminal_states

        async with self.conn.execute(query, params) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return Run(**dict(row))

    async def list_by_conversation(self, conv_id: str) -> List[Run]:
        async with self.conn.execute(
            "SELECT * FROM runs WHERE conversation_id = ? ORDER BY started_at ASC",
            (conv_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [Run(**dict(r)) for r in rows]

    async def update_state(
        self,
        run_id: str,
        new_state: RunState,
        completed_at: Optional[str] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> Run:
        current = await self.get_by_id(run_id)
        if not current:
            raise ValueError(f"Run {run_id} not found")

        # Validate state machine transition
        validate_run_state_transition(current.state, new_state)

        await self.conn.execute(
            """
            UPDATE runs
            SET state = ?, completed_at = COALESCE(?, completed_at),
                error_code = COALESCE(?, error_code),
                error_message = COALESCE(?, error_message)
            WHERE id = ?
            """,
            (new_state.value, completed_at, error_code, error_message, run_id),
        )
        await self.conn.commit()
        updated = await self.get_by_id(run_id)
        assert updated is not None
        return updated

    async def mark_cancel_requested(self, run_id: str, timestamp: str) -> None:
        await self.conn.execute(
            "UPDATE runs SET cancel_requested_at = ? WHERE id = ?",
            (timestamp, run_id),
        )
        await self.conn.commit()

    async def update_last_sequence(self, run_id: str, sequence: int) -> None:
        await self.conn.execute(
            "UPDATE runs SET last_sequence = MAX(last_sequence, ?) WHERE id = ?",
            (sequence, run_id),
        )
        await self.conn.commit()

    async def interrupt_orphaned_runs(self) -> int:
        """Transitions in-flight executing runs to INTERRUPTED on server reboot."""
        from agy_cockpit.backend.domain.models import utc_now_iso
        active_executing_states = [RunState.QUEUED.value, RunState.THINKING.value, RunState.RUNNING_TOOL.value]
        placeholders = ",".join("?" for _ in active_executing_states)
        query = f"UPDATE runs SET state = ?, completed_at = COALESCE(completed_at, ?) WHERE state IN ({placeholders})"
        now = utc_now_iso()
        cursor = await self.conn.execute(query, [RunState.INTERRUPTED.value, now] + active_executing_states)
        await self.conn.commit()
        return cursor.rowcount

