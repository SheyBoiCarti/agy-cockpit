import asyncio
from unittest.mock import AsyncMock, patch
import pytest
from agy_cockpit.backend.services.model_catalog_service import ModelCatalogService

MODELS = """Fetching available models...
gemini-3.8-flash-high\tGemini 3.8 Flash (High)
gemini-3.8-flash-medium\tGemini 3.8 Flash (Medium)
gemini-3.8-flash-low\tGemini 3.8 Flash (Low)
claude-sonnet-4-6\tClaude Sonnet 4.6 (Thinking)
claude-opus-4-6-thinking\tClaude Opus 4.6 (Thinking)
gpt-oss-120b-medium\tGPT-OSS 120B (Medium)
"""


@pytest.mark.asyncio
async def test_model_discovery_accepts_slow_success():
    service = ModelCatalogService()
    worker = AsyncMock(returncode=0)
    async def communicate():
        await asyncio.sleep(0)
        return MODELS.encode(), b''
    worker.communicate.side_effect = communicate
    with patch('shutil.which', return_value='agy'), patch('asyncio.create_subprocess_exec', return_value=worker):
        result = await service.list_models()
    assert result['status'] == 'ready'
    assert len(result['models']) == 6
    assert not any('3.7' in m['slug'] or '3.1' in m['slug'] for m in result['models'])
    assert service.discovery_timeout == 15


@pytest.mark.asyncio
async def test_model_discovery_failure_and_cache():
    service = ModelCatalogService()
    with patch('shutil.which', return_value=None):
        result = await service.list_models()
    assert result['models'] == []
    assert result['status'] == 'unavailable'
    worker = AsyncMock(returncode=0)
    async def communicate():
        await asyncio.sleep(0)
        return MODELS.encode(), b''
    worker.communicate.side_effect = communicate
    with patch('shutil.which', return_value='agy'), patch('asyncio.create_subprocess_exec', return_value=worker) as spawn:
        results = await asyncio.gather(*(service.list_models(force_refresh=True) for _ in range(3)))
        assert all(r['status'] == 'ready' for r in results)
        assert spawn.call_count == 1
    with patch('shutil.which', return_value=None):
        stale = await service.list_models(force_refresh=True)
    assert stale['status'] == 'stale'
    assert len(stale['models']) == 6


@pytest.mark.asyncio
async def test_unavailable_model_is_rejected():
    service = ModelCatalogService()
    worker = AsyncMock(returncode=0)
    worker.communicate.return_value = (MODELS.encode(), b'')
    with patch('shutil.which', return_value='agy'), patch('asyncio.create_subprocess_exec', return_value=worker):
        with pytest.raises(ValueError, match='not available'):
            await service.validate_model_slug('gemini-3.1-pro-high')


@pytest.mark.asyncio
async def test_model_discovery_rejects_malformed_output_and_deduplicates():
    service = ModelCatalogService()
    worker = AsyncMock(returncode=0)
    worker.communicate.return_value = (b'Model Name\nFetching available models...\n', b'')
    with patch('shutil.which', return_value='agy'), patch('asyncio.create_subprocess_exec', return_value=worker):
        result = await service.list_models()
        assert result['status'] == 'unavailable'
        worker.communicate.return_value = ((MODELS + MODELS).encode(), b'')
        result = await service.list_models(force_refresh=True)
        assert len(result['models']) == 6
        await service.list_models()
        assert worker.communicate.call_count == 2  # Successful discovery is cached.
        service._expires = 0
        await service.list_models()
        assert worker.communicate.call_count == 3


@pytest.mark.asyncio
async def test_model_discovery_timeout_reaps_process():
    from unittest.mock import MagicMock
    service = ModelCatalogService()
    worker = AsyncMock(returncode=None)
    worker.kill = MagicMock()
    worker.communicate.side_effect = TimeoutError()
    with patch('shutil.which', return_value='agy'), patch('asyncio.create_subprocess_exec', return_value=worker):
        result = await service.list_models()
    assert result['status'] == 'unavailable'
    worker.kill.assert_called_once()
    worker.wait.assert_awaited_once()
