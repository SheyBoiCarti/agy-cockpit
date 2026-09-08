"""Workspace repository."""

from typing import List, Optional
import aiosqlite

from agy_cockpit.backend.domain.models import Workspace


class WorkspaceRepository:
    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn

    async def create(self, ws: Workspace) -> Workspace:
        await self.conn.execute(
            """
            INSERT INTO workspaces (id, canonical_path, display_name, created_at, last_opened_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (ws.id, ws.canonical_path, ws.display_name, ws.created_at, ws.last_opened_at),
        )
        await self.conn.commit()
        return ws

    async def get_by_id(self, ws_id: str) -> Optional[Workspace]:
        async with self.conn.execute(
            "SELECT * FROM workspaces WHERE id = ?", (ws_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return Workspace(**dict(row))

    async def get_by_canonical_path(self, path: str) -> Optional[Workspace]:
        async with self.conn.execute(
            "SELECT * FROM workspaces WHERE canonical_path = ?", (path,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return Workspace(**dict(row))

    async def list_all(self) -> List[Workspace]:
        async with self.conn.execute(
            "SELECT * FROM workspaces ORDER BY last_opened_at DESC"
        ) as cursor:
            rows = await cursor.fetchall()
            return [Workspace(**dict(r)) for r in rows]

    async def update_last_opened(self, ws_id: str, timestamp: str) -> None:
        await self.conn.execute(
            "UPDATE workspaces SET last_opened_at = ? WHERE id = ?",
            (timestamp, ws_id),
        )
        await self.conn.commit()

    async def delete(self, ws_id: str) -> bool:
        cursor = await self.conn.execute(
            "DELETE FROM workspaces WHERE id = ?", (ws_id,)
        )
        await self.conn.commit()
        return cursor.rowcount > 0
