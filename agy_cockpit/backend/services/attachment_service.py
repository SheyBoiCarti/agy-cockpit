"""Attachment service for secure upload, validation, and storage."""

import hashlib
import os
import uuid
import aiosqlite
from typing import Optional, Set
from fastapi import UploadFile

from agy_cockpit.backend.db.repositories.attachment_repository import AttachmentRepository
from agy_cockpit.backend.domain.models import Attachment, utc_now_iso

DEFAULT_ALLOWED_MIMES: Set[str] = {
    "text/plain",
    "text/markdown",
    "text/csv",
    "text/yaml",
    "application/x-yaml",
    "application/yaml",
    "application/json",
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
}

DEFAULT_MAX_BYTES = 10 * 1024 * 1024  # 10 MB


class AttachmentTooLargeError(Exception):
    pass


class AttachmentTypeNotAllowedError(Exception):
    pass


class AttachmentService:
    def __init__(
        self,
        conn: aiosqlite.Connection,
        storage_dir: str,
        max_bytes: int = DEFAULT_MAX_BYTES,
        allowed_mimes: Optional[Set[str]] = None,
    ):
        self.conn = conn
        self.repo = AttachmentRepository(conn)
        self.storage_dir = storage_dir
        self.max_bytes = max_bytes
        self.allowed_mimes = allowed_mimes or DEFAULT_ALLOWED_MIMES
        os.makedirs(self.storage_dir, exist_ok=True)

    async def save_attachment(
        self,
        conversation_id: str,
        upload_file: UploadFile,
    ) -> Attachment:
        mime = upload_file.content_type or "application/octet-stream"
        if mime not in self.allowed_mimes:
            raise AttachmentTypeNotAllowedError(
                f"MIME type '{mime}' is not supported. Allowed: {', '.join(sorted(self.allowed_mimes))}"
            )

        storage_filename = f"{uuid.uuid4().hex}"
        storage_path = os.path.join(self.storage_dir, storage_filename)

        hasher = hashlib.sha256()
        size_bytes = 0

        with open(storage_path, "wb") as out_f:
            while True:
                chunk = await upload_file.read(64 * 1024)
                if not chunk:
                    break
                size_bytes += len(chunk)
                if size_bytes > self.max_bytes:
                    out_f.close()
                    try:
                        os.remove(storage_path)
                    except OSError:
                        pass
                    raise AttachmentTooLargeError(
                        f"Attachment exceeds maximum allowed size of {self.max_bytes} bytes."
                    )
                hasher.update(chunk)
                out_f.write(chunk)

        # Sanitize original filename for storage metadata
        orig_filename = os.path.basename(upload_file.filename or "attachment")
        att = Attachment(
            conversation_id=conversation_id,
            filename=orig_filename,
            mime_type=mime,
            size_bytes=size_bytes,
            sha256=hasher.hexdigest(),
            storage_path=storage_path,
            created_at=utc_now_iso(),
        )

        await self.repo.create(att)
        return att

    async def get_attachment(self, attachment_id: str) -> Optional[Attachment]:
        return await self.repo.get_by_id(attachment_id)
