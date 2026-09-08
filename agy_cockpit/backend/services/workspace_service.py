"""Workspace service for managing workspaces and indexing workspace files."""

import os
import pathlib
from typing import Any, Dict, List, Optional
import aiosqlite

from agy_cockpit.backend.db.repositories.workspace_repository import WorkspaceRepository
from agy_cockpit.backend.domain.models import Workspace, utc_now_iso
from agy_cockpit.backend.domain.workspace import (
    WorkspaceSecurityError,
    canonicalize_workspace_path,
    get_relative_workspace_path,
    resolve_safe_path,
)

IGNORED_DIRECTORIES = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    "__pycache__",
    ".pytest_cache",
    ".idea",
    ".vscode",
}


class WorkspaceService:
    """Manages workspace lifecycle and safe file searching."""

    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn
        self.repo = WorkspaceRepository(conn)

    async def open_workspace(self, path: str) -> Workspace:
        """Opens or creates a workspace at the given path."""
        canon_path = canonicalize_workspace_path(path)
        if not os.path.exists(canon_path):
            raise WorkspaceSecurityError(f"Workspace path '{canon_path}' does not exist.")
        if not os.path.isdir(canon_path):
            raise WorkspaceSecurityError(f"Workspace path '{canon_path}' is not a directory.")

        existing = await self.repo.get_by_canonical_path(canon_path)
        now = utc_now_iso()
        if existing:
            await self.repo.update_last_opened(existing.id, now)
            existing.last_opened_at = now
            return existing

        display_name = os.path.basename(canon_path) or canon_path
        ws = Workspace(
            canonical_path=canon_path,
            display_name=display_name,
            created_at=now,
            last_opened_at=now,
        )
        return await self.repo.create(ws)

    async def list_workspaces(self) -> List[Workspace]:
        return await self.repo.list_all()

    async def get_workspace(self, workspace_id: str) -> Optional[Workspace]:
        return await self.repo.get_by_id(workspace_id)

    async def search_workspace(
        self,
        workspace_id: str,
        query: str = "",
        limit: int = 50,
        include_hidden: bool = False,
    ) -> List[Dict[str, Any]]:
        """Searches files and folders within a workspace for '@' mentions."""
        ws = await self.repo.get_by_id(workspace_id)
        if not ws:
            raise ValueError(f"Workspace '{workspace_id}' not found.")

        canon_root = ws.canonical_path
        if not os.path.exists(canon_root):
            return []

        results: List[Dict[str, Any]] = []
        clean_query = query.strip().lower()

        for root, dirs, files in os.walk(canon_root, topdown=True):
            # Prune ignored directories
            dirs[:] = [
                d for d in dirs
                if d not in IGNORED_DIRECTORIES
                and (include_hidden or not d.startswith("."))
            ]

            # Match directories
            for d in dirs:
                if len(results) >= limit:
                    break
                full_dir = os.path.join(root, d)
                rel_dir = get_relative_workspace_path(canon_root, full_dir)
                if not clean_query or clean_query in rel_dir.lower():
                    results.append({
                        "path": rel_dir,
                        "type": "directory",
                    })

            # Match files
            for f in files:
                if len(results) >= limit:
                    break
                if not include_hidden and f.startswith("."):
                    continue
                full_file = os.path.join(root, f)
                rel_file = get_relative_workspace_path(canon_root, full_file)
                if not clean_query or clean_query in rel_file.lower():
                    results.append({
                        "path": rel_file,
                        "type": "file",
                    })

            if len(results) >= limit:
                break

        return results
