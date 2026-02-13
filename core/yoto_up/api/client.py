"""Base HTTP client for Yoto API with token management."""

from __future__ import annotations

import base64
import json
import time

import httpx
from loguru import logger

from ..models.user import TokenData
from ..storage.config import CLIENT_ID
from ..storage.tokens import delete_tokens, load_tokens, save_tokens


class AuthenticationError(Exception):
    """Raised when authentication fails and cannot be automatically recovered."""


class YotoClient:
    """Low-level HTTP client with automatic token refresh.

    The client wraps :mod:`httpx` and transparently manages OAuth tokens:
    loading them from disk on construction, refreshing them when they are
    about to expire, and persisting any updates back to disk.

    Example::

        client = YotoClient()
        if client.is_authenticated:
            resp = client.get("/content/mine")
    """

    SERVER_URL = "https://api.yotoplay.com"
    TOKEN_URL = "https://login.yotoplay.com/oauth/token"

    def __init__(self) -> None:
        self._tokens: TokenData | None = load_tokens()
        self._http = httpx.Client(timeout=30.0)

    # ------------------------------------------------------------------
    # Token helpers
    # ------------------------------------------------------------------

    @property
    def is_authenticated(self) -> bool:
        """Return ``True`` if an access token is available."""
        return self._tokens is not None and self._tokens.access_token != ""

    @property
    def access_token(self) -> str | None:
        """Return the current access token, or ``None``."""
        if self._tokens:
            return self._tokens.access_token
        return None

    def _auth_headers(self) -> dict[str, str]:
        """Build an ``Authorization`` header dict using the current token."""
        token = self.access_token
        if not token:
            return {}
        return {"Authorization": f"Bearer {token}"}

    def set_tokens(self, token_data: TokenData) -> None:
        """Store *token_data* in memory and persist to disk."""
        self._tokens = token_data
        save_tokens(token_data)

    def clear_tokens(self) -> None:
        """Remove tokens from memory and disk."""
        self._tokens = None
        delete_tokens()

    # ------------------------------------------------------------------
    # JWT utilities
    # ------------------------------------------------------------------

    @staticmethod
    def decode_jwt(token: str) -> dict | None:
        """Decode the payload of a JWT **without** verifying the signature.

        Returns ``None`` if the token cannot be decoded.
        """
        try:
            payload = token.split(".")[1]
            # Pad to a multiple of 4 for base64 decoding.
            payload += "=" * (-len(payload) % 4)
            return json.loads(base64.urlsafe_b64decode(payload))
        except Exception:
            return None

    def is_token_expired(self) -> bool:
        """Return ``True`` if the current access token is missing or expired.

        A 30-second safety margin is applied so the token is refreshed
        *before* it actually expires.
        """
        if not self._tokens:
            return True
        decoded = self.decode_jwt(self._tokens.access_token)
        if not decoded or "exp" not in decoded:
            return True
        return time.time() >= decoded["exp"] - 30

    # ------------------------------------------------------------------
    # Token refresh
    # ------------------------------------------------------------------

    def refresh_tokens(self) -> bool:
        """Attempt to refresh the access token using the stored refresh token.

        Returns ``True`` on success and ``False`` otherwise.
        """
        if not self._tokens or not self._tokens.refresh_token:
            return False
        try:
            resp = self._http.post(
                self.TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "client_id": CLIENT_ID,
                    "refresh_token": self._tokens.refresh_token,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            data = resp.json()
            new_tokens = TokenData(
                access_token=data["access_token"],
                refresh_token=data.get("refresh_token", self._tokens.refresh_token),
                id_token=data.get("id_token"),
            )
            self.set_tokens(new_tokens)
            logger.debug("Access token refreshed successfully")
            return True
        except Exception as exc:
            logger.error(f"Token refresh failed: {exc}")
            return False

    def _ensure_valid_token(self) -> None:
        """Refresh the access token if it has expired.

        Raises :class:`AuthenticationError` if the token cannot be refreshed.
        """
        if self.is_token_expired():
            if not self.refresh_tokens():
                raise AuthenticationError(
                    "Token expired and refresh failed. Please re-authenticate."
                )

    # ------------------------------------------------------------------
    # Authenticated HTTP verbs (prefixed with SERVER_URL)
    # ------------------------------------------------------------------

    def get(self, path: str, **kwargs) -> httpx.Response:
        """Send an authenticated GET request to ``SERVER_URL + path``."""
        self._ensure_valid_token()
        return self._http.get(
            f"{self.SERVER_URL}{path}", headers=self._auth_headers(), **kwargs
        )

    def post(self, path: str, **kwargs) -> httpx.Response:
        """Send an authenticated POST request to ``SERVER_URL + path``."""
        self._ensure_valid_token()
        return self._http.post(
            f"{self.SERVER_URL}{path}", headers=self._auth_headers(), **kwargs
        )

    def put(self, path: str, **kwargs) -> httpx.Response:
        """Send an authenticated PUT request to ``SERVER_URL + path``."""
        self._ensure_valid_token()
        return self._http.put(
            f"{self.SERVER_URL}{path}", headers=self._auth_headers(), **kwargs
        )

    def delete(self, path: str, **kwargs) -> httpx.Response:
        """Send an authenticated DELETE request to ``SERVER_URL + path``."""
        self._ensure_valid_token()
        return self._http.delete(
            f"{self.SERVER_URL}{path}", headers=self._auth_headers(), **kwargs
        )

    def patch(self, path: str, **kwargs) -> httpx.Response:
        """Send an authenticated PATCH request to ``SERVER_URL + path``."""
        self._ensure_valid_token()
        return self._http.patch(
            f"{self.SERVER_URL}{path}", headers=self._auth_headers(), **kwargs
        )

    # ------------------------------------------------------------------
    # Raw (un-prefixed) HTTP helpers for external URLs (e.g. S3)
    # ------------------------------------------------------------------

    def raw_post(self, url: str, **kwargs) -> httpx.Response:
        """POST to an arbitrary URL (e.g. S3 upload URL)."""
        return self._http.post(url, **kwargs)

    def raw_put(self, url: str, **kwargs) -> httpx.Response:
        """PUT to an arbitrary URL (e.g. S3 upload URL)."""
        return self._http.put(url, **kwargs)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying HTTP transport."""
        self._http.close()

    def __enter__(self) -> YotoClient:
        return self

    def __exit__(self, *args) -> None:
        self.close()
