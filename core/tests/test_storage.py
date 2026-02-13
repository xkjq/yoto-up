"""Tests for storage layer -- paths, tokens, config, cache, versions."""
import json
import os
import time
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from yoto_up.models.user import TokenData


# =========================================================================
# atomic_write
# =========================================================================


class TestAtomicWrite:
    def test_atomic_write_text(self, tmp_path):
        from yoto_up.storage.paths import atomic_write
        target = tmp_path / "test.txt"
        atomic_write(target, "hello world")
        assert target.read_text() == "hello world"

    def test_atomic_write_bytes(self, tmp_path):
        from yoto_up.storage.paths import atomic_write
        target = tmp_path / "test.bin"
        atomic_write(target, b"binary data", text_mode=False)
        assert target.read_bytes() == b"binary data"

    def test_atomic_write_overwrite(self, tmp_path):
        """Writing to an existing file should replace its content."""
        from yoto_up.storage.paths import atomic_write
        target = tmp_path / "overwrite.txt"
        atomic_write(target, "first")
        atomic_write(target, "second")
        assert target.read_text() == "second"

    def test_atomic_write_creates_parents(self, tmp_path):
        """Parent directories should be created automatically."""
        from yoto_up.storage.paths import atomic_write
        target = tmp_path / "a" / "b" / "c" / "deep.txt"
        atomic_write(target, "deep")
        assert target.read_text() == "deep"

    def test_atomic_write_text_with_bytes(self, tmp_path):
        """Bytes are decoded when text_mode=True."""
        from yoto_up.storage.paths import atomic_write
        target = tmp_path / "decoded.txt"
        atomic_write(target, b"bytes as text", text_mode=True)
        assert target.read_text() == "bytes as text"

    def test_atomic_write_binary_with_str(self, tmp_path):
        """Strings are encoded when text_mode=False."""
        from yoto_up.storage.paths import atomic_write
        target = tmp_path / "encoded.bin"
        atomic_write(target, "string as bytes", text_mode=False)
        assert target.read_bytes() == b"string as bytes"

    def test_atomic_write_no_orphaned_tmp(self, tmp_path):
        """After a successful write, no .tmp file should remain."""
        from yoto_up.storage.paths import atomic_write
        target = tmp_path / "clean.txt"
        atomic_write(target, "data")
        tmp_file = target.with_suffix(target.suffix + ".tmp")
        assert not tmp_file.exists()


# =========================================================================
# Token storage
# =========================================================================


class TestTokenStorage:
    def test_save_and_load_tokens(self, tmp_path):
        """Tokens saved to disk can be loaded back."""
        from yoto_up.storage import tokens as token_mod
        token_file = tmp_path / "tokens.json"

        with patch.object(token_mod, "TOKENS_FILE", token_file):
            token_data = TokenData(access_token="abc", refresh_token="xyz")
            token_mod.save_tokens(token_data)

            loaded = token_mod.load_tokens()
            assert loaded is not None
            assert loaded.access_token == "abc"
            assert loaded.refresh_token == "xyz"

    def test_load_missing_tokens(self, tmp_path):
        """Loading from a non-existent file returns None."""
        from yoto_up.storage import tokens as token_mod
        token_file = tmp_path / "nonexistent.json"

        with patch.object(token_mod, "TOKENS_FILE", token_file):
            loaded = token_mod.load_tokens()
            assert loaded is None

    def test_delete_tokens(self, tmp_path):
        """delete_tokens removes the file without raising."""
        from yoto_up.storage import tokens as token_mod
        token_file = tmp_path / "tokens.json"
        token_file.write_text('{"access_token":"a","refresh_token":"b"}')

        with patch.object(token_mod, "TOKENS_FILE", token_file):
            token_mod.delete_tokens()
            assert not token_file.exists()

    def test_delete_tokens_missing_file(self, tmp_path):
        """delete_tokens is a no-op when the file doesn't exist."""
        from yoto_up.storage import tokens as token_mod
        token_file = tmp_path / "nonexistent.json"

        with patch.object(token_mod, "TOKENS_FILE", token_file):
            token_mod.delete_tokens()  # should not raise

    def test_delete_tokens_does_not_raise_on_error(self, tmp_path):
        """After fix 12, delete_tokens should NOT re-raise OSError."""
        from yoto_up.storage import tokens as token_mod

        # Create a mock path that exists but fails on unlink
        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_path.unlink.side_effect = OSError("permission denied")

        with patch.object(token_mod, "TOKENS_FILE", mock_path):
            # Should log error but NOT raise
            token_mod.delete_tokens()

    def test_load_corrupt_tokens_returns_none(self, tmp_path):
        """Corrupt JSON in the tokens file should return None."""
        from yoto_up.storage import tokens as token_mod
        token_file = tmp_path / "tokens.json"
        token_file.write_text("not valid json {{{}}", encoding="utf-8")

        with patch.object(token_mod, "TOKENS_FILE", token_file):
            assert token_mod.load_tokens() is None

    def test_token_round_trip_with_id_token(self, tmp_path):
        """id_token is preserved through save/load cycle."""
        from yoto_up.storage import tokens as token_mod
        token_file = tmp_path / "tokens.json"

        with patch.object(token_mod, "TOKENS_FILE", token_file):
            td = TokenData(access_token="at", refresh_token="rt", id_token="it")
            token_mod.save_tokens(td)
            loaded = token_mod.load_tokens()
            assert loaded is not None
            assert loaded.id_token == "it"


