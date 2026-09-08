"""SubagentNode repository."""

from typing import List, Optional
import aiosqlite

from agy_cockpit.backend.domain.models import SubagentNode
from agy_cockpit.backend.domain.enums import SubagentState


class SubagentRepository:
    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn

    async def create(self, node: SubagentNode) -> SubagentNode:
        await self.conn.execute(
            """
            INSERT INTO subagents (
                id, run_id, parent_id, name_or_role, state,
                depth, current_activity, started_at, finished_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                node.id,
                node.run_id,
                node.parent_id,
                node.name_or_role,
                node.state.value if isinstance(node.state, SubagentState) else str(node.state),
                node.depth,
                node.current_activity,
                node.started_at,
                node.finished_at,
            ),
        )
        await self.conn.commit()
        return node

    async def get_by_id(self, node_id: str) -> Optional[SubagentNode]:
        async with self.conn.execute(
            "SELECT * FROM subagents WHERE id = ?", (node_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return SubagentNode(**dict(row))

    async def list_by_run(self, run_id: str) -> List[SubagentNode]:
        async with self.conn.execute(
            "SELECT * FROM subagents WHERE run_id = ? ORDER BY depth ASC, started_at ASC",
            (run_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [SubagentNode(**dict(r)) for r in rows]

    async def update_state(
        self,
        node_id: str,
        state: SubagentState,
        current_activity: Optional[str] = None,
        finished_at: Optional[str] = None,
    ) -> None:
        await self.conn.execute(
            """
            UPDATE subagents
            SET state = ?,
                current_activity = COALESCE(?, current_activity),
                finished_at = COALESCE(?, finished_at)
            WHERE id = ?
            """,
            (state.value, current_activity, finished_at, node_id),
        )
        await self.conn.commit()

    async def upsert(self, node: SubagentNode) -> SubagentNode:
        existing = await self.get_by_id(node.id)
        if existing:
            await self.update_state(
                node_id=node.id,
                state=node.state if isinstance(node.state, SubagentState) else SubagentState(node.state),
                current_activity=node.current_activity,
                finished_at=node.finished_at,
            )
            return node
        return await self.create(node)
