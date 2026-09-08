"""Artifact repository."""

from typing import List, Optional
import aiosqlite

from agy_cockpit.backend.domain.models import Artifact
from agy_cockpit.backend.domain.enums import ArtifactKind


class ArtifactRepository:
    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn

    async def create(self, artifact: Artifact) -> Artifact:
        await self.conn.execute(
            """
            INSERT INTO artifacts (
                id, run_id, kind, name, mime_type, path_or_storage_key,
                preview_supported, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact.id,
                artifact.run_id,
                artifact.kind.value if isinstance(artifact.kind, ArtifactKind) else str(artifact.kind),
                artifact.name,
                artifact.mime_type,
                artifact.path_or_storage_key,
                1 if artifact.preview_supported else 0,
                artifact.created_at,
                artifact.updated_at,
            ),
        )
        await self.conn.commit()
        return artifact

    async def get_by_id(self, artifact_id: str) -> Optional[Artifact]:
        async with self.conn.execute(
            "SELECT * FROM artifacts WHERE id = ?", (artifact_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            data = dict(row)
            data["preview_supported"] = bool(data["preview_supported"])
            return Artifact(**data)

    async def list_by_run(self, run_id: str) -> List[Artifact]:
        async with self.conn.execute(
            "SELECT * FROM artifacts WHERE run_id = ? ORDER BY created_at ASC",
            (run_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            result = []
            for r in rows:
                data = dict(r)
                data["preview_supported"] = bool(data["preview_supported"])
                result.append(Artifact(**data))
            return result

    async def list_by_conversation(self, conv_id: str) -> List[Artifact]:
        async with self.conn.execute(
            """
            SELECT a.* FROM artifacts a
            JOIN runs r ON a.run_id = r.id
            WHERE r.conversation_id = ?
            ORDER BY a.created_at ASC
            """,
            (conv_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            result = []
            for r in rows:
                data = dict(r)
                data["preview_supported"] = bool(data["preview_supported"])
                result.append(Artifact(**data))
            return result

    async def update(self, artifact_id: str, path_or_storage_key: str, updated_at: str) -> None:
        await self.conn.execute(
            "UPDATE artifacts SET path_or_storage_key = ?, updated_at = ? WHERE id = ?",
            (path_or_storage_key, updated_at, artifact_id),
        )
        await self.conn.commit()
