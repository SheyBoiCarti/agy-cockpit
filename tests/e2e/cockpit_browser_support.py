"""Browser regression server: real transport with isolated storage, no credentials."""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def cockpit_url(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "hello.txt").write_text("attachment regression", encoding="utf-8")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    log = (tmp_path / "server.log").open("w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "tests.e2e.cockpit_browser_support", str(port), str(tmp_path / "data")],
        cwd=ROOT, stdout=log, stderr=log,
        env={**os.environ, "COUNCIL_TEST_MODE": "1"},
    )
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise RuntimeError("Browser server exited; inspect server.log")
            try:
                with urlopen(base + "/health", timeout=1) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("Browser server did not become ready")
        from urllib.parse import urlencode
        yield base + "/?" + urlencode({"token": "browser-regression", "workspace": str(workspace)})
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        log.close()


if __name__ == '__main__':
    import uvicorn
    from agy_cockpit.backend.app import create_app
    from agy_cockpit.backend.config import AppConfig
    from agy_cockpit.backend.services.agent_service import MockAntigravityAdapter
    from agy_cockpit.backend.services.model_catalog_service import ModelCatalogService
    from tests.backend.test_model_catalog import MODELS
    async def discover(self):
        return [{"slug": line.split('\t')[0], "label": line.split('\t')[1]} for line in MODELS.splitlines() if '\t' in line]
    ModelCatalogService._discover = discover
    class BrowserAdapter(MockAntigravityAdapter):
        async def run_turn(self, **kwargs):
            if 'reconnect-test' in kwargs['prompt']:
                await kwargs['on_token']('partial answer ')
            tools = [{'id': 'approval-tool', 'name': 'create_file', 'args': {'file_path': 'approval-probe.txt'}, 'requires_approval': True}] if 'approval-test' in kwargs['prompt'] else []
            adapter = MockAntigravityAdapter(tokens=['APPROVE Isolation is useful.'] if 'ROLL-CALL VOTE' in kwargs['prompt'] else ['Completed response.'], tools=tools, wait_for_cancel='wait-for-cancel' in kwargs['prompt'])
            return await adapter.run_turn(**kwargs)
    port = int(sys.argv[1])
    config = AppConfig(port=port, data_dir=sys.argv[2], token='browser-regression', allowed_origins=[f'http://127.0.0.1:{port}'])
    uvicorn.run(create_app(config, agent_adapter=BrowserAdapter()), host='127.0.0.1', port=port, log_level='warning')
