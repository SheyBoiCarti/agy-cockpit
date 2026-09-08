"""Settings repository."""

import aiosqlite

from agy_cockpit.backend.domain.models import Settings


class SettingsRepository:
    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn

    async def get(self) -> Settings:
        async with self.conn.execute("SELECT * FROM settings WHERE id = 'global'") as cursor:
            row = await cursor.fetchone()
            if not row:
                # Default settings
                default = Settings()
                await self.save(default)
                return default
            return Settings(**dict(row))

    async def save(self, settings: Settings) -> None:
        await self.conn.execute(
            """
            INSERT OR REPLACE INTO settings (id, default_model, policy_preset, theme, updated_at)
            VALUES ('global', ?, ?, ?, ?)
            """,
            (
                settings.default_model,
                settings.policy_preset,
                settings.theme,
                settings.updated_at,
            ),
        )
        await self.conn.commit()