# =========================================================================
# AppSettings
# =========================================================================


class TestAppSettings:
    def test_default_settings(self, tmp_path):
        from yoto_up.storage.config import AppSettings, SETTINGS_FILE
        settings_file = tmp_path / "settings.json"

        with patch("yoto_up.storage.config.SETTINGS_FILE", settings_file):
            settings = AppSettings.load()
            assert settings["debug"] is False
            assert settings["cache_enabled"] is False
            assert settings["audio_target_lufs"] == -16.0

    def test_save_and_load(self, tmp_path):
        from yoto_up.storage.config import AppSettings
        settings_file = tmp_path / "settings.json"

        with patch("yoto_up.storage.config.SETTINGS_FILE", settings_file):
            AppSettings.set("debug", True)
            assert AppSettings.get("debug") is True

    def test_unknown_key_returns_default(self, tmp_path):
        from yoto_up.storage.config import AppSettings
        settings_file = tmp_path / "settings.json"

        with patch("yoto_up.storage.config.SETTINGS_FILE", settings_file):
            assert AppSettings.get("nonexistent") is None
            assert AppSettings.get("nonexistent", 42) == 42

    def test_corrupt_settings_returns_defaults(self, tmp_path):
        from yoto_up.storage.config import AppSettings
        settings_file = tmp_path / "settings.json"
        settings_file.write_text("{{invalid json")

        with patch("yoto_up.storage.config.SETTINGS_FILE", settings_file):
            s = AppSettings.load()
            assert s["debug"] is False


# =========================================================================
# APICache
# =========================================================================


class TestAPICache:
    def test_put_and_get(self, tmp_path):
        from yoto_up.storage.cache import APICache
        cache_file = tmp_path / "cache.json"

        with patch("yoto_up.storage.cache.API_CACHE_FILE", cache_file):
            c = APICache(enabled=True, max_age_seconds=60)
            data = {"cards": [1, 2, 3]}
            c.put("GET", "/content/mine", data)

            result = c.get("GET", "/content/mine")
            assert result is not None
            assert result["cards"] == [1, 2, 3]

    def test_put_does_not_mutate_caller(self, tmp_path):
        """Fix 7: put() must not inject 'timestamp' into the caller's dict."""
        from yoto_up.storage.cache import APICache
        cache_file = tmp_path / "cache.json"

        with patch("yoto_up.storage.cache.API_CACHE_FILE", cache_file):
            c = APICache(enabled=True, max_age_seconds=60)
            original = {"key": "value"}
            c.put("GET", "/test", original)
            assert "timestamp" not in original  # caller's dict unmodified!

    def test_disabled_cache_returns_none(self):
        c = __import__("yoto_up.storage.cache", fromlist=["APICache"]).APICache(enabled=False)
        c.put("GET", "/x", {"data": 1})
        assert c.get("GET", "/x") is None

    def test_expired_entry_returns_none(self, tmp_path):
        from yoto_up.storage.cache import APICache
        cache_file = tmp_path / "cache.json"

        with patch("yoto_up.storage.cache.API_CACHE_FILE", cache_file):
            c = APICache(enabled=True, max_age_seconds=1)
            c.put("GET", "/x", {"value": 1})

            # Manually age the entry
            key = list(c._cache.keys())[0]
            c._cache[key]["timestamp"] = time.time() - 100
            assert c.get("GET", "/x") is None

    def test_clear(self, tmp_path):
        from yoto_up.storage.cache import APICache
        cache_file = tmp_path / "cache.json"

        with patch("yoto_up.storage.cache.API_CACHE_FILE", cache_file):
            c = APICache(enabled=True, max_age_seconds=60)
            c.put("GET", "/x", {"value": 1})
            c.clear()
            assert c.get("GET", "/x") is None


# =========================================================================
# IconCache
# =========================================================================


