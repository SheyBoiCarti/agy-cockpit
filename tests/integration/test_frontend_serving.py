"""Phase 5 Integration Tests: Static Asset Serving and Frontend Contracts."""

import os
import tempfile
from fastapi.testclient import TestClient
from agy_cockpit.backend.app import create_app
from agy_cockpit.backend.config import AppConfig


def test_favicon_serving():
    with tempfile.TemporaryDirectory() as tmpdir:
        with TestClient(create_app(AppConfig(data_dir=tmpdir))) as client:
            response = client.get('/favicon.svg')
            assert response.status_code == 200
            assert 'image/svg+xml' in response.headers['content-type']
            assert '<svg' in response.text


def test_static_index_serving():
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = AppConfig(data_dir=tmpdir, token="test-token-1")
        app = create_app(config=cfg)

        with TestClient(app) as client:
            resp = client.get("/")
            assert resp.status_code == 200
            assert "text/html" in resp.headers["content-type"]
            assert "Antigravity Cockpit" in resp.text
            assert '<div id="root"' in resp.text


def test_health_endpoint():
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = AppConfig(data_dir=tmpdir)
        app = create_app(config=cfg)

        with TestClient(app) as client:
            resp = client.get("/health")
            assert resp.status_code == 200
            assert resp.json()["service"] == "agy-cockpit"


def test_models_endpoint():
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = AppConfig(data_dir=tmpdir)
        app = create_app(config=cfg)

        with TestClient(app) as client:
            resp = client.get("/api/models")
            assert resp.status_code == 200
            data = resp.json()
            assert "models" in data
            assert len(data["models"]) >= 2
            slugs = [m["slug"] for m in data["models"]]
            assert "gemini-3.8-flash-high" in slugs


def test_security_headers_present():
    from agy_cockpit.backend.app import create_app
    from agy_cockpit.backend.config import AppConfig
    from starlette.testclient import TestClient

    cfg = AppConfig()
    app = create_app(config=cfg)
    with TestClient(app) as client:
        resp = client.get("/")
        assert resp.status_code == 200
        csp = resp.headers.get("content-security-policy", "")
        assert "default-src 'self'" in csp
        assert "https://cdn.jsdelivr.net" not in csp
        assert resp.headers.get("x-frame-options") == "DENY"
        assert resp.headers.get("x-content-type-options") == "nosniff"

