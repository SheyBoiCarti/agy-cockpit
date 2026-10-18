import pytest
import aiosqlite
from agy_cockpit.backend.db.connection import init_db, get_db_connection

@pytest.fixture
async def db_conn(tmp_path):
    db_file = str(tmp_path / "test_session.db")
    await init_db(db_file)
    conn = await get_db_connection(db_file)
    try:
        yield conn
    finally:
        await conn.close()
