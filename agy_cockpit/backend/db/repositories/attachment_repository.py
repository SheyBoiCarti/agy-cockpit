"""Attachment repository."""

from typing import List, Optional
import aiosqlite

from agy_cockpit.backend.domain.models import Attachment


class AttachmentRepository:
    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn

    async def create(self, att: Attachment) -> Attachment:
        await self.conn.execute(
            """
            INSERT INTO attachments (
                id, conversation_id, filename, mime_type, size_bytes, sha256, storage_path, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                att.id,
                att.conversation_id,
                att.filename,
                att.mime_type,
                att.size_bytes,
                att.sha256,
                att.storage_path,
                att.created_at,
            ),
        )
        await self.conn.commit()
        return att

    async def get_by_id(self, att_id: str) -> Optional[Attachment]:
        async with self.conn.execute(
            "SELECT * FROM attachments WHERE id = ?", (att_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return Attachment(**dict(row))

    async def list_by_conversation(self, conv_id: str) -> List[Attachment]:
        async with self.conn.execute(
            "SELECT * FROM attachments WHERE conversation_id = ? ORDER BY created_at ASC",
            (conv_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [Attachment(**dict(r)) for r in rows]

    async def delete(self, att_id: str) -> bool:
        cursor = await self.conn.execute("DELETE FROM attachments WHERE id = ?", (att_id,))
        await self.conn.commit()
        return cursor.rowcount > 0
