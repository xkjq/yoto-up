"""Tests for storage layer."""
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from yoto_up.models.user import TokenData


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


class TestTokenStorage:
    def test_save_and_load_tokens(self, tmp_path):
        from yoto_up.storage import tokens as token_mod
        token_file = tmp_path / "tokens.json"

        with patch.object(token_mod, '_get_tokens_path', return_value=token_file):
            token_data = TokenData(access_token="abc", refresh_token="xyz")
            token_mod.save_tokens(token_data)

            loaded = token_mod.load_tokens()
            assert loaded is not None
            assert loaded.access_token == "abc"
            assert loaded.refresh_token == "xyz"

    def test_load_missing_tokens(self, tmp_path):
        from yoto_up.storage import tokens as token_mod
        token_file = tmp_path / "nonexistent.json"

        with patch.object(token_mod, '_get_tokens_path', return_value=token_file):
            loaded = token_mod.load_tokens()
            assert loaded is None


class TestAppSettings:
    def test_default_settings(self, tmp_path):
        from yoto_up.storage.config import AppSettings
        settings_file = tmp_path / "settings.json"

        with patch.object(AppSettings, '_settings_path', return_value=settings_file):
            settings = AppSettings.load()
            assert settings["debug"] is False
            assert settings["cache_enabled"] is False

    def test_save_and_load(self, tmp_path):
        from yoto_up.storage.config import AppSettings
        settings_file = tmp_path / "settings.json"

        with patch.object(AppSettings, '_settings_path', return_value=settings_file):
            AppSettings.set("debug", True)
            assert AppSettings.get("debug") is True


class TestVersionStore:
    def test_save_and_list(self, tmp_path):
        from yoto_up.storage.versions import VersionStore

        with patch.object(VersionStore, '_versions_dir', return_value=tmp_path):
            card_data = {"cardId": "test123", "title": "Test Card"}
            path = VersionStore.save(card_data)
            assert path is not None
            assert path.exists()

            versions = VersionStore.list_versions("test123")
            assert len(versions) == 1

    def test_load_version(self, tmp_path):
        from yoto_up.storage.versions import VersionStore

        with patch.object(VersionStore, '_versions_dir', return_value=tmp_path):
            card_data = {"cardId": "test123", "title": "Test Card"}
            path = VersionStore.save(card_data)

            loaded = VersionStore.load(path)
            assert loaded["title"] == "Test Card"
