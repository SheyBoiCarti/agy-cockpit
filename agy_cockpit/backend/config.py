"""Application configuration for Antigravity Cockpit."""

import os
import pathlib
import secrets
from typing import List, Optional

from pydantic import BaseModel, Field


class AppConfig(BaseModel):
    """Cockpit configuration settings."""
    host: str = "127.0.0.1"
    port: int = 8080
    data_dir: str = Field(
        default_factory=lambda: str(
            (pathlib.Path("~") / ".agy-cockpit").expanduser().resolve()
        )
    )
    token: str = Field(default_factory=lambda: secrets.token_hex(24))
    allowed_origins: List[str] = Field(
        default_factory=lambda: [
            "http://127.0.0.1:8080",
            "http://localhost:8080",
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ]
    )
    max_payload_bytes: int = 2 * 1024 * 1024  # 2MB max WS message
    max_attachment_bytes: int = 25 * 1024 * 1024  # 25MB max attachment
    approval_timeout_seconds: float = 300.0  # 5 minutes
    
    @property
    def db_path(self) -> str:
        return os.path.join(self.data_dir, "cockpit.db")

    @property
    def sessions_dir(self) -> str:
        return os.path.join(self.data_dir, "sessions")

    @property
    def attachments_dir(self) -> str:
        return os.path.join(self.data_dir, "attachments")

    @property
    def logs_dir(self) -> str:
        return os.path.join(self.data_dir, "logs")

    def ensure_directories(self) -> None:
        """Ensures all configured data directories exist."""
        for path in [
            self.data_dir,
            self.sessions_dir,
            self.attachments_dir,
            self.logs_dir,
        ]:
            os.makedirs(path, exist_ok=True)


# Global instance default
_config: Optional[AppConfig] = None


def get_config() -> AppConfig:
    global _config
    if _config is None:
        _config = AppConfig()
        _config.ensure_directories()
    return _config


def set_config(cfg: AppConfig) -> None:
    global _config
    _config = cfg
    _config.ensure_directories()