class TestIconCache:
    def test_save_and_get(self, tmp_path):
        from yoto_up.storage.cache import IconCache
        with patch("yoto_up.storage.cache.ICON_CACHE_DIR", tmp_path):
            IconCache.save("media123", b"fake icon data")
            assert IconCache.exists("media123")
            path = IconCache.get_path("media123")
            assert path is not None
            assert path.read_bytes() == b"fake icon data"

    def test_missing_icon(self, tmp_path):
        from yoto_up.storage.cache import IconCache
        with patch("yoto_up.storage.cache.ICON_CACHE_DIR", tmp_path):
            assert IconCache.get_path("nonexistent") is None
            assert not IconCache.exists("nonexistent")

    def test_sanitizes_media_id(self, tmp_path):
        """Fix 14: malicious media_id must not cause directory traversal."""
        from yoto_up.storage.cache import IconCache
        with patch("yoto_up.storage.cache.ICON_CACHE_DIR", tmp_path):
            malicious_id = "../../../etc/passwd"
            IconCache.save(malicious_id, b"data")
            # The saved file should be inside tmp_path, not in /etc
            path = IconCache.get_path(malicious_id)
            assert path is not None
            assert str(path).startswith(str(tmp_path))
            # The filename should be a hash, not the raw ID
            assert "passwd" not in path.name


# =========================================================================
# VersionStore
# =========================================================================


class TestVersionStore:
    def test_save_and_list(self, tmp_path):
        from yoto_up.storage.versions import VersionStore
        with patch("yoto_up.storage.versions.VERSIONS_DIR", tmp_path):
            card_data = {"cardId": "test123", "title": "Test Card"}
            path = VersionStore.save(card_data)
            assert path is not None
            assert path.exists()

            versions = VersionStore.list_versions("test123")
            assert len(versions) == 1

    def test_load_version(self, tmp_path):
        from yoto_up.storage.versions import VersionStore
        with patch("yoto_up.storage.versions.VERSIONS_DIR", tmp_path):
            card_data = {"cardId": "test123", "title": "Test Card"}
            path = VersionStore.save(card_data)
            loaded = VersionStore.load(path)
            assert loaded["title"] == "Test Card"

    def test_delete_version(self, tmp_path):
        from yoto_up.storage.versions import VersionStore
        with patch("yoto_up.storage.versions.VERSIONS_DIR", tmp_path):
            path = VersionStore.save({"cardId": "c1", "title": "Card 1"})
            assert path is not None
            assert VersionStore.delete(path)
            assert not path.exists()

    def test_empty_title_slug(self, tmp_path):
        """Fix 15: a payload with no ID and empty title should not produce empty path."""
        from yoto_up.storage.versions import VersionStore
        with patch("yoto_up.storage.versions.VERSIONS_DIR", tmp_path):
            payload = {"title": " "}  # no cardId, whitespace-only title
            path = VersionStore.save(payload)
            assert path is not None
            # The directory name should not be empty
            assert path.parent.name != ""
            assert path.parent.name == "untitled"

    def test_special_chars_title_slug(self, tmp_path):
        """Titles with all special chars get slugified to non-empty path."""
        from yoto_up.storage.versions import VersionStore
        with patch("yoto_up.storage.versions.VERSIONS_DIR", tmp_path):
            payload = {"title": "!!!"}  # all replaced by hyphens
            path = VersionStore.save(payload)
            assert path is not None
            # Should fallback to "untitled" since stripped hyphens = empty
            assert path.parent.name == "untitled"

    def test_versions_sorted_newest_first(self, tmp_path):
        from yoto_up.storage.versions import VersionStore
        import time
        with patch("yoto_up.storage.versions.VERSIONS_DIR", tmp_path):
            VersionStore.save({"cardId": "c1", "title": "v1"})
            # Sleep long enough to guarantee a different second in timestamp
            time.sleep(1.1)
            VersionStore.save({"cardId": "c1", "title": "v2"})

            versions = VersionStore.list_versions("c1")
            assert len(versions) == 2
            # First should be newest (alphabetically later timestamp)
            v1 = VersionStore.load(versions[0])
            assert v1["title"] == "v2"

    def test_list_versions_nonexistent_card(self, tmp_path):
        from yoto_up.storage.versions import VersionStore
        with patch("yoto_up.storage.versions.VERSIONS_DIR", tmp_path):
            assert VersionStore.list_versions("nonexistent") == []

    def test_load_missing_file(self, tmp_path):
        from yoto_up.storage.versions import VersionStore
        missing = tmp_path / "nonexistent.json"
        assert VersionStore.load(missing) == {}

    def test_fallback_to_id_key(self, tmp_path):
        """When cardId is missing, fall back to 'id' key."""
        from yoto_up.storage.versions import VersionStore
        with patch("yoto_up.storage.versions.VERSIONS_DIR", tmp_path):
            payload = {"id": "alt-id-123", "title": "Test"}
            path = VersionStore.save(payload)
            assert path is not None
            assert "alt-id-123" in str(path)
