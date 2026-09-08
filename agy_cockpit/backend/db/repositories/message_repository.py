"""Message repository."""

import json
from typing import List, Optional
import aiosqlite

from agy_cockpit.backend.domain.models import Message
from agy_cockpit.backend.domain.enums import MessageRole


class MessageRepository:
    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn

    async def create(self, msg: Message) -> Message:
        attachment_json = json.dumps(msg.attachment_ids)
        await self.conn.execute(
            """
            INSERT INTO messages (id, conversation_id, role, author_time, content, attachment_ids, reasoning)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                msg.id,
                msg.conversation_id,
                msg.role.value if isinstance(msg.role, MessageRole) else str(msg.role),
                msg.author_time,
                msg.content,
                attachment_json,
                msg.reasoning or "",
            ),
        )
        await self.conn.commit()
        return msg

    async def get_by_id(self, msg_id: str) -> Optional[Message]:
        async with self.conn.execute(
            "SELECT * FROM messages WHERE id = ?", (msg_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            data = dict(row)
            data["attachment_ids"] = json.loads(data["attachment_ids"]) if data.get("attachment_ids") else []
            data["reasoning"] = data.get("reasoning") or ""
            return Message(**data)

    async def list_by_conversation(self, conv_id: str) -> List[Message]:
        async with self.conn.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY author_time ASC",
            (conv_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            result = []
            for r in rows:
                data = dict(r)
                data["attachment_ids"] = json.loads(data["attachment_ids"]) if data.get("attachment_ids") else []
                data["reasoning"] = data.get("reasoning") or ""
                result.append(Message(**data))
            return result

    async def update_content(self, msg_id: str, content: str) -> None:
        await self.conn.execute(
            "UPDATE messages SET content = ? WHERE id = ?",
            (content, msg_id),
        )
        await self.conn.commit()
