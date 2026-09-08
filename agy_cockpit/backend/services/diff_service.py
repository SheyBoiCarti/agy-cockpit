"""Diff Service for Git and Non-Git workspace file comparison."""

from dataclasses import dataclass
import logging
import os
from typing import Dict, Optional

try:
    import git
except ImportError:
    git = None

from agy_cockpit.backend.domain.workspace import resolve_safe_path


def is_git_workspace(workspace_path: str) -> bool:
    return os.path.exists(os.path.join(workspace_path, ".git"))

logger = logging.getLogger(__name__)

EXT_TO_LANG = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".json": "json",
    ".html": "html",
    ".css": "css",
    ".md": "markdown",
    ".sql": "sql",
    ".sh": "shell",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".rs": "rust",
    ".go": "go",
    ".cpp": "cpp",
    ".c": "c",
    ".h": "c",
    ".java": "java",
    ".xml": "xml",
}

MAX_DIFF_CHARS = 250_000


@dataclass
class FileDiffData:
    file_path: str
    status: str
    original_content: str
    modified_content: str
    language: str
    is_binary: bool = False
    truncated: bool = False


def normalize_rel_path(workspace_path: str, path_str: str) -> str:
    """Normalizes an absolute or relative path to a workspace-relative POSIX path."""
    try:
        ws_abs = os.path.abspath(workspace_path)
        abs_p = os.path.abspath(os.path.join(workspace_path, path_str) if not os.path.isabs(path_str) else path_str)
        if abs_p.startswith(ws_abs):
            rel = os.path.relpath(abs_p, ws_abs)
            return rel.replace("\\", "/")
    except Exception:
        pass
    return path_str.replace("\\", "/").lstrip("/")


class DiffService:
    """Computes file diffs using Git tree inspection or pre-edit snapshots."""

    def __init__(self):
        # Pre-edit snapshot cache keyed by (workspace_path, rel_path)
        self._snapshots: Dict[str, str] = {}

    def capture_pre_edit_snapshot(self, workspace_path: str, path_or_rel: str) -> None:
        """Captures before-state of a file prior to modification."""
        try:
            rel_path = normalize_rel_path(workspace_path, path_or_rel)
            abs_path = resolve_safe_path(workspace_path, rel_path)
            key = f"{workspace_path}:{rel_path}"
            if os.path.exists(abs_path) and os.path.isfile(abs_path):
                with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                    self._snapshots[key] = f.read(MAX_DIFF_CHARS)
            else:
                self._snapshots[key] = ""
        except Exception as e:
            logger.debug("Failed capturing snapshot for %s: %s", path_or_rel, e)

    def get_file_diff(self, workspace_path: str, path_or_rel: str) -> FileDiffData:
        """Computes diff data between original and modified file state."""
        rel_path = normalize_rel_path(workspace_path, path_or_rel)
        abs_path = resolve_safe_path(workspace_path, rel_path)
        _, ext = os.path.splitext(rel_path)
        language = EXT_TO_LANG.get(ext.lower(), "plaintext")

        # 1. Read current on-disk content
        current_content = ""
        is_binary = False
        truncated = False
        file_exists_on_disk = os.path.exists(abs_path) and os.path.isfile(abs_path)

        if file_exists_on_disk:
            try:
                # Check binary
                with open(abs_path, "rb") as f:
                    chunk = f.read(4096)
                    if b"\x00" in chunk:
                        is_binary = True

                if not is_binary:
                    with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                        current_content = f.read(MAX_DIFF_CHARS + 1)
                        if len(current_content) > MAX_DIFF_CHARS:
                            truncated = True
                            current_content = current_content[:MAX_DIFF_CHARS]
            except Exception as e:
                logger.error("Error reading modified file %s: %s", abs_path, e)
                current_content = f"[Error reading file: {e}]"

        if is_binary:
            return FileDiffData(
                file_path=rel_path,
                status="modified" if file_exists_on_disk else "deleted",
                original_content="[Binary File]",
                modified_content="[Binary File]",
                language="plaintext",
                is_binary=True,
            )

        # 2. Determine original content: try Git first if Git repo
        original_content = ""
        has_git_original = False

        if git and is_git_workspace(workspace_path):
            try:
                repo = git.Repo(workspace_path)
                try:
                    # Get blob from HEAD
                    blob = repo.head.commit.tree[rel_path]
                    raw_data = blob.data_stream.read()
                    if b"\x00" in raw_data[:4096]:
                        is_binary = True
                    original_content = raw_data.decode("utf-8", errors="replace")
                    if len(original_content) > MAX_DIFF_CHARS:
                        truncated = True
                        original_content = original_content[:MAX_DIFF_CHARS]
                    has_git_original = True
                except (KeyError, IndexError):
                    # File does not exist in HEAD commit (added file)
                    original_content = ""
                    has_git_original = True
            except Exception as e:
                logger.debug("Git diff lookup failed for %s: %s", rel_path, e)

        # 3. Fallback to pre-edit snapshot cache if not in Git or Git lookup failed
        if not has_git_original:
            key = f"{workspace_path}:{rel_path}"
            original_content = self._snapshots.get(key, "")

        # 4. Determine status
        if not original_content and file_exists_on_disk:
            status = "added"
        elif original_content and not file_exists_on_disk:
            status = "deleted"
        elif original_content != current_content:
            status = "modified"
        else:
            status = "unmodified"

        return FileDiffData(
            file_path=rel_path,
            status=status,
            original_content=original_content,
            modified_content=current_content,
            language=language,
            is_binary=is_binary,
            truncated=truncated,
        )
