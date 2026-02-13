"""API response caching and icon file caching.

``APICache`` provides a simple disk-backed request/response cache keyed
by SHA-256 of the request parameters.  ``IconCache`` manages a flat
directory of icon image files keyed by media-id.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from loguru import logger

from .paths import API_CACHE_FILE, ICON_CACHE_DIR, atomic_write, ensure_parents


# ---------------------------------------------------------------------------
# API response cache
# ---------------------------------------------------------------------------


class APICache:
    """Disk-backed, TTL-aware cache for API responses.

    Parameters
    ----------
    enabled:
        When ``False``, :meth:`get` always returns ``None`` and
        :meth:`put` is a no-op.
    max_age_seconds:
        Maximum age (in seconds) before a cached entry is considered
        stale and ignored.
    """

    def __init__(self, enabled: bool = False, max_age_seconds: int = 0) -> None:
        self.enabled = enabled
        self.max_age_seconds = max_age_seconds
        self._cache: dict[str, Any] = {}
        if self.enabled:
            self._load()

    # -- key generation -----------------------------------------------------

    @staticmethod
    def _make_key(
        method: str,
        url: str,
        params: Any = None,
        data: Any = None,
        json_data: Any = None,
    ) -> str:
        """Return a deterministic SHA-256 hex key for the request tuple."""
        blob = {
            "method": method,
            "url": url,
            "params": params,
            "data": data,
            "json": json_data,
        }
        raw = json.dumps(blob, sort_keys=True, default=str).encode()
        return hashlib.sha256(raw).hexdigest()

    # -- public interface ---------------------------------------------------

    def get(
        self,
        method: str,
        url: str,
        params: Any = None,
        data: Any = None,
        json_data: Any = None,
    ) -> dict[str, Any] | None:
        """Return a cached response dict, or ``None`` on miss / disabled."""
        if not self.enabled:
            return None
        key = self._make_key(method, url, params, data, json_data)
        entry = self._cache.get(key)
        if entry is None:
            return None
        age = time.time() - entry.get("timestamp", 0)
        if self.max_age_seconds > 0 and age > self.max_age_seconds:
            return None
        return entry

    def put(
        self,
        method: str,
        url: str,
        response_data: dict[str, Any],
        params: Any = None,
        data: Any = None,
        json_data: Any = None,
    ) -> None:
        """Store *response_data* in the cache, keyed by request params."""
        if not self.enabled:
            return
        key = self._make_key(method, url, params, data, json_data)
        entry = dict(response_data)
        entry["timestamp"] = time.time()
        self._cache[key] = entry
        self._save()

    def clear(self) -> None:
        """Drop every cached entry and remove the backing file."""
        self._cache.clear()
        try:
            if API_CACHE_FILE.exists():
                API_CACHE_FILE.unlink()
        except OSError as exc:
            logger.warning(f"Failed to remove cache file: {exc}")

    # -- persistence --------------------------------------------------------

    def _load(self) -> None:
        """Read the cache dict from *API_CACHE_FILE*."""
        if not API_CACHE_FILE.exists():
            self._cache = {}
            return
        try:
            text = API_CACHE_FILE.read_text(encoding="utf-8")
            loaded = json.loads(text)
            self._cache = loaded if isinstance(loaded, dict) else {}
        except (OSError, json.JSONDecodeError, ValueError):
            self._cache = {}

    def _save(self) -> None:
        """Flush the in-memory cache dict to *API_CACHE_FILE*."""
        try:
            ensure_parents(API_CACHE_FILE)
            atomic_write(
                API_CACHE_FILE,
                json.dumps(self._cache, ensure_ascii=False),
            )
        except OSError as exc:
            logger.warning(f"Failed to save API cache: {exc}")


# ---------------------------------------------------------------------------
# Icon file cache
# ---------------------------------------------------------------------------


class IconCache:
    """Simple file-system cache that maps *media_id* strings to icon files.

    Icons are stored as individual files inside :data:`ICON_CACHE_DIR`.
    """

    @staticmethod
    def _safe_filename(media_id: str) -> str:
        """Sanitise *media_id* to a safe filename (SHA-256 hash)."""
        return hashlib.sha256(media_id.encode()).hexdigest()

    @staticmethod
    def get_path(media_id: str) -> Path | None:
        """Return the cached icon file path, or ``None`` if not cached."""
        path = ICON_CACHE_DIR / IconCache._safe_filename(media_id)
        return path if path.exists() else None

    @staticmethod
    def save(media_id: str, data: bytes) -> None:
        """Write *data* (raw icon bytes) into the cache for *media_id*."""
        path = ICON_CACHE_DIR / IconCache._safe_filename(media_id)
        ensure_parents(path)
        path.write_bytes(data)

    @staticmethod
    def exists(media_id: str) -> bool:
        """Return ``True`` when an icon for *media_id* is already cached."""
        return (ICON_CACHE_DIR / IconCache._safe_filename(media_id)).exists()
