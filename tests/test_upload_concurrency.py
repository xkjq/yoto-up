import hashlib
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from yoto_up.yoto_api import YotoAPI


class FakeResp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


def test_concurrent_upload_writes(tmp_path, monkeypatch):
    # Prepare app path so API writes caches to tmp_path
    # Prevent automatic auth flow during tests
    api = YotoAPI("test-client", app_path=tmp_path, auto_start_authentication=False)
    api.OFFICIAL_ICON_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Create two distinct icon files
    icon1 = tmp_path / "icon1.png"
    icon2 = tmp_path / "icon2.png"
    icon1.write_bytes(b"\x00" * 128)
    icon2.write_bytes(b"\x01" * 128)

    # Fake httpx.post to return different URLs based on content
    def fake_post(url, headers=None, params=None, content=None):
        # Use first byte to pick a stable response per file
        first = content[0] if content else 0
        if first % 2 == 0:
            data = {"displayIcon": {"mediaId": "MID-EVEN", "url": "https://cdn.example/icon_even.png"}}
        else:
            data = {"displayIcon": {"mediaId": "MID-ODD", "url": "https://cdn.example/icon_odd.png"}}
        return FakeResp(data)

    monkeypatch.setattr(httpx, "post", fake_post)

    # Run many concurrent uploads (some duplicates) to simulate race
    paths = [str(icon1), str(icon2), str(icon1), str(icon2), str(icon1)]
    results = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = [ex.submit(api.upload_custom_icon, p) for p in paths]
        for f in futures:
            results.append(f.result())

    # Ensure upload cache file contains entries and each referenced cached image exists
    upload_cache = api._load_icon_upload_cache()
    assert isinstance(upload_cache, dict) and len(upload_cache) >= 1

    for sha, meta in upload_cache.items():
        url = meta.get("url")
        assert url, "Upload metadata missing url"
        url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
        ext = Path(url).suffix or ".png"
        p = api.OFFICIAL_ICON_CACHE_DIR / f"{url_hash}{ext}"
        assert p.exists(), f"Cached image file missing: {p}"
