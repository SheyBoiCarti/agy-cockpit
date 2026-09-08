"""Artifact service for registering, fetching, and previewing domain artifacts."""

import os
from typing import Optional, List, Any
import aiosqlite

from agy_cockpit.backend.db.repositories.artifact_repository import ArtifactRepository
from agy_cockpit.backend.domain.enums import ArtifactKind
from agy_cockpit.backend.domain.models import Artifact, utc_now_iso

KIND_TO_MIME = {
    ArtifactKind.FILE: "text/plain",
    ArtifactKind.DIFF: "text/x-diff",
    ArtifactKind.PLAN: "text/markdown",
    ArtifactKind.REPORT: "text/markdown",
    ArtifactKind.IMAGE: "image/png",
    ArtifactKind.CUSTOM: "application/json",
}


class ArtifactService:
    def __init__(self, conn: aiosqlite.Connection, event_service: Any = None):
        self.conn = conn
        self.repo = ArtifactRepository(conn)
        self.event_service = event_service

    async def register_artifact(
        self,
        run_id: str,
        name: str,
        path_or_storage_key: str,
        kind: ArtifactKind = ArtifactKind.FILE,
        mime_type: Optional[str] = None,
        preview_supported: bool = True,
    ) -> Artifact:
        now = utc_now_iso()
        actual_mime = mime_type or KIND_TO_MIME.get(kind, "text/plain")
        art = Artifact(
            run_id=run_id,
            kind=kind,
            name=name,
            mime_type=actual_mime,
            path_or_storage_key=path_or_storage_key,
            preview_supported=preview_supported,
            created_at=now,
            updated_at=now,
        )
        await self.repo.create(art)
        if self.event_service:
            await self.event_service.emit_event(
                event_type="artifact_updated",
                session_id="global",
                payload={
                    "artifact": {
                        "id": art.id,
                        "run_id": art.run_id,
                        "kind": art.kind.value if hasattr(art.kind, "value") else str(art.kind),
                        "name": art.name,
                        "mime_type": art.mime_type,
                        "path_or_storage_key": art.path_or_storage_key,
                        "preview_supported": art.preview_supported,
                        "created_at": art.created_at,
                        "updated_at": art.updated_at,
                    }
                },
                run_id=art.run_id,
            )
        return art

    async def update_artifact(
        self,
        artifact_id: str,
        path_or_storage_key: str,
    ) -> Optional[Artifact]:
        now = utc_now_iso()
        await self.repo.update(artifact_id, path_or_storage_key, now)
        art = await self.repo.get_by_id(artifact_id)
        if art and self.event_service:
            await self.event_service.emit_event(
                event_type="artifact_updated",
                session_id="global",
                payload={
                    "artifact": {
                        "id": art.id,
                        "run_id": art.run_id,
                        "kind": art.kind.value if hasattr(art.kind, "value") else str(art.kind),
                        "name": art.name,
                        "mime_type": art.mime_type,
                        "path_or_storage_key": art.path_or_storage_key,
                        "preview_supported": art.preview_supported,
                        "created_at": art.created_at,
                        "updated_at": art.updated_at,
                    }
                },
                run_id=art.run_id,
            )
        return art

    async def get_artifact(self, artifact_id: str) -> Optional[Artifact]:
        return await self.repo.get_by_id(artifact_id)

    async def list_by_conversation(self, conversation_id: str) -> List[Artifact]:
        return await self.repo.list_by_conversation(conversation_id)

    async def list_by_run(self, run_id: str) -> List[Artifact]:
        return await self.repo.list_by_run(run_id)

    def read_artifact_content(
        self,
        artifact: Artifact,
        allowed_dirs: Optional[List[str]] = None,
    ) -> str:
        """Reads content if file exists on disk and is within allowed directories, else returns stored path/key."""
        path = os.path.abspath(artifact.path_or_storage_key)
        if allowed_dirs:
            is_allowed = any(
                path == os.path.abspath(d) or path.startswith(os.path.abspath(d) + os.sep)
                for d in allowed_dirs
            )
            if not is_allowed:
                raise PermissionError(f"Access to path '{path}' is outside allowed directories.")

        if os.path.exists(path) and os.path.isfile(path):
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return f.read(500_000)
        return artifact.path_or_storage_key

    def read_artifact_bytes(
        self,
        artifact: Artifact,
        allowed_dirs: Optional[List[str]] = None,
        max_bytes: int = 10_000_000,
    ) -> bytes:
        """Reads raw binary content if file exists on disk and is within allowed directories."""
        path = os.path.abspath(artifact.path_or_storage_key)
        if allowed_dirs:
            is_allowed = any(
                path == os.path.abspath(d) or path.startswith(os.path.abspath(d) + os.sep)
                for d in allowed_dirs
            )
            if not is_allowed:
                raise PermissionError(f"Access to path '{path}' is outside allowed directories.")

        if os.path.exists(path) and os.path.isfile(path):
            with open(path, "rb") as f:
                return f.read(max_bytes)
        return artifact.path_or_storage_key.encode("utf-8")

