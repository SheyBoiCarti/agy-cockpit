"""Conversation repository."""

from typing import List, Optional
import aiosqlite

from agy_cockpit.backend.domain.models import Conversation


class ConversationRepository:
    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn

    async def create(self, conv: Conversation) -> Conversation:
        await self.conn.execute(
            """
            INSERT INTO conversations (id, workspace_id, title, model_slug, sdk_save_dir, created_at, updated_at, archived_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                conv.id,
                conv.workspace_id,
                conv.title,
                conv.model_slug,
                conv.sdk_save_dir,
                conv.created_at,
                conv.updated_at,
                conv.archived_at,
            ),
        )
        await self.conn.commit()
        return conv

    async def get_by_id(self, conv_id: str) -> Optional[Conversation]:
        async with self.conn.execute(
            "SELECT * FROM conversations WHERE id = ?", (conv_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return Conversation.model_construct(**dict(row))

    async def list_by_workspace(
        self, workspace_id: str, include_archived: bool = False
    ) -> List[Conversation]:
        query = "SELECT * FROM conversations WHERE workspace_id = ?"
        params = [workspace_id]
        if not include_archived:
            query += " AND archived_at IS NULL"
        query += " ORDER BY updated_at DESC"

        async with self.conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [Conversation.model_construct(**dict(r)) for r in rows]

    async def update_title(self, conv_id: str, title: str, updated_at: str) -> None:
        await self.conn.execute(
            "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
            (title, updated_at, conv_id),
        )
        await self.conn.commit()

    async def update_model_slug(self, conv_id: str, model_slug: str, updated_at: str) -> None:
        await self.conn.execute(
            "UPDATE conversations SET model_slug = ?, updated_at = ? WHERE id = ?",
            (model_slug, updated_at, conv_id),
        )
        await self.conn.commit()

    async def update_updated_at(self, conv_id: str, updated_at: str) -> None:
        await self.conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (updated_at, conv_id),
        )
        await self.conn.commit()

    async def archive(self, conv_id: str, archived_at: str) -> None:
        await self.conn.execute(
            "UPDATE conversations SET archived_at = ?, updated_at = ? WHERE id = ?",
            (archived_at, archived_at, conv_id),
        )
        await self.conn.commit()

    async def delete(self, conv_id: str) -> bool:
        cursor = await self.conn.execute(
            "DELETE FROM conversations WHERE id = ?", (conv_id,)
        )
        await self.conn.commit()
        return cursor.rowcount > 0
