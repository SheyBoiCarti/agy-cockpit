"""Discover account models without presenting guessed access as authoritative."""
import asyncio
import logging
import re
import shutil
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class ModelCatalogService:
    discovery_timeout = 15
    success_ttl = 300
    failure_retry = 30

    def __init__(self):
        self._models = []
        self._last_success = None
        self._error = None
        self._expires = 0.0
        self._generation = 0
        self._lock = asyncio.Lock()

    def _result(self):
        return {"models": [dict(m) for m in self._models],
                "status": "stale" if self._error and self._models else "unavailable" if self._error else "ready",
                "error": self._error, "last_success_at": self._last_success}

    async def list_models(self, *, force_refresh=False):
        generation = self._generation
        if not force_refresh and time.monotonic() < self._expires:
            return self._result()
        async with self._lock:
            if generation != self._generation or (not force_refresh and time.monotonic() < self._expires):
                return self._result()
            try:
                self._models = await self._discover()
                self._last_success = datetime.now(timezone.utc).isoformat()
                self._error = None
                self._expires = time.monotonic() + self.success_ttl
            except Exception:
                logger.exception("Account model discovery failed")
                self._error = "Could not discover account models. Check Antigravity login and retry Refresh models."
                self._expires = time.monotonic() + self.failure_retry
            self._generation += 1
            return self._result()

    async def _discover(self):
        executable = shutil.which("agy")
        if not executable:
            raise RuntimeError("Antigravity CLI is not installed")
        process = await asyncio.create_subprocess_exec(executable, "models", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), self.discovery_timeout)
        except BaseException:
            if process.returncode is None:
                process.kill()
            await process.wait()
            raise
        if process.returncode:
            raise RuntimeError(f"Model discovery exited {process.returncode}: {stderr.decode(errors='replace')[:1000]}")
        models = {}
        output = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", stdout.decode("utf-8", errors="replace"))
        for line in output.splitlines():
            parts = line.strip().split(None, 1)
            if len(parts) == 2 and re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9.]+)+", parts[0]):
                slug, label = parts
                models[slug] = {"slug": slug, "label": label, "is_default": slug == "gemini-3.8-flash-high"}
        if not models:
            raise ValueError("Model discovery returned no model rows")
        return list(models.values())

    async def validate_model_slug(self, slug):
        result = await self.list_models()
        if result["status"] != "ready":
            raise ValueError(result["error"] or "Refresh models before starting a run")
        if slug not in {m["slug"] for m in result["models"]}:
            raise ValueError(f"Model '{slug}' is not available for this account. Select an available model.")
        return slug
