"""Workspace canonicalization and path traversal safety."""

import os
import pathlib
from typing import Optional


class WorkspaceSecurityError(Exception):
    """Raised when a path violates workspace security boundaries."""
    pass


def canonicalize_workspace_path(path_str: str) -> str:
    """Canonicalizes a workspace root path.

    Resolves user expansion (~), environment variables, symlinks,
    and returns a strictly absolute, normalized path.
    """
    if not path_str or not path_str.strip():
        raise WorkspaceSecurityError("Workspace path cannot be empty.")
    
    # Handle home expansion and env variables
    expanded = os.path.expanduser(os.path.expandvars(path_str.strip()))
    
    # Normalize separators (convert Windows backslashes if on posix or vice-versa)
    # On linux, backslashes might be part of filenames if not converted
    normalized = os.path.normpath(expanded)
    
    # Resolve to absolute path with symlink resolution
    try:
        resolved = pathlib.Path(normalized).resolve()
    except (OSError, RuntimeError) as e:
        raise WorkspaceSecurityError(f"Cannot resolve workspace path '{path_str}': {e}") from e
        
    return str(resolved)


def resolve_safe_path(
    workspace_root: str,
    target_path: str,
    allow_outside: bool = False
) -> str:
    """Resolves and validates a target path within a workspace root.

    Protections:
    - Normalizes relative and absolute paths.
    - Resolves '..' directory traversal attempts.
    - Resolves symlinks.
    - Ensures target is strictly inside workspace_root unless allow_outside is True.

    Returns:
        Canonical absolute path string.

    Raises:
        WorkspaceSecurityError: If target escapes the workspace.
    """
    if not target_path or not str(target_path).strip():
        raise WorkspaceSecurityError("Target path cannot be empty.")

    root_canon = canonicalize_workspace_path(workspace_root)
    clean_target = str(target_path).strip()

    # Handle cross-platform separators: replace Windows backslashes with forward slashes
    clean_target = clean_target.replace("\\", "/")

    # If target is relative, join with workspace root
    if os.path.isabs(clean_target):
        candidate = clean_target
    else:
        candidate = os.path.join(root_canon, clean_target)

    # Normalize lexical path
    candidate_norm = os.path.normpath(candidate)
    
    # Resolve symlinks and canonical path
    # If the file does not exist yet (e.g. creating new file), resolve existing parent
    try:
        cand_path = pathlib.Path(candidate_norm)
        if cand_path.exists():
            resolved_target = str(cand_path.resolve())
        else:
            # Resolve existing ancestor and append non-existent parts
            ancestor = cand_path
            tail_parts = []
            while not ancestor.exists() and ancestor.parent != ancestor:
                tail_parts.append(ancestor.name)
                ancestor = ancestor.parent
            tail_parts.reverse()
            resolved_ancestor = ancestor.resolve()
            resolved_target = str(resolved_ancestor.joinpath(*tail_parts))
    except (OSError, RuntimeError) as e:
        raise WorkspaceSecurityError(f"Failed to resolve path '{target_path}': {e}") from e

    if not allow_outside:
        # Check containment
        # Use commonpath or relative_to
        try:
            rel = os.path.relpath(resolved_target, root_canon)
            if rel == ".." or rel.startswith(".." + os.sep) or rel.startswith("../"):
                raise WorkspaceSecurityError(
                    f"Path traversal detected: '{target_path}' resolves outside workspace '{root_canon}'."
                )
        except ValueError as e:
            # Raised on Windows when paths are on different drives
            raise WorkspaceSecurityError(
                f"Path '{target_path}' is on a different root/drive from workspace '{root_canon}'."
            ) from e

    return resolved_target


def get_relative_workspace_path(workspace_root: str, target_path: str) -> str:
    """Returns workspace-relative path using forward slashes."""
    safe_target = resolve_safe_path(workspace_root, target_path, allow_outside=False)
    root_canon = canonicalize_workspace_path(workspace_root)
    rel = os.path.relpath(safe_target, root_canon)
    if rel == ".":
        return "."
    return rel.replace("\\", "/")
