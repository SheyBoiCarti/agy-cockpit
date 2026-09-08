"""Conversation service managing session metadata and SDK save directories."""

import os
from typing import List, Optional
import uuid
import aiosqlite

from agy_cockpit.backend.config import AppConfig, get_config
from agy_cockpit.backend.db.repositories.conversation_repository import ConversationRepository
from agy_cockpit.backend.domain.models import Conversation, utc_now_iso


class ConversationService:
    """Manages conversations and their mapped SDK persistence directories."""

    def __init__(self, conn: aiosqlite.Connection, config: Optional[AppConfig] = None):
        self.conn = conn
        self.config = config or get_config()
        self.repo = ConversationRepository(conn)

    async def create_conversation(
        self,
        workspace_id: str,
        title: str = "New Conversation",
        model_slug: str = "gemini-3.8-flash-high",
    ) -> Conversation:
        conv_id = str(uuid.uuid4())
        save_dir = os.path.join(self.config.sessions_dir, conv_id)
        os.makedirs(save_dir, exist_ok=True)

        now = utc_now_iso()
        conv = Conversation(
            id=conv_id,
            workspace_id=workspace_id,
            title=title or "New Conversation",
            model_slug=model_slug or "gemini-3.8-flash-high",
            sdk_save_dir=save_dir,
            created_at=now,
            updated_at=now,
        )
        return await self.repo.create(conv)

    async def get_conversation(self, conv_id: str) -> Optional[Conversation]:
        return await self.repo.get_by_id(conv_id)

    async def list_conversations(
        self, workspace_id: str, include_archived: bool = False
    ) -> List[Conversation]:
        return await self.repo.list_by_workspace(workspace_id, include_archived=include_archived)

    async def rename_conversation(self, conv_id: str, title: str) -> Conversation:
        conv = await self.repo.get_by_id(conv_id)
        if not conv:
            raise ValueError(f"Conversation '{conv_id}' not found.")
        now = utc_now_iso()
        await self.repo.update_title(conv_id, title, now)
        conv.title = title
        conv.updated_at = now
        return conv

    async def archive_conversation(self, conv_id: str) -> Conversation:
        conv = await self.repo.get_by_id(conv_id)
        if not conv:
            raise ValueError(f"Conversation '{conv_id}' not found.")
        now = utc_now_iso()
        await self.repo.archive(conv_id, now)
        conv.archived_at = now
        conv.updated_at = now
        return conv

    async def delete_conversation(self, conv_id: str) -> bool:
        return await self.repo.delete(conv_id)
