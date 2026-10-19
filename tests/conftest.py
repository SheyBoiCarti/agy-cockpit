import pytest
import aiosqlite
from agy_cockpit.backend.db.connection import init_db, get_db_connection


@pytest.fixture(autouse=True)
def deterministic_model_catalog(request, monkeypatch):
    # Account discovery itself has process-level tests in test_model_catalog.
    if request.node.path.name == 'test_model_catalog.py':
        return
    from agy_cockpit.backend.services.model_catalog_service import ModelCatalogService
    async def discover(self):
        return [{"slug": f"gemini-3.8-flash-{level}", "label": f"Gemini 3.8 Flash ({level.title()})"} for level in ('high', 'medium', 'low')]
    monkeypatch.setattr(ModelCatalogService, '_discover', discover)

@pytest.fixture
async def db_conn(tmp_path):
    db_file = str(tmp_path / "test_session.db")
    await init_db(db_file)
    conn = await get_db_connection(db_file)
    try:
        yield conn
    finally:
        await conn.close()
