"""Artifact service for registering, fetching, and previewing domain artifacts."""

import os
from typing import Optional, List, Any
import aiosqlite

from agy_cockpit.backend.db.repositories.artifact_repository import ArtifactRepository
from agy_cockpit.backend.domain.enums import ArtifactKind, WorkspaceSecurityError
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
    def __init__(self, conn: Optional[aiosqlite.Connection] = None, event_service: Any = None):
        self.conn = conn
        self.repo = ArtifactRepository(conn) if conn is not None else None
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
        workspace_path: Optional[str] = None,
        allowed_dirs: Optional[List[str]] = None,
    ) -> str:
        """Reads content if file exists on disk and is strictly confined within allowed directories or workspace root."""
        raw_path = artifact.path_or_storage_key

        # Resolve canonical absolute path eliminating symlinks
        resolved_path = os.path.realpath(os.path.abspath(raw_path))

        check_dirs = list(allowed_dirs or [])
        if workspace_path:
            check_dirs.append(workspace_path)

        if not check_dirs:
            raise WorkspaceSecurityError("Cannot read artifact: no workspace or allowed directory constraint provided")

        resolved_check_dirs = [os.path.realpath(os.path.abspath(d)) for d in check_dirs]
        is_confined = any(
            os.path.commonpath([resolved_dir, resolved_path]) == resolved_dir
            for resolved_dir in resolved_check_dirs
        )

        if not is_confined:
            raise WorkspaceSecurityError(
                f"Access to path '{raw_path}' is outside allowed directories or outside workspace confinement: resolves to '{resolved_path}'"
            )

        if not os.path.exists(resolved_path) or not os.path.isfile(resolved_path):
            return raw_path

        with open(resolved_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(500_000)

    def read_artifact_bytes(
        self,
        artifact: Artifact,
        workspace_path: Optional[str] = None,
        allowed_dirs: Optional[List[str]] = None,
        max_bytes: int = 10_000_000,
    ) -> bytes:
        """Reads raw binary content if file exists on disk and is strictly confined within allowed directories or workspace root."""
        raw_path = artifact.path_or_storage_key

        resolved_path = os.path.realpath(os.path.abspath(raw_path))

        check_dirs = list(allowed_dirs or [])
        if workspace_path:
            check_dirs.append(workspace_path)

        if not check_dirs:
            raise WorkspaceSecurityError("Cannot read artifact: no workspace or allowed directory constraint provided")

        resolved_check_dirs = [os.path.realpath(os.path.abspath(d)) for d in check_dirs]
        is_confined = any(
            os.path.commonpath([resolved_dir, resolved_path]) == resolved_dir
            for resolved_dir in resolved_check_dirs
        )

        if not is_confined:
            raise WorkspaceSecurityError(
                f"Access to path '{raw_path}' is outside allowed directories or outside workspace confinement: resolves to '{resolved_path}'"
            )

        if not os.path.exists(resolved_path) or not os.path.isfile(resolved_path):
            return raw_path.encode("utf-8")

        with open(resolved_path, "rb") as f:
            return f.read(max_bytes)

