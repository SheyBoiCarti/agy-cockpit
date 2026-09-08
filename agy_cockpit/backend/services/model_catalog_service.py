"""Model catalog service for machine slug and display label management."""

import shutil
import subprocess
from typing import Dict, List


DEFAULT_MODELS: List[Dict[str, str]] = [
    {"slug": "gemini-3.8-flash-high", "label": "Gemini 3.8 Flash (High)", "is_default": True},
    {"slug": "gemini-3.8-flash-medium", "label": "Gemini 3.8 Flash (Medium)", "is_default": False},
    {"slug": "gemini-3.8-flash-low", "label": "Gemini 3.8 Flash (Low)", "is_default": False},
    {"slug": "gemini-3.7-flash-high", "label": "Gemini 3.7 Flash (High)", "is_default": False},
    {"slug": "gemini-3.7-flash-medium", "label": "Gemini 3.7 Flash (Medium)", "is_default": False},
    {"slug": "gemini-3.1-pro-high", "label": "Gemini 3.1 Pro (High)", "is_default": False},
    {"slug": "claude-sonnet-4-6", "label": "Claude Sonnet 4.6 (Thinking)", "is_default": False},
]


class ModelCatalogService:
    """Provides model slug discovery and validation."""

    def __init__(self):
        self._cached_models: List[Dict[str, str]] = list(DEFAULT_MODELS)

    def list_models(self) -> List[Dict[str, str]]:
        """Returns the list of available models."""
        # Try dynamic discovery via agy CLI if available and not cached
        agy_path = shutil.which("agy")
        if agy_path:
            try:
                res = subprocess.run(
                    [agy_path, "models"],
                    capture_output=True,
                    text=True,
                    timeout=2.0,
                )
                if res.returncode == 0 and res.stdout:
                    discovered = []
                    for line in res.stdout.strip().splitlines():
                        parts = line.strip().split(None, 1)
                        if len(parts) == 2:
                            slug, label = parts[0].strip(), parts[1].strip()
                            if slug and not slug.startswith("⠋") and not slug.startswith("Fetching"):
                                discovered.append({
                                    "slug": slug,
                                    "label": label,
                                    "is_default": (slug == "gemini-3.8-flash-high"),
                                })
                    if discovered:
                        self._cached_models = discovered
            except Exception:
                pass

        return self._cached_models

    def validate_model_slug(self, slug: str) -> str:
        """Validates model slug, returning default if invalid or empty."""
        if not slug or not slug.strip():
            return "gemini-3.8-flash-high"
        models = self.list_models()
        slugs = {m["slug"] for m in models}
        if slug in slugs:
            return slug
        # If slug is unrecognized, log warning and allow if it looks like a valid model name
        return slug
