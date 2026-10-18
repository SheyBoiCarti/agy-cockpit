"""Database connection management and initialization."""

from datetime import datetime, timezone
import os
from typing import AsyncGenerator, Optional
import aiosqlite

from agy_cockpit.backend.config import get_config
from agy_cockpit.backend.db.schema import SCHEMA_V1


async def get_db_connection(db_path: Optional[str] = None) -> aiosqlite.Connection:
    """Creates a configured connection to the SQLite database."""
    path = db_path or get_config().db_path
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = await aiosqlite.connect(path)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA foreign_keys = ON;")
    await conn.execute("PRAGMA journal_mode = WAL;")
    await conn.execute("PRAGMA busy_timeout = 5000;")
    return conn


async def init_db(db_path: Optional[str] = None) -> None:
    """Initializes the database schema and applies migrations idempotently."""
    conn = await get_db_connection(db_path)
    try:
        # Check current version
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        await conn.commit()

        async with conn.execute("SELECT MAX(version) FROM schema_migrations") as cursor:
            row = await cursor.fetchone()
            current_version = row[0] if row and row[0] is not None else 0

        if current_version < 1:
            await conn.executescript(SCHEMA_V1)
            applied_at = datetime.now(timezone.utc).isoformat()
            await conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (1, applied_at),
            )
            # Insert default settings if not existing
            await conn.execute(
                """
                INSERT OR IGNORE INTO settings (id, default_model, policy_preset, theme, updated_at)
                VALUES ('global', 'gemini-3.8-flash-high', 'request-review', 'dark', ?)
                """,
                (applied_at,),
            )
            await conn.commit()

        # Ensure 'reasoning' column exists in messages table for backward compatibility
        try:
            await conn.execute("ALTER TABLE messages ADD COLUMN reasoning TEXT NOT NULL DEFAULT ''")
            await conn.commit()
        except Exception:
            pass

        # Ensure active run partial unique index exists
        try:
            await conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_active_run_per_conv
                ON runs (conversation_id)
                WHERE state NOT IN ('completed', 'cancelled', 'failed', 'interrupted');
                """
            )
            await conn.commit()
        except Exception:
            pass
    finally:
        await conn.close()
