"""FileChange repository."""

from typing import List, Optional
import aiosqlite

from agy_cockpit.backend.domain.models import FileChange
from agy_cockpit.backend.domain.enums import FileChangeStatus


class FileChangeRepository:
    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn

    async def create(self, fc: FileChange) -> FileChange:
        await self.conn.execute(
            """
            INSERT INTO file_changes (id, run_id, file_path, status, timestamp)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                fc.id,
                fc.run_id,
                fc.file_path,
                fc.status.value if isinstance(fc.status, FileChangeStatus) else str(fc.status),
                fc.timestamp,
            ),
        )
        await self.conn.commit()
        return fc

    async def list_by_run(self, run_id: str) -> List[FileChange]:
        async with self.conn.execute(
            "SELECT * FROM file_changes WHERE run_id = ? ORDER BY timestamp ASC",
            (run_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [FileChange(**dict(r)) for r in rows]

    async def list_by_conversation(self, conv_id: str) -> List[FileChange]:
        async with self.conn.execute(
            """
            SELECT fc.* FROM file_changes fc
            JOIN runs r ON fc.run_id = r.id
            WHERE r.conversation_id = ?
            ORDER BY fc.timestamp ASC
            """,
            (conv_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [FileChange(**dict(r)) for r in rows]
