"""ToolExecution repository."""

from typing import List, Optional
import aiosqlite

from agy_cockpit.backend.domain.models import ToolExecution
from agy_cockpit.backend.domain.enums import ToolExecutionState


class ToolRepository:
    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn

    async def create(self, tool: ToolExecution) -> ToolExecution:
        existing = await self.get_by_id(tool.id)
        if existing:
            if (existing.run_id, existing.sdk_tool_name, existing.parsed_args) != (tool.run_id, tool.sdk_tool_name, tool.parsed_args):
                raise ValueError('Conflicting tool identity for an existing invocation')
            return existing
        cursor = await self.conn.execute(
            """
            INSERT INTO tool_executions (
                id, run_id, sdk_tool_name, args_json, state,
                started_at, finished_at, success, output_summary
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO NOTHING
            """,
            (
                tool.id,
                tool.run_id,
                tool.sdk_tool_name,
                tool.args_json,
                tool.state.value if isinstance(tool.state, ToolExecutionState) else str(tool.state),
                tool.started_at,
                tool.finished_at,
                1 if tool.success else (0 if tool.success is False else None),
                tool.output_summary,
            ),
        )
        await self.conn.commit()
        if cursor.rowcount == 0:
            existing = await self.get_by_id(tool.id)
            if not existing or (existing.run_id, existing.sdk_tool_name, existing.parsed_args) != (tool.run_id, tool.sdk_tool_name, tool.parsed_args):
                raise ValueError('Conflicting tool identity for an existing invocation')
            return existing
        return tool

    async def get_by_id(self, tool_id: str) -> Optional[ToolExecution]:
        async with self.conn.execute(
            "SELECT * FROM tool_executions WHERE id = ?", (tool_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            data = dict(row)
            if data["success"] is not None:
                data["success"] = bool(data["success"])
            return ToolExecution(**data)

    async def list_by_run(self, run_id: str) -> List[ToolExecution]:
        async with self.conn.execute(
            "SELECT * FROM tool_executions WHERE run_id = ? ORDER BY started_at ASC",
            (run_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            result = []
            for r in rows:
                data = dict(r)
                if data["success"] is not None:
                    data["success"] = bool(data["success"])
                result.append(ToolExecution(**data))
            return result

    async def complete(
        self,
        tool_id: str,
        state: ToolExecutionState,
        finished_at: str,
        success: bool,
        output_summary: Optional[str] = None,
    ) -> None:
        await self.conn.execute(
            """
            UPDATE tool_executions
            SET state = ?, finished_at = ?, success = ?, output_summary = COALESCE(?, output_summary)
            WHERE id = ? AND finished_at IS NULL
            """,
            (state.value, finished_at, 1 if success else 0, output_summary, tool_id),
        )
        await self.conn.commit()
