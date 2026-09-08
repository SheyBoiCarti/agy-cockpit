"""Settings service."""

from typing import Any, Dict
import aiosqlite

from agy_cockpit.backend.db.repositories.settings_repository import SettingsRepository
from agy_cockpit.backend.domain.models import Settings, utc_now_iso


class SettingsService:
    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn
        self.repo = SettingsRepository(conn)

    async def get_settings(self) -> Settings:
        return await self.repo.get()

    async def update_settings(self, updates: Dict[str, Any]) -> Settings:
        settings = await self.repo.get()
        if "default_model" in updates and updates["default_model"]:
            settings.default_model = updates["default_model"]
        if "policy_preset" in updates and updates["policy_preset"]:
            settings.policy_preset = updates["policy_preset"]
        if "theme" in updates and updates["theme"]:
            settings.theme = updates["theme"]
        settings.updated_at = utc_now_iso()
        await self.repo.save(settings)
        return settings
