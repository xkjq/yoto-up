"""Tests for API layer -- client, auth, cards, icons."""
import json
import pytest
from unittest.mock import patch, MagicMock, PropertyMock
from yoto_up.models.user import TokenData
from yoto_up.models.card import Card, CardContent, CardMetadata, Chapter, Track


# =========================================================================
# YotoClient
# =========================================================================


class TestYotoClient:
    def test_unauthenticated_by_default(self):
        """A fresh client with no saved tokens is not authenticated."""
        with patch("yoto_up.api.client.load_tokens", return_value=None):
            from yoto_up.api.client import YotoClient
            client = YotoClient()
            assert not client.is_authenticated
            assert client.access_token is None
            client.close()

    def test_authenticated_with_tokens(self):
        """A client with saved tokens is authenticated."""
        td = TokenData(access_token="valid-token", refresh_token="rt")
        with patch("yoto_up.api.client.load_tokens", return_value=td):
            from yoto_up.api.client import YotoClient
            client = YotoClient()
            assert client.is_authenticated
            assert client.access_token == "valid-token"
            client.close()

    def test_auth_headers_empty_when_no_token(self):
        """Fix 5: _auth_headers returns empty dict when not authenticated."""
        with patch("yoto_up.api.client.load_tokens", return_value=None):
            from yoto_up.api.client import YotoClient
            client = YotoClient()
            headers = client._auth_headers()
            assert headers == {}  # NOT {"Authorization": "Bearer None"}
            client.close()

    def test_auth_headers_with_token(self):
        """_auth_headers returns correct bearer header."""
        td = TokenData(access_token="my-token", refresh_token="rt")
        with patch("yoto_up.api.client.load_tokens", return_value=td):
            from yoto_up.api.client import YotoClient
            client = YotoClient()
            headers = client._auth_headers()
            assert headers == {"Authorization": "Bearer my-token"}
            client.close()

    def test_set_tokens_persists(self):
        """set_tokens stores tokens in memory and calls save_tokens."""
        with patch("yoto_up.api.client.load_tokens", return_value=None):
            with patch("yoto_up.api.client.save_tokens") as mock_save:
                from yoto_up.api.client import YotoClient
                client = YotoClient()
                assert not client.is_authenticated

                td = TokenData(access_token="new-token", refresh_token="r")
                client.set_tokens(td)
                assert client.is_authenticated
                assert client.access_token == "new-token"
                mock_save.assert_called_once_with(td)
                client.close()

    def test_clear_tokens(self):
        """clear_tokens removes auth state."""
        td = TokenData(access_token="t", refresh_token="r")
        with patch("yoto_up.api.client.load_tokens", return_value=td):
            with patch("yoto_up.api.client.delete_tokens"):
                from yoto_up.api.client import YotoClient
                client = YotoClient()
                assert client.is_authenticated
                client.clear_tokens()
                assert not client.is_authenticated
                client.close()

    def test_close(self):
        """close() shuts down the HTTP client."""
        with patch("yoto_up.api.client.load_tokens", return_value=None):
            from yoto_up.api.client import YotoClient
            client = YotoClient()
            client.close()
            # Verify it's closed by checking _http is closed
            assert client._http.is_closed


# =========================================================================
# Auth module
# =========================================================================


class TestDeviceAuthError:
    def test_class_exists(self):
        """DeviceAuthError is importable and is an Exception subclass."""
        from yoto_up.api.auth import DeviceAuthError
        assert issubclass(DeviceAuthError, Exception)
        err = DeviceAuthError("test error")
        assert str(err) == "test error"

    def test_device_auth_info(self):
        """DeviceAuthInfo dataclass can be constructed."""
        from yoto_up.api.auth import DeviceAuthInfo
        info = DeviceAuthInfo(
            device_code="dc", user_code="uc",
            verification_uri="https://example.com",
            verification_uri_complete="https://example.com?code=uc",
            expires_in=300, interval=5,
        )
        assert info.user_code == "uc"


# =========================================================================
# Card API helpers
# =========================================================================


class TestParseCard:
    def test_parse_card_does_not_mutate_input(self):
        """Fix: _parse_card should not modify the input dict."""
        from yoto_up.api.cards import _parse_card
        raw = {
            "title": "Test",
            "metadata": {"author": "A"},
            "content": {"chapters": []},
        }
        raw_copy = json.loads(json.dumps(raw))  # deep copy for comparison
        _parse_card(raw)
        # raw should be unchanged (still plain dicts, no Pydantic objects)
        assert isinstance(raw["metadata"], dict)
        assert isinstance(raw["content"], dict)
        assert raw == raw_copy

    def test_parse_card_basic(self):
        from yoto_up.api.cards import _parse_card
        raw = {"title": "My Card", "cardId": "c123"}
        card = _parse_card(raw)
        assert isinstance(card, Card)
        assert card.title == "My Card"
        assert card.cardId == "c123"

    def test_parse_card_with_nested_objects(self):
        from yoto_up.api.cards import _parse_card
        raw = {
            "title": "Card",
            "metadata": {"author": "Test Author", "category": "music"},
            "content": {
                "chapters": [
                    {
                        "title": "Ch1",
                        "tracks": [
                            {"title": "T1", "trackUrl": "u", "key": "01",
                             "format": "mp3", "type": "audio"}
                        ]
                    }
                ]
            },
        }
        card = _parse_card(raw)
        assert card.metadata.author == "Test Author"
        assert card.total_tracks == 1


# =========================================================================
# Icon URL heuristic
# =========================================================================


class TestLooksLikeIconUrl:
    def test_basic_png(self):
        """Standard .png URL is accepted."""
        from yoto_up.api.icons import _looks_like_icon_url
        assert _looks_like_icon_url("https://cdn.example.com/icon.png") is True

    def test_query_params(self):
        """Fix 18: URLs with query parameters should still match."""
        from yoto_up.api.icons import _looks_like_icon_url
        assert _looks_like_icon_url("https://cdn.example.com/icon.png?v=2") is True
        assert _looks_like_icon_url("https://cdn.example.com/icon.jpg?w=100&h=100") is True

    def test_fragment(self):
        """URLs with fragments should still match."""
        from yoto_up.api.icons import _looks_like_icon_url
        assert _looks_like_icon_url("https://cdn.example.com/icon.webp#section") is True

    def test_rejects_favicon(self):
        from yoto_up.api.icons import _looks_like_icon_url
        assert _looks_like_icon_url("https://example.com/favicon.png") is False

    def test_rejects_non_image(self):
        from yoto_up.api.icons import _looks_like_icon_url
        assert _looks_like_icon_url("https://example.com/script.js") is False

    def test_all_extensions(self):
        from yoto_up.api.icons import _looks_like_icon_url
        for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"):
            assert _looks_like_icon_url(f"https://x.com/img{ext}") is True

    def test_data_uri_rejected(self):
        from yoto_up.api.icons import _looks_like_icon_url
        assert _looks_like_icon_url("data:image/png;base64,abc") is False
