"""ApprovalRequest repository."""

from typing import List, Optional
import aiosqlite

from agy_cockpit.backend.domain.models import ApprovalRequest
from agy_cockpit.backend.domain.enums import ApprovalDecision


class ApprovalRepository:
    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn

    async def create(self, req: ApprovalRequest) -> ApprovalRequest:
        await self.conn.execute(
            """
            INSERT INTO approval_requests (
                id, run_id, tool_execution_id, sdk_tool_name,
                args_json, reason, decision, created_at, resolved_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                req.id,
                req.run_id,
                req.tool_execution_id,
                req.sdk_tool_name,
                req.args_json,
                req.reason,
                req.decision.value if req.decision else None,
                req.created_at,
                req.resolved_at,
            ),
        )
        await self.conn.commit()
        return req

    async def get_by_id(self, req_id: str) -> Optional[ApprovalRequest]:
        async with self.conn.execute(
            "SELECT * FROM approval_requests WHERE id = ?", (req_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return ApprovalRequest(**dict(row))

    async def get_pending_for_run(self, run_id: str) -> Optional[ApprovalRequest]:
        """Returns the pending approval request for a run, if any."""
        async with self.conn.execute(
            "SELECT * FROM approval_requests WHERE run_id = ? AND decision IS NULL LIMIT 1",
            (run_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return ApprovalRequest(**dict(row))

    async def list_by_run(self, run_id: str) -> List[ApprovalRequest]:
        async with self.conn.execute(
            "SELECT * FROM approval_requests WHERE run_id = ? ORDER BY created_at ASC",
            (run_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [ApprovalRequest(**dict(r)) for r in rows]

    async def resolve(
        self, req_id: str, decision: ApprovalDecision, resolved_at: str
    ) -> None:
        await self.conn.execute(
            "UPDATE approval_requests SET decision = ?, resolved_at = ? WHERE id = ?",
            (decision.value, resolved_at, req_id),
        )
        await self.conn.commit()
