import asyncio
import logging
import os
import pathlib
from typing import Any, Callable, Dict, List, Optional, Awaitable
import aiosqlite
import watchfiles

from agy_cockpit.backend.db.repositories.workspace_repository import WorkspaceRepository
from agy_cockpit.backend.domain.models import Workspace, utc_now_iso
from agy_cockpit.backend.domain.workspace import (
    WorkspaceSecurityError,
    canonicalize_workspace_path,
    get_relative_workspace_path,
    resolve_safe_path,
)

logger = logging.getLogger(__name__)

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
    """Manages workspace lifecycle, real-time filesystem watching, and safe file searching."""

    def __init__(
        self,
        conn: aiosqlite.Connection,
        on_file_change: Optional[Callable[[str, str, str], Awaitable[None]]] = None,
    ):
        self.conn = conn
        self.repo = WorkspaceRepository(conn)
        self.on_file_change = on_file_change
        self._watch_tasks: Dict[str, asyncio.Task] = {}
        self._stop_events: Dict[str, asyncio.Event] = {}

    def start_watcher(self, workspace_id: str, path: str) -> None:
        """Starts a background watchfiles watcher on the given workspace path."""
        self.stop_watcher(workspace_id)
        stop_evt = asyncio.Event()
        self._stop_events[workspace_id] = stop_evt

        async def _watch_loop():
            try:
                def _filter(change: watchfiles.Change, p: str) -> bool:
                    parts = pathlib.Path(p).parts
                    return not any(part in IGNORED_DIRECTORIES or part.startswith('.agy-cockpit-') for part in parts)

                async for changes in watchfiles.awatch(path, stop_event=stop_evt, watch_filter=_filter):
                    for change, file_p in changes:
                        try:
                            rel_p = get_relative_workspace_path(path, file_p)
                        except Exception:
                            continue
                        status_str = "modified"
                        if change == watchfiles.Change.added:
                            status_str = "added"
                        elif change == watchfiles.Change.deleted:
                            status_str = "deleted"

                        if self.on_file_change:
                            try:
                                await self.on_file_change(workspace_id, rel_p, status_str)
                            except Exception as ce:
                                logger.debug("Error in on_file_change callback: %s", ce)
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.debug("Filesystem watcher for %s stopped: %s", path, e)

        self._watch_tasks[workspace_id] = asyncio.create_task(_watch_loop())

    def stop_watcher(self, workspace_id: str) -> None:
        """Stops the filesystem watcher for a given workspace."""
        if workspace_id in self._stop_events:
            self._stop_events[workspace_id].set()
            self._stop_events.pop(workspace_id, None)
        task = self._watch_tasks.pop(workspace_id, None)
        if task and not task.done():
            task.cancel()

    def stop_all_watchers(self) -> None:
        """Stops all active filesystem watchers."""
        for ws_id in list(self._watch_tasks.keys()):
            self.stop_watcher(ws_id)

    async def open_workspace(self, path: str) -> Workspace:
        """Opens or creates a workspace at the given path and starts watcher."""
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
            self.start_watcher(existing.id, canon_path)
            return existing

        display_name = os.path.basename(canon_path) or canon_path
        ws = Workspace(
            canonical_path=canon_path,
            display_name=display_name,
            created_at=now,
            last_opened_at=now,
        )
        created = await self.repo.create(ws)
        self.start_watcher(created.id, canon_path)
        return created

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
